"""Fast, hardware-free tests for vox's pure logic.

Run:  python -m pytest    (or just `python tests/test_core.py`)
"""

import io
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vox import config
from vox.cli import _parse_value, _set_dotted
from vox.stt.cloud_openai import _array_to_wav_bytes, _multipart
from vox.stt.local_whisper import _resample_to_16k


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
