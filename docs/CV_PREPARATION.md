# Vacancy-specific CV preparation

Document preparation can use `gpt-6.1-sol` by default for both **Prepare documents** and the agent's new preparations. Enable **Use GPT-6.1 Sol for document preparation by default** in Agent settings after configuring the private API key. Existing workspaces retain local preparation until this setting is enabled. The explicit AI button remains available. The declared model is required; a different `OPENAI_MODEL` is rejected rather than substituted.

## How tailoring works

The adviser receives the vacancy and verified evidence records through the Responses API with structured evidence identifiers, medium reasoning, a 30-second timeout, disabled automatic retries and `store=False`. Contact details and approved questionnaire answers are not included in this request. The model selects relevant records and ranks them for the vacancy. Selection is bounded to six identifiers and no more than three projects; unknown or unverified identifiers are rejected.

The renderer writes PDF and DOCX documents using the approved factual text, rather than accepting unrestricted model-written claims. Skills are filtered against the vacancy's requirements, selected projects follow the relevance order, and experience/education retain their chronology. Factual history, qualifications, languages and awards are preserved. The professional summary remains the approved base summary. Cover letters, when required, use the selected factual examples.

This provides evidence-led tailoring. It does not rewrite every sentence or guarantee that two similar vacancies produce different prose. Identical requirements can justify the same evidence. Different filenames or PDF byte hashes alone do not prove tailoring, because names and PDF metadata can vary without a content change.

## Provenance and submission checks

Each new preparation records the method (`local`, `manual` or `openai`), actual and requested model, provider response identifier, generation time, token counts, selected evidence, profile revision and fingerprints of the candidate/job snapshots. The dashboard shows the origin and vacancy context under **Document preparation**. Legacy records without provenance are labelled as unavailable; their origin is not inferred retrospectively.

When default AI preparation is enabled, the local preflight and actual submission both require valid `gpt-6.1-sol` provenance for the current candidate and vacancy. Switching it on invalidates pending local materials for regeneration while preserving submitted and uncertain history. Candidate or opportunity changes during a request cannot commit stale preparation. Document hashes are checked separately.

Missing credentials, a different configured/returned model, refused or invalid results, API failures and invalid AI-selected documents leave the record in review with no usable submission manifest. No local fallback is used after an AI failure, no submission attempt is reserved, and the worker does not automatically repeat the failed preparation each cycle. Reprepare deliberately after resolving the issue. Exact approved questionnaire answers, including legal work authorisation, remain independent of model selections and fit scores.

## Live verification, 3 October 2026

A read-only audit found one prepared local CV and no recorded model provenance. Therefore, historical AI use could not be established. Code inspection confirmed that the former ordinary and worker preparations used local rules; only the explicit AI button called the model.

After the repair, an isolated workspace used the reviewed candidate evidence and two existing vacancies. Each vacancy was prepared locally and through the normal default-AI endpoint. Two real OpenAI requests returned `gpt-6.1-sol`; four CV PDFs were generated. Personal records, response identifiers, files and snapshots remain in ignored local storage.

| Check | Python backend vacancy | Java/applied-AI vacancy |
| --- | --- | --- |
| Local preparation time | 0.173 s | 0.157 s |
| Default AI preparation time | 8.209 s | 5.025 s |
| Local selected identifiers | 5 | 4 |
| AI selected identifiers | 4 | 4 |
| CV length, both methods | 2 pages | 2 pages |
| Approved text and document hashes | Passed | Passed |

The AI selections and extracted CV text differed between the two vacancies. The Python selection prioritised relevant backend project evidence differently; the Java case retained the same substantive project set as local preparation. These observations verify model use and vacancy-specific content, not a general increase in writing quality, hiring probability or ATS acceptance. The sample is too small for a reliability estimate.

All four PDFs were rendered with Poppler and all eight pages visually inspected. They had selectable text, readable headings, consistent A4 margins and no clipping or overlap. The comparison reserved zero application attempts, used no LinkedIn browser actions and sent no applications or invitations. Ordinary pytest/CI tests use mocked model responses and intercepted provider fixtures, with no paid requests.

The authorised setting was then enabled in the actual local workspace after an SQLite backup and a paused/no-in-flight check. A third real request through **ordinary preparation** regenerated the pending application's two-page CV with confirmed `gpt-6.1-sol` provenance. Its approved text, hashes, snapshot fingerprints and both rendered pages passed validation. The live dashboard displayed the model and enabled default, with no JavaScript errors. The application stayed in review for its unanswered required questionnaire; the attempt count and absent receipt were unchanged. Background automation remained paused.

The [earlier fictional benchmark](AI_BENCHMARK.md) provides a separate twelve-request relevance comparison. It measured evidence selection under the earlier prompt and renderer, so its results must not be treated as measurements of this revised implementation. The model configuration follows [official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol).
