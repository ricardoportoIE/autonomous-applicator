# Required and optional vacancy criteria

Technical fit and submission eligibility are separate decisions. A vacancy can score 100/100 for verified technologies, location and role whilst remaining in review for an explicit professional experience requirement. The score is a routing heuristic, not a hiring probability or an ATS score.

## Technical evidence

Reviewed `Job.requirements` metadata remains authoritative for technical scoring. Known aliases and explicit alternatives are canonicalised and deduplicated; unknown metadata remains a literal requirement, and blank entries are ignored. When that list is absent, the shared policy reads the description and removes explicitly optional sections and clauses before matching exact normalised tags on verified evidence. Repeated technology mentions do not add weight. Unverified evidence cannot earn points.

Optional headings include Preferred qualifications, Desirable experience, Nice-to-have qualifications and Markdown headings. Recognised required headings reset the optional section. A directly scoped statement such as `Python required and Azure preferred` retains Python alone. `No AWS experience is required` does not create an AWS requirement. Ambiguous wording such as `Python and Azure are required or preferred` retains both rather than guessing the intended scope. Greenhouse intake preserves block and bullet boundaries so headings continue to apply to the following lines.

An explicit `Python or Java`, `Django or FastAPI` or `AWS, Azure, or GCP` is one recognised requirement: verified evidence for one member can satisfy it. Slash alternatives are accepted only within supported language, web-framework or cloud-provider families. `Python/Java` is an alternative; `Python/Django` is a stack with two requirements. `AWS and Azure` and a comma-only list remain separate requirements. An independently stated mandatory member still needs its own evidence, even if an earlier alternative matched. Evidence selection uses the same groups as scoring to prioritise relevant verified projects for the tailored CV.

The finite vocabulary includes C++, Go/Golang, Google Cloud Platform/GCP, RAG/retrieval-augmented generation and machine learning. Ordinary English uses of the verb `go` do not establish a Go language requirement. Aliases normalise known names; they do not create a qualification or convert project evidence into employment duration.

This is bounded deterministic interpretation, not a general natural-language eligibility parser. Unrecognised or ambiguous combinations are not granted an inferred equivalence; reviewed requirement metadata can resolve the technical interpretation. A perfect score means all recognised requirements matched, not that every possible competency in the description was assessed. GPT document preparation does not assign the score or approve missing facts.

## Formula and routing

Technical evidence contributes `70 × matched requirements / assessed requirements`, rounded half up to a whole point; no assessed requirements contribute zero. Target location contributes 15 and a recognised technology-role title contributes 15. For example, three of four requirements with both location and role matched score **83/100** (53 + 15 + 15). The weights remain **70/15/15**.

Location credit compares normalised country identities or an exact candidate location confirmation. Northern Ireland belongs to the UK for this policy; England, Scotland and Wales also match UK settings. Other travel/relocation review rules remain separate. Title classification excludes recruiter/sales titles and unrelated physical engineering disciplines unless an explicit technology marker is present. A generic graduate or technical title alone cannot gain role credit. The title classifier is deliberately limited; an unrecognised role requires candidate review even when its score exceeds the automatic threshold.

Configured score thresholds retain their defaults: **80+** can become ready, **50–79** requires review, and below **50** is skipped. Independent factual, experience, location, question and document checks can still hold a high-scoring vacancy. Automatic discovery uses its separate fixed 50-point intake floor; see [queue operations](APPLICATION_QUEUE.md#discovery-screening-and-exclusion-memory) for durable exclusion memory and cached scores.

## Professional experience and production deployment

The policy checks recognised, explicitly scoped professional/work/commercial experience minima against compatible approved duration answers or verified numeric work evidence. Whole-number and decimal minima are supported; a recognised range uses its lower bound. A requirement for 2.5 years must not be misread as five years. Longest-topic matching distinguishes AI Agents from generic AI and backend software engineering from broader overlapping terms.

An approved duration below the stated minimum produces a specific review reason with both numbers. For example, Alex Example's approved two professional Python years do not satisfy a requirement for four. If the duration is unknown, the candidate can confirm that exact requirement using `condition:experience_requirement:<normalised required line>` with the value `Confirmed`. This exact confirmation does not override a known insufficient duration. Dates, independent projects and educational experience do not become paid experience. A vague unscoped years statement alone does not introduce this new hold.

The recognised requirement for deploying ML or machine learning models into production uses the candidate's `condition:production_ml` answer. `Confirmed` satisfies the condition; `No` produces a concrete experience gap; a missing confirmation requires review. An explicitly optional deployment statement does not create this hold. This deliberately bounded wording match does not imply support for every possible deployment phrase.

Interesting vacancies can still have documents prepared while in review. Preparation uses the configured model and current approved evidence; generating a CV cannot approve a missing qualification or remove a genuine experience gap. [Question interpretation](QUESTION_INTERPRETATION.md) explains the separate field-answer rules.

## Closed opportunities

The exact provider observation `The LinkedIn opportunity is no longer accepting applications` marks the record as `skipped`. It is a known closed opportunity, not a questionnaire failure or a confirmed submission. Existing documents and activity remain available, and a proven pre-send stop releases its sending-capacity hold. An unavailable or ambiguous Easy Apply action alone remains in review; it does not prove closure.

Skipped records remain outside the confirmed-submission archive. A historical closure observation must be labelled historical when used during maintenance; it is not a fresh provider check. No closure handling retries a submission or changes a confirmed application record.

## Validation and operational boundaries

The 6 October 2026 scoring audit adds 62 regression cases covering alternatives, optional scope, aliases, role/location credit, decimal minima, rounding, evidence integrity and Greenhouse layout. [Testing](TESTING.md#vacancy-scoring-audit-6-october-2026) records the final affected-path acceptance and complete coverage of the two affected modules. These focused results do not establish a new complete-backend or frontend coverage measurement. The earlier [requirement/closure acceptance](TESTING.md#requirement-interpretation-and-review-recovery-6-october-2026) remains a historical result for its source revision.

Candidate confirmations belong in private local data. Profile changes invalidate pending preparation; archived submissions retain their original snapshots. Maintenance must preserve existing receipts, submitted documents and uncertain sends, and leave paused queues paused. [Operations](OPERATIONS.md#review-recovery-and-closed-opportunities) describes activation and diagnosis.
