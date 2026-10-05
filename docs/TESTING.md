# Testing and coverage

## Backend acceptance gate

The complete Python suite must reach **100% statement and branch coverage in every module under `src/applicator`**, including API endpoints, policy, AI contracts, persistence, document rendering, browser adapters, networking, operation recovery and the command-line entry point. The runtime inventory contains **19 modules**. Statement and branch counts change with source revisions and Python versions; the JSON report and inventory-gate output record the exact counts for each run. Each interpreter must cover its complete measured inventory. The empty package initializer is included in the inventory. Historical measurements are retained in [the delivery record](STATUS.md).

Pytest measures branches as well as statements and fails below 100%. A second gate checks the JSON report against every authored Python application file, rejects missing or unexpected modules, requires zero missing statements and branches in each module and validates the counters. CI runs both checks independently on Windows and Linux with Python 3.12 and 3.14. A percentage rounded to 100% cannot satisfy these checks while a missing path remains.

No runtime module is omitted and no coverage-ignore directives are permitted. Coverage.py's default exclusion of the signature-only `Adapter(Protocol)` declaration is retained: it defines a typing contract with an ellipsis rather than a runtime implementation. The inventory gate checks the source and allows only such signature-only protocols and blank lines; an excluded concrete method fails the gate. Test code, repository tooling and generated frontend assets are outside the Python application metric. The coverage gate has its own acceptance and rejection tests.

## Behaviour verified

| Boundary | Representative assertions |
| --- | --- |
| Candidate facts and questions | Unknown eligibility is never inferred; ambiguous durations and capability modifiers remain in review; stale, sensitive, invalid and oversized routine answers cannot be stored. |
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
uv run pytest tests/test_backend_integrity.py tests/test_browser_boundaries.py --no-cov
uv run pytest tests/test_backend_coverage_gate.py --no-cov
```

Before delivery, rerun the complete suite and the inventory gate. Additional required checks are strict TypeScript/mypy, ESLint/Ruff, formatting, tracked-file privacy, dependency audits and reproducible committed frontend assets. [Delivery status](STATUS.md) records measured results; [review findings](CODE_REVIEW.md) records their interpretation.

## Security and performance reproduction

```powershell
uv run python -m pytest tests/test_security_hardening.py tests/test_security_frontend.py tests/test_local_performance.py --no-cov -o 'addopts=--strict-markers'
uv run python scripts/benchmark_local.py
```

The hardening contributes 53 cases to the 865-case Python inventory: 43 security unit/integration/property cases, one production Chromium case and nine benchmark checks. The DNS-rebinding property runs 40 generated suffixes within one counted pytest case. An autouse fixture clears inherited runtime variables and prevents CLI tests from loading `.env`; an isolated CLI regression proves private credentials/data paths cannot be imported. Individual tests remain free to set explicit fictional configuration. The complete suite also contains transactional concurrency, recovery, document/PDF, controlled AI, provider-contract, accessibility and production-browser checks. These are appropriate complementary layers; the project does not claim every possible type of security audit, live-provider load test or independent penetration test.

CI runs the default offline benchmark and uploads `test-results/local-benchmark.json` per platform/interpreter alongside coverage. [Performance](PERFORMANCE.md) defines its methodology, baseline and limits. Byte/intake-time limits are tested behaviour gates; benchmark milliseconds are observations rather than CI pass/fail thresholds. The [security model](SECURITY.md) defines the account and provider boundaries exercised by the tests.

Windows jobs additionally run `tests/powershell/test_private_permissions.ps1` outside the Python coverage metric. Eight native ACL scenarios use disposable fictional files: recursive private protection, repeat execution, junction refusal without changing the target, an empty workspace, non-project root refusal, default workspace resolution, injected-write-failure rollback with legacy metadata and rejection of genuine permission changes by the comparator. Assertions also verify unchanged content/owners/public-source DACLs and private permission backups. Rollback comparison preserves all access rules, masks, order, ACE inheritance flags and DACL protection state; it normalises only Windows' automatically updated `DiscretionaryAclAutoInherited` metadata flag. A fixture-only native setter constructs that legacy state explicitly. This tooling suite does not claim Python's 100% runtime metric for PowerShell. Reproduce it with `powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test_private_permissions.ps1`.

## Interpretation

100% coverage means every measured application statement and branch outcome was exercised by the suite. Assertions establish the intended behaviour for those cases. It does not establish every possible input, future provider layout, network condition or hiring outcome. Live provider compatibility still depends on the declared authorisation, valid sign-in and the current supported interface contract. Unknown behaviour continues to require review.
