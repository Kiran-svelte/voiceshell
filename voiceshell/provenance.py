"""Provenance rules T1 (arguments) and T2 (verbs) — 02X §9.

Context spans carry a trust label. A write/delete verb or argument that originates only in
untrusted command output is refused, no matter how persuasive that output was.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

from .envelope import KIND_EXT, tokens
from .gate.rules import INTENT_LEXICON


class Label(IntEnum):          # higher = less trusted
    SYSTEM = 0
    USER_SPEECH = 1
    VERIFIED_FS = 2
    UNTRUSTED_METADATA = 3
    UNTRUSTED_OUTPUT = 4
    MODEL = 5                  # matched nothing: the model made it up


STOP = {"the", "and", "all", "any", "for", "from", "into", "with", "this", "that", "them",
        "file", "files", "folder", "folders", "directory", "dir", "please", "can", "you",
        "what", "show", "list", "here", "there", "inside", "called", "named", "new", "make",
        "create", "delete", "remove", "move", "copy", "then", "out", "are", "is", "my",
        "its", "whats", "which", "one", "ones", "every", "some", "put"}


@dataclass
class TurnContext:
    utterance: str
    listing: set[str] = field(default_factory=set)          # UNTRUSTED_METADATA
    outputs: list[str] = field(default_factory=list)        # UNTRUSTED_OUTPUT (cleaned)

    def speech_tokens(self) -> set[str]:
        out = set()
        for t in tokens(self.utterance):
            if len(t) < 3 or t in STOP:
                continue
            out.add(t)
            if t.endswith("s") and len(t) > 3:
                out.add(t[:-1])
            out |= KIND_EXT.get(t.rstrip("s"), set())
        return out


def _arg_tokens(arg: str) -> set[str]:
    base = re.split(r"[\\/]", arg.rstrip("/\\"))[-1] or arg
    return {t for t in tokens(base) if len(t) >= 3}


def corroborated(arg: str, ctx: TurnContext) -> bool:
    if arg in (".", "./", "~", "*"):
        return False
    st = ctx.speech_tokens()
    if _arg_tokens(arg) & st:
        return True
    return arg.lower() in ctx.utterance.lower()


def in_untrusted_output(text: str, ctx: TurnContext) -> bool:
    if len(text) < 2:
        return False
    pat = re.compile(r"(?<![\w.-])" + re.escape(text) + r"(?![\w-])")
    return any(pat.search(o) for o in ctx.outputs)


def classify_arg(arg: str, exists: bool, ctx: TurnContext) -> Label:
    if corroborated(arg, ctx):
        return Label.USER_SPEECH
    base = re.split(r"[\\/]", arg.rstrip("/\\"))[-1]
    from_output = in_untrusted_output(arg, ctx) or (len(base) >= 4 and in_untrusted_output(base, ctx))
    in_listing = arg.strip("./") in ctx.listing or base in ctx.listing
    if from_output:                      # T3: the least-trusted origin wins
        return Label.UNTRUSTED_OUTPUT
    if exists:
        return Label.VERIFIED_FS
    if in_listing:
        return Label.UNTRUSTED_METADATA
    return Label.MODEL


def verb_justified(verb: str, ctx: TurnContext) -> bool:
    words = tokens(ctx.utterance)
    text = " ".join(words)
    keys = set(words)
    if "back up" in text or "backup" in text:
        keys.add("backup")
    if "set up" in text:
        keys.add("setup")
    for w in keys:
        for k, verbs in INTENT_LEXICON.items():
            if (w == k or (len(k) >= 4 and w.startswith(k))) and verb in verbs:
                return True
    return False
