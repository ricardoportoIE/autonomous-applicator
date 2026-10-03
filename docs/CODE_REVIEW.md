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
| Networking entries lacked profile links and individual execution feedback | Add accessible member links in every state and spaced controls. Explicit single-contact invitations use a visible dedicated browser, independent of CV confirmation and background enable switches. Durable progress and browser regressions cover isolated new tabs, desktop/mobile accessibility, current phases, safe failure, uncertainty, lock/reload recovery and duplicate suppression. |
| Generic Connect controls could refer to recommended profiles, or precede client rendering | Bound action selection to the primary card containing the reviewed identity; wait for visible rendered controls and support direct buttons/links and More menus. Intercepted browser regressions check recommended contacts, Follow-only cards, delayed rendering, duplicate controls, redirects and scope revocation. |
| Every invitation exception was treated as uncertain, including pre-browser failures | Record known failures before Connect separately. Conservatively hold outcomes after Connect may have been clicked; require a visible Pending receipt for completion. Run ownership prevents stale progress or receipts after crash recovery. |
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
| `photos.py` | Private URL-keyed cache, bounded PNG dimensions/size, path containment and atomic writes |
| `documents.py` | Approved content, chronology, escaping, A4 layout, page/size limits and hashes |
| `adviser.py` | Explicit model, structured evidence-only output and rejected invented identifiers |
| `discovery.py` | Fixed provider origin, board identifiers, HTML extraction and response limit |
| `cli.py` | Loopback binding, import, dedicated browser login and environment configuration |
| `static/`, `frontend/` | Text-safe rendering, form parsing, session lifecycle, accessibility and deterministic CSS |
| Tests, scripts, CI and documentation | Meaningful assertions, fixture isolation, measured coverage and public-data hygiene |

Conservative stops remain for changed descriptions, ambiguous uploads, missing documents, unsupported controls and unconfirmed receipts. Tests use fictional records and intercepted provider traffic. Coverage measures execution; it does not certify live provider selectors or every employer form. No real application or invitation was sent during this review.

## LinkedIn job discovery follow-up, 3 October 2026

The authenticated search results retained the older list layout, but opening a vacancy produced a new detail layout without an `h1` or the former company, location and description selectors. The shared reader now supports both explicit contracts. The current header requires a matching company label/link, one title paragraph and one location row before reading the section headed **About the job**, including poster-added requirements. Generated CSS classes are excluded from this contract. Unsupported or incomplete details stop instead of borrowing text from recommended vacancies.

Discovery validates limits, canonicalises only exact approved-origin numeric job links, deduplicates results, excludes recommendations when a results container is available, recognises explicit empty results and rejects job redirects. Submission reuses the same reader and preserves title/company/description comparisons while adding a location comparison before opening Easy Apply. Provider-read failures import no records and expose no raw browser diagnostics. The dashboard shows accessible progress, completion or failure, suppresses duplicate clicks and discards late responses after locking.

Thirty-one added regressions cover current and legacy layouts, delayed rendering, incomplete or ambiguous fields, oversized content, origins, redirects, canonicalisation, limits, no results, changed submission snapshots and mobile search feedback/accessibility. The legacy fixture now declares UTF-8 explicitly so its middle-dot location separator matches the real provider encoding. No assertion or submission safeguard was weakened. A separate live dashboard check imported seven local opportunities, returned HTTP 200 and left both application and invitation attempt counts unchanged. Private browser snapshots remain ignored.

## Easy Apply form follow-up, 3 October 2026

An authenticated rehearsal identified a native `dialog` rather than an explicit `role=dialog` attribute, required-label asterisks, separate country/phone controls, a file-chooser resume widget and custom screening radios. The adapter now uses the visible dialog role for both form reading and filling, waits for asynchronously rendered controls and restricts writes to that dialog. Phone components come only from approved facts and available country choices; ambiguous prefixes stop for review.

The current CV chooser requires a bounded Resume section, the job-specific document, an exact uploaded filename and agreement between native and ARIA selection state. Its radio identifiers are excluded from questionnaire handling only after selection is verified and every identifier is unique within the dialog. Additional upload fields, non-document radio labels and overlapping legal controls stop. Optional unchecked preferences remain unchanged; required, mixed or selected unknown consent controls remain review blockers. Screening cards require an exact approved group answer and matching available choice, then verify selection. A repeated form-step signature stops before another upload or navigation click. Final submission confirmation and uncertain-attempt handling remain intact.

Forty-six added cases cover grounded country/phone parsing, native/ARIA and delayed dialogues, scoped contact writes, prefilled unknown answers, approved and malformed custom screening cards, optional and required preferences, resume selection/mapping failures, a stalled Next action and intercepted submission. All provider traffic in these tests is intercepted. A separate authenticated live rehearsal filled approved contact fields, uploaded and verified the selected CV and reached an unanswered mandatory screening question. It stopped before final review or submission. The discovered question was retained locally, and preflight now reports the missing binary answer. Conditional candidate details remain local and do not supply an inferred Yes/No response.

## Contact portrait follow-up, 3 October 2026

Every changed source and test line was reviewed. Discovery captures only a single visible square image from the bounded primary header containing the reviewed member name, role and location. Covers, small company logos and recommended members' portraits are excluded. Missing, ambiguous or failed captures are optional and do not prevent contact discovery. The cache accepts bounded PNGs only, uses URL hashes as filenames and rejects paths escaping the private data directory. The photo endpoint requires the same local authentication as other connection reads and returns no-store responses.

The dashboard fetches only images in the selected connection tab, shares concurrent downloads and displays initials when an image is unavailable. Blob URLs are revoked on image failure and session locking. Late responses cannot restore an image after locking. Locations have a separate, highlighted text element. New regressions exercise delayed image rendering, redirects, incorrect identities, cache errors, authenticated access, corrupt or oversized images, archived contacts, mobile/desktop sizing, accessibility and lock races. A read-only live check captured the existing contacts' portraits and verified their local presentation without sending invitations or modifying the database.

The follow-up CI audit detected [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) in the Tailwind CLI's pinned watcher dependency. A scoped override selects `@parcel/watcher` 2.6.0, which removes the vulnerable `micromatch`/`braces` chain. A clean installation, unchanged generated CSS, an isolated native-watch rebuild and a fresh npm audit verify the change. Tailwind itself remains at 4.3.3. The private `.env` started from a blank template; only key presence and the selected model were checked after local configuration. No key was displayed and no paid model request was made.
