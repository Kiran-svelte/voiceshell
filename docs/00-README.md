# VoiceShell — Documentation Set

**An agentic AI framework for natural-language, voice-controlled operating system interaction.**
Fully offline. No paid models. No cloud. No network.

> *Speak to your OS. Securely.*

---

## Read in this order

| # | Document | What it answers | Lines |
|---|---|---|---|
| **06** | **[Runtime Walkthrough](06-RUNTIME-WALKTHROUGH.md)** ← **start here** | What is it actually like? Millisecond traces and a full day of use. | ~700 |
| **01** | [PRD](01-PRD.md) | What are we building and why? Requirements, personas, non-goals. **No tech.** | ~430 |
| **02** | [SAD / HLD](02-SAD-HLD.md) | How is it built? The honest first design — every tool, layer, and connection. | ~1460 |
| **02X** | **[Extreme Architecture](02X-ARCHITECTURE-EXTREME.md)** | How does it *actually* work after 18 months of shipping? Cascades, speculation, taint tracking. **Supersedes 02 where they conflict.** | ~1150 |
| **03** | [ICD](03-ICD.md) | Exact message contracts between all 11 processes. **Normative.** | ~700 |
| **04** | [Threat Model](04-THREAT-MODEL.md) | What can go wrong and what stops it. **Contributions C3 + C4.** | ~800 |
| **05** | [Test & Eval Plan](05-TEST-EVAL-PLAN.md) | How do we know it works? **Specifies VoiceShell-Bench (C5).** | ~750 |

**Why 02 and 02X both exist:** 02 is the architecture a competent team designs *before*
building. It is correct, defensible, and misses its latency target on CPU. 02X is where
that team ends up after measuring. **The gap between them is the engineering
contribution** — read both, in that order.

---

## The system in one paragraph

You speak. A 40 MB wake-word detector hears one word and wakes the pipeline. Streaming
speech recognition produces a partial transcript while you are still talking, which the
system uses to start planning early. A four-tier cascade routes your request: 41% are
matched by a compiled finite-state transducer in 3 ms, 21% by a 0.5B slot filler, 35% by a
7B coder model with speculative decoding, 3% by a deliberation mode. Whatever tier
produced it, the proposed command passes through a 3,400-line deterministic gate — no
model inside — which parses it to an AST, classifies its risk, checks where every argument
came from, and verifies it falls within the capability envelope derived from your own
sentence. Anything irreversible is rehearsed in a copy-on-write overlay so the confirmation
prompt states measured fact, not an estimate. Execution happens in a pre-warmed sandbox
with no network, a syscall allowlist, and a mandatory access control profile. Output is
stripped, fenced, and labelled untrusted before it re-enters context. Everything is
hash-chain logged. Nothing leaves the machine, ever.

---

## The stack — all free, all offline, all OSI-licensed

| Layer | Component | Licence |
|---|---|---|
| Audio | PipeWire · RNNoise · Silero VAD · openWakeWord | MIT / BSD / Apache 2.0 |
| Speech | faster-whisper · whisper.cpp · WFST biasing | MIT |
| **Model** | **Qwen2.5-Coder-7B-Instruct Q4_K_M** | **Apache 2.0** |
| Draft model | Qwen2.5-Coder-0.5B (speculative decoding + Tier 1) | Apache 2.0 |
| Runtime | llama.cpp (GBNF grammar, radix KV cache) | MIT |
| Safety | tree-sitter-bash · bubblewrap · libseccomp · AppArmor · cgroups v2 | MIT / LGPL / GPL |
| Speech out | Piper TTS · espeak-ng · custom CLI phoneme lexicon | MIT / GPL |
| Core | Rust (hot path) · Python (orchestration) · SQLite · FAISS | — |

**Zero paid components. Zero network dependencies at runtime. Verified in CI by an
automated licence inventory and by packet capture.**

> Llama 3 was rejected as the primary model. Its Meta Community Licence is not
> OSI-approved, which undermines the open-and-indigenous funding argument. Qwen2.5-Coder
> is Apache 2.0 and generates better bash. See [ADR-05](02-SAD-HLD.md#2-key-architectural-decisions).

---

## Performance

| | Baseline design (02) | Extreme design (02X) |
|---|---|---|
| Tier 0 p50 | — | **168 ms** |
| Model path p50, CPU | 1900 ms | **740 ms** |
| Model path p50, GPU | 720 ms | **310 ms** |
| **Weighted mean, CPU** | ~2100 ms | **437 ms** |
| After 8 weeks of use | — | **312 ms** |

**On the proposal's 800 ms claim:** unachievable with the obvious architecture; achievable
at p50 with the cascade; **not** achievable at p95. All three facts are published.
See [Extreme Architecture §14](02X-ARCHITECTURE-EXTREME.md#14-the-complete-optimised-latency-budget).

---

## The five research contributions

| | Contribution | Defined in |
|---|---|---|
| **C1** | CLI-domain speech corpus — first public dataset for POSIX vocabulary, with the **PTER** and **CVER** metrics that predict task success better than WER | [Test Plan §10](05-TEST-EVAL-PLAN.md#10-the-speech-corpus-deliverable-c1) |
| **C2** | Live-state grounded planning — commands conditioned on real filesystem, `/proc`, and history, assembled speculatively | [SAD §8](02-SAD-HLD.md#8-deep-dive-context-assembly) · [02X §5](02X-ARCHITECTURE-EXTREME.md#5-speculative-planning) |
| **C3** | **Prompt-injection taxonomy for shell agents** — 12 classes, 6 of them novel, with a 2,100-payload corpus | [Threat Model §5](04-THREAT-MODEL.md#5-the-injection-taxonomy-contribution-c3) |
| **C4** | **Layered safety architecture** — nine independent defences, model-checked, differentially fuzzed | [Threat Model §7](04-THREAT-MODEL.md#7-the-defence-architecture-contribution-c4) |
| **C5** | **VoiceShell-Bench** — 200 tasks, first benchmark combining voice + live OS state + safety + latency | [Test Plan §6–9](05-TEST-EVAL-PLAN.md#6-voiceshell-bench-overview) |

### The one we would patent

**The Monotonic Capability Envelope** ([02X §10](02X-ARCHITECTURE-EXTREME.md#10-the-monotonic-capability-envelope)).

> Authority for a turn is derived once, from the user's own utterance, and can only
> shrink. It may never grow — regardless of anything the agent reads while executing.

This makes an entire class of agentic failure *impossible* rather than *unlikely*, without
needing to detect the cause. It defends equally against a deliberate injection (PI-9) and
against ordinary model drift. It is decidable in 3 ms, exhaustively testable, and
model-independent. **This — not the pipeline integration — is the defensible IP.**

---

## The safety argument in five lines

```
  1.  We assume the language model is fully compromised. We do not try to fix that.
  2.  Safety rests on a 3,400-line deterministic gate containing no model.
  3.  Four independent checks: risk tier, provenance, envelope, path scope.
  4.  Below them, four kernel layers, each assuming everything above has failed.
  5.  No sandbox → no execution. No audit log → no execution. No exceptions.
```

---

## Build order

```
  M1  Skeleton    typed input, sandbox, audit log, fail-closed        no model, no voice
  M2  Reasoning   7B + grammar + gate + envelope + confirmation       still typed
  M3  Voice       streaming ASR, endpointing, TTS, spoken gates
  M4  Agency      multi-step, recovery, provenance, sanitisation
  M5  Hardening   cascade, all optimisations, corpus, human study
  M6  Release     corpus + benchmark + framework published
```

**Build the dangerous part first, while input is still typed and deterministic.**
Get M1 and M2 right before any microphone is involved.

### If your team can only build five things

From [02X §18](02X-ARCHITECTURE-EXTREME.md#18-optimisation-ledger):

```
  1.  Pre-warmed sandbox pool           −39 ms/command, one week of work
  2.  Tier 0 FST cascade                the single biggest win in the system
  3.  Monotonic Capability Envelope     ~400 lines; the strongest safety property
  4.  Terse output schema               one afternoon, −853 ms
  5.  Adaptive semantic endpointing     −132 ms and fewer truncations
```

Those five take the CPU path from **2412 ms to ~900 ms** and deliver the project's
strongest research claim.

---

## Corrections to the source deck

| Slide | Issue | Resolution |
|---|---|---|
| 4 vs 8 | Layer count disagrees (6 vs 7); planning/orchestration merged in one, split in the other | Use 7 layers ([SAD §4](02-SAD-HLD.md#4-container-view-c4-level-2)) |
| 7 vs 10 | Corpus size stated as both 200+ and 100 | **200 tasks.** 100 is the simple tier alone ([Test Plan §7](05-TEST-EVAL-PLAN.md#7-the-task-corpus)) |
| 4 | Lists Claude / GPT-4 at L3 | **Removed.** Breaks offline, privacy, latency, and sovereignty claims simultaneously |
| 2 | Contents promises Team Competency, Milestones, Research Infrastructure | **Those slides do not exist.** Serious gap for a funding pitch — must be written |
| 5 | 800 ms threshold asserted as a requirement | Treated as a research hypothesis; validated at p50, refuted at p95 |

---

## Still to write

| Document | Why it matters |
|---|---|
| **Project Plan — WBS, milestones, RACI** | The deck promises this slide and it is missing. A funding panel will notice. |
| **Risk Register** | Top entry: the 800 ms budget. Needs a named owner. |
| **LLD** | Module-level design. **Do not start before the ICD is stable.** |
| **ADR log** | One page per decision, ongoing. Seed it from [SAD §2](02-SAD-HLD.md#2-key-architectural-decisions). |
| **Data Management Plan** | **Ethics approval and consent forms are required before any voice recording begins.** |
| **Patent disclosures ×4** | File before the open-source release — publication destroys novelty in most jurisdictions. |
| Deployment runbook | systemd, Ansible, Jenkins, Docker |
| README / CONTRIBUTING / LICENSE / SECURITY.md | The public face |

---

**Source deck:** `VoiceShell_02 - final_to students.pptx` (12 slides)
**Principal Investigator:** Dr. A. Senthil Kumar
