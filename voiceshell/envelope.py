"""The Monotonic Capability Envelope (02X §10).

Derived ONCE from the user's own words. It can only shrink afterwards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gate.rules import Op

DELETE_WORDS = {"delete", "remove", "erase", "clean", "clear", "wipe", "purge", "rid",
                "trash", "empty", "rm", "del", "deleting", "removing", "cleanup"}
WRITE_WORDS = {
    "create", "make", "new", "add", "write", "save", "append", "copy", "duplicate",
    "backup", "move", "rename", "put", "organize", "organise", "compress", "archive",
    "zip", "unzip", "extract", "decompress", "replace", "change", "edit", "link",
    "split", "commit", "stage", "initialise", "initialize", "setup", "touch", "mkdir",
    "store", "place", "transfer", "executable", "tar", "gzip",
}
# "back up", "set up" are two-word intents
WRITE_PHRASES = [r"\bback\s*up\b", r"\bset\s*up\b", r"\bget rid of\b", r"\bsave .* (to|in|as)\b",
                 r"\b(in|into) a (new )?file\b", r"\bsort .* into\b"]

KIND_EXT = {
    "log": {"log"}, "text": {"txt"}, "txt": {"txt"}, "pdf": {"pdf"}, "csv": {"csv"},
    "temp": {"tmp", "temp"}, "tmp": {"tmp"}, "temporary": {"tmp", "temp"}, "backup": {"bak"},
    "bak": {"bak"}, "image": {"png", "jpg", "jpeg", "gif"}, "photo": {"png", "jpg", "jpeg"},
    "png": {"png"}, "jpg": {"jpg", "jpeg"}, "jpeg": {"jpeg", "jpg"}, "json": {"json"},
    "python": {"py"}, "py": {"py"}, "markdown": {"md"}, "md": {"md"}, "mp3": {"mp3"}, "mp4": {"mp4"}, "zip": {"zip"},
    "html": {"html"}, "cache": {"cache"}, "old": set(),
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Envelope:
    ops: set[str]
    delete_scope: set[str] = field(default_factory=set)   # allowed extensions for DELETE; empty = any
    history: list[str] = field(default_factory=list)

    def allows(self, op: str) -> bool:
        return op in self.ops

    def shrink(self, to: set[str], reason: str) -> None:
        new = self.ops & to          # intersection: can never add
        if new != self.ops:
            self.history.append(f"{sorted(self.ops)} -> {sorted(new)}: {reason}")
            self.ops = new

    def drop(self, op: str, reason: str) -> None:
        self.shrink(self.ops - {op}, reason)

    def describe(self) -> str:
        s = "{" + ", ".join(o for o in (Op.READ, Op.WRITE, Op.DELETE) if o in self.ops) + "}"
        if Op.DELETE in self.ops and self.delete_scope:
            s += " delete-scope=" + ",".join(f"*.{e}" for e in sorted(self.delete_scope))
        return s


# Below this confidence the transcription is treated as too unreliable to authorize deletion. Real-microphone
# speech typically scores 0.5-0.85 (synthetic test voices score 0.88-0.95), so the bar is set to admit clear
# real speech while still rejecting garbled input (e.g. a 0.17 "notes.notes.txt"). The real safeguard against a
# mishearing is NOT this threshold but the per-command measured preview the user hears before confirming, plus
# path grounding (the file must exist) and the 24-hour trash/undo.
DELETE_CONF_THRESHOLD = 0.45


def derive(utterance: str, asr_confidence: float = 1.0) -> Envelope:
    text = utterance.lower()
    toks = set(tokens(text))
    ops = {Op.READ}
    if toks & WRITE_WORDS or any(re.search(p, text) for p in WRITE_PHRASES):
        ops.add(Op.WRITE)
    wants_delete = bool(toks & DELETE_WORDS) or "get rid of" in text
    env = Envelope(ops=ops)
    if wants_delete:
        if asr_confidence < DELETE_CONF_THRESHOLD:
            env.history.append(f"DELETE withheld: ASR confidence {asr_confidence:.2f} < {DELETE_CONF_THRESHOLD:.2f}")
        else:
            env.ops |= {Op.WRITE, Op.DELETE}
            env.delete_scope = delete_scope(text)
    return env


def delete_scope(text: str) -> set[str]:
    exts: set[str] = set()
    for m in re.finditer(r"\.([a-z0-9]{1,5})\b", text):
        exts.add(m.group(1))
    for m in re.finditer(r"\b([a-z0-9]+?)s?\s+files?\b", text):
        exts |= KIND_EXT.get(m.group(1), set())
    for m in re.finditer(r"\b(pdf|png|jpg|jpeg|mp3|mp4|csv|txt|log|tmp|bak|json)s\b", text):
        exts.add(m.group(1))
    return exts
