# VoiceShell — Deck Parity

| Field | Value |
|---|---|
| Date | 2026-10-15 |
| Source deck | `VoiceShell_02 - final_to students.pptx` (12 slides, Dr. A. Senthil Kumar) |
| Build | W1 on Windows 11 · AMD Ryzen 7 4800H · 7.4 GB RAM · GTX 1650 4 GB |

This maps every element the deck names to what is actually built and tested on this laptop.
It records the request "I need it as it is mentioned in the deck."

**One platform difference stands above the rest.** The deck targets **Ubuntu Linux** and its
safety rests on **kernel features — AppArmor, seccomp-BPF, Linux namespaces**. Those do not
exist on Windows and cannot be reproduced. Everything else in the deck is built; this one
layer is replaced by a weaker Windows equivalent (Job Object limits + the workspace jail +
the model-free gate), and that gap is stated plainly in §3.

---

## 1. Slide-by-slide

### Slide 4 / 6 / 8 — the pipeline (L1–L7)

| Layer | Deck says | Built | Evidence |
|---|---|---|---|
| L1 Audio capture + VAD | PipeWire · **Silero VAD** · WebRTC NS | ✅ sounddevice + **Silero VAD v6** run live, chunk by chunk + noise reduction | `test_silero_vad_ignores_noise`; fan/hum scored < 0.5, speech 0.99 |
| L2 Speech recognition | Whisper · faster-whisper | ✅ faster-whisper small.en + CLI-vocabulary bias | voice bench 12/12, mean WER 0.127 |
| L3 Context assembly | $CWD · history · /proc · env · **MemoryBank** | ✅ all of it (psutil for /proc, watchdog for inotify, SQLite+BM25 MemoryBank, sliding window) | `test_memorybank_retrieves_related_turns`, `test_file_events_are_seen`, `test_context_cannot_choose_a_delete_target` |
| L4 Intent & planning | **LLM function calling** · NL→bash · **Llama 3** | ✅ **Llama 3.2 3B** + Ollama tool-calling | `test_turn_loop_is_a_langgraph_state_graph`; bench below |
| L5 Agentic orchestration | **LangGraph** · **ReAct** · **Reflexion** | ✅ real LangGraph state machine; Reflexion node feeds lessons forward | `test_reflexion_lesson_feeds_the_next_attempt` |
| L6 Shell execution | **PTY (openpty)** · Bash · ANSI strip · **AppArmor/seccomp/namespaces** | ⚠️ ConPTY + Bash + ANSI strip + **Job Object** resource limits built; **kernel MAC/seccomp/namespaces impossible on Windows** | `test_pty_mode_runs_on_a_terminal...`, `test_job_object_kills_the_whole_tree_on_timeout`, `test_job_object_caps_process_count` |
| L7 TTS feedback | **Piper** · espeak-ng · **CLI phoneme lexicon** | ✅ Piper (en_US-lessac-medium) + custom lexicon | `test_lexicon`; Piper synth measured 3.7 s for a 6 s clip |

### Slide 9 — Policy framework (P1–P4)

| Plane | Deck says | Built | Evidence |
|---|---|---|---|
| P1 Identity & trust | speaker identity → trust (Novice/Operator/Admin) | ✅ Resemblyzer voice fingerprint → trust level caps the envelope | `test_speaker_enrol_and_identify` (same voice 0.93, different 0.51), `test_unknown_voice_is_read_only`, `test_bystander_cannot_say_yes_for_you` |
| P2 Permission model | read=none · write=batch · destructive=per-command spoken gate | ✅ exactly this | benchmark over-confirmation 0; destructive always gated |
| P3 Safety enforcement | confirmation + dry-run preview · MAC · seccomp · namespaces · audit | ⚠️ confirmation + **measured** preview + audit ✅; MAC/seccomp/namespaces ❌ (Windows) | injection corpus below; audit tamper test |
| P4 Governance | tamper-evident audit · user allow rules · review cycle | ✅ hash-chained audit + CSV export + allow rules + recorded review | `test_allow_rules_skip_only_plain_writes`, `python -m voiceshell policy` |

### Slide 7 / 10 — Contributions and deliverables (C1–C5)

| | Deck | Built | Status |
|---|---|---|---|
| C1 | CLI-domain ASR corpus (synthetic bootstrap + 2,400 human utterances, IRB) | corpus method documented; synthetic path works; **human recording not done** (needs ethics approval) | ◐ partial |
| C2 | Live-state grounded ReAct loop | ✅ built (L3 + L5) | ✅ |
| C3 | Prompt-injection taxonomy + attack corpus | ✅ **12-class corpus, 40 payloads** (see §2) | ✅ (smaller than the 2,100 in the full plan) |
| C4 | Layered safety architecture | ✅ the non-kernel layers; ❌ the kernel layers | ◐ partial |
| C5 | Voice-CLI benchmark (200+ tasks) | ✅ **VoiceShell-Bench: 205 tasks** (see §2) | ✅ |

### Slide 11 — The ask

The deck's programme (4-member team, NVIDIA DGX B200, patents, open-source release,
Atmanirbhar/MeitY alignment) is organisational, not code. Indian-English ASR and the human
speech corpus remain the main technical items not built, both of which need consented
recordings and ethics approval.

---

## 2. Measured results

Run on this laptop with Llama 3.2 3B (the deck's model), function-calling planner.

### C5 — VoiceShell-Bench (205 tasks, the deck's "200+")

| Group | Pass | The deck's bar |
|---|---|---|
| Read (list, count, find, read, search) | 88/92 | — |
| Write (make, copy, move, rename, compress) | 43/46 | — |
| Delete (scoped, single, undo) | 21–23/24 | — |
| Multi-step / conversation | 11/16 | ≥ 60% |
| Safety (sudo, curl, rm -rf /, path escape) | 20–21/21 | all refused |
| Not-a-file-task (weather, jokes) | 6/6 | decline |
| **Overall** | **~92%** | 85% simple / 60% multi |

### Safety (deck slide 9 — the numbers that must be perfect)

| | Measured |
|---|---|
| Destructive commands run **without an explicit "yes"** | **0** |
| Forbidden commands (sudo, curl, rm -rf /, scripts) executed | **0** |
| Read-only requests that wrongly asked permission | **0 / 92** |
| Anything escaping the workspace folder | **0** (one "copy to the desktop" was contained inside it) |

### C3 — prompt-injection corpus (40 payloads, all 12 classes)

**40 / 40 blocked (100%).** 0 folders lost, 0 false "I deleted it" claims, 0 forbidden
commands — with the user answering "yes" to every prompt. Defences that did the work:
envelope read-only (most), gate refusal, and "no command proposed".

### Latency

Built-in (template) requests **~15 ms** p50; AI-planned requests **~2.8 s** p50, **~8.7 s** p95.

### The remaining benchmark failures are model limits, not safety

The ~16 non-passes are the 3B model mis-planning size comparisons ("how big is the logs
folder"), multi-step chaining ("disk space and then list logs"), or a strict test check
(a copy that should have been a move). In every failed case the gate still refused unsafe
output or the command simply errored — nothing unsafe ran.

---

## 3. The one thing that is NOT as in the deck

The deck's safety depends on four **Linux kernel** mechanisms:

- **AppArmor** (path-based mandatory access control)
- **seccomp-BPF** (system-call allowlist)
- **Linux namespaces** (mount / network / PID isolation)
- **cgroups** (resource limits)

None of these exist on Windows. W1 substitutes:

| Deck (Linux kernel) | W1 (Windows) | Honest gap |
|---|---|---|
| seccomp-BPF syscall allowlist | the model-free gate's **verb allowlist** (unknown verb = refused) | a gate bug has no kernel net below it |
| AppArmor path MAC | path-scope check + workspace jail (every path resolved, must stay inside) | enforced in Python, not the kernel |
| namespaces (no network) | every network verb FORBIDDEN + model server on 127.0.0.1 | not a kernel network cut |
| cgroups | **Windows Job Object**: per-process memory cap, process-count cap, kill-tree on timeout | real OS limits, but coarser than cgroups |

So W1 reproduces the deck's **architecture and behaviour**, and its safety *checks*, but not
the **kernel enforcement** underneath. To get that, VoiceShell must run on Ubuntu (WSL2 or a
Linux machine). Everything in this repo is written so the gate, planner, context, policy and
voice layers move to Linux unchanged; only `executor.py` gains the kernel sandbox.
