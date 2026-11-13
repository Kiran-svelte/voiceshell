"""Security hardening layer (contribution: data-protection within the context boundary).

Two concrete, testable protections applied to every byte of command output before it reaches the language
model, the spoken reply, or the audit log:

  1. SECRET REDACTION — credentials, keys, tokens and other sensitive identifiers that happen to appear in a
     file the user read, or in a command's output, are replaced with a typed placeholder (e.g. [REDACTED:aws-key]).
     This closes an exfiltration path: a secret the model never sees cannot be placed by the model into a later
     command argument, an outbound-looking string, or the spoken summary; and a redacted audit log cannot leak
     a secret to whoever later reads it.

  2. RESOURCE GUARD — hard caps on how much untrusted text is admitted per step, independent of the model, so a
     pathological or adversarial output (a multi-gigabyte file, a decompression bomb's text) cannot exhaust
     memory or the model's context. Composes with the kernel/Job-Object limits on the executing command.

Redaction is deterministic and runs in the gate path, not in the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each pattern maps to a short type label. Order matters: more specific patterns first.
_SECRETS: list[tuple[str, str]] = [
    ("private-key", r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
    ("aws-key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("aws-secret", r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"),
    ("gcp-key", r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    ("github-token", r"\bgh[pousr]_[0-9A-Za-z]{36,}\b"),
    ("slack-token", r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    ("openai-key", r"\bsk-(?:proj-)?[0-9A-Za-z_\-]{20,}\b"),
    ("jwt", r"\beyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\b"),
    ("bearer-token", r"(?i)\b(?:bearer|authorization)\s*[:=]?\s*[A-Za-z0-9._\-]{20,}"),
    ("password-assignment", r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?"),
    ("connection-string", r"(?i)\b(?:mongodb|postgres(?:ql)?|mysql|redis|amqp)://[^\s]*:[^\s]*@[^\s]+"),
    ("private-ip-cred", r"(?i)://[^\s:/@]+:[^\s:/@]{4,}@"),
    ("credit-card", r"\b(?:\d[ -]?){13,19}\b"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
]
_COMPILED = [(label, re.compile(pat)) for label, pat in _SECRETS]
# a very permissive luhn-ish guard so long ID numbers (not cards) are not over-redacted
_CARD_DIGITS = re.compile(r"\D")


def _looks_like_card(s: str) -> bool:
    digits = _CARD_DIGITS.sub("", s)
    if not 13 <= len(digits) <= 19:
        return False
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0          # Luhn check: real card numbers pass; random IDs usually don't


@dataclass
class Redaction:
    text: str
    count: int = 0
    kinds: list[str] = field(default_factory=list)


def redact(text: str) -> Redaction:
    kinds: list[str] = []

    def sub(label, m):
        if label == "credit-card" and not _looks_like_card(m.group(0)):
            return m.group(0)
        kinds.append(label)
        return f"[REDACTED:{label}]"

    out = text
    for label, rx in _COMPILED:
        out = rx.sub(lambda m, _l=label: sub(_l, m), out)
    return Redaction(text=out, count=len(kinds), kinds=kinds)


def hard_cap(text: str, max_bytes: int) -> tuple[str, bool]:
    """Independent of the model: never admit more than max_bytes of untrusted output into the turn."""
    data = text.encode("utf-8", "replace")
    if len(data) <= max_bytes:
        return text, False
    keep = data[:max_bytes].decode("utf-8", "ignore")
    return keep + f"\n…[output capped at {max_bytes} bytes for safety]…", True
