# Operating guide

## First run on Windows

```powershell
uv sync --extra dev --python 3.14
Copy-Item .env.example .env
uv run python -m applicator.cli serve
```

Use `http://127.0.0.1:8765` and the access token printed in the terminal. The application automatically uses an installed Microsoft Edge on Windows; otherwise install Chromium with `uv run python -m playwright install chromium`. Set `APPLICATOR_BROWSER_CHANNEL` to `chrome`, `msedge` or `chromium` if needed.

The readiness strip shows the saved LinkedIn authorisation, profile confirmation and remaining daily attempts. A scope declaration is separate from enabling application automation or networking. Use **Lock workspace** to clear credentials and visible candidate information from this tab; locking the tab does not pause the background agent. Use **Pause all automation** to stop new attempts.

The dashboard detects stale profile edits using a revision precondition. If another tab changes the record, reload before saving rather than overwriting the newer facts. Pending operations disable workspace controls, while pause remains available. The dashboard uses committed, locally compiled Tailwind CSS. To change its styling, use Node.js 24, `npm ci` and `npm run build:css`.

The module commands avoid unsigned console launchers sometimes blocked by Windows Application Control. If a compiled mypy installation is blocked, install the same locked mypy version from source with `uv pip install --reinstall --no-binary mypy mypy==<locked-version>`. Do not disable Windows security policy.

## Candidate setup

Review the Candidate profile tab. The private working copy has a profile translated from the supplied documents in `data/ricardo-profile.json`, imported into local SQLite. This file is excluded from Git and is not supplied to repository visitors. A fresh clone starts without a candidate profile.

Confirm contacts, qualifications, work authorisation facts and approved answers. An evidence item's approved flag means approved by the candidate for use, not independently audited. Unapproved evidence remains excluded until candidate review. Exact portfolio metrics and unverified equivalences are omitted.

LinkedIn sign-in and local candidate confirmation are separate steps. Application submissions and background networking require a confirmed local candidate record. In **Candidate profile**, review the saved facts, tick **I have reviewed and confirmed the candidate facts**, then choose **Save candidate profile**. A single manual invitation without a note uses the signed-in LinkedIn session and does not require candidate CV facts. It does not change profile confirmation or enable background automation.

Each connection queue entry includes **Open LinkedIn profile**, which opens the stored member URL in a separate tab. The link remains available for queued, sent, failed and uncertain contacts. Opening it does not submit an invitation or change the queue state.

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

Use **Search opportunities** to match role, company and location. Multiple words must all match. Combine the search with **Application status** and sort by newest, highest fit or company. Unevaluated opportunities sort below scored opportunities when sorting by fit. Filters stay in place when records refresh; **Clear filters** resets them. Locking the workspace clears the filters as well as candidate content.

Open an application to see **Submission readiness**. This read-only inspection checks current permissions, attempt capacity, status, integration, LinkedIn scope and identity, candidate confirmation, policy, profile revision, required answers and document integrity. A required cover letter must have a valid PDF. **Recheck readiness** refreshes the inspection without creating materials or consuming an attempt. Manual sources without an integration remain manual hand-offs.

The inspection is an advisory snapshot. Passing it does not prove that the browser is signed in or that the provider still shows the same vacancy and questions. The actual submission repeats all authoritative gates and checks the live provider. A setting or profile change after inspection can still prevent submission.

Expand **Activity for this application** for its latest 200 journal entries, newest first. This includes imports, preparation, reservations, confirmed receipts and outcome changes; unrelated applications and global settings do not appear.

The overview budget counts durable application reservations, including interrupted or uncertain attempts. Safe pre-submission provider stops also consume an attempt once reserved. Manual receipts do not create automatic attempts. The count resets at midnight in Europe/London, including British Summer Time. Lowering a limit below today's usage leaves zero remaining capacity and preserves the actual count. Networking retains its separate limit.

## Browser session

```powershell
uv run python -m applicator.cli browser-login
```

This deliberately opens an interactive, dedicated browser so the candidate can sign in and complete MFA. Press Enter in the terminal once signed in. Passwords are never collected by the application. Cookies remain in `data/browser/linkedin`; protect this folder like a credential. Keep other application browser operations stopped during login.

If the visible window has already been closed after signing in, pressing Enter still finishes the command without an unnecessary closed-browser traceback. Navigation failures and unrelated browser errors remain visible. Finishing this step records the candidate's confirmation; verify access with a read-only search before enabling automation.

The candidate declared that their LinkedIn authorisation covers discovery, Easy Apply and invitations. The application cannot verify that declaration. Configure its scope in Agent settings. No operation edits the public profile. Selector changes, challenges, unrecognised consent or unsupported form controls stop automation for review; nothing bypasses access controls.

## Autonomous cycles

Enable discovery, application automation and the declared scope only after profile review and local sign-in. The worker searches configured keywords/location, imports opportunities, prepares unevaluated or stale pending applications and submits ready applications. Its default application attempt limit is ten per London calendar day. Every external submission is journalled first. Unknown pre-submission questions become review items; a missing receipt after a submission click becomes uncertain.

Networking is a separate queue for European recruiters or hiring contacts, with three attempts per day by default. Contacts can be queued manually or discovered through the networking search. When background automation, networking and discovery are enabled, the worker reviews up to three recruiter profiles per cycle and queues matching European contacts while daily capacity remains. Background invitations retain candidate confirmation and their enable switches. Explicit single-contact invitations share the quota and identity checks, with independent execution. Duplicate invitations and failed or uncertain attempts are held.

Recruiter discovery reads the primary member link from each search-result card, excludes navigation and mutual-connection links, and canonicalises duplicates before applying the profile-review limit. Profile reading supports the legacy header and the current semantic card with its member-specific contact-information link. Generated LinkedIn CSS classes are not used for the current card. Incomplete, ambiguous or changed identities stop for review. Discovery queues matching contacts locally; it does not send invitations. Browser failures return a readable diagnostic rather than a generic 500 response. Check login and the current layout, and reconcile uncertain attempts before retrying an external action.

**Pause all automation** stops new background application and networking attempts. An explicit **Send queued invitation** remains a separate candidate-commanded action and does not resume either background queue. A request already in flight may finish. A restart converts interrupted submission or invitation states to uncertain; reconcile against actual LinkedIn history before recording a receipt or attempting recovery. Never guess that a failed request was rejected.

## Documents

Each application has a PDF CV and editable DOCX, plus cover letter counterparts when required. Rendering uses approved factual snippets selected for the role. The AI selection button uses `gpt-6.1-sol` if a fresh local API key is configured; model output cannot introduce new factual statements. A conservative fixed template is currently used for wording.

Before a real submission, inspect the generated PDF and LinkedIn's parsed fields. Document tests verify text extraction, page dimensions, length, size and hash checks. They do not certify every employer's ATS. Live upload mappings and Easy Apply selectors require initial account-level validation.

## Backup and recovery

Stop the server before copying the entire ignored `data` directory, including SQLite WAL/SHM sidecars if present. Restore while stopped, then restart; interrupted attempts remain uncertain. Store backups securely. The event log and receipt are the source of truth, not a dashboard success message alone.

## AI and feedback

Set a newly issued `OPENAI_API_KEY` in `.env`; the credential supplied in chat must be rotated. The optional adviser is mocked in automated tests and does not incur API charges during testing. The application records outcome counts and observations. It does not train itself or silently change the candidate's facts or permissions.

## Validation limits

The test suite exercises a real browser against local fixtures and intercepts all LinkedIn fixture traffic. It does not log into a real account, submit actual applications or send invitations. Unsupported company portals require manual hand-off. Free-text motivation answers must be candidate-approved; the current adviser selects factual evidence and does not invent questionnaire responses.
