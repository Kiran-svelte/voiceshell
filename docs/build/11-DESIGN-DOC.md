# VoiceShell W1 — Design Document

| Field | Value |
|---|---|
| Document ID | VS-DD-011 |
| Implements | [10-BUILD-PRD](10-BUILD-PRD.md) |
| Derived from | [02-SAD-HLD](../02-SAD-HLD.md), [02X](../02X-ARCHITECTURE-EXTREME.md), [04-THREAT-MODEL](../04-THREAT-MODEL.md) |
| Code | [`voiceshell/`](../../voiceshell) |

---

## 1. One turn, end to end

```
  mic / file / keyboard
          │
          ▼
  ┌───────────────┐   faster-whisper small.en, CLI-vocabulary biasing prompt,
  │ 1 ASR         │   energy endpointing (push-to-talk)            voice/asr.py
  └───────┬───────┘
          ▼
  ┌───────────────┐   "dash l" → -l, "notes dot txt" → notes.txt  voice/normalise.py
  │ 2 NORMALISE   │
  └───────┬───────┘
          ▼
  ┌───────────────┐   E = f(utterance, asr_confidence) — computed ONCE,
  │ 3 ENVELOPE    │   may only shrink afterwards                    envelope.py
  └───────┬───────┘
          ▼
  ┌───────────────┐   Tier 0: compiled templates, no model (≈ms)
  │ 4 CASCADE     │   Tier 2: Qwen2.5-Coder-3B via Ollama, JSON-schema
  │               │           constrained output, temperature 0     planner.py
  └───────┬───────┘
          ▼
  ╔═══════════════╗   tree-sitter-bash AST → risk tier → path scope →
  ║ 5 GATE        ║   provenance T1/T2 → envelope membership.
  ║  (no model)   ║   Any check can refuse. Unknown = refuse.      gate/
  ╚═══════╤═══════╝
          ▼
  ┌───────────────┐   READ: run · WRITE: one approval ·
  │ 6 CONFIRM     │   DESTRUCTIVE: shadow-run on a copy, state measured
  │               │   change set, require explicit "yes"           agent.py, shadow.py
  └───────┬───────┘
          ▼
  ┌───────────────┐   audit record committed FIRST (fail-closed),
  │ 7 EXECUTE     │   then Git Bash in the workspace jail; pure deletes
  │               │   become trash-moves (undoable)                executor.py
  └───────┬───────┘
          ▼
  ┌───────────────┐   strip ANSI/controls/bidi, truncate, scan for
  │ 8 SANITISE    │   injection, fence with per-turn nonce          sanitise.py
  └───────┬───────┘
          ▼
   loop to 4 (≤ 5 steps)  or  speak summary (pyttsx3 / Windows SAPI)
```

## 2. Module map

| Module | Responsibility | Trust |
|---|---|---|
| `config.py` | Paths, model name, limits | — |
| `voice/asr.py` | Mic capture, endpointing, transcription | untrusted input |
| `voice/normalise.py` | Spoken forms → literal text | deterministic |
| `voice/tts.py` | Speech out | — |
| `envelope.py` | Derive and shrink the capability envelope | **safety-critical** |
| `context.py` | Live-state snapshot (cwd, listing, history) as provenance spans | — |
| `planner.py` | Tier 0 templates + Tier 2 LLM | **untrusted** (assumed compromised) |
| `gate/parser.py` | Bash → list of simple commands, fail-closed on anything unanalysable | **safety-critical** |
| `gate/rules.py` | Verb → risk tier / operation class tables | **safety-critical, hashed** |
| `gate/gate.py` | The four checks, verdict record | **safety-critical** |
| `provenance.py` | Argument origin classification (T1, T2) | **safety-critical** |
| `sanitise.py` | Output cleaning, injection scan, fencing | **safety-critical** |
| `shadow.py` | Copy-workspace rehearsal + diff | — |
| `executor.py` | Jailed bash execution, trash-deletes, undo | — |
| `audit.py` | Hash-chained JSONL, verify | **safety-critical** |
| `agent.py` | Orchestrates a turn | — |
| `cli.py` | Text / voice / file front-ends | — |

The planner is the only module that touches the model. **No safety-critical module imports
the planner.** This is checked by a unit test (`test_gate_is_model_free`).

## 3. Key decisions

| ID | Decision | Why | Cost |
|---|---|---|---|
| D-1 | Run commands in **Git Bash** on Windows | Real POSIX bash + coreutils available here; matches the Linux design's command language | No kernel sandbox |
| D-2 | **Qwen2.5-Coder-3B** Q4 via Ollama | 7B would swap on 7.4 GB RAM; 3B fits the 4 GB GPU | Weaker planning than 7B |
| D-3 | Ollama **JSON-schema `format`** | Grammar-constrained decoding, same idea as GBNF in the parent design | — |
| D-4 | Gate in **Python**, not Rust | One language for a student team; still model-free and small | Slower than 3 ms, still ~ms |
| D-5 | Shadow execution on a **file copy** | No overlayfs on Windows. Same property: the preview *is* the command | Ceiling: 200 MB / 5 000 files, else honest estimate |
| D-6 | Unknown verbs are **FORBIDDEN** | Fail-closed allowlist, never a blocklist | Some valid commands refused |
| D-7 | **Wake word by transcription**: every speech segment is transcribed by the same Whisper model and its first words are fuzzy-matched to "VoiceShell" | Hands-free with no extra model or download; answers to its own questions need no wake word; silence = no | Transcribes nearby speech locally (never sent anywhere); ~3 s per segment on CPU |
| D-8 | **Write/delete templates** ("make a folder X and move the Y into it", "delete all the X files in Y") | The 3B model put folders in the wrong place and used non-recursive globs. Templates fill slots; the AI does not author the command | **Deviates from the parent design**, where Tier 0 may never emit a destructive verb. Mitigation: the gate runs identically, deletes stay DESTRUCTIVE (rehearsal, measured count, explicit yes, trash, undo) |
| D-9 | **Writes are rehearsed too**, and every spoken result is the *measured* change, never the AI's claim | The model claimed "copied it" when it had written a text file | One workspace copy per write approval (ceiling 200 MB / 5,000 files, otherwise an honest estimate) |
| D-10 | **The delete-confidence rule averages the request's words, leaving out the wake word and file names** | Wake words and file names score ~0.3–0.4 even when heard perfectly, which blocked every spoken delete. (A first attempt used the single lowest action-word score; that failed too, because the first word of a sentence often scores 0.3) | File names are verified separately: punctuation-insensitive exact match to a real file, read back in the preview, explicit yes |
| D-11 | Audit log takes a **cross-process lock** and chains onto the record on disk; `rotate-log` archives a broken chain bound by SHA-256 | Two VoiceShell windows forked the chain | — |
| D-12 | Trash keeps deletes for **24 h**, per workspace | Design D7 | Expired items are removed for good |

## 4. The gate (D3 + D4 + D1)

### 4.1 Parsing — fail-closed

`tree-sitter-bash` parses the command. The walker accepts only: `program`, `list`
(`&&`, `||`, `;`), `pipeline`, `command`, `redirected_statement` with file redirects,
words, strings, and globs. **Anything else is refused as unanalysable** — command
substitution `$(…)`, backticks, subshells, process substitution, functions, loops,
heredocs, variable assignments, `$VAR` expansions in write/delete arguments, and any
`ERROR` node. `find -exec …` and `xargs …` are unwrapped and their inner command is
classified as well.

### 4.2 Risk tiers

| Tier | Examples | Gate behaviour |
|---|---|---|
| READ | `ls cat head du df find grep wc sort stat` | Run, no confirmation |
| WRITE | `mkdir touch cp mv tar zip sed -i tee`, `>>` | One approval per turn |
| DESTRUCTIVE | `rm rmdir`, `find -delete`, `truncate`, `>` onto an existing file, `mv`/`cp` onto an existing file | Shadow preview + explicit "yes" per command |
| FORBIDDEN | `sudo curl wget ssh nc dd eval bash sh python powershell`, running scripts, `git push/clone`, **any unknown verb** | Never runs, no override |

The final tier of a compound command is the **maximum** over its parts.

### 4.3 Path scope

Every path-like argument and redirect target is resolved against the current directory
(with `~` = workspace root) and must stay inside the workspace. `..` escapes, absolute
paths elsewhere, drive letters (`/c/…`, `C:\…`) and symlinks pointing out are refused.

### 4.4 Provenance (T1, T2)

Context is held as spans labelled `SYSTEM < USER_SPEECH < VERIFIED_FS < UNTRUSTED_METADATA
< UNTRUSTED_OUTPUT`.

* **T2 verb rule** — a WRITE/DESTRUCTIVE verb must be justified by the user's own words
  (a deterministic lexicon: "delete/remove/clean" → `rm`, "move" → `mv`, …). If it is not,
  and the verb text appears in untrusted command output, it is refused outright.
* **T1 argument rule** — an argument to a WRITE/DESTRUCTIVE command is accepted if the
  user's words corroborate it, or if it is an existing path the gate itself stat'd and it
  did **not** come only from untrusted file contents. Unmatched arguments to DESTRUCTIVE
  commands are refused.

### 4.5 Monotonic Capability Envelope

Derived once from the utterance:

| Utterance contains | Envelope |
|---|---|
| nothing that asks for change | `{READ}` |
| create / make / copy / move / rename / compress / save / write … | `{READ, WRITE}` |
| delete / remove / erase / clean up / get rid of … | `{READ, WRITE, DELETE}` (+ scope: extensions named, e.g. "log files" → `*.log`) |

Shrinks (never grows): injection signature seen in any output → `{READ}`; any provenance
refusal → `{READ}`; two failed steps → drop `DELETE`; ASR confidence < 0.8 → `DELETE`
never admitted; more than 5 steps → stop.

ASR confidence is Whisper's **mean per-word probability**. The obvious alternative,
`exp(avg_logprob)`, sits around 0.6–0.8 even for perfect transcripts, and it blocked every
spoken delete in the first voice run ([13-PROOF-REPORT §4](13-PROOF-REPORT.md)).

If the gate refuses a delete only because it is outside the delete *scope* (e.g. `rm tmp/*`
when the user said "temporary files"), the planner gets one retry with that hint. The retry
goes through the full gate again. No other envelope refusal is retried.

## 5. Confirmation and shadow execution

For DESTRUCTIVE commands the workspace is copied to a temp folder, the exact command runs
there, the before/after trees are diffed, the copy is deleted, and the user hears the
measured result: *"This will delete 12 files, 340 KB, in logs. Shall I proceed?"*

* Only an explicit affirmative ("yes", "proceed", "confirm", "go ahead", "do it") runs it.
  Silence, "maybe", "uh", or anything else cancels (FR-46).
* If the rehearsal itself fails, the user is **not** asked. The failure goes back to the
  planner as untrusted output, and nothing is changed.
* If the shadow diff contains **only deletions**, the real run moves exactly those paths
  to `.voiceshell/trash/<turn>/` instead of destroying them. "Undo that" restores them.

## 6. Context boundary (sanitisation)

Every command output, file content, and error is: ANSI/OSC escapes stripped, C0 controls
and bidi/zero-width characters removed, truncated head+tail to 2 000 chars, scanned for
injection signatures, and wrapped in `<<UNTRUSTED id=NONCE>> … <<END NONCE>>` with any
fence-like text inside escaped. A scan hit shrinks the envelope to `{READ}`.

## 7. Audit

`.voiceshell/audit.jsonl` (outside the workspace, so jailed commands cannot touch it).
Each record = `{seq, ts, kind, data, prev, hash}` where `hash = sha256(prev + canonical
json)`. A record of the verdict is written **before** execution; if that write fails,
nothing runs. `python -m voiceshell verify` walks the chain. The gate's ruleset SHA-256 is
in every verdict.

## 8. What W1 does *not* defend that the Linux design does

Stated, not hidden:

* A command the gate classifies as READ still runs as your Windows user — there is no
  syscall filter. The gate's allowlist is the only thing keeping e.g. network tools out.
* No resource cgroups: a pathological READ (e.g. `find /` — refused by scope — or a huge
  `sort`) is bounded only by a 20 s timeout and a 1 MB output cap.
* No packet capture in CI; "no network" rests on (a) the model server being localhost and
  (b) every network-capable verb being FORBIDDEN.
