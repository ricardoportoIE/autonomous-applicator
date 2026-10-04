# React frontend and migration map

The local dashboard is implemented in React and strict TypeScript, built with Vite and Tailwind CSS. All six workspace areas and existing API operations are retained. Forms for adding or editing opportunities, candidate facts, qualifications, contacts and Greenhouse imports open native dialogues from explicit buttons. Dialogues have accessible names, keyboard containment, Escape/close handling and focus restoration. Failed saves keep the draft visible and explain the error inside the dialogue. Closing a dialogue discards unsaved input; successful saves update the underlying record and close it.

The main automation control toggles **Start agent / Pause agent** and shows **Starting agent… / Pausing agent…** while saving. It suppresses duplicate control requests separately from ordinary workspace work, so pausing remains possible during a slow operation. Start wakes the background queue immediately. The global pause preserves the user's separate networking switch, and stale responses cannot repopulate a locked workspace.

The current React unit suite has 154 cases and measures 100% in all ten runtime modules: 817 statements, 740 lines, 294 functions and 862 branch outcomes. The earlier migration measurements below refer to their own source revisions. Production Chromium tests additionally exercise the actual background Start/Pause flow with fictional records.

## Feature parity

| Area | Retained information and operations | Organisation |
| --- | --- | --- |
| Authentication | Local token, automatic session restoration, expiry handling, lock, private record removal | Dedicated lock screen; tokens are not placed in URLs |
| Overview | Opportunities/ready/review/submitted totals, London-day usage, remaining attempts, saved scoring bands, recent vacancies, cautious outcome observations, agent cycle | Hero, metrics and separate decision/capacity cards |
| Processing | Current vacancy, stage, run ID, total/stage elapsed time, terminal failure code, latest 50 results | Shared monitor visible in every unlocked area; read-only polling |
| Opportunities | Manual import, LinkedIn discovery with progress, Greenhouse board import, search/status/sort/clear filters | Queue plus compact discovery controls; imports in dialogues |
| Application overview | Original opportunity, named passed/blocked checks, local snapshot timestamp, fit reasons/blockers/matches/gaps, preparation origin, model/revision/evidence count, prepare/AI/submit/download actions, job editing | Overview tab; expandable full description, requirements, sponsorship, cover-letter requirement and source identity |
| Documents | Current PDF/DOCX CV and cover-letter downloads, manual approved-evidence selection | Documents tab; manual selection is explicitly recorded as a different origin |
| Questions | Exact approved keys/choices, required indicators, sensitive-question holds, application-scoped approval with readiness refresh, optional grounded GPT-6.1 Sol answer ideas | Questions tab; suggestions remain separate editable drafts and never approve answers; approvals retain valid CVs and other applications |
| Application record | Manual receipt reconciliation, confirmed receipt, interview/offer/rejected/no-response/withdrawn outcomes, scoped latest 200 events | Activity & outcome tab |
| Full application record | Original URL, recorded dates, per-attempt candidate/opportunity/evidence snapshots, archived documents and hashes, actual form observations, receipts and private provider confirmation screenshots, complete paginated journal | Dedicated bookmarkable page from the queue and management view; management actions remain in the existing tabs |
| Candidate | Name, e-mail, phone, location, summary, professional links, sponsorship, fact confirmation, approved JSON answers, current revision | Readable record; Edit candidate profile dialogue |
| Qualifications | Identifier, category, title, factual text, dates, technology tags, source, approval flag, edit/remove | Evidence cards; add/edit dialogue; edits still invalidate old documents |
| Networking | Discovery limit/progress, manual contact queueing, independent selected-member send, member link, private 64-pixel portrait/initials, highlighted location, live invitation status, uncertainty/history | Active/Archived tabs; sent requests are archived rather than deleted |
| Settings | Application/AI/discovery/networking switches, declared scope, both daily limits, scoring bands, target countries, interval, search keywords/location | Permission, search/policy and networking cards; one save action |
| Activity | Latest 200 durable global events and en-GB timestamps | Dedicated activity area |

Background pause remains available during long workspace actions. A native modal deliberately makes its background inert: close it to reach navigation or the global pause. Closing a dialogue does not cancel an operation already accepted by the server. The live processing record remains the authority for the operation’s state. Manual selected-member invitations retain their existing independent semantics; background queue invitations respect both saved switches and the global pause.

## Source structure

- `frontend/src/contracts.ts`: typed local API records and component inputs.
- `frontend/src/api.ts`: authenticated JSON, document and portrait requests with session generations. Requests started before locking cannot restore data, even after unlocking with the same token.
- `frontend/src/workspace.ts`: immutable snapshots consumed by React’s `useSyncExternalStore`, mutation ownership, global pause, periodic queue observation, selected invitation observation and private image cache.
- `frontend/src/App.tsx`: navigation, overview, queue filtering, candidate display and dialogue orchestration.
- `frontend/src/forms.tsx`: contract-preserving candidate, evidence, opportunity, contact, board and settings forms.
- `frontend/src/application-detail.tsx`: readiness, document provenance, grounded question ideas, explicit answer approval and journal/outcomes.
- `frontend/src/networking.tsx`: active/archive cards, private portraits and selected invitation progress.
- `frontend/src/application-record.tsx`: dated submission history, immutable materials, observed fields and authenticated confirmation preview/download.
- `frontend/src/components.tsx`: labelled native dialogues, keyboard tabs, tables, badges, events and processing monitor.
- `frontend/src/ui.ts`: pure parsing, identity, status and queue-order helpers.

The API, browser adapters, scoring, FIFO application lease, attempt reservations, CV renderer and GPT-6.1 Sol defaults retain their existing contracts. React does not send invitations or applications from effects: observation and explicit commands are separate. Poll failures never retry external actions. Profile edits retain `If-Match` revision checks. Candidate content is rendered as text, and portrait object URLs are revoked on lock. The existing same-origin Content Security Policy remains enabled; assets, icons and fonts require no CDN.

Read requests have one bounded retry after a transport failure, provided the same session still owns them. HTTP errors and mutation requests are not retried. A failed application action refreshes the opportunity and readiness snapshot through authenticated reads, so cleared documents, review holds or recorded receipts are reflected without repeating the command. Opportunity identity hashing also retains its opening session: a locked draft cannot be imported after another unlock.

The authenticated `POST /api/applications/{id}/questions/{question_id}/suggest` requires the reviewed profile revision in `If-Match`. It uses [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and the SDK’s [structured response parsing](https://developers.openai.com/api/docs/guides/structured-outputs), with `store=False`, a 180-second timeout and no provider retries. It validates cited evidence/fact identifiers and actual model identity, rejects stale snapshots, omits contact fields and sensitive questionnaire answers, and writes no records. Choice suggestions cannot replace missing or different exact approvals. React keeps ideas in component memory, clears them when the profile/question changes or the workspace locks, and uses a separate copy action before explicit approval.

## Development and checks

```powershell
npm ci
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
uv run python -m pytest
npm run coverage:browser
```

`npm run dev` opens the Vite development server for layout work; the packaged FastAPI server is the reference for authenticated integration and CSP checks. `npm run build:css` remains a compatibility alias for the complete React build. Build output replaces `src/applicator/static`, including its production index, hashed JavaScript/CSS and source map. Commit that output with the authored sources so wheel/CLI installations work without Node. CI rebuilds and checks for any static asset difference.

Vitest measures every authored runtime TypeScript/TSX module, including the React entry point, and requires **100% lines, statements, functions and branches for each file**. Only type-only `contracts.ts` and declaration files are excluded. React, icons, generated assets and test code are outside this authored-source measurement. The production-browser report independently maps V8 ranges through the Vite source map, checks the nine dashboard modules, excludes the bootstrap and third-party dependencies, and requires 90% lines and 80% branches. Only coverage matching the current bundle is accepted. These environments are measured separately; execution coverage does not establish defect-free behaviour.

Two isolated Vitest workers bound memory and CPU contention, retaining independent jsdom environments and the default five-second test deadline. GitHub's Windows runners exposed timeouts in two long interaction scenarios with four workers. Splitting authentication/form cleanup and filtering/detail editing into focused cases preserves their assertions and removes cumulative scenario latency; no retries or coverage exclusions were added. The 4 October 2026 review expanded the measured scope from three helpers to all ten runtime files: 147 tests cover 729 lines, 804 statements, 291 functions and 832 branch outcomes. Assertions cover complete saved payloads, rejected actions, draft ownership, stale responses, inaccessible storage, image cleanup, keyboard interaction and exactly-once command requests. Ten additional Chromium regressions verify all six reloaded routes, obsolete record success/failure, focus anchors, read-only record refresh and blocked browser storage against the production bundle.

Browser-marked Python tests use a bounded 15-second assertion deadline, restored to Playwright's five-second default afterwards. These verify eventual state, not a five-second response-time SLA: document writes, SQLite commits and the authenticated refresh can exceed five seconds on Windows CI. Explicit deadlines remain authoritative, and assertions still fail on an incorrect or unfinished state. Two additional production regressions hold a real local preparation/reconciliation response for six seconds, verify the visible busy state and successful completion, and require exactly one command. Increasing the observation window does not retry an application, invitation or mutation. Vitest retains its separate default five-second deadline.

Route and detail reads retain request and session ownership. Navigating, closing a detail or replacing a session invalidates obsolete success and failure responses; focus-only anchors do not cancel a record read. Duplicate history events share an in-flight record request. Reload restores recognised workspace areas, while invalid or unsafe numeric routes are ignored. Browser storage failures allow an explicitly explained in-memory session, and lock still clears private state. Validation errors are parsed as untrusted values. Downloads preserve authentication diagnostics, reject obsolete sessions and release private blob URLs even when a browser download fails. **Refresh record** updates the record with authenticated reads only.

Playwright retains the existing dashboard regressions and adds dialogue creation/editing, draft preservation, modal accessibility/focus restoration, complete opportunity fields, document/question/history tabs and explicit manual evidence selection. Model/provider operations use fictional records and intercepted or mocked adapters. Automated UI validation does not make paid OpenAI requests or send actual invitations/applications.

## Local application identity

The sidebar and browser tab share `frontend/public/icon.svg`: an approved application briefcase with a forward arrow. The 64-unit vector uses the existing lime and ink palette, stays sharp at favicon size and needs no font, CDN or model request. Vite copies the authored SVG into the Python package as `static/icon.svg`; the document declares its SVG favicon. The sidebar image is decorative beside the visible application name, preventing duplicate screen-reader announcements. Desktop/mobile production tests check successful same-origin loading, exact source/package bytes, image dimensions, the link's accessible name, safe vector elements, persistence after locking and WCAG scans.

## Sending capacity and routine answer controls

The overview reports confirmed applications sent and separate held sending slots; preparations remain eligible after the sending cap. Agent settings provide a routine-answer switch and city/country/configured-country location preferences. Application **Questions** includes scoped routine answers discovered during preparation or provider form reading, their provenance and the existing manual editing/suggestion controls. The **Overview** tab provides an explicit per-opportunity location acceptance check; documents stay downloadable during location review. **Activity & outcome** provides explicit negative reconciliation for an uncertain submission, with a required provider-check confirmation and a manual preparation hold before retrying.
