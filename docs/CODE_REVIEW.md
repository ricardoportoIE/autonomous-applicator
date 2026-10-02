# Source review, 2 October 2026

Every line of the authored runtime modules, dashboard HTML, JavaScript and styling, test suite, CLI, repository hygiene script, CI configuration and operational documentation was inspected. Generated CSS and dependency lockfiles were checked through reproducible builds and dependency audits. Dependency source code, the live LinkedIn website and private source documents are outside this review's line-by-line scope.

## Findings and corrections

| Finding | Correction and regression evidence |
| --- | --- |
| Request limits trusted `Content-Length` | Count actual stream bytes. Chunked requests and incorrect/missing length headers cannot bypass the limit. |
| Saved short tokens were accepted | Validate persisted token length without silently replacing the file. |
| Profile edits could overwrite newer facts | Dashboard writes include the profile revision. Stale writes fail and retain the draft. Evidence edits are transactional; six concurrent additions retain every item. |
| LinkedIn scope could change before reservation | Recheck scope in the reservation transaction. Revocation creates no attempt or provider action. |
| LinkedIn URLs accepted unexpected authorities | Reject embedded credentials, lookalike hosts and non-standard ports. Compare the job URL identifier with the stored identity before opening a browser. |
| Long questions could not enter review | Support approved-answer keys for full-length labels and deduplicate discovered questions. |
| Attempt completion could overwrite a receipt | Require the latest owned reservation in submitting state. Wrong, old and repeated finishes are rejected. |
| European locations used substring matching | Use country word boundaries and reject known non-European ambiguities such as New South Wales and New Ireland. |
| Empty discovery settings were accepted | Validate non-empty search values and bounded, deduplicated country names. |
| Mutated model objects could bypass validation | Revalidate before saving; invalid profiles leave the original revision intact. |
| Frontend errors exposed raw validation structures | Format field errors, explain invalid JSON and handle non-JSON server failures. |
| Networking entries lacked profile links and did not explain local confirmation | Add accessible member links in every state, separate the status from action controls, and show a review shortcut for unconfirmed candidate facts. Browser regressions check isolated new tabs, mobile/desktop accessibility, unchanged attempt state when blocked, and the explicit confirmation/save flow. |
| Duplicate actions could race | Disable workspace controls while an operation runs; retain the global pause control. |
| Session locking could retain private content | Clear local credentials, records and form fields; reject responses from an older session. |
| Question controls had ambiguous labels and values | Use explicit accessible labels and constrained choices; sensitive questions show a manual-handling message. |
| Policy labels could diverge from saved settings | Render the configured thresholds. |
| Contrast and responsive hierarchy needed improvement | Use compiled Tailwind styling, prioritise the queue, and check six views with axe, three viewport sizes, keyboard navigation and enlarged text. |
| A ready badge did not explain current operational blockers | Add a read-only local preflight with current policy, scope, target identity, quota, questions and document checks. Actual submission repeats the authoritative gates. |
| A required cover letter could be missing from the manifest | Require the cover PDF before reservation, as well as validating its recorded hash. |
| Invalid LinkedIn targets consumed a reservation before being rejected | Validate the approved job URL and stored identifier before reserving; repeat the browser-side check. |
| Queue listing opened a connection per application | Fetch and decode records in one query and connection. A regression verifies this property. |
| Global activity could bury an individual application's events | Provide an indexed, application-specific journal query, independent of the latest global 200 entries. |
| Saved outcomes were not selected when reopening a record | Initialise the outcome control from the stored outcome. |
| The live recruiter profile no longer used the legacy `h1` and CSS classes | Add a shared profile reader for the observed semantic card, bounded heading ancestry and member-specific contact-information link. Retain strict legacy support; reject ambiguous/incomplete fields. |
| Search cards included links to mutual connections | Read only each card's primary member link. Exclude navigation and unrelated links; canonicalise duplicates before the limit. |
| Playwright failures became an opaque HTTP 500 | Return a sanitised JSON 502 diagnostic without provider traces. A frontend regression verifies the message and a successful subsequent discovery. |
| Invitation checks could match a role elsewhere on the page | Re-read the primary profile card and require exact reviewed identity, headline and location. Profile redirects stop before checking invitation controls. |

The post-test improvement pass reviewed every changed source and test line. New diagnostics use authenticated GET requests, perform no browser or paid model calls, generate no documents and write no journal entries. Additional regressions verify these properties, daily accounting, tampered materials, filter composition and local/mock submission journeys.

## Module inspection

| Surface | Inspection focus |
| --- | --- |
| `models.py` | Input limits, unique identifiers, source contracts and settings |
| `policy.py` | Aliases, score boundaries, sponsorship, seniority, factual evidence and answers |
| `store.py` | SQL parameters, transactional edits, quotas, attempt ownership, history and recovery |
| `service.py` | Current policy, document hashes, registered providers, receipts and uncertainty |
| `api.py` | Authentication, Host/Origin, stream limits, routes, worker exceptions and browser locking |
| `browser.py` | Exact origins and identities, grounded forms, uploads and submission failure boundaries |
| `networking.py` | Identity, European location, deduplication, independent limits and uncertain invitations |
| `documents.py` | Approved content, chronology, escaping, A4 layout, page/size limits and hashes |
| `adviser.py` | Explicit model, structured evidence-only output and rejected invented identifiers |
| `discovery.py` | Fixed provider origin, board identifiers, HTML extraction and response limit |
| `cli.py` | Loopback binding, import, dedicated browser login and environment configuration |
| `static/`, `frontend/` | Text-safe rendering, form parsing, session lifecycle, accessibility and deterministic CSS |
| Tests, scripts, CI and documentation | Meaningful assertions, fixture isolation, measured coverage and public-data hygiene |

Conservative stops remain for changed descriptions, ambiguous uploads, missing documents, unsupported controls and unconfirmed receipts. Tests use fictional records and intercepted provider traffic. Coverage measures execution; it does not certify live provider selectors or every employer form. No real application or invitation was sent during this review.
