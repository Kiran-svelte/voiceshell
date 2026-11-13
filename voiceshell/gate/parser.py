"""Bash → flat list of simple commands. Fail-closed: anything not understood is refused."""
from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_bash as _tsb
from tree_sitter import Language, Parser

_LANG = Language(_tsb.language())
_PARSER = Parser(_LANG)

GLOB_CHARS = set("*?[")


class Unanalysable(Exception):
    """The command uses a construct the gate refuses to reason about."""


@dataclass
class Arg:
    value: str
    glob: bool = False


@dataclass
class Redirect:
    op: str              # '>', '>>', '<', '&>', '>&', ...
    target: str
    fd: str = ""


@dataclass
class SimpleCommand:
    verb: str
    args: list[Arg] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    nested: str = ""       # "find" / "xargs" when unwrapped from -exec or xargs

    @property
    def argv(self) -> list[str]:
        return [a.value for a in self.args]


@dataclass
class ParsedCommand:
    source: str
    commands: list[SimpleCommand]
    operators: list[str]


_OK_OPERATORS = {"&&", "||", ";", "|", "\n"}


def parse(source: str) -> ParsedCommand:
    if not source or not source.strip():
        raise Unanalysable("empty command")
    if "\x00" in source or "`" in source:
        raise Unanalysable("backticks or NUL bytes")
    tree = _PARSER.parse(source.encode("utf-8"))
    root = tree.root_node
    if root.has_error:
        raise Unanalysable("syntax error")
    out: list[SimpleCommand] = []
    ops: list[str] = []
    _walk_statement(root, out, ops)
    if not out:
        raise Unanalysable("no command found")
    for c in list(out):
        out.extend(_unwrap(c))
    return ParsedCommand(source, out, ops)


def _walk_statement(node, out, ops) -> None:
    t = node.type
    if t in ("program", "list", "pipeline"):
        for ch in node.children:
            if ch.is_named:
                if ch.type == "comment":
                    continue
                _walk_statement(ch, out, ops)
            else:
                tok = ch.type
                if tok not in _OK_OPERATORS:
                    raise Unanalysable(f"operator {tok!r} not allowed")
                ops.append(tok)
        return
    if t == "redirected_statement":
        body = node.child_by_field_name("body")
        redirects = []
        for ch in node.children:
            if ch.type == "file_redirect":
                redirects.append(_redirect(ch))
            elif ch.is_named and ch != body:
                raise Unanalysable(f"{ch.type} not allowed")
        if body is None:
            raise Unanalysable("redirect without command")
        before = len(out)
        _walk_statement(body, out, ops)
        if body.type == "command":
            out[before].redirects.extend(redirects)
        elif body.type == "pipeline":
            out[-1].redirects.extend(redirects)
        else:
            raise Unanalysable(f"redirect on {body.type}")
        return
    if t == "command":
        out.append(_command(node))
        return
    raise Unanalysable(f"{t} not allowed")


def _command(node) -> SimpleCommand:
    verb = None
    args: list[Arg] = []
    redirects: list[Redirect] = []
    for ch in node.children:
        if ch.type == "command_name":
            verb = _word(ch.children[0]).value if ch.children else None
        elif ch.type == "file_redirect":
            redirects.append(_redirect(ch))
        elif ch.type == "variable_assignment":
            raise Unanalysable("variable assignment")
        elif ch.is_named:
            args.append(_word(ch))
    if not verb:
        raise Unanalysable("command without a name")
    return SimpleCommand(verb=verb, args=args, redirects=redirects)


def _redirect(node) -> Redirect:
    op, target, fd = "", "", ""
    for ch in node.children:
        if ch.type == "file_descriptor":
            fd = ch.text.decode()
        elif not ch.is_named:
            op += ch.type
        else:
            target = _word(ch).value
    if op not in (">", ">>", "<", "&>", ">&", "&>>", ">|"):
        raise Unanalysable(f"redirect {op!r}")
    if op == ">|":
        op = ">"
    return Redirect(op=op, target=target, fd=fd)


def _word(node) -> Arg:
    t = node.type
    if t in ("word", "number"):
        raw = node.text.decode()
        glob = any(c in GLOB_CHARS for c in raw.replace("\\*", "").replace("\\?", ""))
        return Arg(_unescape(raw), glob)
    if t == "raw_string":
        return Arg(node.text.decode()[1:-1])
    if t == "string":
        parts = []
        for ch in node.children:
            if ch.type == "string_content":
                parts.append(ch.text.decode())
            elif ch.type == '"':
                continue
            else:
                raise Unanalysable(f"{ch.type} inside string")
        return Arg(_unescape_dq("".join(parts)))
    if t == "concatenation":
        vals, glob = [], False
        for ch in node.children:
            a = _word(ch)
            vals.append(a.value)
            glob = glob or a.glob
        return Arg("".join(vals), glob)
    raise Unanalysable(f"{t} not allowed")


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _unescape_dq(s: str) -> str:
    for a, b in (('\\"', '"'), ("\\\\", "\\"), ("\\$", "$")):
        s = s.replace(a, b)
    return s


def _unwrap(cmd: SimpleCommand) -> list[SimpleCommand]:
    """Expose the inner command of find -exec / xargs so it is classified too."""
    inner: list[SimpleCommand] = []
    argv = cmd.argv
    if cmd.verb == "find":
        i = 0
        while i < len(argv):
            if argv[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                body = []
                while j < len(argv) and argv[j] not in (";", "+"):
                    body.append(cmd.args[j])
                    j += 1
                if not body:
                    raise Unanalysable("empty -exec")
                inner.append(SimpleCommand(body[0].value, [b for b in body[1:] if b.value != "{}"], nested="find"))
                i = j
            i += 1
    elif cmd.verb == "xargs":
        j = 0
        while j < len(argv) and argv[j].startswith("-"):
            if argv[j] in ("-I", "-n", "-L", "-P", "-d", "-s", "-E"):
                j += 1
            j += 1
        if j < len(argv):
            inner.append(SimpleCommand(argv[j], cmd.args[j + 1:], nested="xargs"))
        else:
            inner.append(SimpleCommand("echo", [], nested="xargs"))
    return inner
