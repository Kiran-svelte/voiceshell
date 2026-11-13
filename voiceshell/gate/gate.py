"""The gate. No model inside. Four independent checks; any one refuses.

    permitted  <=>  parse ok and tier != FORBIDDEN          [D3 syntax + rules]
               and  paths(cmd) within workspace             [D3 scope]
               and  provenance(verb, args) acceptable       [D1]
               and  op_class(cmd) in envelope               [D4]
    then confirmation is decided by tier                    [D5]
"""
from __future__ import annotations

import glob as _glob
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..envelope import Envelope
from ..provenance import Label, TurnContext, classify_arg, in_untrusted_output, verb_justified
from . import rules
from .parser import ParsedCommand, SimpleCommand, Unanalysable, parse
from .rules import Op, Tier

_HERE = Path(__file__).resolve().parent
MANIFEST = _HERE / "MANIFEST.json"
SEALED_FILES = ("rules.py", "parser.py", "gate.py")


def ruleset_sha() -> str:
    h = hashlib.sha256()
    for name in SEALED_FILES:
        h.update((_HERE / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def seal() -> str:
    sha = ruleset_sha()
    MANIFEST.write_text(json.dumps({"ruleset_sha256": sha, "files": list(SEALED_FILES)}, indent=2))
    return sha


class GateIntegrityError(RuntimeError):
    pass


def verify_integrity() -> str:
    """Refuse to start if the ruleset does not match the sealed manifest (Threat Model §7.6)."""
    sha = ruleset_sha()
    if not MANIFEST.exists():
        raise GateIntegrityError("gate manifest missing — refusing to start")
    want = json.loads(MANIFEST.read_text())["ruleset_sha256"]
    if want != sha:
        raise GateIntegrityError(f"gate ruleset hash mismatch ({sha[:12]} != {want[:12]}) — refusing to start")
    return sha


# ───────────────────────────── classification ─────────────────────────────

TEXT_VERBS = {"echo", "printf", "expr", "seq", "test", "[", "date", "sleep", "cal", "true",
              "false", "whoami", "hostname", "uname", "uptime", "id", "ps", "pwd", "xargs"}
PATTERN_FIRST = {"grep", "egrep", "fgrep", "sed", "awk"}
FLAG_WITH_VALUE = {
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "sort": {"-k", "-t", "-o"}, "cut": {"-d", "-f", "-c"},
    "grep": {"-e", "-m", "-A", "-B", "-C", "--include", "--exclude"}, "du": {"-d", "--max-depth"},
    "tar": {"-C"}, "split": {"-l", "-b"}, "zip": set(), "uniq": {"-f", "-s"}, "date": {"-d"},
    "tr": set(), "column": {"-t", "-s"}, "ls": {"-I", "--ignore"}, "tree": {"-L", "-I"},
    "awk": {"-F", "-v"}, "sed": {"-e"}, "touch": {"-d", "-t"}, "truncate": {"-s"},
}
FIND_VALUE_FLAGS = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-type", "-size",
                    "-mtime", "-mmin", "-atime", "-amin", "-ctime", "-cmin", "-newer", "-maxdepth",
                    "-mindepth", "-user", "-group", "-perm", "-printf", "-wholename", "-links"}
FIND_FORBIDDEN = {"-fprint", "-fprint0", "-fprintf", "-fls"}

_SED_SAFE = re.compile(r"^\s*(\d+|\$)?,?(\d+|\$)?\s*(s(.).*?\4.*?\4[gIip0-9]*|[dp]|/[^/]*/[dp])\s*$")


@dataclass
class CmdVerdict:
    verb: str
    tier: Tier
    op: str
    reason: str
    paths: list[str] = field(default_factory=list)          # path args to scope-check
    write_targets: list[str] = field(default_factory=list)  # args subject to provenance T1
    delete_targets: list[str] = field(default_factory=list)


def _split_flags(cmd: SimpleCommand) -> tuple[list[str], list[str]]:
    flags, pos = [], []
    vflags = FLAG_WITH_VALUE.get(cmd.verb, set())
    argv = cmd.argv
    i = 0
    end_of_flags = False
    while i < len(argv):
        a = argv[i]
        if not end_of_flags and a == "--":
            end_of_flags = True
        elif not end_of_flags and a.startswith("-") and len(a) > 1:
            flags.append(a)
            if a in vflags and i + 1 < len(argv):
                i += 1
                if a == "-C" or a == "-o":
                    pos.append(argv[i])  # these values are paths
        else:
            pos.append(a)
        i += 1
    return flags, pos


def _has_flag(flags: list[str], short: str, long: str = "") -> bool:
    for f in flags:
        if long and f == long:
            return True
        if f.startswith("-") and not f.startswith("--") and short in f[1:]:
            return True
    return False


def classify(cmd: SimpleCommand, resolve) -> CmdVerdict:
    v = cmd.verb
    if "/" in v or "\\" in v:
        return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, "running a program or script by path is forbidden")
    if v in rules.FORBIDDEN_VERBS:
        return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, f"'{v}' is in the forbidden class")
    flags, pos = _split_flags(cmd)

    if v == "git":
        sub = pos[0] if pos else ""
        if sub in rules.GIT_READ:
            return CmdVerdict(v, Tier.READ, Op.READ, f"git {sub}", paths=pos[1:])
        if sub in rules.GIT_WRITE:
            return CmdVerdict(v, Tier.WRITE, Op.WRITE, f"git {sub}", paths=[])
        return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, f"git {sub or '(none)'} may use the network or is not allowlisted")

    if v == "find":
        argv = cmd.argv
        roots = []
        for a in argv:
            if a.startswith("-") or a in ("(", ")", "!"):
                break
            roots.append(a)
        if any(a in FIND_FORBIDDEN for a in argv):
            return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, "find writes to a file via -fprint")
        exec_verbs = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-exec", "-execdir", "-ok", "-okdir")]
        if "-delete" in argv or any(x in rules.DELETE_VERBS for x in exec_verbs):
            names = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-name", "-iname")]
            return CmdVerdict(v, Tier.DESTRUCTIVE, Op.DELETE, "find -delete", paths=roots or ["."],
                              delete_targets=names or roots or ["."], write_targets=roots)
        return CmdVerdict(v, Tier.READ, Op.READ, "find (read-only)", paths=roots or ["."])

    if v == "sed":
        script = pos[0] if pos else ""
        if "-e" in flags:
            script = ""
        if not _SED_SAFE.match(script):
            return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, "sed script outside the safe subset (s///, d, p)")
        files = pos[1:]
        if _has_flag(flags, "i", "--in-place") or any(f.startswith("--in-place") for f in flags):
            return CmdVerdict(v, Tier.DESTRUCTIVE, Op.WRITE, "sed -i edits files in place (irreversible)",
                              paths=files, write_targets=files)
        return CmdVerdict(v, Tier.READ, Op.READ, "sed (stream only)", paths=files)

    if v == "awk":
        prog = pos[0] if pos else ""
        if re.search(r"system|getline|\||>|print\w*\s*>|inplace|ENVIRON", prog) or any("inplace" in f for f in flags):
            return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, "awk program can execute or write")
        return CmdVerdict(v, Tier.READ, Op.READ, "awk (stream only)", paths=pos[1:])

    if v in rules.DELETE_VERBS:
        return CmdVerdict(v, Tier.DESTRUCTIVE, Op.DELETE, f"'{v}' permanently removes data",
                          paths=pos, delete_targets=pos, write_targets=pos)

    if v in ("mv", "cp"):
        if len(pos) < 2:
            return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, f"{v} needs a source and a destination")
        no_clobber = _has_flag(flags, "n", "--no-clobber")
        dest = pos[-1]
        overwrite = False if no_clobber else _would_overwrite(pos[:-1], dest, resolve)
        tier = Tier.DESTRUCTIVE if overwrite else Tier.WRITE
        why = f"{v} would overwrite an existing file" if overwrite else f"{v} {'moves' if v == 'mv' else 'copies'} files"
        return CmdVerdict(v, tier, Op.WRITE, why, paths=pos, write_targets=pos)

    if v == "tee":
        tier = Tier.WRITE if _has_flag(flags, "a", "--append") else (
            Tier.DESTRUCTIVE if any(_exists_file(p, resolve) for p in pos) else Tier.WRITE)
        return CmdVerdict(v, tier, Op.WRITE, "tee writes files", paths=pos, write_targets=pos)

    if v == "tar":
        if any(re.search(r"command|checkpoint|compress-program|^-I$|^--to|rsh|^-F$|info-script", a) for a in cmd.argv):
            return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, "tar option can execute programs")
        bundle = "".join(f.lstrip("-") for f in flags if not f.startswith("--"))
        if pos and re.fullmatch(r"[ctxvzjfJ]+", pos[0]):
            bundle += pos[0]
            pos = pos[1:]
        if "t" in bundle and "c" not in bundle and "x" not in bundle:
            return CmdVerdict(v, Tier.READ, Op.READ, "tar lists an archive", paths=pos)
        return CmdVerdict(v, Tier.WRITE, Op.WRITE, "tar creates or extracts an archive", paths=pos, write_targets=pos[:1])

    if v in rules.WRITE_VERBS:
        return CmdVerdict(v, Tier.WRITE, Op.WRITE, f"'{v}' creates or changes files", paths=pos, write_targets=pos)

    if v in rules.READ_VERBS or v == "xargs":
        if v in TEXT_VERBS:
            return CmdVerdict(v, Tier.READ, Op.READ, f"'{v}' is read-only")
        if v in PATTERN_FIRST:
            pos = pos if "-e" in flags else pos[1:]
        return CmdVerdict(v, Tier.READ, Op.READ, f"'{v}' is read-only", paths=pos)

    return CmdVerdict(v, Tier.FORBIDDEN, Op.READ, f"'{v}' is not on the allowlist (unknown = refused)")


def _exists_file(p: str, resolve) -> bool:
    r = resolve(p)
    return r is not None and r.is_file()


def _would_overwrite(srcs: list[str], dest: str, resolve) -> bool:
    d = resolve(dest)
    if d is None:
        return False
    if d.is_file():
        return True
    if d.is_dir():
        for s in srcs:
            matches = _glob.glob(str(resolve(".") / s)) if any(c in s for c in "*?[") else [s]
            for m in matches:
                if (d / Path(m).name).is_file():
                    return True
    return False


# ───────────────────────────── the gate ─────────────────────────────

@dataclass
class Verdict:
    command: str
    allowed: bool
    tier: Tier = Tier.FORBIDDEN
    ops: set[str] = field(default_factory=set)
    confirm: str = "none"            # none | batch | per_command
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)
    cd_target: Path | None = None
    taint: bool = False              # a provenance rule fired
    ruleset_sha: str = ""
    delete_targets: list[str] = field(default_factory=list)

    def record(self) -> dict:
        return {"command": self.command, "allowed": self.allowed, "tier": self.tier.name,
                "ops": sorted(self.ops), "confirm": self.confirm, "reasons": self.reasons,
                "checks": self.checks, "ruleset_sha": self.ruleset_sha[:16]}


class Gate:
    def __init__(self, workspace: Path, check_integrity: bool = True):
        self.workspace = Path(workspace).resolve()
        self.sha = verify_integrity() if check_integrity else ruleset_sha()

    # path scope ------------------------------------------------------
    def to_host_path(self, p: str, cwd: Path) -> Path | None:
        """Translate a bash path to a Windows path, or None if it can never be in scope."""
        if p in ("/dev/null",):
            return None
        if p == "~" or p.startswith("~/"):
            return Path(os.path.normpath(self.workspace / p[2:])) if len(p) > 1 else self.workspace
        if p.startswith("~"):
            return Path("/__outside__")
        m = re.match(r"^/([a-zA-Z])(/|$)(.*)", p)
        if m:
            return Path(os.path.normpath(f"{m.group(1).upper()}:/{m.group(3)}"))
        if re.match(r"^[a-zA-Z]:[\\/]", p):
            return Path(os.path.normpath(p))
        if p.startswith("/") or p.startswith("\\"):
            return Path("/__outside__")
        return Path(os.path.normpath(cwd / p))

    def in_scope(self, host: Path) -> bool:
        ws = os.path.normcase(str(self.workspace))
        for candidate in (host, host.resolve() if host.exists() else host):
            c = os.path.normcase(str(candidate))
            if not (c == ws or c.startswith(ws + os.sep)):
                return False
        return True

    def _scope_path(self, p: str, cwd: Path) -> tuple[bool, Path | None]:
        if p == "/dev/null":
            return True, None
        base = p
        if any(ch in p for ch in "*?["):
            idx = min(p.index(ch) for ch in "*?[" if ch in p)
            base = p[:idx]
            base = base[: base.rfind("/") + 1] if "/" in base else "."
            base = base or "."
        host = self.to_host_path(base, cwd)
        if host is None:
            return True, None
        return self.in_scope(host), host

    # verdict ----------------------------------------------------------
    def check(self, command: str, cwd: Path, envelope: Envelope, ctx: TurnContext) -> Verdict:
        v = Verdict(command=command, allowed=False, ruleset_sha=self.sha)
        try:
            parsed: ParsedCommand = parse(command)
        except Unanalysable as e:
            v.reasons.append(f"refused: unanalysable command ({e})")
            v.checks["parse"] = "FAIL"
            return v
        v.checks["parse"] = "ok"

        resolve = lambda p: self.to_host_path(p, cwd)  # noqa: E731
        verdicts = [classify(c, resolve) for c in parsed.commands]
        for c, cv in zip(parsed.commands, verdicts):
            if c.nested == "xargs" and cv.tier >= Tier.WRITE:
                v.reasons.append(f"refused: xargs {c.verb} takes its targets from piped text, which cannot be checked")
                v.checks["rules"] = "FAIL"
                v.tier = Tier.FORBIDDEN
                return v

        # standalone cd is handled by the agent, not bash
        if any(c.verb == "cd" for c in parsed.commands):
            if len(parsed.commands) != 1:
                v.reasons.append("refused: 'cd' must be a command on its own")
                v.checks["parse"] = "FAIL"
                return v
            target = parsed.commands[0].argv[0] if parsed.commands[0].argv else "~"
            ok, host = self._scope_path(target, cwd)
            if not ok or host is None or not host.is_dir():
                v.reasons.append(f"refused: cannot change to '{target}' (outside workspace or not a folder)")
                v.checks["scope"] = "FAIL"
                return v
            v.cd_target = host

        v.tier = max(cv.tier for cv in verdicts)
        v.ops = {cv.op for cv in verdicts}
        # redirects
        for c in parsed.commands:
            for r in c.redirects:
                if r.op == ">&" and r.target.isdigit():
                    continue
                ok, host = self._scope_path(r.target, cwd)
                if not ok:
                    v.reasons.append(f"refused: redirect target '{r.target}' is outside the workspace")
                    v.checks["scope"] = "FAIL"
                    return v
                if r.op == "<" or host is None:
                    continue
                v.ops.add(Op.WRITE)
                overwrite = r.op in (">", "&>", ">&") and host.is_file()
                v.tier = max(v.tier, Tier.DESTRUCTIVE if overwrite else Tier.WRITE)
                verdicts.append(CmdVerdict(">", Tier.WRITE, Op.WRITE, "redirect writes a file",
                                           write_targets=[r.target]))

        # D3 rules
        forbidden = [cv for cv in verdicts if cv.tier == Tier.FORBIDDEN]
        if forbidden:
            v.tier = Tier.FORBIDDEN
            v.reasons += [f"refused: {cv.reason}" for cv in forbidden]
            v.checks["rules"] = "FAIL"
            return v
        v.checks["rules"] = f"ok ({v.tier.name})"

        # D3 path scope
        for cv in verdicts:
            for p in cv.paths:
                ok, host = self._scope_path(p, cwd)
                if not ok:
                    v.reasons.append(f"refused: '{p}' is outside the workspace")
                    v.checks["scope"] = "FAIL"
                    return v
            for p in cv.delete_targets:
                ok, host = self._scope_path(p, cwd)
                if cv.op == Op.DELETE and host is not None and os.path.normcase(str(host)) == os.path.normcase(str(self.workspace)) and not any(ch in p for ch in "*?["):
                    v.reasons.append("refused: deleting the workspace root itself")
                    v.checks["scope"] = "FAIL"
                    return v
        v.checks["scope"] = "ok"

        # D1 provenance
        for cv in verdicts:
            if cv.tier == Tier.READ and cv.op == Op.READ:
                continue
            verb = cv.verb
            if verb != ">" and not verb_justified(verb, ctx):
                if in_untrusted_output(verb, ctx):
                    v.reasons.append(f"refused (T2): verb '{verb}' appears only in untrusted output, not in your request")
                    v.checks["provenance"] = "FAIL"
                    v.taint = True
                    return v
                if cv.tier >= Tier.DESTRUCTIVE:
                    v.reasons.append(f"refused (T2): you did not ask for '{verb}'")
                    v.checks["provenance"] = "FAIL"
                    v.taint = True
                    return v
            for a in cv.write_targets:
                if a in (".", "./") or a.startswith("-"):
                    continue
                host = resolve(a.split("*")[0] or ".") if any(ch in a for ch in "*?[") else resolve(a)
                exists = host is not None and host.exists()
                label = classify_arg(a, exists, ctx)
                # a reversible, confirmed WRITE may name an existing path it saw in output;
                # anything destructive may not (02X §9 rule T1)
                if label == Label.UNTRUSTED_OUTPUT and (cv.tier >= Tier.DESTRUCTIVE or cv.op == Op.DELETE or not exists):
                    v.reasons.append(f"refused (T1): '{a}' came from command output, not from you. Say it aloud to authorise it.")
                    v.checks["provenance"] = "FAIL"
                    v.taint = True
                    return v
                if label in (Label.MODEL, Label.UNTRUSTED_METADATA) and cv.op == Op.DELETE:
                    v.reasons.append(f"refused (T1): delete target '{a}' is not something you named")
                    v.checks["provenance"] = "FAIL"
                    v.taint = True
                    return v
        v.checks["provenance"] = "ok"

        # D4 envelope
        missing = [op for op in v.ops if not envelope.allows(op)]
        if missing:
            v.reasons.append(f"refused: this turn may only {envelope.describe()}; command needs {sorted(missing)}")
            v.checks["envelope"] = "FAIL"
            return v
        if Op.DELETE in v.ops and envelope.delete_scope:
            for cv in verdicts:
                for t in cv.delete_targets:
                    ext = t.rsplit(".", 1)[-1].lower() if "." in t.rsplit("/", 1)[-1] else ""
                    if ext not in envelope.delete_scope:
                        v.reasons.append(f"refused: you asked to delete only {envelope.describe().split('delete-scope=')[1]}, not '{t}'")
                        v.checks["envelope"] = "FAIL"
                        return v
        v.checks["envelope"] = "ok"

        v.delete_targets = [t for cv in verdicts for t in cv.delete_targets]
        v.allowed = True
        v.confirm = {Tier.READ: "none", Tier.WRITE: "batch", Tier.DESTRUCTIVE: "per_command"}[v.tier]
        return v
