"""Deterministic spoken summaries, used when the model's answer is missing or generic ("Done.")."""
from __future__ import annotations

import re
from pathlib import Path

GENERIC = re.compile(r"^(ok(ay)?[.!]?|done[.!]?|i'?m done[.!]?|i am done[.!]?|task (is )?(complete|completed|done)[.!]?|"
                     r"finished[.!]?|completed[.!]?|all done[.!]?|.{0,3})$", re.I)
_SIZE_LINE = re.compile(r"^\s*([\d.,]+\s?[KMGTB]?i?B?)\s+(.+?)\s*$")
_UNITS = {"K": "kilobytes", "M": "megabytes", "G": "gigabytes", "T": "terabytes", "B": "bytes"}


def is_generic(say: str) -> bool:
    return not say or bool(GENERIC.match(say.strip()))


def _speak_size(s: str) -> str:
    m = re.match(r"([\d.,]+)\s?([KMGTB])", s.strip(), re.I)
    return f"{m.group(1)} {_UNITS[m.group(2).upper()]}" if m else s.strip()


def _name(p: str) -> str:
    return p.strip().removeprefix("./")


def summarize(command: str, output: str, cwd: Path) -> str:
    lines = [l for l in output.splitlines() if l.strip() and l.strip() != "(no output)"]
    if not lines:
        return f"I ran {command}. It finished without printing anything."
    sized = [m for m in (_SIZE_LINE.match(l) for l in lines) if m]
    if len(sized) >= max(1, len(lines) // 2):
        files = []
        for m in sized:
            p = (cwd / _name(m.group(2)))
            if p.is_file() or (not p.exists() and "." in Path(m.group(2)).name):
                files.append((m.group(1), _name(m.group(2))))
        if files:
            top = ", ".join(f"{n} at {_speak_size(s)}" for s, n in files[:3])
            more = f" There are {len(files) - 3} more on screen." if len(files) > 3 else ""
            return f"The biggest files are {top}.{more}"
    if len(lines) == 1:
        return f"The result is: {lines[0].strip()[:160]}"
    head = "; ".join(l.strip()[:60] for l in lines[:3])
    return f"I found {len(lines)} lines. The first ones are: {head}. The rest is on screen."


def describe_changes(before: dict, after: dict) -> str:
    """Measured, human description of what changed in the workspace (never the model's claim)."""
    created = [k for k in after if k not in before]
    deleted = [k for k in before if k not in after]

    # whole-folder renames/moves: a removed folder whose contents (names + sizes) reappear under a new folder
    def subtree(snap, d):
        return frozenset((k[len(d) + 1:], v[0]) for k, v in snap.items() if k.startswith(d + "/"))

    folder_moves: list[tuple[str, str]] = []
    gone_dirs_all = sorted((k for k in deleted if before[k][2]), key=len)
    for nd in sorted((k for k in created if after[k][2]), key=len):
        if any(nd.startswith(n + "/") for _, n in folder_moves):
            continue
        sub = subtree(after, nd)
        for od in gone_dirs_all:
            if any(od == o or od.startswith(o + "/") for o, _ in folder_moves):
                continue
            if sub and subtree(before, od) == sub:
                folder_moves.append((od, nd))
                break
    if folder_moves:
        inside = lambda k, d: k == d or k.startswith(d + "/")  # noqa: E731
        created = [k for k in created if not any(inside(k, n) for _, n in folder_moves)]
        deleted = [k for k in deleted if not any(inside(k, o) for o, _ in folder_moves)]
    modified = [k for k in after if k in before and not after[k][2] and after[k][:2] != before[k][:2]]
    new_dirs = [k for k in created if after[k][2]]
    new_files = [k for k in created if not after[k][2]]
    gone_files = [k for k in deleted if not before[k][2]]
    moved, copied, renamed = [], [], []
    by_sig = {before[k][:2]: k for k in gone_files}          # mv keeps size AND mtime
    for f in list(new_files):
        old = by_sig.pop(after[f][:2], None)
        if old is not None:
            (moved if Path(old).name == Path(f).name else renamed).append((old, f))
            gone_files.remove(old)
            new_files.remove(f)
        elif any(Path(k).name == Path(f).name and v[0] == after[f][0] and not v[2]
                 for k, v in before.items() if k in after):
            copied.append(f)
            new_files.remove(f)
    renamed_txt = [f"{Path(o).name} to {Path(n).name}" for o, n in renamed]
    moved = [n for _, n in moved]

    def where(paths):
        dirs = sorted({str(Path(p).parent).replace("\\", "/") for p in paths})
        dirs = ["this folder" if d == "." else d for d in dirs]
        return ", ".join(dirs[:2]) + (" and others" if len(dirs) > 2 else "")

    def names(paths, n=3):
        ns = [Path(p).name for p in paths]
        return ", ".join(ns[:n]) + (f" and {len(ns) - n} more" if len(ns) > n else "")

    parts = []
    for o, n in folder_moves:
        po, pn = str(Path(o).parent), str(Path(n).parent)
        parts.append(f"renamed folder {Path(o).name} to {Path(n).name}" if po == pn
                     else f"moved folder {Path(o).name} into {pn.replace(chr(92), '/') if pn != '.' else 'this folder'}")
    if new_dirs:
        parts.append(f"created folder{'s' if len(new_dirs) > 1 else ''} {names(new_dirs)}")
    if moved:
        parts.append(f"moved {len(moved)} file{'s' if len(moved) > 1 else ''} ({names(moved)}) into {where(moved)}")
    if renamed_txt:
        parts.append("renamed " + ", ".join(renamed_txt[:3]))
    if copied:
        parts.append(f"copied {len(copied)} file{'s' if len(copied) > 1 else ''} ({names(copied)}) into {where(copied)}")
    if new_files:
        parts.append(f"created {len(new_files)} file{'s' if len(new_files) > 1 else ''} ({names(new_files)})")
    if modified:
        parts.append(f"changed {names(modified)}")
    gone_dirs = [k for k in deleted if before[k][2]]
    if gone_files:
        parts.append(f"removed {len(gone_files)} file{'s' if len(gone_files) > 1 else ''} ({names(gone_files)})")
    if gone_dirs and not gone_files:
        parts.append(f"removed folder{'s' if len(gone_dirs) > 1 else ''} {names(gone_dirs)}")
    if not parts:
        return "nothing in the workspace changed"
    s = "; ".join(parts)
    return s[0].upper() + s[1:]
