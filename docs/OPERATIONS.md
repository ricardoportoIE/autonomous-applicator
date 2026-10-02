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

Confirm contacts, qualifications, work authorisation facts and approved answers. An evidence item's approved flag means approved by the candidate for use, not independently audited. The accounting specialisation remains unapproved because its original certificate has not been visually checked. Exact portfolio metrics and unverified equivalences are omitted.

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

The candidate declared that their LinkedIn authorisation covers discovery, Easy Apply and invitations. The application cannot verify that declaration. Configure its scope in Agent settings. No operation edits the public profile. Selector changes, challenges, unrecognised consent or unsupported form controls stop automation for review; nothing bypasses access controls.

## Autonomous cycles

Enable discovery, application automation and the declared scope only after profile review and local sign-in. The worker searches configured keywords/location, imports opportunities, prepares unevaluated or stale pending applications and submits ready applications. Its default application attempt limit is ten per London calendar day. Every external submission is journalled first. Unknown pre-submission questions become review items; a missing receipt after a submission click becomes uncertain.

Networking is a separate queue for European recruiters or hiring contacts, with three attempts per day by default. Contacts can be queued manually or discovered through the networking search. When networking and discovery are both enabled, the worker reviews up to three recruiter profiles per cycle and queues matching European contacts while daily capacity remains. Identity, displayed role and location are checked again before an invitation without a note. Duplicate invitations and uncertain attempts are held.

Pause all automation stops new attempts. A request already in flight may finish. A restart converts interrupted submission states to uncertain; reconcile against actual LinkedIn application history before recording a manual receipt. Never guess that a failed request was rejected.

## Documents

Each application has a PDF CV and editable DOCX, plus cover letter counterparts when required. Rendering uses approved factual snippets selected for the role. The AI selection button uses `gpt-6.1-sol` if a fresh local API key is configured; model output cannot introduce new factual statements. A conservative fixed template is currently used for wording.

Before a real submission, inspect the generated PDF and LinkedIn's parsed fields. Document tests verify text extraction, page dimensions, length, size and hash checks. They do not certify every employer's ATS. Live upload mappings and Easy Apply selectors require initial account-level validation.

## Backup and recovery

Stop the server before copying the entire ignored `data` directory, including SQLite WAL/SHM sidecars if present. Restore while stopped, then restart; interrupted attempts remain uncertain. Store backups securely. The event log and receipt are the source of truth, not a dashboard success message alone.

## AI and feedback

Set a newly issued `OPENAI_API_KEY` in `.env`; the credential supplied in chat must be rotated. The optional adviser is mocked in automated tests and does not incur API charges during testing. The application records outcome counts and observations. It does not train itself or silently change the candidate's facts or permissions.

## Validation limits

The test suite exercises a real browser against local fixtures and intercepts all LinkedIn fixture traffic. It does not log into a real account, submit actual applications or send invitations. Unsupported company portals require manual hand-off. Free-text motivation answers must be candidate-approved; the current adviser selects factual evidence and does not invent questionnaire responses.
