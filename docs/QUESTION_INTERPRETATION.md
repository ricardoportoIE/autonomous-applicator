# Grounded questionnaire and HTML interpretation

The provider adapter reads the current application dialogue and resolves known exact answers first. When an ordinary question is unfamiliar, GPT-6.1 Sol can interpret its wording and the observed control structure before the adapter fills it. This reduces unnecessary review holds caused by different labels for the same candidate fact or technical experience.

## What the model receives

Each live unresolved question carries transient `form_context`: the observed control type, enabled choices, required state and bounded attributes such as `type`, `role`, `inputmode`, `min`, `max`, `step`, `pattern` and length limits. The adapter reconstructs a small semantic HTML fragment from these allowlisted properties and the question label. It does not send the original page or a control's filled value, identifier, handler, token, hidden input or script. Attributes and text are escaped. A fragment exceeding 12,000 characters is rejected before a model request.

Each question can retain up to 500 choices, allowing observed 249-option country/dialling-code lists without truncation. An application still accepts at most 100 questions. These bounds apply consistently to browser collection, persistence and authenticated API intake. Known telephone details use the approved international prefix locally; an unknown telephone fact retains the full observed choice list for deliberate review. Expanding the choice count does not relax the HTML bound or exact-answer validation.

This is a representation of the observed field, rather than its raw `outerHTML`. Native select options appear in the fragment; radio, checkbox and opened ARIA dropdown choices are supplied separately as the exact enabled labels. Contact values are copied locally when the model selects an available contact question. Direct profile name, email and telephone fact fields are omitted from the routine interpretation prompt; observed question/choice text and vacancy content are still included. Verified professional evidence and the vacancy description are sent as required for semantic assessment.

The context is excluded from ordinary question serialization, SQLite question records and job/document fingerprints. A provider presentation change therefore cannot invalidate an otherwise current CV. It is rebuilt when the browser reads the field again. The manual answer adviser also accepts context when supplied directly, but reopening a stored question in the dashboard does not recover transient HTML or start a browser inspection.

## Decisions and validation

The model uses the [Responses API and structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses). The requested and returned model must be `gpt-6.1-sol` or its provider snapshot. Live form interpretation uses high reasoning effort, at most 4,000 output tokens, the configured 180-second request deadline, no automatic SDK retry and `store=false`.

The structured decision contains `needs_review`, `canonical_label` and up to three `evidence_ids`. It contains no generated answer, executable selector or browser action. There are two supported routes:

- Map a paraphrase to an exact available canonical question. The catalogue contains only contact facts or supported technical experience that the deterministic resolver can already answer for this candidate and these choices. The application derives the answer locally. A canonical mapping cannot also select narrative evidence; an email/telephone mapping must match its native type.
- Select verified evidence for a professional text or textarea answer. The application copies the original source wording, deduplicates identifiers, checks technology relevance and enforces the answer limit. A narrative cannot become a checkbox, radio, dropdown or contact value.

Uninterpretable controls, unavailable facts, unsupported mappings and unverified identifiers remain in review. Numeric fields require explicit approved numbers. Legal eligibility, consent, salary, availability, expertise and unusual conditions retain review boundaries. Independent projects cannot establish paid-work experience. Exact application-scoped approvals take precedence over shared defaults, including while deriving a canonical answer.

The model evaluates meaning; the adapter retains control identity, native validity, exact option matching, checked state and final value checks. AI cannot select an arbitrary element, override pause/capacity, alter a public profile or click Submit. Semantic model errors remain possible: grounded selection prevents fabricated candidate values but does not prove that every future question has been understood correctly.

## Execution and records

The existing **Answer routine questions from approved facts** setting controls this assistance. A local `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-6.1-sol` are required for model interpretation. Missing configuration, a provider error or an invalid response leaves the question for review without another model or invented answer.

During an actual model request the operation detail identifies GPT-6.1 Sol, the field type and question label. Valid answers are saved against the current application, candidate revision and vacancy fingerprint; source and evidence references are visible in Questions and the private journal. Re-reading the same compatible question reuses its saved answer. Before saving, the transaction checks the candidate and vacancy again.

## Collecting questions for one review

The adapter inspects every current field rather than stopping at the first missing fact. It fills independently supported answers, retains exact enabled choices and groups radio options into one question. A rejected interpretation leaves that question pending whilst other fields are inspected. Optional empty fields retain their existing skip behaviour. Unlabelled or unsupported controls require review without being guessed.

Approved selections can reveal conditional questions. Collection rereads the same page, with at most three structural passes, and also rereads controls when Next/Review validation prevents advancement. Next/Review remains reversible and bounded; collection never uses placeholder answers or bypasses provider validation. New dialogues are inspected only when there is one visible application dialogue.

Pending answers accumulate across the existing ten-step Easy Apply bound. Unknown prefills or selected controls prevent advancement; the adapter does not use a provider default as a candidate claim. Blank unresolved fields may advance only where the provider permits it. Reaching the final review with any pending question stops before the final sending gate and Submit. Required-field validation, authentication or an unsupported layout can make later pages unreachable; the collection summary records the stopping step and reason rather than claiming to have inspected hidden questions.

The service commits the entire observed batch and its pre-send hold in one SQLite transaction. Existing question identifiers and sensitive flags are preserved. Unrelated current approvals, routine-answer records and location approvals move to the updated question fingerprint; changed question choices invalidate the affected approval, and pending routine answers are removed. Old candidate revisions cannot become current through this migration. An invalid oversized batch rolls back the reservation release as well as its questions and events. Transient semantic HTML remains excluded from stored questions.

Questions shows the last collection summary and the reachable-page limit. The candidate can approve the collected answers in one review session, then prepare any materials whose provenance changed and resume the FIFO queue. This gathers all currently reachable gaps together; it cannot discover a page which the provider only opens after a required answer is supplied.

## Batch collection validation

Twelve large-list regressions verify 100/249/500-option round trips, API acceptance and rejection at 501, unchanged question and HTML bounds, approved telephone selection beyond option 100 in direct filling and collection, and unknown-contact persistence with subsequent approval of the last option. All 12 passed using fictional data and forms; no model request or real send occurred. [The delivery record](STATUS.md#large-dialling-code-lists-6-october-2026) distinguishes these focused checks from the preceding complete coverage baseline.

Fictional real-Chromium forms exercise multiple unresolved fields, independent known answers, radio deduplication, native and ARIA choices, approved conditional rendering, required validation, prefilled claims, replacement dialogues, late validation questions, cyclic and overlong forms, numeric constraints and bounded structural changes. Service/storage tests cover complete batch persistence, restart durability, scoped approvals, stale candidate revisions, sensitive flags, routine/location migration, capacity release and atomic rollback. Ordinary tests make no paid model calls and send no real applications.

The earlier interpretation enhancement added 54 questionnaire/HTML regressions and 11 benchmark-tool checks. They exercise all supported control families, contact type compatibility, approved negative answers, source-only prose, unavailable paid-work facts, numeric keyboard hints, sensitive/exceptional questions, invalid mappings, escaping, value omission, oversized fragments, scoped persistence, model-stage progress and no-fill/no-advance failure behaviour. Ordinary tests and CI use controlled responses and fictional browser forms.

The separate [live fictional benchmark](AI_BENCHMARK.md#questionnaire-html-comparison-5-october-2026) made eight authorised API calls, with no provider actions. It improved correct outcomes from 2/8 under deterministic rules alone to 8/8 with interpretation, including two deliberate review cases. This small sample validates the tested wording and contracts; it does not estimate accuracy across all LinkedIn or employer questionnaires.
