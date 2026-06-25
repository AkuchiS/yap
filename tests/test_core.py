"""Fast, hardware-free tests for yap's pure logic.

Run:  python -m pytest    (or just `python tests/test_core.py`)
"""

import io
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap import config
from yap.cli import _parse_value, _set_dotted
from yap.stt.cloud_openai import _array_to_wav_bytes, _multipart
from yap.stt.local_whisper import _resample_to_16k
from yap.text import apply_replacements, build_prompt


def test_config_deep_merge_preserves_defaults():
    merged = config._deep_merge(config.DEFAULT_CONFIG, {"engine": "cloud",
                                                        "local": {"model": "small"}})
    assert merged["engine"] == "cloud"
    assert merged["local"]["model"] == "small"
    # untouched sibling keys survive the merge
    assert merged["local"]["beam_size"] == config.DEFAULT_CONFIG["local"]["beam_size"]
    assert merged["cloud"]["base_url"] == config.DEFAULT_CONFIG["cloud"]["base_url"]


def test_set_dotted_creates_nested():
    d = {}
    _set_dotted(d, "hotkey.mode", "hold")
    assert d == {"hotkey": {"mode": "hold"}}


def test_parse_value_json_then_string():
    assert _parse_value("true") is True
    assert _parse_value("3") == 3
    assert _parse_value('"hold"') == "hold"
    assert _parse_value("plain") == "plain"  # not valid JSON -> kept as string


def test_wav_roundtrip_is_valid_16bit_pcm():
    sr = 16000
    samples = (np.sin(np.linspace(0, 50, sr)) * 0.5).astype(np.float32)
    data = _array_to_wav_bytes(samples, sr)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == sr
        assert w.getsampwidth() == 2
        assert w.getnchannels() == 1
        assert w.getnframes() == sr


def test_resample_changes_length_proportionally():
    sr = 48000
    samples = np.zeros(sr, dtype=np.float32)  # 1 second
    out = _resample_to_16k(samples, sr)
    assert abs(len(out) - 16000) <= 1


def test_multipart_has_boundary_and_file_part():
    body, ctype = _multipart({"model": "whisper-1"}, "audio.wav", b"RIFFxxxx")
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=")[1]
    assert boundary.encode() in body
    assert b'name="file"; filename="audio.wav"' in body
    assert b'name="model"' in body
    assert b"RIFFxxxx" in body


def test_hardware_model_tiers():
    from yap.hardware import recommend_model

    def info(**kw):
        base = {"ram_gb": 16, "cores": 8, "intel_mac": False,
                "apple_silicon": False, "cuda": False}
        base.update(kw)
        return base

    assert recommend_model(info=info(ram_gb=3, cores=2)) == "tiny.en"
    assert recommend_model(info=info(ram_gb=8, intel_mac=True)) == "base.en"
    assert recommend_model(info=info(ram_gb=16)) == "small.en"
    # multilingual users get the non-.en variant
    assert recommend_model(prefer_english=False, info=info(ram_gb=16)) == "small"


def test_integration_state_file(tmp_path=None):
    import json
    import tempfile

    d = tmp_path or tempfile.mkdtemp()
    sf = os.path.join(str(d), "state.json")
    from yap.integration import Integration

    ig = Integration({"integration": {"state_file": sf}})
    ig.record_started()
    assert json.load(open(sf))["active"] is True
    ig.record_stopped()
    assert json.load(open(sf))["active"] is False


def test_learn_extract_candidates():
    from yap.learn import extract_candidates

    c = extract_candidates("I told NASA to push JavaScript to GitHub. Anthropic ships Claude.")
    assert "NASA" in c          # acronym
    assert "JavaScript" in c and "GitHub" in c   # CamelCase
    assert "Claude" in c          # mid-sentence proper noun
    assert "Anthropic" not in c   # sentence-initial → skipped (grammar, not a name)
    assert "I" not in c           # too short / stopword


def test_learn_promotes_after_min_count():
    import tempfile

    os.environ["YAP_CONFIG_DIR"] = tempfile.mkdtemp()
    try:
        from yap.learn import VocabLearner

        learner = VocabLearner({"vocabulary": [],
                                "learning": {"enabled": True, "min_count": 3,
                                             "max_words": 80}})
        for _ in range(2):
            learner.observe("Open ComfyUI please.")
        assert "ComfyUI" not in learner.words()   # only seen twice
        learner.observe("Open ComfyUI please.")
        assert "ComfyUI" in learner.words()        # third time → promoted
        assert learner.forget("comfyui") is True
        assert "ComfyUI" not in learner.words()
    finally:
        os.environ.pop("YAP_CONFIG_DIR", None)


def test_build_prompt_glossary():
    assert build_prompt([]) is None
    assert build_prompt(None) is None
    assert build_prompt(["NASA", "Anthropic"]) == "Glossary: NASA, Anthropic."


def test_apply_replacements_whole_word_case_insensitive():
    assert apply_replacements("i love github and Github", {"github": "GitHub"}) == \
        "i love GitHub and GitHub"
    # multi-word keys work
    assert apply_replacements("write java script", {"java script": "JavaScript"}) == \
        "write JavaScript"
    # doesn't clobber substrings inside other words
    assert apply_replacements("githubson", {"github": "GitHub"}) == "githubson"
    # empty inputs are safe
    assert apply_replacements("", {"a": "b"}) == ""
    assert apply_replacements("x", {}) == "x"


def test_license_install_record_is_stable():
    import tempfile

    os.environ["YAP_CONFIG_DIR"] = tempfile.mkdtemp()
    try:
        from yap import licensing

        first = licensing.install_record()
        assert first["installed_at"] and first["id"]
        # second call must return the SAME record (date never re-stamped)
        second = licensing.install_record()
        assert second == first
    finally:
        os.environ.pop("YAP_CONFIG_DIR", None)


def test_license_grandfather_code_roundtrip_and_cutoff():
    import tempfile

    os.environ["YAP_CONFIG_DIR"] = tempfile.mkdtemp()
    try:
        from yap import licensing

        rec = licensing.install_record()
        # signed code verifies; a tampered one does not
        code = licensing.grandfather_code(rec, secret="s3cret")
        assert licensing.verify_code(code, "s3cret")["valid"] is True
        assert licensing.verify_code(code, "wrong")["valid"] is False
        assert licensing.verify_code(code + "x", "s3cret")["valid"] is False
        # unsigned when no secret
        assert licensing.grandfather_code(rec).endswith(".unsigned")
        # cutoff logic: installed today → not grandfathered against a past cutoff,
        # but grandfathered against a far-future one
        assert licensing.is_grandfathered("2000-01-01", rec) is False
        assert licensing.is_grandfathered("2999-01-01", rec) is True
    finally:
        os.environ.pop("YAP_CONFIG_DIR", None)


def test_audio_resample_rate_conversion():
    from yap.audio import _resample

    sig = np.ones(4800, dtype=np.float32)        # 0.1s of DC at 48 kHz
    out = _resample(sig, 48000, 16000)
    assert abs(out.shape[0] - 1600) <= 1         # ~1/3 the samples
    assert np.allclose(out, 1.0, atol=1e-3)      # DC level preserved
    assert _resample(sig, 16000, 16000).shape[0] == sig.shape[0]   # no-op when equal
    assert _resample(np.zeros(0, dtype=np.float32), 48000, 16000).size == 0  # empty safe


def test_audio_resolve_device_preference_list():
    from yap import audio

    orig = audio._match_substring
    present = {"studio display": 3}  # simulate clamshell: only the display mic exists
    audio._match_substring = lambda s: present.get(str(s).lower())
    try:
        # int / None pass straight through (no device query)
        assert audio.resolve_device(None) is None
        assert audio.resolve_device(7) == 7
        # single substring: present -> its index; absent -> None (system default)
        assert audio.resolve_device("Studio Display") == 3
        assert audio.resolve_device("MacBook Pro Microphone") is None
        # preference list: first present wins (built-in missing -> display mic)
        assert audio.resolve_device(["MacBook Pro Microphone", "Studio Display"]) == 3
        assert audio.resolve_device(["nope", "nada"]) is None
    finally:
        audio._match_substring = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
