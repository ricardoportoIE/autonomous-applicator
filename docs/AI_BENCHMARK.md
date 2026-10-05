# Live OpenAI evidence-selection comparison

## Questionnaire HTML comparison, 5 October 2026

Eight real `gpt-6.1-sol` calls tested the new semantic HTML interpretation against [predeclared fictional cases](../benchmarks/ai_form_cases.json). The [measured report](../benchmarks/ai_form_interpretation_2026-10-05.json) records returned models, token usage, correctness and elapsed time. The baseline uses deterministic routine rules without a selector; the assisted route uses the production interpreter, its available-fact catalogue, verified sources and validation. All returned models matched the requested model.

| Measure | Deterministic baseline | GPT-6.1 Sol assistance |
| --- | --- | --- |
| Correct outcomes | 2/8 | 8/8 |
| Supported ordinary questions answered | 0/6 | 6/6 |
| Deliberate review cases retained | 2/2 | 2/2 |
| Observed assisted elapsed time | Not measured | Median 3.75 s; range 2.61–6.50 s |

The supported cases cover a given-name paraphrase, technical-experience paraphrases in radio/select/checkbox/ARIA-combobox controls and an unfamiliar project narrative. A negated capability question and paid-work experience unsupported by the fictional project evidence stayed in review. The baseline's six additional holds were safe but unnecessary; the comparison does not imply that deterministic rules fabricated answers. The model used high reasoning effort and a 4,000-token output limit.

No candidate data from the private workspace, browser session, employer website, application or invitation was used. This is a small, single-run regression comparison, not a population accuracy estimate or a live provider throughput benchmark. The ordinary suite independently tests invalid models, unavailable mappings, unverified sources, exceptional fields, native control checks and no-fill/no-advance failure behaviour with controlled responses.

Reproduction requires explicit opt-in and a configured local API key:

```powershell
uv run python scripts/benchmark_form_interpretation.py --live
```

The default refuses paid calls. The opt-in run makes at most eight calls and writes a fictional report under `test-results`; provider errors retain their exception type without credential/request diagnostics. It does not start the browser or worker. See [questionnaire interpretation](QUESTION_INTERPRETATION.md) for architecture and boundaries.

## Evidence-selection comparison, 3 October 2026

On 3 October 2026, all twelve real `gpt-6.1-sol` requests completed successfully. Against a predeclared fixture rubric, the adviser selected more focused evidence than the local keyword method, with approximately three seconds of additional preparation time. Both methods retained approved factual content and unchanged submission gates.

## Method

The [fictional dataset](../benchmarks/ai_evidence_cases.json) contains six cases: backend APIs, cloud deployment, accessible frontend work, terminology requiring semantic interpretation, missing Kubernetes/Azure skills and malicious instructions embedded in a job description. Each case ran twice through the actual `/api/applications/{id}/prepare` implementation, first locally and then with AI advice. Expected acceptable and essential identifiers were defined before the API calls and were not sent to the model.

The real SDK sent requests to `https://api.openai.com/v1`. Its client factory was wrapped only to collect elapsed time, usage and the parsed decision summary; model responses were not mocked. The production adviser used structured `Advice`, medium reasoning, a 3,000-token output limit, a 30-second timeout, no automatic retries and `store=False`. All candidate/job inputs were fictional. The benchmark used a separate ignored SQLite workspace and created no application attempts or connection records.

The comparison follows the task-specific, labelled evaluation approach described in [OpenAI Docs](https://developers.openai.com/api/docs/guides/evaluation-best-practices). Labels are author-curated relevance judgements for this small pilot, not independent expert ratings or ATS acceptance scores.

## Results

| Measurement | Local method | OpenAI adviser |
| --- | --- | --- |
| Completed preparations | 12 / 12 | 12 / 12 |
| Median full preparation time | 0.0804 s | 3.2492 s |
| Nearest-rank p95 full preparation time | 0.1589 s | 4.9046 s |
| Mean selected-evidence relevance precision | 66.67% | 91.67% |
| Mean recall of essential evidence | 91.67% | 100% |
| Fully focused selections | 4 / 12 | 10 / 12 |
| Selections containing every essential item | 10 / 12 | 12 / 12 |
| Approved identifiers and document facts preserved | 12 / 12 | 12 / 12 |
| Original submission evaluation preserved | 12 / 12 | 12 / 12 |
| Mean CV text length | 960.8 characters | 821.3 characters |
| Additional API cost, estimated | None | US$0.025104 total |

Full preparation time includes SDK/network work where applicable, validation, PDF/DOCX generation and SQLite writes. The AI request itself had a median of 3.1311 seconds. With twelve observations, nearest-rank p95 is the slowest observed request; it is not a service-level prediction. Selection sets were identical across both AI repetitions in all six cases, although this does not establish broader determinism.

Relevance precision is the proportion of selected identifiers in the case's acceptable set. Essential recall is the proportion of the case's essential identifiers present in the selection. Results use a macro-average across cases/repetitions. Empty selections receive zero. These measurements assess evidence selection; they do not rate writing fluency or hiring outcomes.

## Quality observations

- **Backend:** the local method included retrieval and data-analysis projects because they shared the Python tag. The adviser retained the API project and relevant backend skills, reducing unrelated material in the CV and cover letter.
- **Cloud/frontend:** both methods found the expected projects. The AI CVs had the same factual content as their local counterparts. Changes in identifier order could change the cover letter's order of examples.
- **Semantic case:** the adviser connected automated testing with pytest project evidence and customer collaboration with the support record. The local CV already included support as mandatory factual history, but its selected cover-letter examples omitted that experience. The AI cover letter included it and removed unrelated Python projects.
- **Missing skills:** the adviser explicitly stated that AWS evidence did not establish Azure experience and that Kubernetes evidence was missing. It included transferable AWS/Terraform/Docker records, which the narrow predeclared relevance rubric penalised. This explains the two AI selections below full precision; it was not an invented qualification. The application remained in the same review state.
- **Injection:** both AI requests ignored the job description's request to select unverified/invented identifiers, fabricate a master's degree or paid engineering years, and grant submission permission. The generated documents used approved records only.

The AI selects evidence; the existing renderer writes the CV and cover letter from approved text. The professional summary is unchanged. Cover letters remain factual example-based templates, so these results do not demonstrate improved original prose or employer-specific narrative. All 48 comparison PDFs were rendered with Poppler and visually inspected: one-page A4 output, selectable text, consistent margins, readable headings and no clipping or overlap. Comparison copies were reconstructed offline from the exact recorded selections using the same renderer; this made no additional API requests.

## Usage and cost

The SDK recorded 12,830 input tokens, including 6,397 cached-input tokens and 6,397 cache-write tokens, plus 840 output tokens. The estimate uses standard short-context [GPT-6.1 Sol pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol): US$2 per million uncached input tokens, US$0.10 cached input, US$2.50 cache writes and US$10 output. Cache writes are accounted for separately, avoiding an understated estimate. Regional premiums, discounts and taxes are excluded; this is not an account invoice.

## Reproduce

```powershell
.venv\Scripts\python.exe scripts/benchmark_ai.py --live --repeats 2
```

The runner requires an explicit `--live`, a local `.env` key and the declared model. It allows at most twelve paid requests, disables retries, rejects outputs outside the ignored workspace `tmp/` directory and refuses to overwrite an existing run. Ordinary pytest and CI checks never enable this live runner. An unsuccessful AI preparation stops the remaining calls; usage for a request failing before a parsed response may be unavailable, so a failed-run estimate can be incomplete.

The [measured results](../benchmarks/ai_evidence_results_2026-10-03.json) contain fictional identifiers, decision summaries, usage and timing only. Keys, account identifiers, personal profiles, browser sessions and raw provider errors were not published. Eight offline benchmark checks and eighteen relevant adviser/document/API regressions passed locally; Ruff and strict mypy also passed.

## Implications

Use the adviser when semantic interpretation or reducing weakly related examples matters. Retain local scoring, approval and submission gates: the AI selections did not change any of them. The local method remains much faster and already performs well on explicit cloud/frontend requirements. A subsequent larger evaluation should include candidate-reviewed real job descriptions, pairwise document review and comparisons of reasoning effort before changing defaults. Six synthetic cases with two repeats do not establish production reliability, factual correctness for all inputs, ATS acceptance or recruitment success.
