# VoiceShell

> **Talk to your computer. It runs the command — but only what you actually asked for.**

VoiceShell lets you control your files by speaking plain English. A small AI model (running
**on your own machine**, no cloud) turns *"delete all the log files in the logs folder"* into the
right shell command. Then the part that makes VoiceShell different takes over: a **safety gate with
no AI in it** decides whether that command is allowed to run — and it can only ever do what *your
words* permitted.

Nothing leaves your computer. No account, no API key, no internet after setup.

```
You ▸  "VoiceShell, delete all the log files in the logs folder."

VoiceShell ▸  That will permanently delete 4 items, 331 KB, in logs
              (app.log, debug.log, error.log, server.log). Shall I proceed?
You ▸  "Yes."
VoiceShell ▸  Done. Deleted 4 items. Say "undo that" within 24 hours to restore them.
```

It shows you the **measured** result before touching anything, waits for your "yes", keeps deleted
files recoverable for 24 hours, and writes every action to a tamper-proof log.

---

## Why it's different

Most AI assistants trust the AI. VoiceShell assumes the AI is **unreliable or even hostile**, and
puts a deterministic checker between the AI and your files. That checker — not the AI — has the
final say. Five ideas make it safe:

| | Idea | What it means for you |
|---|---|---|
| 🔒 | **Authority from your words, and it can only shrink** | If you only asked to *look*, nothing can be changed this turn — no matter what the AI reads or decides next. |
| 🧾 | **You can only delete what you named** | A hidden instruction inside a file can't choose what gets deleted. Injection attacks fail by construction. |
| 🔎 | **Measured preview, not a guess** | Before a delete or overwrite, it rehearses the exact command on a throwaway copy and tells you the real count, size, and location. |
| ↩️ | **Undo** | Deletes go to a 24-hour trash. *"Undo that"* brings them back. |
| 📋 | **Tamper-evident log** | Every request, decision, and action is hash-chained. Editing the past is detectable. |

Plus: **secrets** (API keys, passwords) found in files are masked before the AI or the log ever
see them, and **every memory store is size-bounded** so it can't grow forever.

---

## Proof it works

Measured on an ordinary laptop (AMD Ryzen 7, 7.4 GB RAM, GTX 1650) with the local Llama 3.2 model:

| | |
|---|---|
| **169** automated tests | ✅ pass |
| **195 / 205** task benchmark | 95% |
| **40 / 40** prompt-injection attacks (12 classes) | 100% blocked |
| Destructive commands run **without your "yes"** | **0** |
| Forbidden commands (sudo, curl, `rm -rf /`) executed | **0** |
| Anything escaping the workspace folder | **0** |

Reproduce it yourself: `python -m pytest -q tests`, `python bench/run_bench.py`,
`python bench/injection_corpus.py`. Details in [docs/build/13-PROOF-REPORT.md](docs/build/13-PROOF-REPORT.md).

---

## Quick start

**1. Install** (one time, needs internet):

```bash
python -m pip install faster-whisper sounddevice pyttsx3 tree-sitter tree-sitter-bash httpx rich pytest psutil langgraph pywinpty watchdog piper-tts noisereduce resemblyzer
```

```bash
ollama pull llama3.2:3b
```

**2. Check everything is ready** (also starts the local AI server):

```bash
python -m voiceshell doctor
```

**3. Create a safe demo folder to play in:**

```bash
python -m voiceshell demo-setup
```

**4. Use it:**

```bash
python -m voiceshell voice        # hold Enter, speak, release
```

```bash
python -m voiceshell handsfree    # say "VoiceShell …" — no keyboard at all
```

```bash
python -m voiceshell text         # just type your requests
```

> Prefer Apache-licensed Qwen instead of Llama? `ollama pull qwen2.5-coder:3b` then set
> `VOICESHELL_MODEL=qwen2.5-coder:3b`.

---

## What you can say

A verified, tested list is in [docs/build/20-PHRASEBOOK.md](docs/build/20-PHRASEBOOK.md). The
reliable essentials:

- **Look:** *"what's in downloads"* · *"show me the biggest files in logs"* · *"how many pdf files are in downloads"*
- **Read:** *"read notes.txt"* · *"search for the word dentist in notes.txt"* · *"how many lines are in todo.md"*
- **Create:** *"make a folder called reports"* · *"create a file called ideas.txt and write buy milk in it"*
- **Organize:** *"make a folder called pdfs and move all the PDFs from downloads into it"* · *"copy notes.txt to backup.txt"* · *"rename a.txt to b.txt"*
- **Delete (asks first, undoable):** *"delete all the log files in logs"* · then *"undo that"*
- **Converse:** *"go to downloads"* → *"how many files are here"* · *"what did you just do?"* · *"delete it"* (it asks which file)

It **refuses** downloaded scripts, internet access, anything outside the workspace folder, and
chit-chat — and never obeys instructions hidden inside a file.

---

## How it works

```
  speak / type
      │   faster-whisper (speech→text) · Silero VAD · spoken-form normalise
      ▼
  LangGraph agent  ──  Llama 3.2 / Qwen (local, via Ollama) plans one command
      ▼
 ┌─ SAFETY GATE (no AI inside) ─────────────────────────────────────────┐
 │  parse to AST → risk tier → path scope → provenance → capability      │
 │  envelope → measured-preview confirm → fail-closed hash-chained audit │
 └──────────────────────────────────────────────────────────────────────┘
      ▼   Git Bash, confined to one folder, in a memory/CPU-limited job
  run the command · deletes → 24h trash · Piper TTS speaks the measured result
```

Every component is free and open-source and runs locally. Full list with licences:
[docs/build/12-TECH-STACK.md](docs/build/12-TECH-STACK.md).

---

## Honest limits

- **One folder only.** It works inside a `workspace` folder — never your real drives, other apps, or the web. (That's the point.)
- **Small local model.** Simple and medium tasks are reliable; genuinely complex multi-step ones succeed ~half the time. When the AI gets it wrong, the gate catches it and nothing bad happens.
- **Speed.** Built-in commands are instant (~15 ms); AI-planned ones take ~3 s, plus ~3 s for speech recognition.
- **Windows build.** The Linux kernel sandbox (AppArmor/seccomp/namespaces) can't run on Windows; it's replaced by a Windows Job Object + the workspace jail + the model-free gate. Not independently security-reviewed.
- **Voice testing.** Automated tests use synthetic voices; real-microphone and accented-speech testing is ongoing. Try it yourself: [docs/build/16-LIVE-TEST-GUIDE.md](docs/build/16-LIVE-TEST-GUIDE.md).

---

## Documentation

| | |
|---|---|
| [10 — Build PRD](docs/build/10-BUILD-PRD.md) | What this build delivers and how it's judged |
| [11 — Design doc](docs/build/11-DESIGN-DOC.md) | How it works, module by module |
| [12 — Tech stack](docs/build/12-TECH-STACK.md) | Every component and its licence |
| [13 — Proof report](docs/build/13-PROOF-REPORT.md) | Measured results, bugs found, honest limits |
| [14 — Scenario tests](docs/build/14-SCENARIO-TESTS.md) | Every promised scenario, run for real |
| [15 — Market & uniqueness](docs/build/15-MARKET-AND-UNIQUENESS.md) | Who needs it, competitors, what's unique |
| [16 — Live test guide](docs/build/16-LIVE-TEST-GUIDE.md) | Test it yourself with your own voice |
| [17 — Deck parity](docs/build/17-DECK-PARITY.md) | How the build maps to the original research design |
| [20 — Phrasebook](docs/build/20-PHRASEBOOK.md) | Verified list of what you can say |
| [docs/](docs/00-README.md) | The original research design (Linux target) |

---

*VoiceShell started as a research concept — "Speak to your OS. Securely. Offline." — and is a
working prototype of its core idea: that an AI agent can be let loose on a real computer safely,
because a small deterministic layer, not the AI, decides what may run.*
