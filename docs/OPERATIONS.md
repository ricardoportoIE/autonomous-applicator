# Operating guide

## First run on Windows

Technical form recovery runs within the normal FIFO worker. The monitor shows **recovering form** and **form recovered**; inspect the application's status check and activity for exhausted strategies. The worker can resume a proven pre-send technical hold twice, reusing valid documents. Unknown answers and genuine availability preferences still need approval. Restart preserves recovery hints and budgets. [Queue operation](APPLICATION_QUEUE.md#bounded-form-recovery-and-local-learning) records the limits and evidence required for resumption.

```powershell
uv sync --extra dev --python 3.14
Copy-Item .env.example .env
New-Item -ItemType Directory -Path data -Force | Out-Null
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/protect_private_workspace.ps1
uv run python -m applicator.cli serve
```

Use `http://127.0.0.1:8765` and the access token printed in the terminal. The application automatically uses an installed Microsoft Edge on Windows; otherwise install Chromium with `uv run python -m playwright install chromium`. Set `APPLICATOR_BROWSER_CHANNEL` to `chrome`, `msedge` or `chromium` if needed.

The private-permissions helper limits existing repository-local `data`, `tmp`, `output` and private `.env` files to the current Windows account, SYSTEM and Administrators. It saves the original DACLs in ignored `tmp`, checks all paths before mutation, refuses reparse points and restores prior DACLs if protection fails. It changes permissions only, preserves file content and leaves public source/sample permissions unchanged. Rerun after creating extra secret files or restoring backups. Apply account permissions separately to a custom data directory outside the repository. [Security and privacy](SECURITY.md) documents the trust boundary; the Windows CI suite checks protection and rollback using fictional files.

The readiness strip shows the saved LinkedIn authorisation, profile confirmation and remaining daily attempts. A scope declaration is separate from enabling application automation or networking. Use **Lock workspace** to clear credentials and visible candidate information from this tab; locking the tab does not pause the background agent. Use **Pause all automation** to stop new attempts.

The React dashboard keeps the six existing navigation areas. **Add opportunity**, **Add evidence**, **Add contact**, **Import from Greenhouse** and **Edit candidate profile** open focused dialogues. Save commits the record and closes the dialogue; an error retains the draft. Escape or **Close dialogue** discards unsaved input and restores focus to its opening button. Close an open dialogue before using background navigation or the global pause; closing a dialogue does not cancel a request already running. Reload the dashboard after a frontend update. Installed builds do not need a Node.js server.

The dashboard detects stale profile edits using a revision precondition. If another tab changes the record, reload before saving rather than overwriting the newer facts. Pending operations disable workspace controls, while pause remains available. The dashboard uses committed, locally compiled Tailwind CSS. To change its styling, use Node.js 24, `npm ci` and `npm run build:css`.

The module commands avoid unsigned console launchers sometimes blocked by Windows Application Control. If a compiled mypy installation is blocked, install the same locked mypy version from source with `uv pip install --reinstall --no-binary mypy mypy==<locked-version>`. Do not disable Windows security policy.

## Full application records

In **Applications**, choose **Full record** beside an opportunity, or **View full application record** from its management view. Each record has its own local address, `/#/applications/{id}`, which can be bookmarked. Unlocking the workspace is still required. Reload to read subsequent attempt or outcome changes; the shared processing monitor remains live. **Manage this application** returns to the existing preparation, question and outcome controls.

The page shows the original opportunity URL, imported/prepared/submitted dates, current decision, provider receipts and every recorded attempt. Times use Europe/London. Submission dates represent the locally recorded confirmation event, including manual receipts; they are not a reconstructed historical provider sending time. The application journal loads 200 entries at a time; **Load older activity** reads the remaining entries without starting any browser action.

New submissions preserve the reviewed candidate contacts, selected evidence text, opportunity, profile revision, preparation metadata and document hashes for each attempt. The adapter uploads the archived copies, and the LinkedIn final gate verifies them again before clicking Submit. **Archived documents for this attempt** downloads these copies rather than a later replacement CV. **Observed application form** shows values and file names actually observed in the provider form, separately from approved answers supplied to the adapter. Observations include the form step when available. An archived DOCX is a prepared editable copy; the observed upload list identifies what the browser supplied.

After LinkedIn visibly confirms submission, the adapter attempts a full-page PNG capture. The supported local employer fixture follows the same confirmation workflow; external employer sites need a compatible adapter before they can provide automatic evidence. The confirmation panel shows the captured provider URL and offers authenticated image preview/download. A recorded URL is the page seen at confirmation time, not a guaranteed permanent receipt link. A failed screenshot leaves the confirmed receipt intact and does not retry the send.

Snapshots, archived documents and screenshots stay in ignored local storage under `data/submissions/{application}/{attempt}/`. They are served only through authenticated API routes, are checked against their recorded hashes and are never published to GitHub. Locking removes the visible record and releases preview URLs. Include both SQLite and the local submissions directory in a private backup.

Historical attempts may have no archived materials, form observations, exact sending time or screenshot. The page explicitly marks absent evidence; it never reconstructs sent information from today's profile. A manual receipt confirms the outcome but cannot manufacture a provider screenshot.

## Candidate setup

Review the Candidate profile tab. The private working copy has a profile translated from the supplied documents in `data/ricardo-profile.json`, imported into local SQLite. This file is excluded from Git and is not supplied to repository visitors. A fresh clone starts without a candidate profile.

Confirm contacts, qualifications, work authorisation facts and approved answers. An evidence item's approved flag means approved by the candidate for use, not independently audited. Unapproved evidence remains excluded until candidate review. Exact portfolio metrics and unverified equivalences are omitted.

LinkedIn sign-in and local candidate confirmation are separate steps. Application submissions and background networking require a confirmed local candidate record. In **Candidate profile**, review the saved facts, tick **I have reviewed and confirmed the candidate facts**, then choose **Save candidate profile**. A single manual invitation without a note uses the signed-in LinkedIn session and does not require candidate CV facts. It does not change profile confirmation or enable background automation.

Each connection queue entry includes **Open LinkedIn profile**, which opens the stored member URL in a separate tab. The link remains available for queued, sent, failed and uncertain contacts. Opening it does not submit an invitation or change the queue state.

Contact cards show a circular 64-pixel portrait, a separate role/headline and a highlighted location. Discovery captures only one visible square portrait from the verified primary profile section; covers, small company logos and recommended members' images are excluded. Missing, ambiguous or unavailable portraits leave initials visible. Portrait PNGs are kept in the ignored local `data/contact-photos` directory and delivered through a token-protected endpoint. The dashboard loads images only for the selected queue tab, does not request LinkedIn image URLs directly and releases its image URLs when locked. Existing contacts can retain their cached portraits after archiving.

**Find European recruiters** uses the saved **Daily connection attempt limit** as the maximum number of new matching contacts per manual search. With a limit of five, discovery aims for five new contacts rather than a fixed three. Existing contacts in every state are excluded. The provider adapter checks at most ten new primary results from the available search page, continuing past unsuitable roles or locations until the target is met; fewer matches can be returned when suitable results are exhausted. Searches do not consume invitation attempts. Background discovery uses the remaining invitation quota as its target.

While discovery runs, the button displays **Searching…**, an activity indicator and an accessible status message. Duplicate clicks cannot start another search. Completion, no matching results and failure are explained before the button returns to **Find European recruiters**.

The connection queue opens on **Active**, containing queued, running, failed and uncertain contacts. Confirmed sent invitations move automatically to **Archived**, with their original profile links, delivery status and confirmation retained. Archiving changes the displayed tab only: it does not delete records, reset quotas or allow a second invitation. Both tabs show counts and support arrow, Home and End keys. New search results open in Active.

**Send queued invitation** executes only that contact. It opens the dedicated signed-in browser visibly, goes directly to the stored member URL, verifies name, role and location, and uses **Connect** or **More → Connect** before sending without a note. It never invokes the application worker, creates CVs, searches for more contacts or follows a member. The browser closes when the operation ends. Manual execution is independent of the application/networking background enable switches; the declared LinkedIn scope, daily networking quota and duplicate safeguards still apply.

When LinkedIn displays **Add a note to your invitation?**, the agent always selects **Send without a note**. It never selects **Add a note** or writes an invitation message.

Successful delivery requires one visible **Pending** or **Invitation pending** control on the verified member's primary card. Both buttons and links are supported, including an accessible label such as **Pending, click to withdraw invitation sent to Example Recruiter**. A pending control on a recommended member's card cannot confirm this invitation. **Needs reconciliation** means the outcome was not confirmed; it does not mean the invitation definitely failed, and the agent will not send it again automatically.

The selected card reports **Started**, **Running**, **Done**, **Failed** or **Needs review**, with the current step. Progress is stored locally and polled while the request runs. Reloading resumes observation of an existing run without sending again. A lost HTTP response or status request never retries the invitation automatically. An already occupied dedicated browser rejects a new manual send immediately; other dashboard sections remain available.

Only visible connection controls belonging to the primary member card are used. Recommended members' buttons are excluded. The adapter waits for rendered actions and supports a connection menu or a uniquely appearing Connect button/link after opening More. A failure before Connect is recorded as failed. Once Connect may have been clicked, any unconfirmed outcome is held for manual review, since even opening Connect can have provider-specific consequences. **Done** requires a visible Pending confirmation. Inspect LinkedIn before reconciling an uncertain record; failed and uncertain records are not automatically retried.

To import a prepared local profile:

```powershell
uv run python -m applicator.cli import-profile data/my-profile.json
```

Edits invalidate pending documents. Reprepare before sending. Documents from confirmed submissions remain available as historical records after profile edits. Use **Edit job details** to update the same opportunity after a description change; submitted and uncertain records are immutable. Unknown salary, availability, work authorisation or screening answers must be supplied explicitly. Store exact approved LinkedIn question answers using `question:` followed by the lower-case label with normalised spaces. Required questions discovered during a safe pre-submission stop appear on the application detail for approval.

## Reviewing the queue

The **One opportunity at a time** monitor appears above the workspace views. It shows the active vacancy and application identifier, current stage, total/stage duration and run identifier. Expand **Recent application results** for the latest 50 results, including the failure stage and exception class. An empty later cycle does not remove earlier failures. Application-specific journal entries contain the same run identifier and UTC timestamps. See [Application queue operation](APPLICATION_QUEUE.md) for ordering, review, restart and pause behaviour.

Processing follows arrival order rather than the dashboard's chosen sort. Each eligible vacancy completes evidence selection, document generation, current readiness checks, questionnaire handling and confirmed submission or a durable hold before the next starts. No second vacancy is prepared while the first is awaiting the model or provider. Review and uncertain records need deliberate resolution; they do not cause automatic retries or block other eligible vacancies. The sending budget is checked after preparation; exhausted capacity leaves prepared records ready and waiting for the next sending slot.

Manual preparation, manual submission and agent cycles cannot run concurrently. A competing request receives a busy conflict. The live monitor remains readable during long operations, and reloading observes the existing run without restarting it. Locking clears its private content; the pause control remains available during an operation. A pause during preparation allows that preparation to finish but stops submission and the next vacancy. An external action already in flight may still finish.

Run one server per private workspace. A second instance is rejected before it can recover another instance's records. A graceful shutdown waits for current background work and takes no new vacancies; abrupt interruptions retain their recorded stage on restart. Interrupted preparations require manual review and fresh preparation, while interrupted reserved submissions require reconciliation.

**Search LinkedIn** uses the saved search keywords and location, with the Easy Apply filter. It reads up to ten unique vacancies from the available results, imports complete job details and leaves existing opportunities unchanged. It does not submit applications or consume an application attempt. The button shows **Searching…** and a status message until completion or failure; zero imports can mean no matches or already imported results. Locking the workspace clears the status and discards late dashboard responses.

Job reading supports the legacy layout and the current detail layout, whose header uses company-labelled links and title/location paragraphs. The description includes requirements added by the job poster. Canonical job URLs, exact identifiers and complete fields are required; unexpected redirects or ambiguous details stop the search. Submission repeats the same reader and compares title, company, location and description with the reviewed opportunity before opening Easy Apply. Search errors explain that no opportunities were imported or applications sent during the failed provider read.

Use **Search opportunities** to match role, company and location. Multiple words must all match. Combine the search with **Application status** and sort by newest, highest fit or company. Unevaluated opportunities sort below scored opportunities when sorting by fit. Filters stay in place when records refresh; **Clear filters** resets them. Locking the workspace clears the filters as well as candidate content.

Open an application to see **Submission readiness**. This read-only inspection checks current permissions, sending capacity, status, integration, LinkedIn scope and identity, candidate confirmation, policy, profile revision, required answers and document integrity. A required cover letter must have a valid PDF. **Recheck readiness** refreshes the inspection without creating materials or consuming an attempt. Manual sources without an integration remain manual hand-offs.

The inspection is an advisory snapshot. Passing it does not prove that the browser is signed in or that the provider still shows the same vacancy and questions. The actual submission repeats all authoritative gates and checks the live provider. A setting or profile change after inspection can still prevent submission.

An application’s **Overview** tab contains submission readiness, fit, preparation provenance and the existing preparation/submission controls. **Documents** contains the current downloads and explicit manual evidence selection. **Questions** contains exact candidate-approved answers and manual-handling notices. In **Activity & outcome**, expand **Activity for this application** for its latest 200 journal entries, newest first. This includes imports, preparation, reservations, confirmed receipts and outcome changes; unrelated applications and global settings do not appear. The same tab retains manual submission receipt recording and outcome updates.

In **Questions**, **Suggest with GPT-6.1 Sol** generates one answer idea from the selected question, vacancy, verified evidence and approved candidate facts. Configure `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-6.1-sol` in the local `.env` and restart the server after changing them. The button shows **Generating answer idea…**, then displays a separate draft, factual references and review notes. It keeps your current answer unchanged. **Use as editable draft** copies prose into the answer field; edit it, then explicitly choose **Approve answer**. Approval is saved for this application only, with a candidate-revision precondition. It does not change the global profile revision or invalidate other CVs. Readiness is refreshed immediately: valid documents are retained; materials that need generation appear as **Queued for preparation**. Other genuine blockers remain in review with their reasons. Neither generating nor copying a draft saves an answer, consumes a submission attempt or starts the browser.

Missing facts require clarification. Sensitive questions remain manual and have no AI button. For choices without a matching previously approved exact answer, the idea is explanatory only: select the exact choice yourself. Conditional part-time work permission cannot become an approved full-time Yes/No response through this button. Changed candidate/question snapshots reject a late result; locking or closing the application details discards the visible suggestion. A provider failure retains your typed answer and shows an error without a model fallback or automatic retry. Drafts are not saved to the database or journal.

The overview shows confirmed **applications sent** against the configured daily limit. Preparations, model calls and proven pre-submission stops do not consume that allowance. Pending or uncertain submissions hold sending slots separately until reconciled; a hold survives midnight. Confirmed manual receipts also count as sent. Confirmed usage resets at midnight in Europe/London, including British Summer Time; the final sending click records the send day. Lowering a limit preserves the recorded counts and leaves zero capacity where necessary. Networking retains its separate limit.

### Routine questions and exceptional locations

**Answer routine questions from approved facts** is enabled by default. The system first honours exact answers you have already approved. It can copy contact fields, use the configured sponsorship flag and answer simple supported technology questions from verified evidence. A numeric duration requires a complete explicit approved numeric statement; project dates or a model guess cannot establish years of experience. For supported professional prose, GPT-6.1 Sol selects verified evidence identifiers and the system copies their original wording. Independent projects remain independent projects. Unknown salary, availability, legal eligibility, consent or unusual conditions stay in review.

Automatic answers appear in **Questions** with their source and can be edited through the existing approval controls. They are scoped to this application and candidate/job version, including routine questions discovered in the provider form. They do not alter the global candidate profile or invalidate a prepared CV. Editing candidate facts or the vacancy invalidates stale derived answers. Turning routine answers off prevents their use. **Suggest with GPT-6.1 Sol** remains a separate manually reviewed drafting tool.

**Automatic application locations** defaults to the candidate's current city or a remote role explicitly in the same country. Choose the same country or configured target countries if preferred. Interesting vacancies outside this scope still receive documents and remain in review. Open the vacancy, check its location and choose **Accept location for this opportunity** to allow the queue to recheck it. Acceptance is specific to the current vacancy and candidate version; it does not change other vacancies or target countries. A location approval does not approve work eligibility or sponsorship.

For an uncertain application, check the provider history first. Record a confirmed receipt if it was sent. If it was definitely not sent, use **Activity & outcome ? I checked the provider and this application was not sent ? Confirm application was not sent**. This releases the held sending slot, preserves the journal and leaves a manual review hold. Prepare again deliberately before retrying; the background queue does not retry the reconciled record automatically.

## Browser session

```powershell
uv run python -m applicator.cli browser-login
```

This deliberately opens an interactive, dedicated browser so the candidate can sign in and complete MFA. Press Enter in the terminal once signed in. Passwords are never collected by the application. Cookies remain in `data/browser/linkedin`; protect this folder like a credential. Keep other application browser operations stopped during login.

LinkedIn can require sign-in again after the initial job page loads. A delayed redirect to `/authwall`, `/login` or `/checkpoint` is reported as an authentication requirement, including when it happens during a locator wait or renders a login heading that resembles the expected profile layout. The message identifies the dedicated browser session and the command above; signing in through a separate everyday browser does not update this session. Provider tracking parameters and locator diagnostics are not included in this authentication message.

Pause automation before running `browser-login`, complete any verification manually, then press Enter in the terminal to retain the session. For an application stopped before the final sending click, the record moves to review and releases its reserved sending slot; its prepared documents and archived attempt remain available. Prepare it again after restoring sign-in. If the final sending click may already have happened and no receipt was observed, the outcome remains uncertain and its slot stays held: inspect the actual provider history and reconcile it before any retry. A receipt already observed remains confirmed if the session changes during the optional screenshot; capture failure is recorded separately and the send is never repeated. Authentication failures do not cause an automatic replay or establish a submission receipt. Discovery failures import no partial batch and send nothing.

If the visible window has already been closed after signing in, pressing Enter still finishes the command without an unnecessary closed-browser traceback. Navigation failures and unrelated browser errors remain visible. Finishing this step records the candidate's confirmation; verify access with a read-only search before enabling automation.

The candidate declared that their LinkedIn authorisation covers discovery, Easy Apply and invitations. The application cannot verify that declaration. Configure its scope in Agent settings. No operation edits the public profile. Selector changes, challenges, unrecognised consent or unsupported form controls stop automation for review; nothing bypasses access controls.

## Autonomous cycles

Enable discovery, application automation and the declared scope only after profile review and local sign-in. The worker resumes eligible saved opportunities before another search, imports a bounded batch when the queue has no work that can progress, then evaluates, prepares and submits each vacancy in FIFO order. Networking follows application processing. Its default sent-application limit is ten per London calendar day. Even at the limit, discovery and FIFO preparation continue and unchanged prepared documents are reused. Every external submission is journalled first. Unknown pre-submission questions become review items with their observed choices; a missing receipt after a submission click becomes uncertain.

Networking is a separate queue for European recruiters or hiring contacts, with three attempts per day by default. Contacts can be queued manually or discovered through the networking search. When background automation, networking and discovery are enabled, the worker reviews up to three recruiter profiles per cycle and queues matching European contacts while daily capacity remains. Background invitations retain candidate confirmation and their enable switches. Explicit single-contact invitations share the quota and identity checks, with independent execution. Duplicate invitations and failed or uncertain attempts are held.

Recruiter discovery reads the primary member link from each search-result card, excludes navigation and mutual-connection links, and canonicalises duplicates before applying the profile-review limit. Profile reading supports the legacy header and the current semantic card with its member-specific contact-information link. Generated LinkedIn CSS classes are not used for the current card. Incomplete, ambiguous or changed identities stop for review. Discovery queues matching contacts locally; it does not send invitations. Browser failures return a readable diagnostic rather than a generic 500 response. Check login and the current layout, and reconcile uncertain attempts before retrying an external action.

**Pause all automation** stops new background application and networking attempts. An explicit **Send queued invitation** remains a separate candidate-commanded action and does not resume either background queue. A request already in flight may finish. A restart converts interrupted submission or invitation states to uncertain; reconcile against actual LinkedIn history before recording a receipt or attempting recovery. Never guess that a failed request was rejected.

## Documents

Each application has a PDF CV and editable DOCX, plus cover letter counterparts when required. Rendering uses approved factual snippets selected for the role. The AI selection button uses `gpt-6.1-sol` if a fresh local API key is configured; model output cannot introduce new factual statements. A conservative fixed template is currently used for wording.

Before a real submission, inspect the generated PDF and LinkedIn's parsed fields. Document tests verify text extraction, page dimensions, length, size and hash checks. They do not certify every employer's ATS. Live upload mappings and Easy Apply selectors require initial account-level validation.

Easy Apply supports native and ARIA dialogues, waits for asynchronously rendered controls and reads required markers. A separate phone country selector is matched against the approved international phone number and the form's actual choices. Ambiguous country prefixes require an exact approved choice. The current **Upload resume** chooser uploads the job-specific CV and verifies its filename and selected native/ARIA radio state within the Resume section. Additional upload types or overlapping questionnaire controls stop for review. The older labelled file-input form remains supported.

Optional unchecked preferences, including premium top-choice selections, remain unchecked. Required or already selected unknown consent controls require review. Custom screening radio cards use the exact approved question and available choice; a prefilled answer does not establish permission or eligibility. A provider-discovered question is retained in the application record so the next local preflight can explain the missing answer. Preserve conditional work-authorisation details as candidate facts; do not convert them automatically into a generic Yes/No answer. When a step does not advance, the adapter stops rather than uploading the CV repeatedly or clicking through validation errors.

## Backup and recovery

Stop the server before copying the entire ignored `data` directory, including SQLite WAL/SHM sidecars if present. Restore while stopped, then restart; interrupted attempts remain uncertain. Store backups securely. The event log and receipt are the source of truth, not a dashboard success message alone.

## AI and feedback

The OpenAI integration is optional. Copy `.env.example` to the repository root as `.env`, then set a newly issued `OPENAI_API_KEY` locally and retain `OPENAI_MODEL=gpt-6.1-sol`. Restart the server after changing this file. The credential previously supplied in chat must be rotated. Both `.env` and private runtime files are excluded from Git. This follows the [OpenAI developer quickstart](https://developers.openai.com/api/docs/quickstart), where the SDK reads the key from the server environment.

Open an application and choose **Select evidence with GPT-6.1 Sol** to invoke the adviser. It selects approved evidence identifiers for that job; it does not invent candidate facts or authorise submissions. Without a configured key, this action explains how to enable the adviser; ordinary networking, deterministic scoring and document preparation remain available. The optional adviser is mocked in automated tests and does not incur API charges during testing. The application records outcome counts and observations. It does not train itself or silently change the candidate's facts or permissions.

To use the model for ordinary and automatic document preparation, enable **Use GPT-6.1 Sol for document preparation by default** in Agent settings. API or document validation failures remain in review with no silent local fallback or automatic preparation retry. Existing pending local materials need regeneration after enabling this setting. Submitted and uncertain history is retained. The **Document preparation** section identifies the method and actual model; submission checks verify the current candidate/job fingerprints. See the [CV preparation audit](CV_PREPARATION.md) for the live comparison, retained factual wording and validation limits.

## Validation limits

The backend enforces 100% statement and branch coverage for every Python application module. Run `uv run pytest` followed by `uv run python scripts/check_backend_coverage.py` for a fresh measurement and complete-inventory check. CI applies both gates to every supported Windows/Linux and Python combination. Reports remain local under `test-results` and are uploaded as CI artifacts. See [testing and coverage](TESTING.md) for the scope, focused development checks and separate frontend measurements.

The test suite exercises a real browser against local fixtures and intercepts all LinkedIn fixture traffic. It does not log into a real account, submit actual applications or send invitations. Unsupported company portals require manual hand-off. Unusual motivation questions, personal decisions and unsupported factual answers require review. Supported professional questions may use verified source text selected by GPT-6.1 Sol; the model cannot invent questionnaire facts.
