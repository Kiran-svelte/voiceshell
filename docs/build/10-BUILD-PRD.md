# VoiceShell — Build PRD (Release "W1": the runnable Windows build)

| Field | Value |
|---|---|
| Document ID | VS-BPRD-010 |
| Status | Implemented — see [12-TECH-STACK](12-TECH-STACK.md) and [13-PROOF-REPORT](13-PROOF-REPORT.md) |
| Parent | [01-PRD](../01-PRD.md) (the research PRD). This document narrows it to what is built and runnable **on this machine today**. |
| Target machine | Windows 11, 16 logical cores, 7.4 GB RAM, GTX 1650 4 GB, no WSL |

---

## 1. What we are shipping

A working, offline, voice-controlled shell agent. You speak (or type) a request in plain
English; VoiceShell works out the bash command, checks it with a deterministic safety
gate that contains no AI, asks you to confirm anything that changes or deletes files,
runs it confined to one workspace folder, and speaks the result back.

> **Speak to your OS. Securely. Offline.** — same promise as the parent PRD, delivered on
> Windows by running commands in Git Bash instead of a Linux sandbox.

## 2. Why a narrowed release

The parent PRD targets Ubuntu and relies on Linux kernel isolation (bubblewrap, seccomp,
AppArmor, cgroups). Those do not exist on Windows. Rather than build nothing, W1 ships
every layer that is **not** kernel-specific and states plainly which layer is missing.

| Parent-PRD layer | W1 status |
|---|---|
| Voice in (push-to-talk, endpointing, ASR) | **Built** |
| Spoken-form normalisation ("dash l" → `-l`) | **Built** |
| Tier 0 template matcher (no model) | **Built** |
| Tier 2 language-model planner, schema-constrained | **Built** (Qwen2.5-Coder **3B**, not 7B — RAM limit) |
| Tier 1 slot filler, Tier 3 deliberation | Not built (Tier 2 covers both) |
| Live-state grounding | **Built** |
| Deterministic gate: AST parse, risk tiers, path scope | **Built** |
| Provenance / taint rules T1–T3 | **Built** |
| Monotonic Capability Envelope | **Built** |
| Graduated confirmation + shadow-execution preview | **Built** (copy-based shadow instead of overlayfs) |
| Reversible deletes (trash + "undo that") | **Built** |
| Output sanitisation + nonce fencing | **Built** |
| Hash-chained, fail-closed audit log | **Built** |
| Kernel confinement (namespaces/seccomp/AppArmor/cgroups) | **Not possible on Windows.** Replaced by workspace jail + env scrub + timeouts + network-verb ban. Documented as weaker. |
| Wake word | **Built** (`handsfree` mode): wake word "VoiceShell", spoken answers, silence = no. Push-to-talk kept as `voice` mode |
| Speech corpus (C1), 200-task bench (C5) | Scaled-down bench built (see §6) |

## 3. Users (unchanged from parent)

Ananya (learning developer), Ravi (accessibility), Meera (operator), Dr. Iyer (researcher).

## 4. In scope for W1

1. Typed mode, voice mode (microphone, push-to-talk), and audio-file mode.
2. Single-step and multi-step tasks (≤ 5 steps) with bounded retry on failure.
3. Risk tiers READ / WRITE / DESTRUCTIVE / FORBIDDEN, decided without the model.
4. READ runs immediately; WRITE needs one approval; DESTRUCTIVE needs a per-command
   explicit "yes" after a **measured** preview; FORBIDDEN can never run.
5. All commands confined to one workspace folder (`./workspace` by default).
6. Every turn written to a tamper-evident audit log before anything executes.
7. Spoken + on-screen results; every command shown before and after it runs.
8. No network use at runtime: the model runs on localhost; network tools are forbidden.

## 5. Out of scope for W1

Everything in the parent PRD's non-goals, plus: Linux kernel sandbox, wake word, speaker
ID, on-device learning, speculative planning, Tier 1/3, a GUI. The keyboard stays
authoritative (NG-1).

## 6. Acceptance criteria — how W1 is judged

Each is measured by the automated proof run and reported in
[13-PROOF-REPORT](13-PROOF-REPORT.md).

| ID | Criterion | Target | Parent ref |
|---|---|---|---|
| AC-1 | Unit tests for gate, envelope, provenance, sanitiser, audit | 100 % pass | — |
| AC-2 | Simple-task success on the W1 bench | ≥ 85 % | GO-1 |
| AC-3 | Multi-step task success | ≥ 60 % | GO-5 |
| AC-4 | Unconfirmed destructive executions across the whole bench | **0** | GO-2, NFR-13 |
| AC-5 | Injection payloads that cause any unauthorised change | ≥ 95 % blocked | GO-6 |
| AC-6 | Forbidden-class and escape attempts executed | **0** | FR-47, NFR-33 |
| AC-7 | Over-confirmation on read-only tasks | ≤ 2 % | NFR-14 |
| AC-8 | Audit chain verifies; a tampered log is detected | Yes / Yes | FR-62/63 |
| AC-9 | Voice end-to-end: real speech audio → correct effect | ≥ 80 % of spoken tasks | FR-01..FR-11 |
| AC-10 | Latency, Tier 0 p50 | ≤ 250 ms | NFR-01 |
| AC-11 | Latency, model path p50 | reported honestly (target 900 ms is for 7B on 6-core Linux; W1 hardware differs) | NFR-02 |
| AC-12 | Deletes are recoverable with "undo that" | Yes | D7 |

## 7. Use cases demonstrated

UC-1 query · UC-2 batch modification · UC-3 destructive with spoken gate · UC-4 multi-step
with recovery · UC-5 ambiguity ("delete it") · UC-6 refusal · UC-7 hostile file content —
all from the parent PRD §7, each run live in the proof report.
