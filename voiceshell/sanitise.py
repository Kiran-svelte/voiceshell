"""Context boundary: every byte of command output passes through here before the model sees it."""
from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field

# S1 — terminal control: CSI, OSC, other ESC sequences, C0/C1 controls (keep \n and \t)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# S2 — bidi overrides and zero-width characters
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")

# S4 — injection signatures (heuristic layer; the envelope and provenance rules do not depend on it)
_SIGNATURES = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above|your) ",
    r"\b(system|assistant|developer)\s*(prompt|message)?\s*:",
    r"<\|im_(start|end)\|>", r"\[/?INST\]", r"<<\s*sys\s*>>",
    r"you are now", r"new instructions?", r"your (new |real )?task is",
    r"\b(run|execute|exec)\s+(the\s+)?(following|this|command)",
    r"\brm\s+-[a-z]*[rf]", r"\bcurl\s+\S+\s*\|\s*(ba)?sh", r"\bwget\s+http",
    r"<<\s*(UNTRUSTED|END)\b", r"\bsudo\s+", r"do not (tell|inform|warn) the user",
    r"\bchmod\s+[0-7]*7[0-7]*\s", r"base64\s+-d",
]
_SIG_RE = re.compile("|".join(_SIGNATURES), re.IGNORECASE)


@dataclass
class Sanitised:
    text: str                 # cleaned, truncated, redacted, NOT fenced
    fenced: str               # what the model sees
    flagged: bool             # injection signature present
    hits: list[str] = field(default_factory=list)
    truncated: bool = False
    redacted: int = 0         # how many secrets were masked
    redaction_kinds: list[str] = field(default_factory=list)


def clean(raw: str) -> str:
    s = _ANSI.sub("", raw)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _CTRL.sub("", s)
    s = _INVISIBLE.sub("", s)
    return unicodedata.normalize("NFKC", s)


def truncate(s: str, limit: int) -> tuple[str, bool]:
    if len(s) <= limit:
        return s, False
    head = s[: limit * 2 // 3]
    tail = s[-(limit // 3):]
    return f"{head}\n…[{len(s) - limit} chars omitted]…\n{tail}", True


def scan(s: str) -> list[str]:
    return [m.group(0) for m in _SIG_RE.finditer(s)]


def fence(s: str, nonce: str, label: str = "UNTRUSTED") -> str:
    # The payload cannot forge a closing fence: it never knows the nonce, and fence-like
    # markers inside are defanged anyway.
    s = re.sub(r"<<\s*(UNTRUSTED|END)", r"«\1", s, flags=re.IGNORECASE)
    return f"<<{label} id={nonce}>>\n{s}\n<<END {nonce}>>"


def sanitise(raw: str, limit: int = 2000, nonce: str | None = None, label: str = "UNTRUSTED") -> Sanitised:
    from .security import redact
    nonce = nonce or secrets.token_hex(4)
    cleaned = clean(raw)
    # scan a variant where every stripped character became a space, so a payload glued to the
    # previous word with escapes or invisible characters ("normal‮SYSTEM:") is still seen
    spaced = _INVISIBLE.sub(" ", _CTRL.sub(" ", _ANSI.sub(" ", raw)))
    hits = scan(cleaned) or scan(spaced)
    red = redact(cleaned)               # mask secrets BEFORE the model, the reply, or the audit see the text
    text, cut = truncate(red.text, limit)
    return Sanitised(text=text, fenced=fence(text, nonce, label), flagged=bool(hits), hits=hits, truncated=cut,
                     redacted=red.count, redaction_kinds=red.kinds)
