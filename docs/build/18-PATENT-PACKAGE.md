# VoiceShell — Patent Filing Package

| Field | Value |
|---|---|
| Prepared | 2026-10-22 |
| For | Dr. A. Senthil Kumar (PI) and the filing institution |
| Jurisdiction focus | India (Patents Act 1970; CRI Guidelines 2025), with PCT/US path |
| Companion | [19-PROVISIONAL-SPECIFICATION-DRAFT](19-PROVISIONAL-SPECIFICATION-DRAFT.md) — the drafted spec + claims |

> **This is not legal advice.** It is an engineer's filing-preparation package to hand to a
> **registered Indian patent agent/attorney**. Only a registered agent can file and prosecute.
> Every fee and form below must be confirmed on **ipindia.gov.in** before you rely on it.

---

## 0. The one rule that governs everything: file BEFORE you disclose

India has **no general grace period**. A public disclosure before your filing/priority date
destroys novelty almost everywhere in the world. For VoiceShell that means **do not, before a
provisional is on file**:

- push the code to a public GitHub/GitLab repo, or release under an OSI licence;
- publish or present the corpus, the benchmark, or any paper describing the mechanisms;
- demo it publicly, post a video, or describe the mechanisms in a public talk or pitch;
- upload the design docs (this `docs/` set) anywhere public.

(The narrow Section 31 exceptions — a notified exhibition, or a paper to a "learned society"
with a filing within 12 months — are conditional fallbacks, **not a plan**.)

**Therefore the first action is a provisional application that captures a priority date.** After
that provisional is filed, you may publish and open-source freely, *provided* the later complete
specification claims nothing the provisional did not already support.

Sources: [India grace period — RK Dewan](https://www.rkdewan.com/blogs/patent-after-public-disclosure-in-india/) ·
[Intepat: novelty](https://www.intepat.com/blog/decoding-the-requirement-of-novelty-in-patents) ·
[Kan & Krishme: grace period](https://kankrishme.com/grace-period-in-indian-patent-law/)

---

## 1. Honest patentability assessment (read before spending money)

Software/AI patents are **hard** in India and the US. Be realistic:

| Element of VoiceShell | Patentable? | Why |
|---|---|---|
| The overall pipeline (voice → ASR → LLM → sandbox → TTS) | **Unlikely** | A combination of individually known, mature components. Obvious combination; no inventive step. |
| Using an LLM to generate shell commands | **No** | Known art; "computer programme / algorithm per se" under §3(k). |
| **Monotonic Capability Envelope** (authority derived once from the user's utterance, can only shrink) | **Best candidate** | A concrete security *mechanism* with a technical effect: it makes an entire class of unauthorized state-changing operations **impossible rather than unlikely**, decidably and model-independently. Frame as a technical solution to a technical problem (OS security), not as a business rule. |
| **Provenance/taint rule** refusing operations whose verb/arguments derive only from untrusted program output | **Strong secondary** | Information-flow security mechanism; technical effect = prevents injection-driven execution. |
| **Measured-preview ("shadow") confirmation** — rehearse the exact command in a disposable copy, confirm against the measured diff | **Possible secondary** | Technical effect = the confirmation states measured fact, closing the "says X, does Y" failure class. |
| CLI speech corpus, PTER/CVER metrics, the benchmark | **Not patents** | These are datasets/benchmarks → publish as papers + open data (copyright/CC-BY), not patents. |

**The India §3(k) hurdle (CRI Guidelines 2025):** a "computer programme *per se*", algorithm, or
mathematical/business method is not patentable. You survive only by showing a **technical
contribution producing a technical effect beyond an incidental one**. The Guidelines accept
effects like faster processing, reduced memory, lower latency, higher throughput. **Security /
prevention of unauthorized operation is a recognised technical effect** — so the envelope and the
provenance rule must be drafted around *what they prevent in the machine*, not "a better way to
organise permissions". Novel hardware is **not** required (that requirement was removed in 2017;
Delhi HC confirmed 2023).

Sources: [CRI Guidelines 2025 (official PDF)](https://ipindia.gov.in/frontend/pdf/patents/guidelines/GUIDELINES%20FOR%20EXAMINATION%20OF%20COMPUTER%20RELATED%20INVENTIONS%20(CRIs)%20-%202025.pdf) ·
[Intepat: §3(k) & CRI 2025](https://www.intepat.com/blog/cri-guidelines-2025-patent-india-3k) ·
[Anand & Anand: software patents in India](https://www.anandandanand.com/news-insights/software-patents-in-india-explained/)

> **Recommendation:** File **one** provisional covering the Monotonic Capability Envelope as the
> primary claim, with the provenance rule, the measured-preview confirmation, and the fail-closed
> hash-chained audit as dependent/secondary aspects of the same system. Do **not** file four
> separate patents (the deck's "4 patents" line); one well-drafted application covering the
> security architecture is stronger and far cheaper. Split later only if an examiner objects to
> unity of invention.

---

## 2. Who is the inventor, and who owns it

- **Inventors** are the natural persons who conceived the inventive mechanism (likely Dr. A.
  Senthil Kumar and any student/engineer who conceived the envelope/provenance design — contribution
  to *conception of the claims*, not just coding).
- **Applicant/owner** is usually the **institution**, if the inventors are its employees/students and
  the work used its resources — most institutions have an IP policy assigning this. **Resolve this
  before filing.** File in the applicant's name with an **assignment (Form 6 / deed)** from each
  inventor.
- An **educational institution** applicant qualifies for the reduced fee tier (same as
  individual/startup/MSME) — see §5.

---

## 3. The filing route and timeline

```
  NOW ─────────────▶ PROVISIONAL (India)                 secures PRIORITY DATE; disclosure safe after
     (before any       Form 1 + Form 2 (provisional spec) + Form 5(decl) + Form 28(small-entity)
      disclosure)
        │
        │  ≤ 12 months (hard deadline, NO extension)
        ▼
     COMPLETE SPECIFICATION (India)                      full claims; must be supported by provisional
     Form 1 + Form 2 (complete) + Form 3 (foreign-filing) + Form 5
        │
        │  within 12 months of the PRIORITY date (to keep the priority)
        ▼
     PCT international application  (optional, for US/EU/etc.)
        │
        │  31 months from priority
        ▼
     NATIONAL PHASE in chosen countries (US, EPO, …)
```

Other India deadlines that matter:
- **Request for Examination (Form 18):** within **31 months** of priority, or the application is
  treated as withdrawn. Expedited examination (Form 18A) is available for startups/edu/female
  applicants/MSME.
- **Publication:** automatic at 18 months, or **early publication (Form 9)** if you want it sooner.
- **Foreign filing permit (Form 25 / Section 39):** if the invention was made in India, you must
  **either file in India first, or obtain a foreign-filing licence, before filing abroad.** Do not
  file a US provisional first from India without this.

Sources: [Provisional filing guide (Unimarks)](https://unimarkslegal.com/provisional-patent-filing-process/) ·
[PCT from India (ip-coster)](https://ip-coster.com/IPGuides/patent-pct-india) ·
[Patent filing steps (IntellectBastion)](https://intellectbastion.com/patent-filing-india-guide/)

---

## 4. The documents you file (India provisional)

| Form | What it is | Notes |
|---|---|---|
| **Form 1** | Application for grant of patent | Names applicant(s) + inventor(s) |
| **Form 2** | Specification (tick **Provisional**) | The drafted spec — see [19-PROVISIONAL-SPECIFICATION-DRAFT](19-PROVISIONAL-SPECIFICATION-DRAFT.md) |
| **Form 3** | Statement & undertaking re foreign applications | Update as you file abroad |
| **Form 5** | Declaration as to inventorship | With the complete spec (and good practice to include) |
| **Form 28** | Claim small-entity/startup/edu status | Needed for the reduced fee; attach proof (Udyam/startup cert/institution proof) |
| **Form 26** | Power of attorney | If a patent agent files for you |
| **Form 6** / assignment deed | Proof of right (inventor → applicant) | If applicant ≠ inventor |
| Drawings | Figures referenced by the spec | See the 5 figures listed in the draft |

Filed online at the IPO e-filing portal; a registered agent normally does this.

---

## 5. Costs (India, e-filing; confirm on ipindia.gov.in)

Reduced tier = **individual / startup / small entity (MSME, via Udyam) / educational institution** (claim with Form 28).

| Item | Reduced tier | Large entity |
|---|---|---|
| Filing (Form 1, incl. provisional or complete; ≤30 pp, ≤10 claims) | **₹1,600** | ₹8,000 |
| Each page over 30 / each claim over 10 | small per-unit fee | higher per-unit |
| Request for examination (Form 18) | **~₹4,000** | ~₹20,000 |
| Early publication (Form 9) | **~₹2,500** | ~₹12,500 |
| **Government fees, provisional → grant, rough total** | **~₹8,000–10,000** | ~₹40,000+ |
| Patent agent/attorney drafting + prosecution (the real cost) | **~₹40,000–1,50,000+** | same |
| PCT filing (if going international) | separate, **~₹1.5–4 lakh+** all-in | — |

The **attorney fee dwarfs the government fee** — budget for a good agent; a weak specification is
worse than none. Fee figures vary across sources; verify.

Sources: [Patent cost India 2026 (Intepat)](https://www.intepat.com/blog/patent-fees-cost-india) ·
[Fee schedule (IncorpX)](https://www.incorpx.io/blog/patent-filing-fees-india-2026-startup-vs-company) ·
[Cost of filing (IPHelm)](https://iphelm.com/cost-of-filing-a-patent-in-india/)

---

## 6. Prior-art / patentability search (do this before drafting the complete spec)

A novelty search protects you from spending on a complete spec that an examiner will reject. Search:

- **Patent databases:** Google Patents, Espacenet, WIPO PATENTSCOPE, the **Indian Patent Advanced
  Search (InPASS)**, USPTO Patent Public Search.
- **Search terms (combine):** "capability" / "authorization envelope" / "least privilege" +
  "large language model" / "LLM agent"; "prompt injection" + "defense" / "mitigation";
  "taint tracking" / "information flow" + "command execution"; "monotonic" + "privilege" /
  "capability"; "LLM" + "shell" / "command" + "sandbox"; "agent" + "confirmation" + "irreversible".
- **Non-patent prior art (this is where the real risk is):** arXiv and security venues
  (USENIX Security, IEEE S&P, CCS) on LLM-agent security, prompt-injection defences, capability-based
  security, information-flow control; vendor docs (any "human-in-the-loop"/permission systems for
  coding/computer-use agents). **Capability-based security and taint tracking are decades-old fields** —
  the inventive step must be the *specific combination*: authority derived once from the input
  utterance + monotonic non-expansion + model-independent deterministic enforcement over an agent's
  proposed OS operations.

Deliver the search to your agent; it shapes the claims.

---

## 7. What to file now vs. later (recommended sequence)

1. **This week — provisional.** Hand [19-PROVISIONAL-SPECIFICATION-DRAFT](19-PROVISIONAL-SPECIFICATION-DRAFT.md)
   and this package to a registered patent agent. Resolve ownership/assignment. File the provisional
   **before any public disclosure.** This buys the priority date and 12 months.
2. **After the provisional is on file** — you may open-source, publish the corpus/benchmark, present
   papers, demo. (Keep records of dates.)
3. **Months 1–10** — commission the prior-art search; let the agent draft the **complete
   specification** with refined claims; decide single vs. divisional.
4. **Month ≤12** — file the complete specification in India; if international, file the **PCT** within
   12 months of the priority date.
5. **≤31 months** — file Request for Examination; enter PCT national phase in chosen countries.

---

## 8. Checklist to hand your patent agent

- [ ] Signed engagement + Form 26 (power of attorney)
- [ ] Inventor list with each person's contribution to the *conception* of the claimed mechanism
- [ ] Ownership resolved; assignment deed / Form 6 drafted
- [ ] Small-entity/edu proof for Form 28 (Udyam / institution registration / startup cert)
- [ ] Confirmation that **nothing has been publicly disclosed yet** (repo private, docs private, no talks)
- [ ] The drafted provisional spec ([doc 19](19-PROVISIONAL-SPECIFICATION-DRAFT.md)) + the 5 figures
- [ ] Foreign-filing intention noted (for Form 3 and the §39 licence question)
- [ ] Prior-art search commissioned (or scoped per §6)
- [ ] Decision: provisional-only now, complete within 12 months; PCT yes/no

---

## 9. Reality check, one paragraph

The **pipeline is not patentable**; the **corpus and benchmark are papers, not patents**; and even
the strong candidate — the Monotonic Capability Envelope — faces a real §3(k) hurdle that stands or
falls on **drafting it as a security mechanism with a concrete technical effect**, and on a prior-art
search of a field (capability security, taint tracking) that is decades old. A good patent agent and
an honest novelty search are worth more than filing speed — but the **priority date must be secured by
a provisional before you disclose anything**, so file the provisional first and refine afterwards.
