"""Risk rules. Deterministic, model-free, hashed at start-up.

Every verb not listed here is FORBIDDEN (fail-closed allowlist).
"""
from __future__ import annotations

from enum import IntEnum


class Tier(IntEnum):
    READ = 0
    WRITE = 1
    DESTRUCTIVE = 2
    FORBIDDEN = 3


class Op:
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"


READ_VERBS = {
    "ls", "cat", "head", "tail", "wc", "du", "df", "grep", "egrep", "fgrep", "sort",
    "uniq", "cut", "tr", "echo", "printf", "pwd", "stat", "file", "date", "whoami",
    "basename", "dirname", "realpath", "readlink", "diff", "cmp", "md5sum", "sha1sum",
    "sha256sum", "column", "nl", "rev", "seq", "true", "false", "test", "[", "tac",
    "od", "strings", "ps", "uptime", "hostname", "uname", "cal", "comm", "join",
    "paste", "fold", "fmt", "expr", "sleep", "id", "tree", "less", "more", "cd",
}

WRITE_VERBS = {"mkdir", "touch", "cp", "mv", "tar", "zip", "unzip", "gzip", "gunzip",
               "ln", "tee", "chmod", "split", "sed", "awk"}

DELETE_VERBS = {"rm", "rmdir", "truncate", "unlink"}

# Named for the record; they are FORBIDDEN by the default rule anyway.
FORBIDDEN_VERBS = {
    "sudo", "su", "doas", "runas", "dd", "mkfs", "fdisk", "mount", "umount",
    "curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "netcat", "telnet", "ftp",
    "rsync", "ping", "nslookup", "socat", "eval", "exec", "source", ".", "bash", "sh",
    "zsh", "dash", "fish", "python", "python3", "py", "perl", "ruby", "node", "php",
    "powershell", "pwsh", "cmd", "cmd.exe", "start", "chown", "chgrp", "kill",
    "pkill", "killall", "taskkill", "crontab", "at", "shutdown", "reboot", "halt",
    "reg", "netsh", "sc", "systemctl", "service", "nohup", "setsid", "env", "xdg-open",
    "explorer", "shred", "wipe", "alias", "export", "unset", "set", "trap", "builtin",
    "command", "type", "hash", "history", "fc", "vi", "vim", "nano", "emacs", "watch",
    "timeout", "nice", "time",
}

GIT_READ = {"status", "log", "diff", "show", "branch", "ls-files", "blame", "rev-parse"}
GIT_WRITE = {"add", "commit", "init", "checkout", "switch", "restore", "stash", "tag", "mv"}
# Everything else under git (push, pull, fetch, clone, remote, submodule, config…) is FORBIDDEN.

# Spoken intent → verbs it justifies (provenance rule T2) and envelope classes.
INTENT_LEXICON: dict[str, set[str]] = {
    "delete": DELETE_VERBS | {"find"}, "remove": DELETE_VERBS | {"find"},
    "erase": DELETE_VERBS | {"find"}, "clean": DELETE_VERBS | {"find"},
    "clear": DELETE_VERBS | {"find"}, "wipe": DELETE_VERBS | {"find"},
    "purge": DELETE_VERBS | {"find"}, "rid": DELETE_VERBS | {"find"},
    "trash": DELETE_VERBS | {"find"}, "empty": DELETE_VERBS | {"find"},
    "create": {"mkdir", "touch", "tee", "cp"}, "make": {"mkdir", "touch", "tee", "cp"},
    "new": {"mkdir", "touch", "tee"}, "add": {"mkdir", "touch", "tee", "git"},
    "write": {"tee", "touch", "sed", "awk"}, "save": {"tee", "cp", "touch"},
    "append": {"tee"}, "copy": {"cp"}, "duplicate": {"cp"}, "backup": {"cp", "tar", "zip"},
    "back": {"cp", "tar", "zip"},
    "move": {"mv", "mkdir"}, "rename": {"mv"}, "put": {"mv", "cp", "mkdir"},
    "organize": {"mv", "mkdir"}, "organise": {"mv", "mkdir"}, "sort": {"mv", "mkdir"},
    "compress": {"tar", "zip", "gzip"}, "archive": {"tar", "zip"}, "zip": {"zip", "tar"},
    "extract": {"tar", "unzip", "gunzip"}, "unzip": {"unzip", "tar"},
    "decompress": {"tar", "unzip", "gunzip"},
    "replace": {"sed", "awk"}, "change": {"sed", "chmod", "mv"}, "edit": {"sed", "awk"},
    "executable": {"chmod"}, "permission": {"chmod"}, "permissions": {"chmod"},
    "link": {"ln"}, "split": {"split"}, "commit": {"git"}, "stage": {"git"},
    "initialise": {"git", "mkdir"}, "initialize": {"git", "mkdir"},
    "set": {"mkdir", "touch", "tee"}, "setup": {"mkdir", "touch", "tee"},
}
