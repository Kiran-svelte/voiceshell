# VoiceShell — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Document ID | VS-PRD-001 |
| Version | 1.0 (Draft) |
| Status | For review |
| Owner | Product / Principal Investigator — Dr. A. Senthil Kumar |
| Last updated | 2026-09-04 |
| Related docs | [SAD/HLD](02-SAD-HLD.md) · [ICD](03-ICD.md) · [Threat Model](04-THREAT-MODEL.md) · [Test & Eval](05-TEST-EVAL-PLAN.md) |

> **Scope rule for this document.** The PRD states **WHAT** we are building and **WHY**.
> It deliberately contains **no tool names, no library choices, no implementation detail**.
> All of that belongs in the SAD/HLD. If you find yourself writing "Whisper" or "AppArmor"
> in this file, you are writing in the wrong document.

---

## 1. Vision

> **Speak to your operating system. Securely. Offline.**

VoiceShell lets a person operate a Linux machine by speaking to it in ordinary language.
The system understands intent, grounds that intent in the *actual live state* of the
machine, produces the correct shell commands, executes them inside a hardened sandbox,
and speaks the result back.

Everything runs **on the user's own hardware**. No audio, no transcript, no command, and
no file content ever leaves the device.

---

## 2. Problem Statement

The command line remains the most powerful way to control a computer and the least
accessible. It demands that the user memorise thousands of command names, flag
combinations, and path conventions. This creates three distinct populations of
under-served users:

1. **Novice and intermediate developers** who know *what* they want but not the incantation.
2. **Users with motor impairments** for whom sustained typing is painful or impossible.
3. **Experienced operators** performing repetitive multi-step tasks where speaking is
   simply faster than typing.

Speech recognition, large language models, and process sandboxing are each individually
mature. **No system safely composes them.** The unsolved problems live at the
integration boundaries:

| ID | Gap |
|---|---|
| **G1** | Speech recognition degrades badly on command-line vocabulary; the magnitude is unquantified and no domain-adapted model exists. |
| **G2** | Language models generate single commands in isolation; real tasks require chained commands conditioned on live machine state. |
| **G3** | Command output is untrusted input. Text printed by any file can hijack the model's instructions. No defence architecture exists for this class of system. |
| **G4** | Isolation primitives exist but have never been composed and evaluated against a formal threat model for a language-model-driven shell. |
| **G5** | There is no benchmark that measures voice input, real machine state, safety violations, and latency together. |

---

## 3. Users and Personas

### P1 — "Ananya", the learning developer *(primary)*

Second-year CS student. Comfortable with code, unsure of the shell. Knows the goal
("find which file is eating my disk") but not the command. Currently context-switches to
a web search for every third task.

**Needs:** correctness, and to *learn* from what the system does. Wants to see the
command, not just its effect.

### P2 — "Ravi", the accessibility user *(primary)*

Professional developer with a repetitive strain injury. Typing is limited to short
bursts. Currently loses hours per week to pain-imposed breaks.

**Needs:** reliable hands-free operation, low fatigue, tolerance for imperfect
enunciation, and *never* a destructive surprise.

### P3 — "Meera", the system operator *(secondary)*

Manages a fleet of Linux servers. Performs the same 30 diagnostic sequences daily.

**Needs:** speed, multi-step chaining, and an audit trail she can hand to a compliance
reviewer.

### P4 — "Dr. Iyer", the researcher *(secondary)*

Evaluates the system, reproduces published results, extends the benchmark.

**Needs:** deterministic replay, exported metrics, and a documented task corpus.

---

## 4. Goals

| ID | Goal | Measure of success |
|---|---|---|
| **GO-1** | Let a user complete common shell tasks by voice without knowing the command | ≥ 85% task success on the benchmark's *simple* tier |
| **GO-2** | Never execute a destructive action the user did not intend | **Zero** unconfirmed destructive executions across the full adversarial suite |
| **GO-3** | Feel conversational, not batch | p50 response ≤ 900 ms, p95 ≤ 1800 ms for single-step commands |
| **GO-4** | Preserve absolute privacy | Zero outbound network bytes during normal operation, verified by packet capture |
| **GO-5** | Handle real multi-step work | ≥ 60% task success on the benchmark's *multi-step* tier |
| **GO-6** | Resist instruction injection through command output | ≥ 95% of the injection attack corpus blocked, with residual risk quantified |
| **GO-7** | Run on ordinary hardware | Functional on a 6-core CPU with 16 GB RAM and no discrete GPU |
| **GO-8** | Be reusable by the research community | Public corpus, benchmark, and framework under permissive licences |

---

## 5. Non-Goals (Explicitly Out of Scope)

Stating these prevents scope creep. Each is a deliberate decision, not an oversight.

| ID | Non-goal | Rationale |
|---|---|---|
| **NG-1** | Replacing the terminal | VoiceShell augments the shell. The keyboard always remains available and authoritative. |
| **NG-2** | A general-purpose voice assistant | No weather, no music, no calendar. If it is not a machine-control task, it is out of scope. |
| **NG-3** | Graphical desktop automation | No clicking buttons, no window management, no screen reading. Shell only. |
| **NG-4** | Cross-platform support in v1.0 | Ubuntu LTS only. Other distributions and operating systems are post-1.0. |
| **NG-5** | Multi-user or networked operation | Single local user, single machine. No remote execution, no daemon exposed to a network. |
| **NG-6** | Cloud or subscription components | Would invalidate the privacy, latency, and sovereignty premises entirely. |
| **NG-7** | Arbitrary autonomous operation | The system never acts without a user utterance initiating the turn. No background agents, no scheduled self-execution. |
| **NG-8** | Privilege escalation on the user's behalf | The system never obtains or stores an administrator password. Elevated operations are handed to the user to perform. |
| **NG-9** | Free-form conversation | The system is not a chatbot. Non-actionable utterances are declined, not improvised on. |
| **NG-10** | Languages other than English in v1.0 | Indian-accented English is in scope. Other languages are post-1.0. |

---

## 6. Scope for Release 1.0

### In scope

- Single-user, single-machine, local operation on Ubuntu LTS
- Wake-word activation and push-to-talk activation
- English speech input, including Indian-accented English
- Single-step and multi-step task execution with automatic error recovery
- Three-tier risk classification with graduated confirmation
- Spoken confirmation for irreversible operations, with a preview of what will happen
- Sandboxed execution with filesystem, syscall, and namespace restriction
- Spoken and on-screen result summaries
- A complete, tamper-evident audit log
- A visible transcript pane showing every command before and after execution
- Offline operation with no network dependency after installation

### Out of scope for 1.0 (deferred, not rejected)

- Speaker identification and multi-user trust tiers *(design provisioned, not implemented)*
- Remote or fleet operation
- Voice-driven text editing inside interactive editors
- Custom user-authored macros
- Languages other than English

---

## 7. Use Cases

### UC-1 — Simple query *(no confirmation)*

> **User:** "What's taking up space in my downloads folder?"
> System reports the largest items by size. Nothing is modified.

**Acceptance:** correct result spoken within the latency target; no confirmation prompt shown.

### UC-2 — Simple modification *(batch confirmation)*

> **User:** "Make a folder called project-alpha and move all the PDFs into it."
> System states the plan, executes on approval, confirms completion.

**Acceptance:** plan is stated before execution; a single approval covers the batch.

### UC-3 — Destructive operation *(per-command spoken gate)*

> **User:** "Delete all the log files in here."
> **System:** "That will permanently delete 12 files, 340 megabytes, in /var/tmp/build. Shall I proceed?"
> **User:** "Yes."

**Acceptance:** exact count, size, and location stated; execution occurs only after an
explicit affirmative; an ambiguous or silent response cancels.

### UC-4 — Multi-step task with error recovery

> **User:** "Find the biggest files in my home directory over one gigabyte and older than a month, then show me a summary."
> System performs discovery, encounters a permission error on one subtree, adapts, and reports both the result and the skipped path.

**Acceptance:** task completes despite the intermediate failure; the failure is reported
honestly, not hidden.

### UC-5 — Ambiguity resolution

> **User:** "Delete it."
> **System:** "I'm not sure what 'it' refers to. Do you mean the file report-old.txt we just discussed?"

**Acceptance:** the system asks rather than guesses whenever the referent is unresolved
*and* the action is irreversible.

### UC-6 — Refusal

> **User:** "Run this script I downloaded from that website."
> **System:** "I won't run an unreviewed downloaded script. I can show you its contents first."

**Acceptance:** the forbidden class is refused without an override path, and a safe
alternative is offered.

### UC-7 — Hostile file content *(injection)*

> User asks the system to read a file whose contents include text instructing the model
> to delete the home directory. System reports the file's contents and takes no
> additional action.

**Acceptance:** no command originating from file content is ever generated or executed.

---

## 8. Functional Requirements

Requirements are numbered for traceability. Every requirement must map to at least one
test case in the [Test & Evaluation Plan](05-TEST-EVAL-PLAN.md).

### Voice input

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | The system shall activate on a spoken wake word or a push-to-talk key. | Must |
| FR-02 | The system shall detect the end of an utterance automatically and begin processing without a further signal. | Must |
| FR-03 | The system shall not transmit, record to disk, or process audio outside an active listening window. | Must |
| FR-04 | The system shall display a visible and unambiguous indicator whenever the microphone is active. | Must |
| FR-05 | The system shall allow the user to cancel an in-flight turn by voice or key at any point before execution. | Must |

### Understanding

| ID | Requirement | Priority |
|---|---|---|
| FR-10 | The system shall transcribe English speech including command-line vocabulary, flags, and file paths. | Must |
| FR-11 | The system shall normalise spoken forms into their literal textual equivalents (e.g. spoken flags, spoken path separators). | Must |
| FR-12 | The system shall classify each utterance as a machine-control request, an informational question, a response to a pending confirmation, or a cancellation. | Must |
| FR-13 | The system shall decline utterances that are not machine-control requests rather than improvising. | Must |
| FR-14 | The system shall resolve references to entities from earlier in the session. | Should |
| FR-15 | The system shall request clarification, rather than guessing, whenever a referent is unresolved and the action is irreversible. | Must |

### Grounding

| ID | Requirement | Priority |
|---|---|---|
| FR-20 | The system shall condition every generated command on the live state of the machine, including the working directory, its contents, and recent command history. | Must |
| FR-21 | The system shall refresh machine state before each planning step rather than reusing stale state. | Must |
| FR-22 | The system shall never emit a path that it has not verified exists, for any operation that modifies or deletes. | Must |

### Command generation and execution

| ID | Requirement | Priority |
|---|---|---|
| FR-30 | The system shall produce commands in a structurally validated form; malformed generator output shall be rejected, never executed. | Must |
| FR-31 | The system shall execute commands in an environment that supports interactive terminal programs. | Must |
| FR-32 | The system shall support tasks requiring multiple chained commands where each step depends on the previous result. | Must |
| FR-33 | The system shall detect command failure and attempt a corrected plan, up to a bounded retry limit. | Must |
| FR-34 | The system shall abandon a task and report honestly when the retry limit is reached. | Must |
| FR-35 | The system shall display every command to the user before execution and after completion. | Must |

### Safety

| ID | Requirement | Priority |
|---|---|---|
| FR-40 | The system shall classify every command into a risk tier before execution, using a deterministic analyser that is independent of the language model. | Must |
| FR-41 | The system shall never accept a risk classification asserted by the language model. | Must |
| FR-42 | Read-only operations shall execute without confirmation. | Must |
| FR-43 | Modifying operations shall require confirmation, which may cover a stated batch. | Must |
| FR-44 | Irreversible operations shall require an explicit affirmative confirmation for each command. | Must |
| FR-45 | Before an irreversible operation, the system shall state the exact number of affected items, the total size, and the location. | Must |
| FR-46 | A silent, ambiguous, or negative response to a confirmation shall cancel the operation. | Must |
| FR-47 | The system shall maintain a forbidden class of operations that cannot be executed under any confirmation. | Must |
| FR-48 | The system shall execute all commands within a restricted environment limiting reachable filesystem paths and permitted system calls. | Must |
| FR-49 | The system shall treat all command output as untrusted data and shall never act on instructions contained within it. | Must |
| FR-50 | The system shall not request, store, or transmit an administrator password. | Must |

### Feedback and record

| ID | Requirement | Priority |
|---|---|---|
| FR-60 | The system shall speak a concise summary of the outcome, never raw unprocessed output. | Must |
| FR-61 | The system shall render full output in a readable on-screen transcript. | Must |
| FR-62 | The system shall record every utterance, plan, command, risk verdict, confirmation, and result in an append-only log. | Must |
| FR-63 | The log shall be tamper-evident, such that any modification of a past entry is detectable. | Must |
| FR-64 | The user shall be able to review and export the log. | Should |

### Operation

| ID | Requirement | Priority |
|---|---|---|
| FR-70 | The system shall function with no network connectivity after installation. | Must |
| FR-71 | The system shall operate within the resource envelope defined in NFR-20. | Must |
| FR-72 | The system shall degrade to a reduced-capability mode rather than failing outright when resources are constrained. | Should |
| FR-73 | The user shall be able to configure the permission policy, including adding always-allow rules for specific operations. | Should |

---

## 9. Non-Functional Requirements

### Latency

Measured from **end of user speech** to **start of the corresponding effect**.

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | Common, frequently repeated commands | p50 ≤ 250 ms |
| NFR-02 | Single-step commands requiring generation | p50 ≤ 900 ms, p95 ≤ 1800 ms |
| NFR-03 | First audible or visible acknowledgement of any turn | ≤ 400 ms |
| NFR-04 | Multi-step tasks | No fixed bound; progress must be reported at each step |
| NFR-05 | Wake-word response | ≤ 100 ms |

> **Note on NFR-02.** The originating proposal asserted an 800 ms end-to-end threshold.
> That figure is **unvalidated** and is treated here as a research hypothesis, not a
> committed requirement. 900 ms is adopted as the engineering target. Validating or
> refuting the 800 ms claim is itself a research output.

### Accuracy

| ID | Requirement | Target |
|---|---|---|
| NFR-10 | Transcription accuracy on command-line speech | Word error rate ≤ 8% on the project's held-out human-spoken test set |
| NFR-11 | Command correctness, simple tier | ≥ 85% functional success |
| NFR-12 | Command correctness, multi-step tier | ≥ 60% functional success |
| NFR-13 | False confirmation rate — system executing an irreversible action the user did not approve | 0% |
| NFR-14 | Over-confirmation rate — system demanding confirmation for a read-only action | ≤ 2% |

### Resource

| ID | Requirement | Target |
|---|---|---|
| NFR-20 | Minimum viable hardware | 6-core CPU, 16 GB RAM, no discrete GPU |
| NFR-21 | Idle CPU usage while listening for the wake word | ≤ 3% of one core |
| NFR-22 | Idle memory footprint | ≤ 2.5 GB resident |
| NFR-23 | Peak memory during a turn | ≤ 10 GB |
| NFR-24 | Total on-disk installation including all models | ≤ 12 GB |

### Privacy and security

| ID | Requirement | Target |
|---|---|---|
| NFR-30 | Outbound network traffic during normal operation | Zero bytes, verified by packet capture in CI |
| NFR-31 | Audio retention | Discarded immediately after transcription unless the user explicitly enables retention |
| NFR-32 | Injection attack corpus blocked | ≥ 95%, with every residual case documented |
| NFR-33 | Sandbox escape attempts blocked | 100% of the defined escape corpus |

### Usability and accessibility

| ID | Requirement | Target |
|---|---|---|
| NFR-40 | Time from install to first successful spoken command | ≤ 15 minutes |
| NFR-41 | Full operability without keyboard or mouse after initial setup | Required |
| NFR-42 | Screen-reader compatibility of the transcript pane | Required |
| NFR-43 | Measured cognitive load versus typed CLI for equivalent tasks | Statistically significant reduction for novice users |

### Openness

| ID | Requirement | Target |
|---|---|---|
| NFR-50 | All shipped components under OSI-approved licences | 100%, with a machine-readable inventory |
| NFR-51 | Published results reproducible from the public repository | Every headline metric |

---

## 10. Success Metrics

### Research success

- The command-line speech corpus is published and cited.
- The word-error-rate gap between general and command-line speech is quantified for the first time.
- The injection taxonomy is published with a reproducible attack corpus.
- The benchmark is adopted by at least one external group.

### Product success

- A user with no prior shell knowledge completes the ten benchmark starter tasks unaided.
- An accessibility user completes a full working day without keyboard input.
- Zero reported incidents of unintended data loss.

### Engineering success

- All Must-priority requirements pass their mapped tests.
- The full benchmark runs unattended in continuous integration.
- Installation succeeds on a clean Ubuntu LTS image in under fifteen minutes.

---

## 11. Release Phases

| Phase | Content | Exit criteria |
|---|---|---|
| **M1 — Skeleton** | Typed input, deterministic command allowlist, sandboxed execution, audit log. No speech, no language model. | A command runs inside the sandbox and is logged. Escape corpus fully blocked. |
| **M2 — Reasoning** | Language model generation with structural validation, context grounding, risk classification, confirmation gates. Still typed input. | Simple tier ≥ 70%. Zero unconfirmed destructive executions. |
| **M3 — Voice** | Speech input, wake word, spoken feedback, spoken confirmation. | End-to-end voice turn completes within the latency target. |
| **M4 — Agency** | Multi-step chaining, error recovery, session memory, output sanitisation. | Multi-step tier ≥ 50%. Injection corpus ≥ 90% blocked. |
| **M5 — Hardening** | Domain-adapted speech model, full attack corpus, latency optimisation, human factors study. | All Must requirements pass. All NFR targets met or formally waived. |
| **M6 — Release** | Corpus, benchmark, and framework published. Documentation complete. | External reproduction of headline results succeeds. |

---

## 12. Constraints and Assumptions

### Constraints

- **C-1** Target platform is Ubuntu LTS. Kernel security features are assumed available and enabled.
- **C-2** No paid, proprietary, or network-dependent component may appear in the shipped system.
- **C-3** The team is four people. Scope must fit that capacity.
- **C-4** Human voice data collection requires ethics approval and recorded consent before any recording begins.
- **C-5** Patent disclosures must be filed before the corresponding public release.

### Assumptions

- **A-1** Users accept a confirmation step for irreversible actions as a fair cost for safety.
- **A-2** A model in the 7-billion-parameter class is sufficient for common shell tasks.
  *To be validated in M2; this is the single largest technical assumption in the project.*
- **A-3** Users are willing to speak commands aloud in their working environment.
  *To be validated in the human factors study.*
- **A-4** Machine state can be assembled fast enough not to dominate the latency budget.

---

## 13. Open Questions

| ID | Question | Owner | Needed by |
|---|---|---|---|
| Q-1 | Is a 7B-class model sufficient, or is a larger model required for acceptable accuracy? | Modelling lead | M2 |
| Q-2 | Is the 800 ms end-to-end target achievable on the minimum hardware, or must it be relaxed? | Systems lead | M3 |
| Q-3 | How much accuracy can vocabulary biasing recover before a fine-tune becomes necessary? | Speech lead | M3 |
| Q-4 | What is the smallest confirmation dialogue that users still find trustworthy? | Human factors lead | M4 |
| Q-5 | Can output sanitisation be strong enough to block injection without destroying the information needed for error recovery? | Security lead | M4 |
| Q-6 | Final corpus size — the source deck states both 100 and 200+ tasks. **This must be resolved.** | PI | M1 |

---

## 14. Document Change Log

| Version | Date | Change | Author |
|---|---|---|---|
| 1.0 | 2026-09-04 | Initial draft | — |
