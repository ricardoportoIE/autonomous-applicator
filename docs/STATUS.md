# Delivery and validation record

Version 0.3.0 reviewed and locally validated through the React migration on 4 October 2026. Repository: [ricardoportoIE/autonomous-applicator](https://github.com/ricardoportoIE/autonomous-applicator).

## React migration validation, 4 October 2026

The six workspace areas now use React, strict TypeScript, Vite and locally compiled Tailwind CSS. All existing data fields and controls are retained in the [feature parity map](FRONTEND.md). Creation/editing forms open native dialogues; application tabs organise readiness, documents, approved questions and journal/outcome information. Active/Archived networking, private portraits and independent invitation observation remain available. No backend submission, scoring, FIFO, provider-authorisation or GPT-6.1 Sol contract was changed.

The first complete Windows/Python 3.14 pass ran 425 tests: 424 passed and one dashboard fixture encountered a transient local read transport failure. All 97 affected frontend cases subsequently passed. The final review added three regressions for bounded read recovery, refreshing a failed preparation's review/document state and rejecting a locked opportunity draft after asynchronous hashing. The final production-bundle run passed all **100 dashboard cases** in 269 seconds. Together with the unchanged backend cases from the complete run, this covers **428 distinct passing Python tests**. No failed assertion was removed.

| Check | Local result |
| --- | --- |
| Vitest/React Testing Library | 45 tests passed |
| Core TypeScript coverage | 100% lines; 99.31% statements; 93.20% branches; 98.59% functions |
| Production React browser coverage | 98.77% lines; 94.09% branches; 97.03% functions, mapped to authored TypeScript with dependencies excluded |
| Combined Python coverage | 97.65%; 98.44% statements (1,897/1,927); 95.21% branches (596/626) |
| Accessibility and responsive layouts | Six views, native dialogues and application/connection tabs; axe WCAG checks; 390/768/1,440 pixels, keyboard use and enlarged text |
| TypeScript / strict mypy | Passed; 15 Python runtime modules |
| ESLint / Prettier / Ruff / formatting | Passed |
| Production assets | Rebuilt byte-for-byte without changes; four packaged assets verified against the wheel |
| Dependency audits | npm and Python reported no known vulnerabilities |
| Repository hygiene | 92 tracked files checked; no credentials or local contact fields |

Authenticated read-only inspection of the actual local workspace verified all six React views, desktop/mobile layout, native dialogue opening/closing, actual GPT-6.1 Sol CV provenance and the unresolved exact work-authorisation question. Application/invitation attempt totals stayed at three/seven and all nine application records remained in review. Automation remains paused. No paid model request, actual application or invitation was sent during this migration. Personal records, portraits, CVs, tokens and live screenshots remain ignored.

Implementation commits: `cf2d898` (React migration) and `8a6920f` (failed-action reconciliation and asynchronous draft protection). The [complete GitHub Actions run](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37182102270) passed all four Linux/Windows and Python 3.12/3.14 combinations at `8a6920f`, including all 428 Python tests, 45 frontend unit tests and the production browser coverage checks. The subsequent validation-record commit changes documentation only.

## Implemented

- FIFO completion of each vacancy's preparation and submission, durable operation ownership, live opportunity/stage/timing feedback and correlated failure history.
- Workspace ownership covering initial migrations and recovery, interrupted-preparation review holds, current browser candidate snapshots and graceful shutdown without taking another vacancy.

- Current and legacy LinkedIn job detail readers, exact job redirect checks, bounded canonical discovery and visible job-search progress/outcomes.
- Native/ARIA Easy Apply dialogues, grounded phone country components, verified CV chooser selection, custom screening radios and stopped-step detection.
- Configurable default GPT-6.1 Sol preparation for ordinary and worker flows, visible model provenance, candidate/job fingerprints and review after API failures without local fallback.
- Read-only submission preflight, current gate explanations, actual daily attempt capacity, searchable/filterable/sortable queues and application-specific activity.
- Single-connection queue reads, indexed journals and quota queries, required-cover-PDF checks and LinkedIn identity validation before reservation.
- Locally compiled Tailwind CSS, responsive layouts, semantic navigation, agent readiness, session locking and outcome counts.
- Request-stream limits, stale profile edit detection, transactional evidence changes and latest-attempt receipt protection.
- Loopback dashboard, local token authentication, same-origin checks and browser security headers.
- Versioned candidate profile, qualifications, evidence, approved questionnaire answers and historical application documents.
- Transparent job fit and 80/50 routing, sponsorship exclusions, mandatory-condition review and stale-material invalidation.
- Manual and Greenhouse imports; LinkedIn discovery, bounded Easy Apply, approved text/select/radio answers, document uploads and confirmation checks.
- European recruiter discovery and controlled invitations; no public profile edits.
- Private, authenticated 64-pixel contact portraits with initials fallback and highlighted locations in active and archived queues.
- Accessible profile links for every connection state, spaced controls and independent single-contact invitations in a visible dedicated browser.
- Durable Started/Running/Done/Failed/Needs review feedback, primary-card Connect/More selection, concurrent status reads and lock/reload observation without resending.
- Current semantic and legacy LinkedIn profile cards, primary-result link selection, exact invitation identity checks and readable browser-error diagnostics.
- Ten daily application attempts and three daily networking attempts by default, pause controls, durable attempt journalling, deduplication, uncertain-state recovery and outcome recording.
- A4, single-column, selectable-text PDF CVs, optional cover letters and editable DOCX versions, with job-specific evidence selection and document hash checks.
- Optional `gpt-6.1-sol` adviser using structured evidence identifiers. No factual generation or private chain-of-thought logging.

## Local validation

### Sequential application queue follow-up, 4 October 2026

The previous worker prepared all pending documents before submitting ready applications, in newest-first listing order. The shared service now completes each eligible vacancy in arrival order, from preparation through confirmed submission or a durable hold. A read-only live status endpoint and dashboard monitor show the selected vacancy, current or failed stage, timing and run identifier. Recent per-vacancy outcomes remain available after empty cycles.

Twenty-three backend queue cases and nine browser scenarios were added. They cover exact end-to-end order, ready/unprepared mixtures, no fallback or automatic retries, exact required-answer holds, quota before the next model call, pauses during preparation and after a receipt, shutdown boundaries, slow status observation, immediate competing-request conflicts, run-correlated journals, current browser facts, interruption and exclusive server ownership. Browser coverage adds live AI/form stages, failure persistence, reload observation, pause, status failure/recovery and session clearing. The intercepted native-dialogue test now asserts the actual browser stage sequence. No real applications or invitations are sent by these fixtures.

The complete suite passed twice locally: 410 Python tests in 934 seconds, followed by a final-source run of **410 tests in 889 seconds**, plus **8 JavaScript unit tests**. Forty-five focused checks also passed after tightening startup ownership. Final Windows/Python 3.14 combined coverage is **97.65%**, with **98.44%** statement coverage (1,897/1,927) and **95.21%** branch coverage (596/626). Durable operation tracking reaches 100% measured coverage; the service reaches 98% and the store 99%. Dashboard browser coverage is **99.28%** of lines, **96.56%** of branches and **100%** of functions. Helper unit coverage remains 100%.

Ruff/formatting, strict mypy across 15 modules, frontend lint/format checks, deterministic Tailwind generation, package construction, repository hygiene and fresh Python/npm dependency audits passed. The [GitHub Actions run for the implementation](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37160671863) passed all four Linux/Windows and Python 3.12/3.14 jobs for commit 3057892. The subsequent validation-record commit changes documentation only.

The running local server was updated after a private SQLite backup and paused/no-in-flight checks. Authenticated read-only checks at desktop and mobile widths verified the monitor, no horizontal overflow, session clearing and zero JavaScript errors. Existing prepared-document hashes and AI provenance remained valid, the required work-authorisation question remained blocked for review, and application/invitation attempt counts and application states were unchanged. Automation remains paused. No paid model calls or real applications/invitations were made during this queue follow-up.

### Default AI CV preparation follow-up

The [CV preparation audit](CV_PREPARATION.md) distinguishes historical local preparations from actual model calls. A read-only inspection found one prepared CV with no model provenance. Two new real `gpt-6.1-sol` requests through an isolated default-preparation workspace then produced different evidence sets and CV content for two existing vacancies, while preserving approved text and zero submission attempts. Four PDFs/eight pages passed content, hash and Poppler visual checks. Preparation took 8.209/5.025 seconds with AI and 0.173/0.157 seconds locally. The summary remains approved base wording; this comparison does not establish improved hiring outcomes or ATS acceptance.

The candidate authorised default AI preparation and review after API failure. The shared service now applies that setting to ordinary and new worker preparations, records actual response/model metadata and current snapshot fingerprints, and checks provenance before reservation. Twenty-six new backend cases and two real-browser scenarios cover these behaviours with mocked responses and no paid API calls. Previous live benchmark results concern the earlier prompt/renderer and remain a historical comparison.

After a private SQLite backup and paused/no-in-flight checks, the local server was updated and default AI preparation enabled. A third real request regenerated the pending CV through the ordinary endpoint and confirmed `gpt-6.1-sol`, current revision, valid factual content/hashes and two visually verified pages. An authenticated dashboard check showed the actual model and checked default setting, with no JavaScript errors. The required questionnaire remained unanswered, the application stayed in review, the original attempt count was unchanged and automation remained paused.

Full local validation on Windows/Python 3.14 passed **372 Python tests** in 873 seconds and **8 JavaScript unit tests**. A subsequent coverage review added six failure cases; all **26 AI preparation tests** then passed in eight seconds with coverage appended, for **378 distinct passing Python tests**. Combined Python coverage is **97.73%**, with **98.48%** statement coverage (1,690/1,716) and **95.47%** branch coverage (548/574). The adviser and API reach 100% measured coverage; the service reaches 97%. Dashboard browser coverage is **99.22%** of lines, **96.00%** of branches and **100%** of functions. Ruff/formatting, strict mypy, frontend lint/format/unit checks, deterministic Tailwind compilation, repository hygiene and the distribution build passed. Personal CVs, credentials, provider response identifiers and live reports remain ignored.

### Easy Apply form follow-up

The live failure occurred before final submission because the current form used a native dialogue without an explicit role attribute. The repair also covers required-label markers, separate phone country/number inputs, the current resume file chooser and custom screening radio cards. Resume selection is verified against the job-specific CV filename and both native/ARIA checked state; questionnaire controls cannot be excluded through overlapping identifiers. Optional unchecked preferences remain unchecked, and stalled steps stop before repeated uploads.

An authenticated rehearsal filled approved contacts, uploaded and verified the job-specific CV and reached an unanswered mandatory work-authorisation question. No final submission was clicked or new attempt reserved. The discovered question and its actual binary choices are retained locally. Conditional candidate facts were saved separately; they were not converted into an approved Yes/No answer. The target remains in review, with current documents and an explicit unanswered-question blocker. Automation remains paused. Private records, CVs and browser snapshots remain excluded from Git.

A read-only authenticated dashboard check verified a blank answer selector with the provider's actual choices, blocked preflight, valid regenerated documents and no JavaScript errors. It changed no candidate answers and sent no application.

Full local validation on Windows/Python 3.14: **350 Python tests passed** in 804 seconds, including 46 new form regressions, plus **8 JavaScript unit tests**. Python statement coverage is **98.23%** (1,605/1,634), branch coverage **95.04%** (517/544), and combined coverage **97.43%**. Dashboard browser coverage remains **99.19%** of lines, **95.91%** of branches and **100%** of functions. Ruff, source/test formatting, strict mypy, frontend lint/format checks, repository hygiene and the distribution build passed. No paid OpenAI requests were made. The local server was restarted after a private SQLite backup and paused/no-in-flight checks; a repeated authenticated dashboard check retained the unanswered question, valid documents and original attempt count.

### LinkedIn job search follow-up

The live search failure was traced to changed vacancy detail markup: results were accessible, but the old detail selectors were absent. The reader now supports the observed paragraph-based header and **About the job** section, while retaining the explicit legacy contract. Search uses canonical approved-origin job IDs, filters duplicate and malformed links, scopes structured results away from recommendations, recognises explicit empty results and verifies the opened vacancy. Submission shares this reader and compares the reviewed title, company, location and description before Easy Apply.

Thirty-one new regressions cover complete identity, unsupported fields/layouts, delayed rendering, limits, redirects, origins, deduplication, no results, changed submission snapshots and accessible mobile progress/outcomes. The legacy provider fixture now explicitly declares its UTF-8 encoding; submission and receipt assertions remain intact.

The local server was restarted after a private SQLite backup and checks that neither queue had an in-flight submission. A live dashboard search returned HTTP 200, imported seven complete local opportunities and showed its progress and completion at 390 pixels without overflow or JavaScript errors. Application and invitation attempt counts were unchanged. Automation remained paused; no real application or invitation was sent. Private identities, snapshots and credentials were not published.

Full local validation on Windows/Python 3.14: **304 Python tests passed** in 813 seconds, plus **8 JavaScript unit tests**. Python statement coverage is **98.31%** (1,508/1,534), branch coverage **95.27%** (463/486), and combined coverage **97.57%**. Dashboard browser coverage is **99.19%** of lines, **95.91%** of branches and **100%** of functions; helper unit coverage remains 100%. Ruff, formatting, strict mypy, frontend lint/format checks, deterministic Tailwind compilation, repository hygiene, distribution verification and Python/npm dependency audits passed. The suite uses fictional or intercepted provider fixtures and makes no paid OpenAI requests. Live Easy Apply submission remains outside this read-only discovery validation.

### Live OpenAI comparison follow-up

A separate user-authorised comparison made twelve real `gpt-6.1-sol` requests using six fictional cases with two repetitions each. Every AI preparation passed, preserved the original submission evaluation and generated documents from approved facts only. Median full preparation time was 3.2492 seconds with AI and 0.0804 seconds locally. Mean selected-evidence relevance precision was 91.67% versus 66.67% against the predeclared fixture rubric. The standard token-based cost estimate was US$0.025104, including cache writes. No application or invitation was submitted. The [complete benchmark report](AI_BENCHMARK.md) records methods, usage, content/visual review, reproduction instructions and the small-sample limitations. Eight new offline benchmark checks and eighteen relevant existing regressions passed; the earlier full-suite coverage below is unchanged and excludes these new helper tests.

### Contact portraits and local OpenAI configuration follow-up

Contact discovery optionally captures the single primary member portrait after checking the reviewed identity, role and location. Images stay in the ignored local data directory and are served through an authenticated no-store PNG endpoint. The dashboard shows circular 64-pixel portraits, a separate highlighted location and initials when a photo cannot be loaded. Only the selected tab's images are fetched; locking revokes their blob URLs and discards late downloads. Twenty-five new regressions cover browser capture, bounds and identity checks, cache/storage failures, authenticated access, unavailable or invalid images, tab caching, mobile/desktop accessibility and session locking.

A read-only profile inspection cached all eight existing contact portraits. The running local dashboard then displayed all eight images at the intended size at both 390- and 1,440-pixel widths, highlighted their locations and removed their images on lock. The mobile check also confirmed no horizontal overflow with the actual longer roles and locations. This verification used only authenticated local GET requests, sent no invitations and changed no database records. An SQLite backup was taken before starting the updated local server.

The optional OpenAI adviser is implemented and was not called during the earlier portrait checks. A private ignored `.env` was initially prepared with an empty `OPENAI_API_KEY`; a subsequent presence-only check found a locally configured key before the updated server started. The key was not displayed or validated through a paid request at that stage. Operational documentation explains how to enter a fresh local key and restart the server. The adviser remains explicitly selected through the evidence-selection button.

The first remote run stopped at a newly reported Tailwind tooling dependency advisory before Python tests. A scoped watcher 2.6.0 override removes the vulnerable dependency chain. Fresh npm/Python audits report no known vulnerabilities. A clean npm installation, byte-for-byte unchanged compiled CSS and an isolated native-watch rebuild also passed.

### Recruiter discovery and archive follow-up

Manual recruiter discovery now uses the saved daily connection limit as its target instead of a fixed three. Background discovery uses the remaining networking quota. Existing contacts are excluded regardless of state, and the adapter reviews at most ten new primary results to fill the requested number of suitable European hiring contacts. Searches can return fewer matches when available suitable results are exhausted.

The search button displays Searching, an activity indicator and an accessible status message until completion, no results or failure. Duplicate clicks are suppressed and a locked workspace discards late responses. Active and Archived tabs show counts and support keyboard navigation. Confirmed sent contacts move automatically to Archived, preserving profile links, delivery confirmation, historical records and quotas. Failed and uncertain contacts remain active for review.

Fifteen new regressions cover saved limits, remaining quota, known-contact exclusion, filtered results and bounded inspection, search progress/outcomes, duplicate suppression, locking, automatic archiving, keyboard tabs and desktop/mobile accessibility. An older mocked receipt fixture now configures the combined button/link locator used by the Pending check; provider ambiguity guards are unchanged. A read-only check of the running local dashboard confirmed the saved limit and archived history, without searching or sending invitations. Packaging and repository hygiene checks passed; test screenshots use fictional contacts.

### Pending invitation confirmation follow-up

The live LinkedIn profile layout renders **Pending** as a link whose accessible name includes an invitation-withdrawal description. The previous confirmation check accepted only a button, so a successful invitation could remain uncertain. Confirmation now accepts a visible button or link, with either a plain or extended Pending label, and requires exactly one matching control on the verified primary member card. Recommended members' controls cannot confirm an invitation.

Five intercepted-provider regressions cover plain Pending links, extended button/link labels, a recommended member's pending control and duplicate confirmations. A separate read-only account inspection confirmed existing invitations and reconciled the corresponding local records without clicking Connect, Follow, Send or Withdraw. Private identities and runtime records remain outside the repository.

Follow-up validation: **45 tests passed** across the manual-networking and contact-discovery modules. Ruff checks, Python formatting and strict mypy also passed. These checks do not repeat the complete frontend suite or establish live submission behaviour for every LinkedIn layout.

The full-suite results below include the contact portrait implementation `9f33692`. The tooling-only dependency correction is `53411b4`; it reproduces the same dashboard CSS.

| Check | Result |
| --- | --- |
| Python tests | 265 passed, including backend and real-browser integration tests |
| JavaScript unit tests | 8 passed |
| Python statement coverage | 98.26% (1,470 / 1,496 statements) |
| Python branch coverage | 95.04% (441 / 464 branches) |
| Combined statement/branch coverage | 97.50%; CI minimum 90% |
| Dashboard JavaScript browser line coverage | 99.18% (1,216 / 1,226 lines), across app.js and ui.js |
| Dashboard JavaScript browser branch coverage | 95.81% (343 / 358 branches) |
| Dashboard JavaScript browser function coverage | 100% (63 / 63 functions) |
| Helper unit coverage | 100% lines, branches and functions in ui.js |
| Frontend journeys | 67 scenarios, including 46 axe scans across six views, application detail, invitation progress, search outcomes, portraits and the active/archive tabs at desktop and mobile widths |
| Responsive checks | 390, 768 and 1,440 pixels; keyboard navigation and 200% text enlargement |
| Ruff | Passed |
| Frontend checks | ESLint and Prettier passed |
| Strict mypy | Passed for all 13 source modules |
| Dependency audits | Python and npm reported no known vulnerabilities; the unpublished local package is not a PyPI audit target |
| Packaging | Source archive and wheel built; packaged dashboard assets match current source, private data absent |
| Document QA | PDF/DOCX content and layout checks repeated; earlier visual inspection of the unchanged renderer produced a two-page CV and one-page cover letter |
| Browser journeys | Dashboard/profile/evidence/job/settings journey, local upload/submission fixture, intercepted LinkedIn Easy Apply and recruiter-discovery fixtures |
| Persistence and security | Threshold properties, concurrent reservation, daily limits, unknown answers, altered documents, origin/Host/token checks, crash recovery and SQLite backup/restore |
| Repository hygiene | Credential patterns and private contact details absent from 58 tracked files |

The improvement pass adds 22 Python regressions and three JavaScript helper tests. Diagnostics are explicitly tested to leave records, journals, attempt counts and submission adapters untouched. A browser submission journey uses a mocked provider adapter, records its fictional receipt and checks the quota and timeline. Preview screenshots use fictional example records only. Both 0.3.0 distributions were verified, including byte-for-byte dashboard assets and exclusion of private runtime paths.

Browser coverage uses precise V8 ranges from the actual local application, converted with v8-to-istanbul. Helper unit coverage is reported separately. The browser report gate requires 90% lines and 80% branches. Python coverage explicitly traces Playwright greenlets and API worker threads using the C tracing core, following the [Coverage.py configuration guidance](https://coverage.readthedocs.io/en/latest/config.html).

The [complete source review](CODE_REVIEW.md) records the line-by-line inspection and regression findings. The CI matrix checks Linux and Windows with Python 3.12 and 3.14, using Node.js 24. It also rebuilds the committed Tailwind CSS and verifies unchanged output, runs frontend checks, audits dependencies and publishes coverage reports. [Remote CI passed all four combinations](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37108488461) for commit `53411b4`, including the portrait implementation and tooling correction. The first Windows/Python 3.14 attempt encountered two five-second timeouts in existing dashboard-unlock/manual-queue checks. Both checks passed in a targeted local repeat, and the complete Windows job then passed on rerun without changing assertions or runtime code. The previous networking implementation `cc82fac` and earlier member-link, recruiter-discovery, browser-login and version 0.3.0 matrices also passed. This final record changes documentation only. The [improvement assessment](IMPROVEMENTS.md) distinguishes delivered capabilities from proposed next priorities.

## Required live setup and limits

The current coverage measurements and full-suite counts above include contact portraits, recruiter discovery limits, visible search progress, automatic archiving and Pending link confirmation. The login correction has three tests distinguishing expected window closure from setup or unrelated failures. The discovery repair adds 19 regressions covering semantic/deeply wrapped/legacy cards, ambiguous or incomplete identity, wrong contact-information links, result scoping, canonical deduplication, bounded discovery, sanitised API errors and frontend recovery. Invitation checks require the same primary profile identity, role and location; redirects stop before examining invitation controls.

The initial networking UI follow-up added isolated member links. The independent invitation implementation adds 30 test cases: 22 backend/provider cases and eight frontend scenarios. A single manual invitation works with no candidate facts and paused background queues, shares the networking quota, and opens the selected profile with visible-browser intent. Intercepted browser cases exercise direct buttons and links, More menus and delayed popovers, rendering delays, Follow-only and recommended-member controls, duplicate controls, identity/location changes, login challenges, redirects, revoked scope and missing confirmation. Other checks cover sanitised failures, database migration, interrupted-run ownership, readable concurrent status and immediate busy-browser rejection. Frontend checks verify phase changes, failure/uncertainty, independent navigation, duplicate suppression, lost responses, status errors, reload observation and locking without resending. No real invitation was sent during these checks.

The updated local server was restarted after an SQLite backup and a check that no invitation was in flight. Authenticated status reads verify the new fields and retained historical uncertainty; unauthorised reads and unknown records are rejected. Background application automation remains disabled. A read-only inspection of available live profiles verified primary More controls and a Connect menu item where available. The inspection opened menus but did not click Connect, Follow or Send. An unavailable Connect action remains a bounded failure, rather than a fallback to Follow. Live invitation submission and receipt behaviour still require account-level validation.

Manual LinkedIn sign-in was completed in the dedicated local profile on 2 October 2026. A separate read-only check reopened that saved profile headlessly and reached both the authenticated feed and the configured job search. It imported no records and sent no applications or invitations. This verifies session reuse and search access; Easy Apply uploads and submission selectors still need live validation.

Recruiter discovery was subsequently checked against the authenticated account and observed profile layout. The actual local discovery endpoint returned HTTP 200 with three matching European recruiters, retained as queued contacts in the ignored database. Their invitation attempt dates and receipts remain empty, and automation remains paused. No invitation was sent. Live member identities and browser snapshots were not published.

The candidate-declared LinkedIn scope for discovery, Easy Apply and networking is configured in the local workspace. The initial adapter still requires validation against the authenticated account and current live selectors. All LinkedIn traffic in the automated tests is intercepted; tests send no real applications or invitations. A missing visible confirmation after a submission click is explicitly tested as uncertain, without automatic retry.

The local candidate profile was translated from the supplied documents and subsequently confirmed in the local workspace. Unapproved evidence remains excluded until candidate review. This confirmation does not independently certify qualifications. Use `browser-login` to renew authentication when needed. Keep a fresh, rotated API key in the ignored local environment file to use live AI advice. Credentials were not displayed or committed. The earlier implementation/mocked suites made no paid OpenAI requests; the separately authorised live benchmark above made twelve.

Automation remains paused locally. Unknown or unsupported questions stop for review; employer-specific portals without an adapter use manual hand-off. Feedback currently provides recorded outcomes and cautious observations, not self-training or automatic factual/policy changes. This is a tested local prototype, not a guarantee of defect-free live job applications or ATS acceptance.
- React and strict TypeScript frontend, Vite production packaging, locally compiled Tailwind styling, focused creation/editing dialogues and keyboard-accessible application tabs.
- Immutable React workspace snapshots, session generations, out-of-order refresh protection and draft-bound candidate revisions; all existing functions mapped in [FRONTEND.md](FRONTEND.md).
