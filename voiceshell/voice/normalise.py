"""Spoken forms → literal text (FR-11). Deterministic; runs before the envelope and planner."""
from __future__ import annotations

import re

_NUM = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
        "seven": "7", "eight": "8", "nine": "9", "ten": "10", "twenty": "20", "fifty": "50", "hundred": "100"}

_RULES = [
    (r"\b(\w+) dot (txt|text|pdf|log|csv|json|md|py|sh|png|jpg|jpeg|zip|tar|gz|html|bak|tmp|mp3|mp4)\b",
     lambda m: f"{m.group(1)}.{'txt' if m.group(2) == 'text' else m.group(2)}"),
    (r"\bdot (txt|pdf|log|csv|json|md|py|png|jpg|zip|tmp|bak)\b", r".\1"),
    (r"\b(dash|hyphen|minus) (\w)\b", r"-\2"),
    (r"(\w) (dash|hyphen) (\w)", r"\1-\3"),
    (r"(\w) underscore (\w)", r"\1_\2"),
    (r"\bforward slash\b|\bslash\b", "/"),
    (r"\bstar\b|\basterisk\b", "*"),
    (r"\btilde\b", "~"),
    (r"\bp[. ]?d[. ]?f[. ]?s\b", "PDFs"),
    (r"\bp[. ]?d[. ]?f\b", "PDF"),
    (r"\bdownloads? folder\b", "downloads folder"),
]


def normalise(text: str) -> str:
    t = " ".join(text.strip().split())
    t = re.sub(r"[,]", "", t)
    t = t.rstrip(".!")
    for pat, rep in _RULES:
        t = re.sub(pat, rep, t, flags=re.I)
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"\b(" + "|".join(_NUM) + r")\b(?= (files?|lines?|items?|largest|biggest|megabytes?|mb|gb|kb))",
               lambda m: _NUM[m.group(1).lower()], t, flags=re.I)
    return t
