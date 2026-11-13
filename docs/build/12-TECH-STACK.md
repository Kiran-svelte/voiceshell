# VoiceShell W1 — Tech Stack

All components are free, open-source, and run locally. Nothing calls the internet at
runtime; the only network socket is the Ollama server on `127.0.0.1:11434`.

The table maps each layer of the deck (slides 4, 6, 8) to what is actually installed. "Deck
component" is what the slide names; "Built here" is what runs on this Windows laptop.

| Deck layer | Deck component | Built here | Licence | Note |
|---|---|---|---|---|
| L1 audio capture | PipeWire · Silero VAD · WebRTC NS | sounddevice (PortAudio) · **Silero VAD v6** (bundled in faster-whisper, run chunk-by-chunk) · spectral-gating noise reduction (`noisereduce`) | MIT / MIT / MIT | WebRTC NS needs a C++ compiler on Windows; spectral gating is the substitute |
| L2 speech recognition | Whisper · faster-whisper · whisper.cpp | **faster-whisper `small.en`** (CTranslate2, int8 CPU) + CLI-vocabulary `initial_prompt` | MIT | Per-word confidence drives the "no DELETE when unsure" rule |
| L3 context assembly | Claude/GPT-4/Llama 3 · MemoryBank · $CWD+history+/proc | $CWD · env · **psutil** (/proc equivalent) · **watchdog** (inotify equivalent) · command history · **MemoryBank** (SQLite + BM25) · sliding window | BSD / MIT / — | All of it labelled untrusted → can't pick a delete target |
| L4 intent & planning | LLM function calling · NL→bash | **Llama 3.2 3B** via Ollama, **Ollama tool-calling** (JSON-schema fallback) | Llama 3.2 Community · MIT | Deck's "Llama 3 local". `VOICESHELL_MODEL` swaps in Qwen2.5-Coder-3B |
| L5 agentic orchestration | LangGraph · ReAct · Reflexion | **LangGraph** state machine (plan→gate→confirm→execute→reflect→respond) with a **Reflexion** node | MIT | The turn loop is a real LangGraph graph |
| L6 shell execution & safety | PTY (openpty) · AppArmor · seccomp · namespaces · ANSI strip | Git Bash on **ConPTY** (pywinpty) · **Windows Job Object** (memory + process caps, kill-tree) · workspace jail · ANSI strip | GPL / — | **No kernel MAC/seccomp/namespaces on Windows** — see §limits. PTY built; pipes are the default (faster, byte-exact) |
| L7 TTS feedback | Piper TTS · espeak-ng · CLI phoneme lexicon | **Piper** engine + **custom CLI lexicon**; Windows SAPI fallback | **engine GPL-3.0** (`OHF-Voice/piper1-gpl`); espeak-ng GPL-3.0 | ⚠️ **voice model matters** — see licence note below |
| Safety gate | tree-sitter-bash · risk tiers | tree-sitter + tree-sitter-bash, model-free gate, hashed ruleset | MIT | Identical to design |
| Preview | dry-run enumeration | **shadow execution** (temp-dir copy + measured diff) | — | Exceeds the deck: the preview *is* the command |
| Policy (slide 9) | identity→UID, trust tiers, allow rules, audit | **Resemblyzer** speaker ID → trust level · allow rules · hash-chained audit · CSV export | Apache 2.0 / stdlib | Voice fingerprint only; no audio stored |

## Install (once, needs internet)

```bash
python -m pip install faster-whisper sounddevice pyttsx3 tree-sitter tree-sitter-bash httpx rich pytest psutil langgraph pywinpty watchdog piper-tts noisereduce resemblyzer
```

```bash
ollama pull llama3.2:3b
```

```bash
python -m piper.download_voices en_US-lessac-medium --data-dir models/piper
```

The Whisper weights (~470 MB) download on first ASR use and are cached. After that the
machine can be fully offline. `VOICESHELL_MODEL=qwen2.5-coder:3b` switches the planner model;
`VOICESHELL_EXEC=pty` runs commands on a pseudo-terminal; `VOICESHELL_PLANNER=json` uses the
schema planner instead of function calling.

## Licence note — verified 2026-10-16 (corrects two earlier entries)

Everything is open source, but two items are **not** as permissively licensed as earlier
drafts of this doc stated:

| Item | Earlier (wrong) | Verified now | Impact |
|---|---|---|---|
| **Silero VAD** | MIT | **MIT** ✓ (confirmed: repo LICENSE, PyPI, NVIDIA NGC) | none — fully permissive |
| **Piper engine** | MIT | **GPL-3.0-or-later** (the maintained `OHF-Voice/piper1-gpl`; the old MIT `rhasspy/piper` was archived read-only Oct 2025) | open source, but copyleft — matters only for a *closed-source* product |
| **`en_US-lessac-medium` voice** | "free" | trained on the **Blizzard Challenge 2013 Lessac corpus — non-commercial research terms** | fine for a research project; **for a public/commercial release, swap it** |

**If a fully permissive, commercial-safe voice is needed**, replace the lessac voice with a
CC-licensed Piper voice (e.g. a LibriTTS/CC-BY voice), or rely on espeak-ng (GPL, no model
restriction) or the Windows SAPI fallback. VoiceShell uses the Windows voice automatically
when no Piper model is present, so it runs with no TTS licence concern at all out of the box.

All other components are permissive (MIT / BSD / Apache 2.0) except the deliberately-GPL
pieces (Git Bash, espeak-ng) and the **Llama 3.2 Community Licence** (open weights, free for
this scale of use; note it is not OSI-approved — `VOICESHELL_MODEL=qwen2.5-coder:3b` switches
to Apache-2.0 Qwen, which the deck's own ADR-05 preferred for exactly this reason).

## Run

```bash
python -m voiceshell --text
```

```bash
python -m voiceshell --voice
```

```bash
python -m voiceshell verify
```

## Hardware budget (measured on the target machine)

| Resource | Use |
|---|---|
| Disk | ~2 GB model + ~470 MB Whisper |
| RAM, idle | Python process + Ollama keep-alive |
| GPU | Qwen 3B Q4 fully offloaded to the GTX 1650 |
