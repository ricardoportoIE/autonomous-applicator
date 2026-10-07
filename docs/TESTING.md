# Testing and coverage

## Unresolved experience requirement decisions, 7 October 2026

Extended the explicit per-opportunity review decision to professional experience criteria whose wording cannot be mapped to a confirmed duration, including commercial software development and combined technology requirements. The candidate can choose to apply without confirming that the criterion is met. Numerical scoring, documents and factual answers stay unchanged; a missing experience-question answer remains a separate hold, and sibling opportunities retain their own decisions.

Fresh affected-path acceptance passed **112 backend cases in 25.44 seconds**, with **100% statements and branch outcomes in `application_management.py`** (86 statements, 34 branch outcomes), and **40 React cases in 3.76 seconds**, with **100% in `review-guidance.tsx`** (52 statements, 46 lines, 13 functions, 61 branch outcomes). Four packaged desktop/mobile cases passed in 13.22 seconds, exercising both known and unmapped experience requirements through approval, Trash and restoration. These are focused measurements; previous full-system results retain their separately dated scope. An initial new fixture used an unsupported `Question.kind` field and was corrected; one formerly covered fallback moved into the new decision path, so a candidate-confirmation regression restored the focused coverage gate. No provider send or paid model call was used in testing.

```powershell
uv run pytest tests/test_application_management.py tests/test_requirement_interpretation.py tests/test_preflight.py tests/test_application_queue.py --override-ini addopts= --cov=applicator.application_management --cov-branch --cov-report=term-missing --cov-fail-under=100 -q
npx vitest run tests/frontend/review-management.test.tsx tests/frontend/detail.test.tsx --coverage --coverage.include=src/review-guidance.tsx
npm run build
uv run pytest tests/test_review_management_browser.py --override-ini addopts= --no-cov -q
```

## Actionable review and reversible Trash, 7 October 2026

The focused backend gate passed **208 cases in 45.60 seconds** across the new management module and affected FIFO, preflight, scoped-answer, capacity, requirement, receipt and discovery paths. `application_management.py` reached **100% statements and branch outcomes: 86/86 statements and 34/34 branch outcomes**. The complete React suite passed **223 cases in 21.16 seconds**, with **100% statements, lines, functions and branches in every measured runtime file** (1,016 statements, 923 lines, 361 functions and 1,097 branch outcomes across 13 files). This is a fresh complete React measurement and focused backend acceptance, not a new complete-backend coverage measurement.

Tests verify exact, truthful, opportunity-specific decisions; candidate/job expiry; untouched scores; unresolved factual/legal/question gates; concurrent operation refusal; stale revision and acknowledgement validation; idempotent removal; FIFO/reservation/preparation exclusion; rediscovery deduplication; preserved manifests across candidate/settings changes in Trash; restoration requiring fresh preparation; and retained submitted/skipped history. Component tests exercise corrective navigation, explicit acknowledgements, failed-removal editor retention, empty Trash, restoration and profile-save detail refresh. The first full React run passed behaviour but failed the strict coverage gate; additional action/branch regressions closed those gaps. One new profile-save test exposed a nested busy-state read being skipped, which was corrected before final acceptance. Incorrect new fixture button labels and a missing detail response were also corrected.

Four packaged Chromium journeys cover desktop/mobile review approval and removal/restoration, plus the existing submission archive. They use a real isolated API, fictional candidates and generated documents, reject external requests, check overflow and JavaScript errors, and verify unchanged candidate facts, document hashes and sending counts. No paid model call, real application or invitation is part of these tests. Ruff, formatting, strict mypy, TypeScript, ESLint and production build also passed.

Reproduce:

```powershell
uv run pytest tests/test_application_management.py tests/test_application_queue.py tests/test_preflight.py tests/test_scoped_answers.py tests/test_sending_capacity.py tests/test_requirement_interpretation.py tests/test_submission_records.py tests/test_discovery_memory.py --override-ini addopts= --cov=applicator.application_management --cov-branch --cov-report=term-missing --cov-fail-under=100 -q
npm test
npm run typecheck
npm run lint
npm run format:check
npm run build
uv run pytest tests/test_review_management_browser.py tests/test_application_archive_browser.py --override-ini addopts= --no-cov -q
```

[Operations](OPERATIONS.md#resolve-a-review-or-remove-an-opportunity) explain the explicit decision and retained safeguards; [queue design](APPLICATION_QUEUE.md#active-queue-and-submission-archive) explains lifecycle and discovery exclusion.

## Discovery read recovery, 7 October 2026

The fresh broad affected-path run passed **149 backend cases in 373.39 seconds** across discovery, authentication, API, scoped answers, worker controls and recovery. A final **42-case run passed in 75.82 seconds**, covering all **19 new discovery cases** and **23 existing FIFO cases**. This includes the two subsequently added navigation/shutdown checks, also verified independently in 16.72 seconds. Both coverage runs measured **100% statements and branch outcomes in `discovery_memory.py`: 43/43 statements and 8/8 branch outcomes**. The executions overlap; they exercise 174 distinct backend cases rather than 191 distinct cases. These are focused measurements, not a fresh complete-backend coverage claim.

New cases exercise the company-logo layout, nested logo markup, independent primary-name validation, missing/conflicting/duplicate identity, preservation of valid batch results, navigation/read errors, delayed authentication and unexpected-origin global stops, pause/shutdown boundaries, persistent retry timing and expiry, a 60-minute backoff ceiling, successful-read reset, manual retry, known-record filtering, idle review counts and continued FIFO preparation during a discovery hold. Controlled errors containing private-looking text verify that raw provider diagnostics never enter the new public API/run messages or private event details.

All **23 affected React cases passed in 6.47 seconds**, including three new monitor cases for per-job deferral, global discovery waiting and idle review waiting. They verify the reported stage, retry/polling information and absence of a false application-failure claim. Runtime frontend source and packaged assets did not change. Ruff, formatting, strict mypy, TypeScript, ESLint and documentation-link checks passed.

The first broad execution recorded 129 passes and four fixture failures because newly written rejection tests expected the word `ambiguous`, whereas the established reader correctly raised its incomplete/unsupported review message. Corrected expectations and final-source additions preceded the fresh successful run. Test fixtures use fictional opportunities without paid model calls or external sends. A separate live, read-only check reproduced the actual provider layout and verified successful extraction after the repair; it did not test a real submission.

Reproduce the affected-path gate (the two subsequently added cases are included by these files):

```powershell
uv run pytest tests/test_discovery_memory.py tests/test_discovery_read_recovery.py tests/test_discovery_diagnostics.py tests/test_job_discovery.py tests/test_discovery_screening.py tests/test_linkedin_authentication.py tests/test_review_and_worker.py tests/test_scoped_answers.py tests/test_worker_controls.py tests/test_worker_recovery.py tests/test_api.py --override-ini addopts= --cov=applicator.discovery_memory --cov-branch --cov-report=term-missing --cov-fail-under=100 -q
uv run pytest tests/test_discovery_memory.py tests/test_discovery_read_recovery.py tests/test_application_queue.py --override-ini addopts= --cov=applicator.discovery_memory --cov-branch --cov-report=term-missing --cov-fail-under=100 -q
npx vitest run tests/frontend/components.test.tsx tests/frontend/app-flows.test.tsx
```

[Queue recovery](APPLICATION_QUEUE.md#discovery-read-recovery-and-idle-monitoring) documents backoff and partial-result boundaries. [Delivery](STATUS.md#discovery-loop-diagnosis-and-recovery-7-october-2026) records paused activation, immutable submitted evidence and local-only version control.

## Populated instruction-library operational checks, 6 October 2026

The authorised private population used the existing generation and versioned save endpoints. All 16 empty rules received reviewed real-model drafts against the newly confirmed candidate revision; 15 were enabled and one legal-status rule remained manual. Final saved prompts measured 41–59 words. Initial drafts were superseded after the operator supplied missing facts; source/runtime files did not change.

Four real answering-model checks with controlled opportunity contexts verified geographical scope: both hybrid and commuting accepted the approved city and required review for another city. Seven new approved duration values fitted numerical controls without a model call or date inference. A stale save returned 409 and retained the current prompt/version. Private backup comparison checked unrelated facts/evidence, all five existing prompts, confirmed submission rows, sending attempts, networking rows and all 54 document files. Pending materials remained invalidated for fresh preparation. Previously skipped historical/low-fit outcomes were preserved after the general profile-save invalidation; this does not establish a new shared-runtime safeguard for future edits.

These are operational and bounded real-model checks, not a fresh full-suite or coverage measurement. Both queues stayed paused and no application or invitation was requested. Real candidate values, generated prompts and reports remain private. [Delivery](STATUS.md#authorised-instruction-library-population-6-october-2026) and [operations](OPERATIONS.md#draft-a-reusable-question-instruction) distinguish confirmed facts, live context and manual decisions.

## Concise question instruction drafts, 6 October 2026

Final fresh acceptance passed **104 affected backend cases in 50.95 seconds**, including **four new regressions**. The complete changed `question_library.py` measured **100% statements and branch outcomes**: **219 statements and 106 branch outcomes**, with zero missing paths. New cases verify the 120-word boundary, preservation of material conditions without truncation, private API failure with saved data intact, and the unchanged manual editor limit. Existing grounding, field-context, authentication, change-control and two packaged Chromium journeys remain green. A new fixture's trailing-space expectation was corrected to respect existing contract normalisation before the final fresh acceptance.

All **29 affected React cases passed in 3.21 seconds**. `routine-answers.tsx` retained **100% statements, lines, functions and branches**: 80 statements, 74 lines, 24 functions and 74 branch outcomes. The existing generation journey now also checks the concise helper text and explicit-save guidance. Strict TypeScript/mypy, ESLint/Ruff, formatting and the production build passed. Two refreshed screenshots were visually inspected using fictional records with no model/provider requests. These are focused results, not fresh complete-system coverage measurements.

Four real `gpt-6.1-sol` requests with fictional facts produced **41–50-word instructions**, taking **12.59–18.35 seconds**. Approved sponsorship retained material part-time/full-time conditions; approved professional duration produced a direct scoped instruction; unknown salary requested confirmation. A duration question with incompatible Yes/No variants requested interpretation review whilst retaining the approved number. The initial sample assertion incorrectly expected no review for that incompatible control; a distinct follow-up with actual numerical/select choices confirmed acceptance without a new fact. This bounded sample checks current prompt behaviour, not general semantic accuracy or a latency guarantee. It made no provider application or invitation and sent no private candidate record.

Reproduce focused acceptance:

```powershell
uv run pytest tests/test_instruction_draft.py tests/test_question_library.py --override-ini addopts= --cov=applicator.question_library --cov-branch --cov-fail-under=100 --cov-report=term-missing -q
npx vitest run tests/frontend/routine-answers.test.tsx tests/frontend/instruction-draft.test.tsx --coverage --coverage.include=src/routine-answers.tsx
```

[Instruction design](QUESTION_INSTRUCTIONS.md#generate-an-instruction-draft) records the generation-only limit and shared field policy. [Delivery](STATUS.md#concise-question-instruction-drafts-6-october-2026) records activation and local version control.

## Vacancy scoring audit, 6 October 2026

Final fresh acceptance passed **401 affected-path cases in 42.98 seconds**, including **62 new cases** in `tests/test_scoring_audit.py`. Both complete affected runtime modules measured **100% statements and branch outcomes**: `policy.py` covers **194 statements and 98 branch outcomes**, and `discovery.py` covers **24 statements and 12 branch outcomes**, with zero missing paths. These are focused measurements, not a new complete-backend or frontend coverage result.

Regressions cover optional headings and directly scoped clauses, explicit negation, known OR alternatives versus peer-family slashes and mandatory stacks, reviewed metadata canonicalisation, independent requirements, verified evidence selection, finite technology aliases, ordinary Go verbs, exact country identity, unrelated and recognised role titles, decimal professional minima/ranges, half-up rounding, repeated mentions and unverified evidence. Controlled Greenhouse responses verify preserved block boundaries and the unchanged encoding guard. Existing policy, intake/exclusion, document, capacity, readiness, answer-style and duration paths were exercised together.

An initial affected run exposed an incorrect new test expectation for an alternative containing an unknown platform. It was corrected to assert that the parser does not invent an OR equivalence; production behaviour was retained. The fresh 401-case acceptance above ran after that correction. Ruff, formatting and strict mypy passed across all 21 runtime modules. No frontend source changed, no complete system suite was rerun, and no model request or provider submission occurred. Tests use fictional records and controlled providers.

Reproduce the final two-module coverage gate:

```powershell
uv run pytest tests/test_scoring_audit.py tests/test_requirement_interpretation.py tests/test_policy.py tests/test_discovery_screening.py tests/test_documents_adviser_discovery.py tests/test_sending_capacity.py tests/test_preflight.py tests/test_answer_style_policy.py tests/test_backend_integrity.py tests/test_resume_duration_regressions.py --override-ini addopts= --cov=applicator.policy --cov=applicator.discovery --cov-branch --cov-fail-under=100 --cov-report=term-missing -q
```

[Scoring rules](REQUIREMENT_INTERPRETATION.md#formula-and-routing) retain the 70/15/15 formula and independent eligibility gates. [Queue operations](APPLICATION_QUEUE.md#requirement-and-closure-decisions) explain cached scores and exclusion memory; [delivery](STATUS.md#vacancy-scoring-audit-6-october-2026) distinguishes the read-only operational audit from fictional tests.

## Field-aware instruction drafts, 6 October 2026

The final affected-library run passed **100 backend cases in 62.06 seconds**, including **36 new cases** in `tests/test_instruction_draft.py`. The complete changed library measured **100% statements and branch outcomes**: **217/217 statements and 104/104 branch outcomes**, with zero missing paths. The new authenticated API route's executable paths were exercised, whilst the broader API module was only partially measured by this focused run. No new complete-backend coverage claim is made.

Checks cover read-only draft generation, current candidate/instruction revision provenance, distinct field variants from multiple opportunities and cached observations, duplicate/unrelated variants, sensitive historic controls, data minimisation, all seven tested control labels, verified source references, missing facts, Pydantic bounds, authentication/configuration/provider failures and changes during a model request. The two new packaged Chromium journeys verify visible progress, disabled duplicate/edit/save actions, unsaved database integrity, clarification guidance, deliberate editing/saving, mobile overflow and zero browser errors. Controlled model fixtures make no paid calls or external submissions.

All **29 affected React cases passed in 2.58 seconds**, including **15 new cases**. `routine-answers.tsx` measured **100% statements, lines, functions and branches**: **80 statements, 74 lines, 24 functions and 74 branch outcomes**. UI cases verify the revision-bearing request, explicit save, field variants, disabled sensitive/unconfirmed generation, error/retry preservation, progress and late-result rejection after closing or locking. This is a focused component result, not a fresh complete React measurement. Strict TypeScript/mypy, ESLint/Ruff, formatting and the production build passed. Existing complete coverage baselines remain historical.

A separate real `gpt-6.1-sol` check used three fictional scenarios. Approved professional Python duration produced a fact-referencing instruction covering numerical/text/choice fields; unknown salary and marketing consent both requested candidate clarification. All expected outcomes passed, with calls taking **22.27–26.75 seconds**. These are bounded draft checks, not a general quality or performance guarantee. No private candidate record or provider action was involved. Two refreshed screenshots use fictional local records without model requests.

Reproduce focused acceptance:

```powershell
uv run pytest tests/test_instruction_draft.py tests/test_question_library.py --override-ini addopts= --cov=applicator.question_library --cov-branch --cov-fail-under=100 --cov-report=term-missing -q
npx vitest run tests/frontend/routine-answers.test.tsx tests/frontend/instruction-draft.test.tsx --coverage --coverage.include=src/routine-answers.tsx
```

[Draft design](QUESTION_INSTRUCTIONS.md#generate-an-instruction-draft) explains explicit saving and factual limits. [Delivery](STATUS.md#field-aware-instruction-drafts-6-october-2026) records paused activation and local-only version control.

## Requirement interpretation and review recovery, 6 October 2026

Final acceptance passed **268 cases in 53.13 seconds**, including **51 new cases** in `tests/test_requirement_interpretation.py`. The complete changed policy module measured **100% statements and branch outcomes**: **168/168 statements and 86/86 branch outcomes**, with zero missing paths. Closure handling in the store was exercised by both the exact closed-opportunity and ambiguous-action cases, including capacity release and retained document files.

The new cases cover optional clauses and headings, required-section resets, conservative mixed wording, reviewed metadata priority, cloud alternatives versus mandatory lists, repeated independent requirements, matching evidence selection, scoped professional minima and ranges, approved and unknown durations, exact candidate confirmation, contradictory known durations, production ML confirmations and explicit negative answers. Preparation is also verified for an interesting vacancy held for review. All ordinary fixtures use fictional candidates and controlled providers without paid model calls or external sends.

A separate wider affected-path execution passed **567 behavioural cases in 439.65 seconds** across policy, persistence, answers, sending capacity, multi-page questionnaires and discovery/provider regressions. Its initial policy coverage gate reported **99.21%** because one exact-confirmation path was not exercised. The final fresh 268-case run above covers that path and the completed source; the wider run is not presented as a green 100% gate. Ruff, formatting and strict mypy passed across all 21 backend runtime modules.

This is **focused backend acceptance**, not a new full-system or complete-backend coverage claim. The historical full baseline below remains associated with `f0119b6`; no frontend source changed. An authorised private operational recovery additionally regenerated five current review document sets through the normal API with `gpt-6.1-sol` and checked readiness, revisions and hashes. Submitted records, archived files, attempts and networking records were unchanged; both queues stayed paused. That paid model use is separate from the fictional test count.

Reproduce the final policy gate:

```powershell
uv run pytest tests/test_requirement_interpretation.py tests/test_policy.py tests/test_answer_style_policy.py tests/test_backend_integrity.py tests/test_resume_duration_regressions.py --override-ini addopts= --cov=applicator.policy --cov-branch --cov-fail-under=100 --cov-report=term-missing -q
```

[Requirement interpretation](REQUIREMENT_INTERPRETATION.md) records the supported wording and review boundaries. [The delivery record](STATUS.md#requirement-interpretation-and-activated-review-recovery-6-october-2026) distinguishes loaded runtime recovery from historical restart notes.

## Resolved duration review holds, 6 October 2026

The shared correction passed **418 affected-path cases in 138.28 seconds**, including **14 new cases** in `tests/test_missing_duration_review.py`. The existing exact-instruction precedence regression now expects an explicitly supplied duration to resolve a legacy narrative; compatible approvals still bypass generation.

New checks cover preparation/readiness, cache provenance after reuse/restart, rule disablement, retained documents, verified numeric work evidence, rejected constrained numbers, unrelated/differently worded rules, exceptional non-duration fields, and integration/review/invalid-output failures. Real Chromium forms independently complete one known technology whilst collecting another missing professional duration; zero is filled only when explicitly approved. Assertions verify the unchanged profile/revision, no submission clicks and unchanged sending capacity. Model responses and provider forms use controlled fictional fixtures.

Focused coverage recorded zero missing changed executable lines and zero missing branches originating from changed lines in `service.py` and `store.py`. It is **not** a new 100% measurement of either complete module or the full backend. Ruff, formatting and strict mypy passed. The full-suite figures below describe the previous source baseline at `f0119b6`; the complete suite and frontend suite were not rerun for this correction.

A separate authorised local recovery used the normal API to save an existing confirmed answer and prepare a real vacancy-specific CV with `gpt-6.1-sol`. Document integrity and generation provenance validated against the unchanged candidate revision and current opportunity. The independent unresolved duration stayed in review; no LinkedIn submission or invitation was requested. This operational check is separate from the fictional test count.

Reproduce focused acceptance:

```powershell
uv run pytest tests/test_missing_duration_review.py tests/test_question_library.py tests/test_legacy_duration_resolution.py tests/test_answer_style_policy.py tests/test_scoped_answers.py tests/test_store_service.py tests/test_routine_answers.py tests/test_routine_browser.py tests/test_routine_api.py tests/test_sending_capacity.py tests/test_question_collection.py tests/test_question_collection_edges.py tests/test_resume_duration_regressions.py --override-ini addopts= --no-cov -q
```

## Full-system validation, 6 October 2026

The complete local execution on **Windows/Python 3.14.2 and Node.js 24.20.0** collected **1,436 Python cases**. It finished with **1,430 passes and six stale-test failures in 2,253.00 seconds**. The failures were two expectations for verbatim experience paragraphs superseded by the candidate's concise-answer policy, two discovery simulators without the new excluded-opportunity argument, and two desktop/mobile record journeys which searched the active queue after a confirmed application moved to Archive. The final corrected four-file recheck passed **all 51 cases in 135.44 seconds**. Production application sources remained unchanged; assertions now also verify evidence provenance and the empty active queue before opening archived records. No timeout, retry, assertion boundary or coverage gate was relaxed.

The complete run measured **100% statements and branch outcomes in every one of the 21 backend modules**: **3,619/3,619 statements and 1,346/1,346 branch outcomes**, with zero missing paths and no runtime exclusions. Coverage from the final affected-file recheck was appended to that same-source measurement; the independent inventory gate passed afterwards. This records a complete execution followed by corrected-case acceptance, rather than claiming a second fresh full local run. CI starts a fresh complete measurement independently for each platform/interpreter.

| Check | Accepted result |
| --- | --- |
| Complete React unit suite | 181 cases across 17 files, 26.59 seconds; all 11 runtime modules have 100% statements, lines, functions and branches |
| React unit counters | 907 statements, 824 lines, 327 functions and 962 branch outcomes |
| Packaged Chromium coverage | Ten dashboard modules; 98.68% statements/lines, 91.90% branches and 94.38% functions; independent browser gates passed |
| Static checks and formatting | Strict TypeScript/mypy, ESLint, Ruff and Prettier passed; 21 Python source modules checked by mypy |
| Windows permissions | All eight isolated native ACL scenarios passed |
| Dependencies | npm audit and pip-audit found no known dependency vulnerabilities; installed-package consistency and frozen lockfile checks passed |
| Build and distribution | Production assets reproduced without drift; wheel/source archive contain all five current assets and no private runtime paths |
| Documentation and privacy | Relative file/image links validated; tracked-file credential/contact checks passed |
| Offline performance | Default 1/100/1,000-opportunity workload passed its count/order/fit/zero-send assertions; [new report](PERFORMANCE.md#complete-validation-recheck-6-october-2026) records timings and contention limits |

The complete and affected-file suites use disposable fictional records, controlled model responses and local/intercepted providers. They make no paid API calls and send no real applications or invitations. The existing private workspace and document hashes were checked read-only and remained unchanged. The preceding separately authorised six-case real model experiment retains its distinct scope below. Earlier measurements are historical records for their own revisions.

## Question instruction library, 6 October 2026

The broader affected-path acceptance passed **295 backend cases in 163.72 seconds** across library, routine-answer, field-formatting, API, intercepted browser, multi-page collection and Store/Service regressions. After adding the packaged Settings test, client-initialisation failure guard, legacy sponsorship compatibility, automatic re-preparation and semantic HTML cache binding, the accepted focused run passed **190 cases in 42.80 seconds**, including **64 new library/API/provider/UI cases**. The new `question_library.py` module reached **100% statement and branch coverage**, covering **169/169 statements and 78/78 branch outcomes**, with no exclusions. Measurements use private coverage paths and do not replace the preceding complete-backend report.

The final complete React acceptance passed **181 tests in 23.09 seconds** across 17 files, including **14 new cases**. All **11 authored runtime modules** reached **100% statements, lines, functions and branches**: **907 statements, 824 lines, 327 functions and 962 branch outcomes**. New cases verify complete prompt payloads, other-row preservation, disablement, sensitive controls, option lists, save/load failures, saving/loading states, filters, polling, late responses after unmount and escaped provider text. The final standalone packaged Chromium case passed in **6.66 seconds**, verifying actual authenticated persistence, keyboard tabs, reload and mobile behaviour. Its broader production-browser coverage report was not regenerated.

The actual GPT-6.1 Sol Responses API was exercised separately with **six fictional cases**; all produced the expected answer, no-match or review outcome. The sample covers exact and paraphrased numeric questions, concise text, rejection of a different technology, unknown salary and conditional work permission. Calls took **3.72–8.03 seconds**. These are bounded observations, not general performance/accuracy guarantees. Ordinary automated tests use mocked model boundaries and intercepted/local providers, make no paid API calls and never send a real application or invitation.

The tests also verify existing-record backfill, distinct observation counts, 249 choices, current rule versions, native constraints, the instruction/data trust boundary, supporting owner quotes, evidence/fact references, exact approval precedence, unknown/wrong model results, API configuration failures, preservation of candidate revision and archived submissions, and provider observer restoration. Ruff, strict mypy, TypeScript, ESLint, formatting and the production build passed. [The instruction guide](QUESTION_INSTRUCTIONS.md) records operator usage and limitations.

## Candidate-authorised answer policy, 6 October 2026

The final focused acceptance passed **249 cases in 68.86 seconds**, including **122 new policy/presentation cases**, existing routine/API/HTML interpretation and legacy-duration checks, and all cross-application recovery regressions. Targeted measurement reached **100% statements and branches in both answer modules**: `answer_style.py` covered 49/49 statements and 30/30 branch outcomes; `routine_answers.py` covered 211/211 statements and 130/130 branch outcomes. The combined gate covered 260 statements and 160 branch outcomes without exclusions. Coverage files for this focused measurement are private, separate from the preceding complete-suite reports.

New cases exercise absent/unanswered technology zero/prose defaults; profile, unverified and alias mentions; existing factual answers; exact numerical choices; confirmed duration paraphrases and short prose; professional/project scope; decimals, ranges, conflicts and forbidden date inference; native/inputmode/pattern numerical fields; min/max/step rejection; native radio/select filling; real text/textarea/number filling without Submit; control-type changes; version-bound restart persistence; scoped/manual priority; disabled automatic answering; preparation without a question-model call; and preservation of candidate records and sending capacity. The default's two educational/development sentences survive cached reuse.

Broader focused checks also exercised policy, provider controls, typed fields and CV/duration behaviour. One existing assertion expected whitespace around an approved numeric value to survive; it now checks the deliberately normalised number. All **30 CV/duration regressions passed in 12.04 seconds** after that expectation was aligned. The final 249-case run then accepted the completed duration-reuse implementation. Ruff, formatting and strict mypy passed across the current 20 backend modules. No paid model request or real application/invitation was sent.

This is a focused measurement of the affected answer modules, not a new complete-backend or frontend coverage claim. The historical complete baseline below remains unchanged. The frontend was not modified. [Answer rules](QUESTION_INTERPRETATION.md#candidate-authorised-technology-defaults-and-answer-style) and [delivery evidence](STATUS.md#candidate-authorised-answer-formatting-6-october-2026) describe the accepted behaviour and paused rollout.

The resume/navigation learning regressions add 17 fictional cases for accessible CV names outside the radio, delayed rendering, stale selections, wrong labels, verified reuse, durable contract-specific hints, the bounded version 3 budget and navigation timeouts before/after dispatch. Tests assert that a completed transition receives no second click, delayed completion is observed, invalid/stalled forms stop and Submit is never replayed. All 17 new cases passed. Complete-suite acceptance is recorded below.

The CV/duration regression suite adds 30 cases for duplicate filename references, existing same-name CVs, nested/hidden labels, ambiguous native/ARIA states, stale selections, operation-scoped reuse, changed file hashes and React node replacement, numeric readiness and scoped approval without document regeneration. It replaces an older depth rejection with a supported deep-filename case. Chromium providers are fictional and no model calls or real submissions occur.

The preceding complete Windows/Python 3.14.2 baseline passed **1,151 cases in 1,612.89 seconds**, covering **3,083/3,083 statements and 1,088/1,088 branch outcomes across all 19 backend modules**. The independent inventory gate confirmed 100% in every module. All **162 React cases** passed with 100% in each of the ten runtime modules: 837 statements, 758 lines, 299 functions and 888 branch outcomes. The separate production-browser report measured **98.69% statements/lines, 92.37% branches and 97.54% functions**. [Delivery record](STATUS.md#questionnaire-collection-6-october-2026) distinguishes the accepted complete measurement from superseded runs, the paused rollout and actual provider reads. Ordinary tests use fictional providers and no paid model calls or real submissions.

After that baseline, the large-choice contract correction passed **12 additional focused cases in 10.22 seconds**. They preserve 249-option telephone-country lists, verify exact approved contact selection and unknown-fact persistence, exercise authenticated API intake, and reject 501 choices while retaining the question-count and HTML bounds. The complete suite and frontend checks were not rerun for this backend-only bounded change. These focused results are not a fresh full coverage measurement. [The correction record](STATUS.md#large-dialling-code-lists-6-october-2026) also records paused deployment and existing-hold re-evaluation.

## Backend acceptance gate

The cross-application audit passed **14 new focused cases in 13.60 seconds**. Each uses distinct newly added opportunities and reopens the store between them. Checks cover 249/500-choice contact forms, portal cities and React replacement, incompatible narrative resolution from explicitly verified numeric work evidence, learned boolean methods with opposite scoped answers, real prepared CV bytes for each vacancy, navigation after a post-dispatch timeout, independent persistent recovery budgets and isolated multi-page questions/HTML. Negative cases prevent scoped Python-duration, salary, eligibility and relocation approvals from becoming unapproved global facts. Ordinary provider traffic is fully intercepted; no model request or real submission occurs. These tests are included automatically by the existing pytest/CI discovery. Runtime sources and existing coverage gates are unchanged; the complete suite and coverage reports were not regenerated. [Recovery design](REUSABLE_RECOVERY.md) maps the proofs to each shared contract.

The city-portal correction passed **64 focused cases in 44.08 seconds**: 14 new portal/collection regressions, all 41 existing provider-form regressions and nine legacy-duration regressions. New Chromium cases cover lists within the row, in dialogue portals and outside the dialogue; React identifier replacement; lists without test identifiers; unrelated distractors; escaped input identifiers and `aria-labelledby` token relationships; delayed rendering; missing identifiers; duplicate linked lists/city matches; disabled and foreign options; and a controlled timeout that preserves all other current-page questions and fills known fields. No fixture clicks Submit or makes paid model requests. The existing missing-list assertion now expects the controlled review error instead of a raw Playwright timeout. Ruff, formatting and strict mypy passed. Complete-suite and frontend coverage measurements were not regenerated.

The final legacy-duration run passed **209 focused cases in 177.74 seconds**, including nine new service/Chromium regressions and 200 existing duration, CV-selection, collection-edge, field-type, provider, interpretation and browser checks. They verify incompatible cache fall-through, exact scoped/global numeric priority, verified employment evidence versus independent projects or missing facts, unchanged candidate records/capacity, filling a required plain-text years field, advancement to final review without Submit, retention of unknown prefills, completion of other known fields and exact provider-offered ranges. Invalid choices still fail explicit field validation without a resolver. Ruff, formatting, strict mypy and repository hygiene passed. The complete coverage baseline above remains historical; the React unit suite and complete application suite were not rerun for this backend correction.

The form-diagnostic/upload enhancement passed **30 focused cases in 38.09 seconds**: 29 new regressions plus the existing intercepted successful submission flow. New checks cover inert/value-free HTML, multi-page retention, missing/ambiguous/oversized dialogues, unsafe paths and disk errors, the pre-send capture boundary, durable activity events and non-disruptive journal failure. Upload checks verify actual browser `File` bytes for two vacancy-specific PDFs, visible/accessibility-name selection, within-attempt reuse and strict format/size boundaries, including refusal before opening the chooser. Fixtures send no real applications or paid model requests. The complete coverage baseline above predates these changes; no new full-suite or frontend coverage claim is made.

The complete Python suite must reach **100% statement and branch coverage in every module under `src/applicator`**, including API endpoints, policy, AI contracts, persistence, document rendering, browser adapters, networking, operation recovery and the command-line entry point. The current runtime inventory and accepted coverage contain **21 modules**, including the shared answer formatter and question instruction library; the earlier historical baseline covered 19. Statement and branch counts change with source revisions and Python versions; the JSON report and inventory-gate output record the exact counts for each run. Each interpreter must cover its complete measured inventory. The empty package initializer is included in the inventory. Historical measurements are retained in [the delivery record](STATUS.md).

Pytest measures branches as well as statements and fails below 100%. A second gate checks the JSON report against every authored Python application file, rejects missing or unexpected modules, requires zero missing statements and branches in each module and validates the counters. CI runs both checks independently on Windows and Linux with Python 3.12 and 3.14. A percentage rounded to 100% cannot satisfy these checks while a missing path remains.

No runtime module is omitted and no coverage-ignore directives are permitted. Coverage.py's default exclusion of the signature-only `Adapter(Protocol)` declaration is retained: it defines a typing contract with an ellipsis rather than a runtime implementation. The inventory gate checks the source and allows only such signature-only protocols and blank lines; an excluded concrete method fails the gate. Test code, repository tooling and generated frontend assets are outside the Python application metric. The coverage gate has its own acceptance and rejection tests.

## Behaviour verified

The archive/discovery follow-up passed **22 focused backend cases in 17.00 seconds**, **seven React cases** and **three production-Chromium cases in 7.03 seconds**. New cases cover the exact 49/50 boundary, full-description scoring, unconfirmed/stale candidate refusal, separate durable logs, canonical duplicate memory, batch rollback/concurrency, all three discovery entry points, authenticated pagination, and skipping excluded links before navigation without consuming the result limit. UI checks cover all unresolved states, confirmed-only archive partitioning, counts, filters, keyboard access, automatic refresh, lock reset, full-record links, no duplicate controls, and production desktop/mobile records with zero mutations/external requests. Ordinary tests make no paid model requests or real sends. This is focused acceptance, not a new complete coverage measurement.

| Boundary | Representative assertions |
| --- | --- |
| Single-link import | Authenticated, bounded intake rejects unsupported origins before browser access; declared scope is required. Paused imports save once without candidate facts or sending capacity. Duplicate identifiers preserve existing records; failures retain the durable stage without a partial save. Intercepted Chromium verifies canonical navigation, primary details, identity/authentication redirects and zero application clicks. React and production-browser cases verify URL-only entry, visible loading, duplicate-click suppression, explicit retry, manual-entry parity and stale completion after locking. |
| Candidate facts and questions | Unknown eligibility is never inferred; ambiguous durations and capability modifiers remain in review; stale, sensitive, invalid and oversized routine answers cannot be stored. |
| Questionnaire collection | Multiple current questions, radio groups, conditional controls, replacement dialogues and safely reachable later pages are gathered before review. Required validation, prefills, cyclic/overlong forms and unstable rendering stop without invented claims or a Submit click. Batch transactions preserve scoped facts and release capacity; invalid batches roll back completely, including held reservations. |
| Documents | Real PDF/DOCX generation preserves approved text, identity and page constraints; extraction failures and an oversized cover letter reject preparation; optional font registration is portable and idempotent. |
| Submission records | Hash checks detect changes between validation and archiving; existing archives cannot be overwritten; unreserved attempts and escaping archive/download paths are rejected. |
| Queue and ownership | Work remains sequential; a global pause stops further invitations; disabled networking cannot reserve capacity; discovery-only recovery preserves the interrupted stage without fabricating an application result. |
| Browser contracts | Primary profile traversal is bounded; multiple headings, identity redirects and last-moment identity changes stop the action; incomplete portraits must finish loading before caching. |
| Easy Apply | Unsupported upload widgets and inconsistent visual/native answers require review; ten distinct form steps stop before submission; CV observations retain step numbers and implicit employer following is disabled. Incompatible legacy text consults grounded live-question resolution, exact manual choices remain authoritative, and unknown answers never adopt prefilled values. |
| Invitations | Menu controls are scoped to the reviewed member; unavailable Connect controls fail visibly; scope revocation before sending prevents the final click; successful fixtures use Send without a note. |
| Provider confirmation | Redirected local fixtures and untrusted receipt text cannot establish a confirmed submission; uncertain outcomes are not automatically retried. |
| LinkedIn authentication | Redirects during actual job, profile and form waits return an actionable sign-in message without provider tracking data; a pre-send stop releases capacity, while a post-click, pre-confirmation redirect retains an uncertain attempt, archived materials and the failure stage. A later session change during optional screenshot capture preserves an already observed receipt. Discovery never imports a partial batch. |
| Discovery diagnostics | Intercepted browser failures at search navigation, search results, the results list, detail navigation, the primary header and the description retain their precise stage. Tests verify 60-second navigation and 30-second read budgets, canonical URLs without tracking parameters, no retries and no raw provider errors in progress or journals. Worker and React tests distinguish discovery failures from application-specific activity. |
| Application-scoped approval | Approval persists across reload without changing candidate revision or another CV; valid model-prepared materials are reused without a further paid call. Missing, modified, stale and required-cover-letter checks queue preparation. Tests reject invalid choices, sensitive questions, stale facts and protected states, retain observed live choices with automatic answering enabled or disabled, preserve other approvals when later questions appear without reviving stale facts, handle explicit answer keys and verify FIFO resumption, daily-cap discovery and privacy on genuine failures. Real mobile/desktop browser tests cover the revision header and updated readiness flow. |
| Typed questionnaire controls | Native/ARIA checkbox fixtures verify exact binary answers, required consent, prefilled states and agreement between visual and native selection. Dropdown fixtures exercise mapped portal options, disabled/empty/duplicate choices, unknown answers and failed selection. Native selects additionally verify disabled duplicate labels, options changed before/after selection and explicit visible-label overrides. Native input fixtures verify numeric/date formats, range, pattern, length and post-fill validation. Ambiguous identifiers and multiple-select controls stop before submission. |
| Technical recovery and learning | Fictional Chromium controls exercise hidden associated labels, CSS-hidden clones, accessible wrappers, changed React IDs, transient failures, exact idless labels, changed choices and invalid constraints. SQLite tests verify whitelist-only hints, restart persistence, concurrent claims and the two-resumption cap. Queue checks retain materials, pause, capacity, unknown-answer and uncertain-send boundaries. Semantic step tests distinguish ID/value/order-only renders from new questions or headings, and reject backward cycles. Opening tests cover sticky actions outside main, visible text aliases and authentication redirects after the real opening action. Opening and unchanged Next/Review recovery never replay Submit or repeat uploads. |
| Start/Pause | An hourly polling interval does not delay Start; repeated wake requests coalesce on one worker thread. The real production UI drives a fictional application through the background queue, then pauses with its networking preference retained. React checks duplicate suppression, starting/pausing feedback, pause during pending work, error recovery and late responses after locking. |
| HTTP security | Complete authority/port checks, duplicate Host/Origin rejection, property-generated rebinding suffixes, private headers on controlled errors, exact body-size boundaries and cancellation of stalled intake before any operation begins. Operation timeouts remain distinct from intake timeouts. |
| Credentials and public intake | Exclusive token creation preserves another starter's token, POSIX creation requests owner-only permissions and unsafe token paths are refused before reading. Endless/oversized boards stop consumption and close; redirects and unsolicited compression never reach parsing. |
| Packaged private fetch | Chromium verifies that a redirected profile mutation is not followed or retried, sends no cookies and changes neither facts nor application attempts. Unit tests assert explicit redirect/cache/credential policies. |
| Performance contracts | Offline temporary workloads preserve list counts/order, expected fit and zero sends; percentile conversion, workload bounds and report privacy have assertions. Timings and traced allocations are recorded separately without machine-specific latency gates. |
| Platform ownership | Native workspace-exclusion tests run on each operating system; isolated OS-interface fault tests also verify both lock protocols, contention and cleanup on every runner. |

The wider suite includes API authentication and validation, concurrent SQLite operations, migrations, property tests, grounded OpenAI response contracts, application-specific CVs, reconciliation and production React browser scenarios. The new fault tests simulate failures at policy, rendering, filesystem, OS and provider boundaries, then assert retained state and the absence of an unauthorised send. Controlled adapters isolate provider outcomes; transaction tests and real DOM fixtures verify the corresponding state and action boundaries.

All ordinary tests use fictitious candidate records and disposable local workspaces. Provider browser requests are intercepted or served on loopback. OpenAI responses are controlled fixtures; neither the normal suite nor CI makes paid API calls or sends real applications or invitations. Separately authorised live experiments are documented in [the AI benchmark](AI_BENCHMARK.md).

## Reproduce the measurements

Run from the repository root after installing Python and frontend dependencies and Playwright Chromium:

```powershell
uv sync --frozen --extra dev
npm ci
npm run build
uv run python -m playwright install chromium
uv run python -m pytest
uv run python scripts/check_backend_coverage.py
npm test
npm run coverage:browser
```

The full pytest command starts a fresh measurement; it does not append previous coverage. It writes `coverage.xml` and `test-results/backend-coverage.json`. Both are ignored locally and uploaded as CI artifacts. Production browser coverage must run after pytest has collected V8 coverage. React unit coverage is a separate 100% per-file gate across all authored runtime TS/TSX modules; production-browser coverage is reported separately and does not claim the same percentage. See [frontend checks](FRONTEND.md#development-and-checks).

For focused development checks, select tests without claiming a full coverage result:

```powershell
uv run pytest tests/test_discovery_screening.py tests/test_application_archive_browser.py --override-ini addopts= --no-cov
npx vitest run tests/frontend/application-archive.test.tsx --coverage.enabled=false
uv run pytest tests/test_form_diagnostics_upload.py tests/test_application_dialog.py::test_native_dialog_full_submission_against_an_intercepted_provider --override-ini addopts= --no-cov
uv run pytest tests/test_large_choice_lists.py --override-ini addopts= --no-cov
uv run pytest tests/test_backend_integrity.py tests/test_browser_boundaries.py --no-cov
uv run pytest tests/test_backend_coverage_gate.py --no-cov
```

Before delivery, rerun the complete suite and the inventory gate. Additional required checks are strict TypeScript/mypy, ESLint/Ruff, formatting, tracked-file privacy, dependency audits and reproducible committed frontend assets. [Delivery status](STATUS.md) records measured results; [review findings](CODE_REVIEW.md) records their interpretation.

## Form recovery reproduction

```powershell
uv run python -m pytest tests/test_provider_form_regressions.py tests/test_form_recovery.py tests/test_application_dialog.py tests/test_linkedin_authentication.py --no-cov -o 'addopts=--strict-markers'
```

The initial recovery pass added 66 cases and two variants to an existing stalled-dialogue case. Its historical 933-case Windows/Python 3.14.2 suite passed in 1,651.82 seconds with 2,826 statements and 992 branch outcomes exercised across all 19 runtime modules. The subsequent provider audit adds 41 fictional form regressions, one versioned-budget regression and one modern phone/CV integration variant, bringing that inventory to 976 before the questionnaire interpretation enhancement below. The new cases verify city suggestions in different countries, duplicate/disabled/unmapped choices, React identifier replacement, final selection validity, numeric narrative rejection, telephone keyboard hints, label-only inline validation, primary closed-job status and conservative residence/employment facts. Focused checks do not replace the full suite or inventory gate. [Delivery status](STATUS.md) records current complete measurements and remote runner availability.

## Questionnaire HTML interpretation reproduction

```powershell
uv run python -m pytest tests/test_ai_form_interpretation.py tests/test_form_benchmark.py --no-cov -o 'addopts=--strict-markers'
```

The enhancement adds 65 cases to the previous 976-case inventory: 54 grounded interpretation/HTML cases and 11 opt-in benchmark contract checks. Seven of the interpretation cases run real Chromium against fictional forms. They verify contact type compatibility, choices, semantic attributes, value omission, escaping, review guards, application-scoped precedence, cached persistence, progress details and rejection before filling or advancing. Model contracts check the requested and returned model, valid sources and mappings. They do not call the paid API. The separate eight-call fictional comparison is recorded in [the AI benchmark](AI_BENCHMARK.md#questionnaire-html-comparison-5-october-2026). Complete coverage measurements require the complete suite and inventory gate; focused measurements are not full coverage claims.

## Security and performance reproduction

```powershell
uv run python -m pytest tests/test_security_hardening.py tests/test_security_frontend.py tests/test_local_performance.py --no-cov -o 'addopts=--strict-markers'
uv run python scripts/benchmark_local.py
```

The hardening contributes 53 cases to the 865-case Python inventory: 43 security unit/integration/property cases, one production Chromium case and nine benchmark checks. The DNS-rebinding property runs 40 generated suffixes within one counted pytest case. An autouse fixture clears inherited runtime variables and prevents CLI tests from loading `.env`; an isolated CLI regression proves private credentials/data paths cannot be imported. Individual tests remain free to set explicit fictional configuration. The complete suite also contains transactional concurrency, recovery, document/PDF, controlled AI, provider-contract, accessibility and production-browser checks. These are appropriate complementary layers; the project does not claim every possible type of security audit, live-provider load test or independent penetration test.

CI runs the default offline benchmark and uploads `test-results/local-benchmark.json` per platform/interpreter alongside coverage. [Performance](PERFORMANCE.md) defines its methodology, baseline and limits. Byte/intake-time limits are tested behaviour gates; benchmark milliseconds are observations rather than CI pass/fail thresholds. The [security model](SECURITY.md) defines the account and provider boundaries exercised by the tests.

Windows jobs additionally run `tests/powershell/test_private_permissions.ps1` outside the Python coverage metric. Eight native ACL scenarios use disposable fictional files: recursive private protection, repeat execution, junction refusal without changing the target, an empty workspace, non-project root refusal, default workspace resolution, injected-write-failure rollback with legacy metadata and rejection of genuine permission changes by the comparator. Assertions also verify unchanged content/owners/public-source DACLs and private permission backups. Rollback comparison preserves all access rules, masks, order, ACE inheritance flags and DACL protection state; it normalises only Windows' automatically updated `DiscretionaryAclAutoInherited` metadata flag. A fixture-only native setter constructs that legacy state explicitly. This tooling suite does not claim Python's 100% runtime metric for PowerShell. Reproduce it with `powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test_private_permissions.ps1`.

## Interpretation

The hostile-authority property retains 40 generated suffixes and all rejection/header assertions. Its Hypothesis deadline is disabled because each example includes constructing the complete API, disposable SQLite setup and a request under coverage instrumentation. A Windows example took 399.88 ms and exceeded the default 200 ms while its security assertions passed. Dedicated performance measurements and the tested ten-second intake deadline retain their timing checks; no application timeout, security guard or coverage gate is relaxed.

100% coverage means every measured application statement and branch outcome was exercised by the suite. Assertions establish the intended behaviour for those cases. It does not establish every possible input, future provider layout, network condition or hiring outcome. Live provider compatibility still depends on the declared authorisation, valid sign-in and the current supported interface contract. Unknown behaviour continues to require review.
