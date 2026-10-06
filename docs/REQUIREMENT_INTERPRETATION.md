# Required and optional vacancy criteria

Technical fit and submission eligibility are separate decisions. A vacancy can score 100/100 for verified technologies, location and role whilst remaining in review for an explicit professional experience requirement. The score is a routing heuristic, not a hiring probability or an ATS score.

## Technical evidence

Reviewed `Job.requirements` metadata remains authoritative for technical scoring. When that list is absent, the shared policy reads the description and removes explicitly optional sections and clauses before matching verified evidence. Recognised required headings reset the optional section. Ambiguous clauses containing both mandatory and optional wording remain assessable rather than silently removing a possible requirement.

For example, an optional Azure qualification does not penalise a candidate with the required Python evidence. A recognised `AWS/Azure/GCP` or `AWS, Azure, or GCP` alternative is one requirement: verified Azure evidence can satisfy it. `AWS and Azure` and a comma-only list remain separate requirements. An independently stated mandatory AWS requirement still requires AWS evidence, even if an earlier cloud alternative matched. Evidence selection uses the same groups as scoring, so a matching verified project can be prioritised for the tailored CV.

This is bounded deterministic interpretation, not a general natural-language eligibility parser. It recognises specific headings, optional markers and cloud-provider alternatives. Unrecognised or ambiguous combinations are not granted an inferred equivalence; manual requirement metadata can resolve the technical interpretation after review.

## Professional experience and production deployment

The policy checks recognised, explicitly scoped professional/work/commercial experience minima against compatible approved duration answers or verified numeric work evidence. A recognised range uses its lower bound. Longest-topic matching distinguishes AI Agents from generic AI and backend software engineering from broader overlapping terms.

An approved duration below the stated minimum produces a specific review reason with both numbers. For example, Alex Example's approved two professional Python years do not satisfy a requirement for four. If the duration is unknown, the candidate can confirm that exact requirement using `condition:experience_requirement:<normalised required line>` with the value `Confirmed`. This exact confirmation does not override a known insufficient duration. Dates, independent projects and educational experience do not become paid experience. A vague unscoped years statement alone does not introduce this new hold.

The recognised requirement for deploying ML or machine learning models into production uses the candidate's `condition:production_ml` answer. `Confirmed` satisfies the condition; `No` produces a concrete experience gap; a missing confirmation requires review. An explicitly optional deployment statement does not create this hold. This deliberately bounded wording match does not imply support for every possible deployment phrase.

Interesting vacancies can still have documents prepared while in review. Preparation uses the configured model and current approved evidence; generating a CV cannot approve a missing qualification or remove a genuine experience gap. [Question interpretation](QUESTION_INTERPRETATION.md) explains the separate field-answer rules.

## Closed opportunities

The exact provider observation `The LinkedIn opportunity is no longer accepting applications` marks the record as `skipped`. It is a known closed opportunity, not a questionnaire failure or a confirmed submission. Existing documents and activity remain available, and a proven pre-send stop releases its sending-capacity hold. An unavailable or ambiguous Easy Apply action alone remains in review; it does not prove closure.

Skipped records remain outside the confirmed-submission archive. A historical closure observation must be labelled historical when used during maintenance; it is not a fresh provider check. No closure handling retries a submission or changes a confirmed application record.

## Validation and operational boundaries

The 6 October 2026 final affected-policy run passed 268 cases, including 51 new requirement/closure regressions. The complete policy module measured 100% statements and branch outcomes: 168 statements and 86 branch outcomes. Store closure tests cover the exact positive and ambiguous negative cases, capacity release and retained documents. These focused results do not establish a new complete-backend or frontend coverage measurement. [Testing](TESTING.md#requirement-interpretation-and-review-recovery-6-october-2026) records reproduction and the separate wider execution.

Candidate confirmations belong in private local data. Profile changes invalidate pending preparation; archived submissions retain their original snapshots. Maintenance must preserve existing receipts, submitted documents and uncertain sends, and leave paused queues paused. [Operations](OPERATIONS.md#review-recovery-and-closed-opportunities) describes activation and diagnosis.
