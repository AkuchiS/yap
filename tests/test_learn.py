"""Tests for relearn's correction diffing — the 'learn my last fix' feature.

Run:  python -m pytest tests/test_learn.py   (or: python tests/test_learn.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap.learn import diff_corrections
from yap.text import apply_replacements


def test_multiword_to_single_phrase_fix():
    # The most common real correction — and the case that used to be dropped.
    fixes, casings = diff_corrections("post grey sequel", "PostgreSQL")
    assert fixes == {"post grey sequel": "PostgreSQL"}
    # ...and it actually rewrites a later transcript:
    assert apply_replacements("i love post grey sequel", fixes) == "i love PostgreSQL"


def test_phrase_fix_with_surrounding_context():
    fixes, _ = diff_corrections("the cube an eddies cluster", "the Kubernetes cluster")
    assert fixes == {"cube an eddies": "Kubernetes"}


def test_casing_only_becomes_a_vocab_entry():
    fixes, casings = diff_corrections("i use anthropic daily", "i use Anthropic daily")
    assert "Anthropic" in casings and fixes == {}


def test_clean_one_to_one_spelling_fix():
    fixes, _ = diff_corrections("send the file to jon", "send the file to John")
    assert fixes == {"jon": "John"}


def test_sentence_sized_rewrite_is_ignored():
    old = "this is a long sentence the user completely rewrote by hand afterwards"
    new = "totally different words here now please"
    fixes, _ = diff_corrections(old, new)
    assert fixes == {}                       # too big to learn as one find/replace


def test_identical_learns_nothing():
    fixes, casings = diff_corrections("nothing changed here", "nothing changed here")
    assert fixes == {} and casings == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
