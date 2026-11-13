# VoiceShell — Complete Invention Disclosure (for patent filing)

| Field | Value |
|---|---|
| Prepared | 2026-11-11 |
| For | the filing institution + a **registered patent agent** (this is the complete technical basis for the application) |
| Companions | [18-PATENT-PACKAGE](18-PATENT-PACKAGE.md) (process/fees/timeline) · [19-PROVISIONAL-SPECIFICATION-DRAFT](19-PROVISIONAL-SPECIFICATION-DRAFT.md) (Form-2 draft) |
| Reduction to practice | Working implementation in `voiceshell/`; 169 automated tests pass; benchmark 195/205; injection corpus 40/40 |

> **Not legal advice.** This is an engineer's complete disclosure for a registered patent agent to
> turn into claims and a specification. **File a provisional BEFORE any public disclosure** — India
> has no general grace period (see [18 §0](18-PATENT-PACKAGE.md)).

---

## 1. One-line statement of the invention

A deterministic authorization stage, interposed between an automated agent (a language model) and
the execution of operating-system commands the agent generates from a user's input, in which the
**authority for a turn is derived once from the user's own input and can only shrink**, the operation
is checked by four independent model-free tests, its effect is **measured on a disposable copy before
it runs**, any **secret in the data is masked before the model or the log sees it**, and every durable
store is **bounded in size** — making unauthorized, destructive, injection-driven, data-leaking, or
memory-exhausting behaviour impossible as a function of the user's input, independently of the agent.

---

## 2. The technical problem

An automated agent translates a user's natural-language request into executable OS commands and runs
them. This is unreliable in security-relevant ways:

- **Prompt injection:** text in a file or in a command's output induces the agent to issue a command
  the user never asked for (e.g. `rm -rf`).
- **Model drift:** over multiple steps the agent departs from the user's original intent.
- **Mis-transcription:** speech recognition mishears a request as a destructive command.
- **Data exfiltration:** a secret (API key, password, private key) in a file the agent reads can be
  echoed into a later command argument, a spoken reply, or a persistent log.
- **Resource exhaustion:** unbounded context, memory, logs, or a runaway command can exhaust the host.
- **Unverifiable action:** the agent describes one effect and performs another ("says X, does Y").

Existing mitigations (output filtering, asking the model to respect labels, per-operation prompts,
sandboxing) are heuristic, rely on the unreliable component, fatigue the user, or confine damage
without preventing the unintended operation. **No prior mechanism makes a class of these failures
impossible as a decidable function of the user's own input, independently of the agent's correctness.**

---

## 3. System overview

```
 user input (spoken or typed)
   │  [ASR + spoken-form normalisation; per-word confidence]
   ▼
 ┌──────────────────────── DETERMINISTIC AUTHORIZATION STAGE (no model) ────────────────────────┐
 │  (A) derive CAPABILITY ENVELOPE once, from the user input + policy + trust level              │
 │  agent (LLM) proposes a command → parse to AST (model-free) →                                 │
 │  (B) RISK TIER   (C) PATH SCOPE   (D) PROVENANCE/TAINT   (E) ENVELOPE MEMBERSHIP  — all must pass │
 │  (F) MEASURED-PREVIEW confirmation for irreversible ops   (G) FAIL-CLOSED hash-chained AUDIT   │
 │  (H) SECRET REDACTION + bounded output on everything read back                                │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
   │  execute in a resource-bounded confinement (Job Object / kernel sandbox); deletes → reversible store
   ▼  measured result spoken; every durable store is size-bounded
```

The agent is treated as **fully untrusted**. The authorization stage contains no model and is small
enough to be audited.

---

## 4. The novel mechanisms (the patentable matter)

Each is described as a technical mechanism, with its technical effect and its location in the working
code (enabling disclosure / reduction to practice).

### M1 — Monotonic Capability Envelope *(primary)*

From the user input U (and a policy, and a trust level), the system computes **once** an envelope
E₁ ⊆ C, where C is a finite set of operation classes (e.g. {READ, WRITE, DELETE}). The derivation maps
features of U to classes and uses **U only** — never anything observed during execution. Thereafter the
envelope may be updated **only by intersection with a subset** (it may shrink) and **never by union**
(it may never grow). Each proposed operation is permitted only if its class ∈ the current envelope.

- **Contraction triggers** (examples): an injection signature in any observed output → {READ}; any
  provenance refusal → {READ}; two step failures → drop DELETE; input-confidence below a threshold →
  DELETE never admitted; step-count bound exceeded → {READ}.
- **Technical effect:** an operation of a class not derivable from the user's own words **cannot**
  execute, regardless of what the agent proposes or reads. An entire class of unauthorized
  state-changing operations is made **impossible rather than unlikely**, decidably (bounded time),
  exhaustively testable (finite envelope × operations), and **model-independent** (survives swapping
  the model).
- **Code:** `voiceshell/envelope.py` (`derive`, `Envelope.shrink`), enforced in `voiceshell/gate/gate.py`.

### M2 — Provenance / taint rule over verbs and arguments

Every span of information available to the agent carries a provenance label from an ordered lattice
(SYSTEM < USER_INPUT < VERIFIED_OBJECT < UNTRUSTED_METADATA < UNTRUSTED_OUTPUT; join-preserving = least
trusted wins). After the agent proposes a command, the origin of its **verb** and each **argument** is
determined by matching against the labelled spans. A state-changing operation is **refused** if its verb
derives solely from an untrusted span and is not in U (rule T2), or if an argument to it derives solely
from untrusted output and is not corroborated by U (rule T1).

- **Technical effect:** neither the operation nor its target can be chosen by untrusted content; the
  user's spoken word is the only thing that can authorize a verb/target. Recovery is for the user to
  restate the target (promoting it to USER_INPUT).
- **Code:** `voiceshell/provenance.py`, enforced in `gate.py`.

### M3 — Measured-preview ("shadow") confirmation

For an operation above a risk threshold (irreversible delete/overwrite), the exact proposed command is
executed against a **disposable copy** of the affected data, the resulting difference is **measured**,
the copy is discarded, and the user is asked to confirm a prompt stating the **measured** effect (exact
count, size, location). Execution proceeds only on an explicit affirmative.

- **Technical effect:** the confirmation states measured fact, not an estimate, closing the "describes
  X, does Y" failure class; a rehearsal that fails means nothing is asked and nothing changes.
- **Code:** `voiceshell/executor.py` (`shadow`), `voiceshell/summary.py` (`describe_changes`).

### M4 — Four independent, model-free authorization checks

An operation executes only if **all** hold, any one sufficient to refuse: (1) it is fully analysable
by a deterministic parser (else refuse — fail-closed); (2) its class ∈ envelope (M1); (3) every path
stays within a scope boundary; (4) provenance holds (M2); (5) confirmation given if required (M3);
(6) an audit record is committed first (M6). Each conjunct is computed by different code from different
inputs, so **no single fault disables the boundary**; defeating the model defeats none of them.

- **Code:** `voiceshell/gate/{parser.py, rules.py, gate.py}`; the ruleset is hashed and verified at
  start-up (refuse to run if tampered).

### M5 — Input-confidence-gated authority

A class permitting deletion is admitted only if U expresses a deletion intent **and** a confidence
value derived from the speech recognition (mean per-word probability over the request's authority
words, excluding the wake word and file names) exceeds a threshold; below it, deletion is never
admitted, so an unreliable transcription cannot authorize deletion.

- **Technical effect:** mis-transcription cannot escalate to a destructive operation.
- **Code:** `voiceshell/envelope.py` (`DELETE_CONF_THRESHOLD`), `voiceshell/voice/asr.py`.

### M6 — Fail-closed, tamper-evident audit as a precondition to execution

Before any operation executes, a record of the authorization decision is appended to a log in which
each record is cryptographically **hash-chained** to the previous one; if the record cannot be durably
committed, **the operation does not execute**. Any later modification of a past record is detectable;
a cross-process lock makes the chain safe under concurrent writers; a size/break rotation archives the
old chain bound by its SHA-256.

- **Technical effect:** an auditable, non-repudiable, fail-closed record; a forensic reviewer can prove
  exactly which rule produced any historical decision.
- **Code:** `voiceshell/audit.py`.

### M7 — Reversible destructive operations

A deletion is routed to a retained store (trash) from which it can be undone within a retention period,
rather than being destroyed, converting the worst case of a mis-heard or mis-planned deletion from
"data lost" to "data recoverable".

- **Code:** `voiceshell/executor.py` (`trash`, `undo`, `purge_expired`).

### M8 — Speaker-identity trust capping

The identity of the speaker is determined from a voice characteristic (a fingerprint/embedding, not the
recording) and mapped to a trust level; the derived envelope is intersected with the classes permitted
at that level, so an unrecognized speaker receives a reduced (e.g. read-only) envelope, and only the
voice that issued a request can confirm it.

- **Code:** `voiceshell/voice/speaker.py`, `voiceshell/policy.py`.

### M9 — Secret redaction at the context boundary *(security refinement)*

Every byte of command output (including file contents the agent reads) passes a **deterministic
redactor** before it reaches the model, the spoken reply, or the audit log. Credentials, keys, tokens,
connection strings, private keys, and card/identifier patterns are replaced with a typed placeholder
(e.g. `[REDACTED:aws-key]`), a Luhn check distinguishing real card numbers from ordinary long IDs.

- **Technical effect:** a secret the model never sees cannot be placed by the model into a later
  command argument, an outbound-looking string, or the spoken summary; and a redacted log cannot leak a
  secret to whoever later reads it. This **closes a data-exfiltration path** — a recognised technical
  (security) effect.
- **Code:** `voiceshell/security.py` (`redact`), applied in `voiceshell/sanitise.py`.

### M10 — Bounded-resource memory management *(resource refinement)*

Every durable store and the per-step data flow is **size-bounded, independently of the model**: the
untrusted output admitted per step is hard-capped; the long-term memory (a BM25-retrievable store of
past turns) is capped and evicts oldest entries; the command-history file is line-capped; the reversible
trash is both age- and total-size-capped (oldest batches purged past the cap); the audit log is
size-rotated; and each executed command runs under a per-process memory cap, a process-count cap, and a
timeout (OS Job Object / cgroups), with the whole process tree killed together.

- **Technical effect:** bounded memory and disk use; an adversarial or pathological output, a runaway
  command, or long-running use cannot exhaust host resources — a recognised technical effect (reduced
  memory/resource consumption).
- **Code:** `voiceshell/security.py` (`hard_cap`), `voiceshell/context.py` (MemoryBank/history caps),
  `voiceshell/executor.py` (trash caps, `_Job`), `voiceshell/runtime.py` (`resources`, `enforce_limits`).

---

## 5. Why this is patentable (India §3(k) / CRI Guidelines 2025; US §101)

Under India's CRI Guidelines 2025 a computer-related invention is patentable if it provides a
**technical contribution producing a technical effect beyond an incidental one** (novel hardware is not
required). This disclosure supplies multiple recognised technical effects, each tied to the operation of
the machine, not to a business rule:

| Mechanism | Technical effect (recognised category) |
|---|---|
| M1 Monotonic envelope | prevents unauthorized state-changing operations; decidable in bounded time |
| M2 Provenance | prevents injection-driven execution (information-flow security) |
| M3 Measured preview | prevents unverified irreversible operations |
| M4 Four checks | fault-isolated authorization; no single fault disables it |
| M6 Fail-closed audit | tamper-evident, non-repudiable record; integrity |
| **M9 Secret redaction** | **prevents data exfiltration** |
| **M10 Bounded resources** | **reduced/bounded memory and resource consumption** |

The claims must be drafted around *what the machine is prevented from doing / what resource is saved*,
not "a better permission scheme". The security (M9) and resource (M10) effects are among the clearest
to argue, because "reduced memory consumption" and "prevention of unauthorized data disclosure" are
standard accepted technical effects. In the US, the same framing (a specific improvement to computer
security and resource usage, not an abstract idea applied on a generic computer) is the path past §101.

**What is NOT patentable (do not claim):** the overall voice→ASR→LLM→shell→TTS pipeline (a combination
of known components); using an LLM to produce shell commands; the speech corpus and benchmark (publish
as papers / open data).

---

## 6. Novelty and inventive step

Capability-based security, taint tracking, and least-privilege are decades-old fields; a prior-art
search is required (see [18 §6](18-PATENT-PACKAGE.md)). The inventive step is the **specific
combination** not found together in the prior art:

1. authority derived **once from the user's input utterance** (not from a static policy or per-call
   prompt), as a set of operation classes;
2. enforced as a **monotonic (never-increasing) property** over the turn;
3. by a **model-free deterministic stage** that composes it with provenance, measured preview,
   fail-closed audit, secret redaction and bounded resources;
4. such that the guarantees are **decidable, exhaustively testable, and independent of the agent/model**.

No single prior reference is expected to teach authority-from-utterance + monotonic non-expansion +
model-independent enforcement over an agent's proposed OS operations, combined with the data-leak and
resource bounds.

---

## 7. Claims (illustrative; the agent will redraft)

Independent claims 1 (method), 12 (system), 13 (medium) are as in
[19-PROVISIONAL-SPECIFICATION-DRAFT](19-PROVISIONAL-SPECIFICATION-DRAFT.md). Add dependent claims for
the refinements:

**14.** The method of claim 1, further comprising, before information produced by executing an
operation is provided to the automated agent, to a spoken reply, or to a stored log, replacing within
that information any substring matching a predetermined class of sensitive identifier with a typed
placeholder, such that the sensitive identifier is not provided to the agent, spoken, or stored.

**15.** The method of claim 14, wherein a candidate sequence of digits is replaced only if it satisfies
a checksum test characteristic of a payment-card number, whereby non-sensitive numeric identifiers are
preserved.

**16.** The method of claim 1, further comprising bounding, independently of the automated agent, the
quantity of information admitted per step from executing an operation, and bounding the size of each of:
a retrievable store of prior turns, a command-history store, and a reversible-deletion store, by
removing oldest entries when a respective cap is exceeded, such that memory and storage consumption are
bounded during unbounded operation.

**17.** The method of claim 16, wherein each executed operation runs within an operating-system-enforced
limit on process memory, on the number of concurrent processes, and on wall-clock time, and wherein the
entire process tree of the operation is terminated together upon exceeding a limit or upon cancellation.

**18.** The method of claim 1, further comprising deriving a confidence value from a speech-recognition
of a spoken user input and withholding a class permitting deletion from the capability envelope when
the confidence value is below a threshold.

---

## 8. Reduction to practice (evidence the invention works)

A working embodiment exists and is tested; this supports enablement and (in jurisdictions that value it)
actual reduction to practice:

| Evidence | Result |
|---|---|
| Automated tests (gate, envelope, provenance, preview, audit, speaker, policy, **security**, **memory**) | **169 pass** |
| Task benchmark (205 tasks) | **195/205**; **0** destructive ops without explicit confirmation; **0** forbidden ops executed |
| Prompt-injection corpus (40 payloads, 12 attack classes) | **40/40 blocked**; 0 data loss; 0 false claims |
| Secret redaction (M9) | secrets in a read file never appear in the reply, on-screen output, or the audit log (`test_secret_in_a_file_is_never_spoken_or_logged`) |
| Bounded memory (M10) | MemoryBank, history, trash, audit all provably bounded (`test_*_is_bounded`, `trash_size_cap`); `python -m voiceshell resources` reports each store vs its cap |
| Tamper-evidence (M6) | a forged "No→yes" in the log is detected at the exact record; startup refused |

Figures for the specification: FIG. 1 architecture; FIG. 2 turn flowchart; FIG. 3 monotonic contraction;
FIG. 4 provenance lattice; FIG. 5 measured preview; **FIG. 6 redaction at the context boundary**;
**FIG. 7 bounded-store enforcement**.

---

## 9. Industrial applicability

Any system in which an automated agent executes operations derived from natural-language input on a
computer — voice assistants controlling a machine, agentic coding and "computer-use" assistants,
automated administration, accessibility tools — can apply the authorization stage to make an entire
class of unauthorized, injection-driven, data-leaking, or resource-exhausting behaviour impossible as a
function of the user's input, independently of the agent. The stage is OS-independent (kernel confinement
composes beneath it where available) and model-independent.

---

## 10. Filing checklist specific to this disclosure

- [ ] File a **provisional first**, before any public disclosure (repo private, docs private, no talk).
- [ ] Resolve inventorship (who conceived M1/M2/M9/M10) and ownership/assignment.
- [ ] Commission the prior-art search (capability security, taint tracking, LLM-agent security, DLP).
- [ ] Hand this document + [19](19-PROVISIONAL-SPECIFICATION-DRAFT.md) + the 7 figures to a registered
      patent agent.
- [ ] Decide single application (recommended) vs. divisionals; keep M1 as the lead claim, M2/M3/M6/M9/M10
      as dependents.
- [ ] Preserve the test outputs (`bench/out/*.json`, the proof pages) as dated evidence of reduction to
      practice.
