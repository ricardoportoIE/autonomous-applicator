# Application queue operation

The queue completes one vacancy at a time. Quality checks and a confirmed provider outcome take precedence over throughput.

## Starting and pausing

The main **Start agent / Pause agent** control reflects the saved automation setting. Start enables automation and wakes the existing background worker immediately, rather than waiting for the polling interval. Repeated wake requests coalesce, and cycles remain on one worker thread with the durable operation guard. Pause remains available during slow preparation or provider work; it prevents subsequent actions at the existing pause boundaries. An external action already in flight can finish. Pausing keeps the separate networking preference: both queues require the global enable switch. Starting a server configured without its background worker returns an actionable error instead of claiming that processing has begun.

## Questionnaire controls

The adapter reads the current dialogue, accessible labels, required markers and enabled options. Text, email, phone, numeric and date/time inputs are filled only with an approved or grounded answer that satisfies native format, range, pattern and length constraints. Native selects and radio groups require an exact available choice. Placeholder and disabled select options are excluded; duplicate selectable labels require review. Native select options are read again immediately before selection, using the unique enabled index and visible option label, then checked again after the action. Disabled duplicates and options changed during filling cannot silently become a selected answer.

Native checkboxes and ARIA checkbox widgets use exact **Yes / No** answers: Yes selects, No clears. Unknown unchecked optional preferences remain untouched. Checked/required unknown preferences and consent statements are held for review with their exact question and binary choices; no general consent is inferred. Wrapper and native checked states are verified together. The company-follow checkbox is cleared as before.

Mapped ARIA comboboxes are opened to read visible enabled options from their own `aria-controls` listbox, including portal-rendered options. The chosen accessible option must be unique and the control must display the selected answer afterwards. Unmapped dropdowns, unsupported inputs and native multiple-select controls require explicit review. Form inspection does not change candidate facts, existing job fingerprints or document provenance.

## Ordering and completion

The worker resumes eligible records already in its durable queue before running another job search. When there is no pending preparation or ready record with sending capacity, enabled discovery imports a bounded batch with canonical URLs and duplicate checks. The worker then takes an application snapshot ordered by import identifier from oldest to newest. Ready records waiting only for the daily sending cap do not prevent further discovery and preparation. Networking discovery and invitations run after the application queue. Dashboard search, filters and sorting do not alter processing order. For each eligible vacancy:

1. Reload the opportunity and candidate revision; check pause state. Preparation does not require daily sending capacity.
2. Evaluate approved facts and prepare current materials where required. When AI preparation is enabled, await GPT-6.1 Sol and validate its actual response provenance.
3. Generate the vacancy-specific documents and verify their factual content, limits and recorded hashes.
4. Recheck submission policy, source integration, declared scope, exact opportunity identity, current revision and approved questionnaire answers.
5. Hold one sending slot, access the provider, verify the live vacancy, upload the verified documents and complete supported form steps.
6. Persist the confirmed receipt, review hold or uncertain outcome before beginning another vacancy.

Already prepared opportunities keep their original position. Imports arriving after the snapshot wait for the next cycle. Submitted, uncertain and skipped records are excluded. Reviews already evaluated against the current candidate revision normally wait for deliberate resolution. A classified technical hold with a released pre-send attempt may resume automatically twice when all current readiness checks pass. Unknown answers, consent, authentication problems, model failures and uncertain sends require their existing resolution. A failure does not prevent later eligible records from being processed.

**Approve answer** saves an application-scoped record against the current candidate revision and opportunity fingerprint; it does not update the global candidate profile. Approved application answers override a shared answer only for that vacancy, remain effective when automatic routine answers are disabled and expire when candidate facts or the opportunity change. Approval rechecks readiness immediately. Current verified documents are reused and a fully eligible vacancy becomes ready without another model call. Missing, modified, untrusted or stale documents produce an explicit **Queued for preparation** state in the dashboard. The next cycle prepares those materials before attempting submission. A genuine preparation failure becomes a review hold and is not automatically retried. Profile and evidence edits still invalidate documents whose factual basis changed.

An unanswered live question retains its exact label, choices and required flag for review, including with automatic answering disabled. Recording a later question preserves other current application approvals. A changed question loses its own approval; expired facts or an independently edited opportunity are never revived. Known approved facts can answer ordinary questions; an unknown choice is never inferred. If an older free-text answer does not fit live radio/select choices, the browser checks grounded facts before selecting anything. An exact fitting manual choice stays authoritative. Sponsorship uses the explicitly confirmed candidate fact for the recognised wording; it does not establish legal work authorisation. A pre-click stop releases its sending reservation and records the question before moving to the next vacancy. Approval resumes that vacancy when its policy and document checks permit it.

A source without a submission adapter becomes a review hold for manual hand-off; its valid prepared documents remain available. Unknown required answers stop for review, even when the provider has prefilled a value. No fit score or model response approves an immigration or other factual questionnaire answer.

The daily cap counts confirmed applications sent. Preparation and routine question handling continue in FIFO order after capacity is exhausted; ready records wait at **waiting for capacity** and do not regenerate unchanged documents. Pending or uncertain submissions hold capacity separately until their outcome is established, including across calendar days. A proven pre-submission stop releases its hold atomically with the review state. Transactional reservation and a final pre-click gate enforce the sending limit. Model calls have a 180-second timeout and no automatic retries; failure leaves review without local fallback.

## Visible stages and logs

### Bounded form recovery and local learning

Checkbox and radio recovery tries native input, associated visible label and scoped ARIA widget strategies. It reacquires the current control by its type, label and group, verifies unchanged choices and checks both native and accessible checked state. A React render may change element identifiers without changing the reviewed question. Hidden clones are excluded; a hidden boolean input remains usable when its own label or widget is visible. Labelled controls without IDs use their exact accessible label. Visible ambiguity, changed choices, invalid constraints and unknown facts stop safely.

Successful strategies are stored under `browser_recovery:*` in private SQLite. The key contains only control type and three structural visibility/label/role flags; the value is one of three implemented methods. It stores no answer, personal identity, arbitrary selector or executable code. A preferred method is only an ordering hint and must pass the same verification on reuse. Corrupt or unsupported hints cannot grant a new action.

Easy Apply opening checks the verified page's main region first, then permits a single visible page action for sticky controls outside that region. It accepts visible button text when the accessible name differs, requires an unambiguous action and permits a same-page link variant. It rereads after a timeout and never clicks again once the dialogue has appeared. External application links retain manual hand-off. Form steps are identified by question semantics, visible headings and navigation actions rather than generated IDs, input values or DOM order. ID-only React renders do not count as progress; a return to a previous step stops the cycle. An unchanged Next/Review step can be reread and refilled with approved facts up to three times without repeating document uploads. Invalid visible fields are named without recording their answer values. Submit application is excluded from every recovery loop.

Across cycles, `form_recovery:v2:{application}` records a transactional, persistent limit of two technical resumptions. Only a review with its latest attempt released and a recognised provider technical stop qualifies. Scope, fit, questionnaire, current revision, document integrity, model provenance and sending capacity must still pass. Valid materials are reused without another model preparation. Pause prevents a new cycle or final send. A changed or exhausted hold stays in review; restarting does not reset the budget. Sending, uncertain and confirmed attempts cannot qualify. The tested phone/city adapter upgrade introduced version 2 deliberately; version 1 history remains intact. Ordinary restarts, answer approvals and UI commands do not create new recovery budgets.

The current provider contract recognises `Phone` alongside the existing phone labels. A narrowly identified city typeahead selects one offered suggestion matching both the confirmed current city and country, checks its association with the input and verifies selection after React updates. Ambiguous, disabled, foreign or unmapped suggestions require review. Text fields asking for years, and numeric input modes, reject narrative answers before filling. Provider inline validation stops repeated Next/Review actions and records field labels without answer values. A primary job-header closure message stops opening recovery; messages on recommendations below the job description do not classify the reviewed job as closed.

The monitor records **recovering form** and **form recovered**, including the method and bounded pass number. The journal records automatic resumption counts. Provider review reasons are retained in the stored evaluation and displayed by the application-status readiness check, rather than only appearing in the activity history. This is operational learning from verified interactions, not model retraining or automatic editing of candidate facts.

The monitor is available across dashboard views and polls the authenticated status endpoint once a second without holding the browser lock. It reports:

- Current or latest vacancy, company and application identifier.
- Run state and current or last stage.
- Total run duration, stage duration and run identifier.
- The latest 50 processed records across runs, with outcome, failure stage and exception class.

Preparation stages cover evaluation, routine question resolution, model evidence selection, document generation and saving. Prepared vacancies can finish at **waiting for capacity**. Submission stages cover readiness, reservation, opening and verifying the vacancy, opening Easy Apply, uploads, approved questions, advancing numbered form steps, submitting, awaiting confirmation and recording the receipt. Discovery and the separate networking queue have their own stage descriptions when no application is selected.

Job discovery records **opening job search**, **reading job results**, **opening discovered job** and **reading discovered job** separately. Each detail-page step includes its position in the bounded batch and the canonical opportunity URL, without tracking parameters. Navigation allows 60 seconds and search/detail DOM waits allow 30 seconds. These waits do not trigger retries. A browser failure retains the exact read stage and controlled recovery advice; a failed batch imports no opportunities and does not enter submission. A discovery failure stops that discovery cycle; eligible existing FIFO work takes precedence and bypasses discovery until it has been processed. Discovery-only failures direct the user to the stage and dedicated browser session rather than a nonexistent application activity log.

An enabled background worker still starts later cycles at the configured polling interval. These are separate runs, not retries inside a failed discovery call. Pause automation to stop new cycles while inspecting a repeated provider failure.

Each stage is stored before the corresponding action and has a UTC journal timestamp. Application activity connects its application_stage and application_processing_result entries through run_id. The API returns current stage timestamps for timing comparisons. Raw exception messages, private answer values and credentials are not included in processing diagnostics. Existing provider review messages remain available in the scoped application activity.

Completed describes a finished cycle; individual results can still show review or uncertainty. Inspect the result and its failure stage rather than assuming every vacancy was submitted. No visible confirmation means no successful delivery claim.

## Ownership, pause and interruption

Manual preparation, manual submission and worker cycles share one durable application-operation owner. A second request receives HTTP 409 rather than starting another operation. A workspace-level operating-system lock prevents a second server from running recovery or a background queue against an active server's database.

Reloading resumes observation without reissuing the action. Locking clears content, stops polling and ignores late responses. The pause control remains available while ordinary workspace controls are disabled. Pausing during preparation allows verified documents to finish but prevents submission and the next vacancy. The pause state is rechecked between vacancies; an external submission already in flight can still finish.

Graceful shutdown retains workspace ownership until current background work finishes, then takes no new vacancies. A fully verified preparation completed before graceful shutdown may remain ready. Abrupt interruption is different: restart recovery preserves the failure stage, invalidates interrupted pending materials and holds preparation for manual review. A reserved submission becomes uncertain and cannot be sent again until its external outcome is reconciled.

## Verification

Queue regressions use fictional candidate facts, local documents and intercepted provider traffic. They check exact preparation/submission order, mixed ready and unprepared jobs, slow model observation, concurrent request exclusion, daily budget boundaries, pause and shutdown boundaries, exact question holds, failures without retries, correlated stage logs, current browser facts, restart recovery and server ownership. Browser tests check model/form stage changes, completion, failed-result persistence, reload observation, pause, status errors, session locking, accessibility and responsive layouts.

These tests make no paid model requests and submit no real applications or invitations. They do not guarantee support for every employer form or future LinkedIn layout.
