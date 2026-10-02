# Security and privacy

Run on loopback only. The API requires a random local bearer token and checks the request origin and Host header. The dashboard does not interpolate external text as HTML. Apply strict content security headers. Keep tokens in memory or session storage rather than URLs.

Do not commit `.env`, private source files, candidate profiles, generated CVs, databases, logs, browser cookies or screenshots. A sample profile must be fictional. A dedicated browser profile is preferable to the candidate's everyday browser. Never collect a LinkedIn password in the dashboard.

The optional AI adviser sends selected profile evidence and the job description to OpenAI. `store=False` does not claim zero vendor retention; consult current vendor data policies. Avoid sending civil identification or protected institutional information. Candidate facts are not changed by model output.

Local files and SQLite are protected by the Windows account and file permissions, not application-level encryption at rest. Backups contain personal information and must be handled accordingly. Dependency auditing and CI are safeguards, not a guarantee of defect-free operation.

External adapters must use an exact approved origin and reject redirects, unexpected fields and missing receipts. Do not evade CAPTCHA, MFA, access controls or anti-bot restrictions. Unknown or sensitive questions require manual handling.
