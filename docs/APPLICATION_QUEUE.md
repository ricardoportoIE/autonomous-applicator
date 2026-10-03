# Application queue operation

The queue completes one vacancy at a time. Quality checks and a confirmed provider outcome take precedence over throughput.

## Ordering and completion

Each cycle first performs enabled discovery, then takes an application snapshot ordered by import identifier from oldest to newest. Dashboard search, filters and sorting do not alter processing order. For each eligible vacancy:

1. Reload the opportunity and candidate revision; check pause state and available daily attempts.
2. Evaluate approved facts and prepare current materials where required. When AI preparation is enabled, await GPT-6.1 Sol and validate its actual response provenance.
3. Generate the vacancy-specific documents and verify their factual content, limits and recorded hashes.
4. Recheck submission policy, source integration, declared scope, exact opportunity identity, current revision and approved questionnaire answers.
5. Reserve one attempt, access the provider, verify the live vacancy, upload the verified documents and complete supported form steps.
6. Persist the confirmed receipt, review hold or uncertain outcome before beginning another vacancy.

Already prepared opportunities keep their original position. Imports arriving after the snapshot wait for the next cycle. Submitted, uncertain and skipped records are excluded. Reviews already evaluated against the current candidate revision wait for deliberate resolution. A safe failure does not prevent later eligible records from being processed, and it is not retried in another cycle.

A source without a submission adapter becomes a review hold for manual hand-off; its valid prepared documents remain available. Unknown required answers stop for review, even when the provider has prefilled a value. No fit score or model response approves an immigration or other factual questionnaire answer.

The current daily attempt budget is checked before another preparation, so exhausted capacity does not trigger another model request. A transactional reservation remains the authority for the actual limit. Model calls have a 180-second timeout and no automatic retries; failure leaves review without local fallback.

## Visible stages and logs

The monitor is available across dashboard views and polls the authenticated status endpoint once a second without holding the browser lock. It reports:

- Current or latest vacancy, company and application identifier.
- Run state and current or last stage.
- Total run duration, stage duration and run identifier.
- The latest 50 processed records across runs, with outcome, failure stage and exception class.

Preparation stages cover evaluation, model evidence selection, document generation and saving. Submission stages cover readiness, reservation, opening and verifying the vacancy, opening Easy Apply, uploads, approved questions, advancing numbered form steps, submitting, awaiting confirmation and recording the receipt. Discovery and the separate networking queue have their own stage descriptions when no application is selected.

Each stage is stored before the corresponding action and has a UTC journal timestamp. Application activity connects its application_stage and application_processing_result entries through run_id. The API returns current stage timestamps for timing comparisons. Raw exception messages, private answer values and credentials are not included in processing diagnostics. Existing provider review messages remain available in the scoped application activity.

Completed describes a finished cycle; individual results can still show review or uncertainty. Inspect the result and its failure stage rather than assuming every vacancy was submitted. No visible confirmation means no successful delivery claim.

## Ownership, pause and interruption

Manual preparation, manual submission and worker cycles share one durable application-operation owner. A second request receives HTTP 409 rather than starting another operation. A workspace-level operating-system lock prevents a second server from running recovery or a background queue against an active server's database.

Reloading resumes observation without reissuing the action. Locking clears content, stops polling and ignores late responses. The pause control remains available while ordinary workspace controls are disabled. Pausing during preparation allows verified documents to finish but prevents submission and the next vacancy. The pause state is rechecked between vacancies; an external submission already in flight can still finish.

Graceful shutdown retains workspace ownership until current background work finishes, then takes no new vacancies. A fully verified preparation completed before graceful shutdown may remain ready. Abrupt interruption is different: restart recovery preserves the failure stage, invalidates interrupted pending materials and holds preparation for manual review. A reserved submission becomes uncertain and cannot be sent again until its external outcome is reconciled.

## Verification

Queue regressions use fictional candidate facts, local documents and intercepted provider traffic. They check exact preparation/submission order, mixed ready and unprepared jobs, slow model observation, concurrent request exclusion, daily budget boundaries, pause and shutdown boundaries, exact question holds, failures without retries, correlated stage logs, current browser facts, restart recovery and server ownership. Browser tests check model/form stage changes, completion, failed-result persistence, reload observation, pause, status errors, session locking, accessibility and responsive layouts.

These tests make no paid model requests and submit no real applications or invitations. They do not guarantee support for every employer form or future LinkedIn layout.
