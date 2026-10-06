# Reusable recovery for future applications

Previously validated technical repairs are implemented in the common LinkedIn adapter, question resolver and storage contracts. Every new opportunity uses those same functions. They contain no exceptions tied to the application or vacancy identifiers that originally exposed the failures. Importing another opportunity or restarting the workspace does not remove these repairs.

## Shared repairs and their proof

| Supported contract | Behaviour in a new opportunity | Verification |
| --- | --- | --- |
| Telephone-country choices | Read up to 500 exact choices and select the country matching the confirmed international number, including entries beyond the former 100-option limit. | New opportunities complete 249/500-option contact forms after reopening the store. |
| City suggestions | Find the explicitly linked suggestion list even when rendered outside the field row, and select the uniquely matching confirmed city/country. | New opportunities use portal lists without test identifiers, including React input replacement. |
| Numeric experience | Reject incompatible legacy narratives; use compatible approved numbers/statements or explicit verified numeric evidence. Separately apply the candidate-authorised zero for recognised absent, unanswered technologies. | Both opportunities resolve their own employment duration; new policy regressions verify zero/prose defaults, scoped priority and native constraints. Dates do not establish a number. |
| Native and ARIA controls | Reuse a previously verified interaction method, reacquire the current control and check its actual native/ARIA result. | The first opportunity learns ARIA; after reopening the store, the next uses it first while applying its own opposite approved answer. |
| Vacancy-specific CVs | Reuse the upload method while validating and uploading the current vacancy's file. | Two newly prepared CVs have distinct filenames; actual browser `File` bytes match each document's recorded hash. Both contained-label and accessible-name contracts are exercised. |
| Next/Review navigation | Check whether a timed-out action already completed before considering another reversible click. | A post-dispatch timeout teaches the navigation hint; the next opportunity completes with exactly one click and no Submit click. |
| Question collection and diagnostics | Retain all unanswered questions on safely reachable pages and preserve private, uniquely named HTML for that opportunity. | Two new intercepted provider flows retain both pages' questions, distinct diagnostic files and the correct source identifiers. Neither sends an application. |
| Recovery budgets | Give each qualifying opportunity its own persistent two-resumption allowance. Shared learning does not reset an exhausted allowance. | Exhausting one opportunity leaves the other's allowance intact; reopening the store resets neither. |

The detailed upload, city, duration, form-collection and recovery suites also exercise rejection cases for ambiguous controls, changed identities, disabled options, invalid constraints, stale documents, authentication and uncertain sends. A shared method is a verified hint, not permission to bypass these checks.

## What is shared

Implemented form contracts are shared through application code. Verified interaction hints are stored in private SQLite under `browser_recovery:*`, independent of an application identifier. Boolean hints encode structural control properties; resume and navigation hints identify implemented contracts. Their values come from fixed allowlists and contain no candidate answer, filename, personal identity, arbitrary selector or executable code. A fresh Store instance reads the same hints after a restart.

Candidate facts are a separate source. Confirmed global profile answers and verified evidence can serve every suitable opportunity, subject to the observed question and its constraints. Application-specific approvals and derived routine answers remain tied to their own candidate revision and opportunity fingerprint. An exact scoped approval takes precedence for that opportunity.

For example, approving “3” for a Python work-duration question in one application's Questions tab does not change the global profile. A future application needs that number in its own approval or in a compatible confirmed global fact/explicit verified numeric employment statement. Learning a click method cannot promote a scoped approval to a global fact. Salary, legal eligibility, relocation and consent retain the same distinction.

The candidate has separately authorised a standard zero/educational answer for recognised technologies absent from the profile which have no existing factual answer. This explicit preference applies to new opportunities through the common resolver; it does not arise from browser learning or another application's scoped approval. Generated defaults retain source `candidate_technology_policy`, current revision and vacancy identity. Their own records can coexist across numerical/text questions, whilst later manual approvals and profile mentions prevent conflicting absence claims. See [the answer rules](QUESTION_INTERPRETATION.md#candidate-authorised-technology-defaults-and-answer-style).

## What stays with each opportunity

Each application retains its own opportunity identity, fit, documents, question approvals, diagnostic files, attempts and submission record. A reusable upload strategy does not reuse a different vacancy's CV. A reusable control strategy does not reuse another application's answer. The final identity, scope, readiness, pause and capacity gates remain authoritative.

The `form_recovery:v3:{application}` budget is also local to that application and survives restarts. Only a recognised technical stop with a released pre-send attempt and current passing readiness can qualify. Unknown facts, authentication holds, model failures and uncertain or confirmed sends keep their existing review or reconciliation path. See [queue recovery](APPLICATION_QUEUE.md#bounded-form-recovery-and-local-learning).

## Adding the next general repair

Use the stage journal and private HTML to identify the actual failed contract. Implement a semantic correction in the common adapter/resolver rather than an application-ID exception. Add a regression with two distinct opportunities and a reopened store, checking both successful reuse and the relevant refusal boundary. Retain each opportunity's current document/answer checks and the pre-send diagnostic guard. Update the operating guide and delivery record, run the focused cases and create a local commit. Run the complete suite when the change or a failure requires broader validation.

The normal pytest discovery and existing CI command include [the cross-application regressions](../tests/test_cross_application_recovery.py). A focused local check is:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_cross_application_recovery.py --override-ini addopts= --no-cov -q
```

The accepted focused run passed **14 cases in 13.60 seconds** using fictional candidate/opportunity data, real Chromium, temporary stores and fully intercepted provider traffic. It made no paid model request or real application send. This verifies reuse of the supported contracts; it is not a new complete-suite coverage measurement. [The delivery record](STATUS.md#cross-application-reuse-6-october-2026) records acceptance and scope.
