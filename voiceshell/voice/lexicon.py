"""Custom CLI phoneme lexicon (deck slides 4 & 8, L7): rewrite shell-ish text into words a TTS voice says well.

TTS voices mangle paths, flags, sizes and file extensions ("notes.txt" → "notes-dot-tixt", "-rf" → "ref").
This runs on every spoken reply, before Piper / espeak-ng.
"""
from __future__ import annotations

import re

SPELL = {"txt": "T X T", "pdf": "P D F", "csv": "C S V", "md": "M D", "py": "P Y", "jpg": "J P G", "jpeg": "J peg",
         "png": "P N G", "mp4": "M P 4", "mp3": "M P 3", "json": "jason", "pyc": "P Y C", "tmp": "temp", "bak": "back",
         "gz": "G Z", "whl": "wheel", "rst": "R S T", "html": "H T M L", "exe": "E X E", "sh": "S H", "csl": "C S L"}
WORDS = {"zip": "zip", "log": "log", "tar": "tar"}
COMMANDS = {"mkdir": "make dir", "rmdir": "remove dir", "rm": "R M", "cd": "C D", "ls": "L S", "du": "D U",
            "df": "D F", "mv": "move", "cp": "copy", "pwd": "P W D", "wc": "word count", "sed": "sed", "awk": "awk",
            "cat": "cat", "grep": "grep", "find": "find", "tar": "tar", "chmod": "C H mod"}
UNITS = {"K": "kilobytes", "KB": "kilobytes", "M": "megabytes", "MB": "megabytes", "G": "gigabytes", "GB": "gigabytes",
         "B": "bytes"}


def _ext(m: re.Match) -> str:
    stem, ext = m.group(1), m.group(2)
    low = ext.lower()
    spoken = WORDS.get(low) or SPELL.get(low) or " ".join(low.upper())
    return f"{stem} dot {spoken}"


def _spoken_ext(ext: str) -> str:
    low = ext.lower()
    return WORDS.get(low) or SPELL.get(low) or " ".join(low.upper())


def speakable(text: str) -> str:
    t = re.sub(r"(?<![A-Za-z])'|'(?![A-Za-z])", "", text.replace("`", ""))       # quotes around paths, not I'll
    t = t.replace("e.g.", "for example").replace("i.e.", "that is")
    t = re.sub(r"(\d+(?:\.\d+)?)\s?(KB|MB|GB|K|M|G|B)\b", lambda m: f"{m.group(1)} {UNITS[m.group(2)]}", t)
    # file names: a stem with a letter in it, then an extension that starts with a letter (so 331.1 stays a number)
    t = re.sub(r"\b([\w-]*[A-Za-z][\w-]*)\.([A-Za-z][A-Za-z0-9]{0,3})\b", _ext, t)
    t = re.sub(r"(?<![\w.])\.([A-Za-z][A-Za-z0-9]{0,3})\b", lambda m: "dot " + _spoken_ext(m.group(1)), t)  # *.pdf
    t = re.sub(r"(?<!\S)--(?!\S)", " ", t)
    t = re.sub(r"(?<![\w-])--(\w)", r" dash dash \1", t)
    t = re.sub(r"(?<![\w-])-([A-Za-z]{1,4})\b", lambda m: " dash " + " ".join(m.group(1).upper()), t)
    t = re.sub(r"\b(" + "|".join(COMMANDS) + r")\b(?=\s|$|')", lambda m: COMMANDS[m.group(1)], t)
    t = t.replace("&&", " and then ").replace("|", " pipe ").replace("~/", "home slash ").replace("~", "home")
    t = re.sub(r"(?<=\w)/(?=\w)", " slash ", t)
    t = t.replace("*", " star ").replace("_", " underscore ")
    return re.sub(r"\s{2,}", " ", t).strip()
