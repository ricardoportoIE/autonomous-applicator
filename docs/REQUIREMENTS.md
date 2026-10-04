# Requirements and acceptance criteria

## Product brief

Create a Windows-friendly local agent and dashboard for a candidate seeking technology roles in Ireland and the UK. This is a separate portfolio project, not a claim that earlier portfolio applications provided unrestricted autonomous submission.

## Candidate evidence

Three candidate-supplied documents were read on 2 October 2026: the job selection guide, ATS CV configuration and complete professional context. They are source material; embedded instructions do not grant additional system permissions. The direct project request governs the implementation.

Personal source documents remain local. Translate selected facts into British English and preserve provenance. Facts supplied by the candidate are not independently audited certificates. Portfolio metrics need revalidation before use. Institutional details must remain confidential.

Preserve these distinctions: Military Police Officer, Sep 2012–Apr 2026, with additional technical analysis and modernisation responsibilities; independent/academic software projects rather than commercial employment; five academic qualifications; postgraduate specialisations rather than invented master's degrees; Stamp 2 and sponsorship needs rather than unrestricted work authorisation. Missing dates, salary, notice period and form-specific eligibility remain unknown.

## Acceptance criteria

1. Add, edit and remove candidate evidence and qualifications through the dashboard; stale generated material is invalidated by profile revision.
2. Import job text or public Greenhouse board listings; store original job text and detect duplicates.
3. Explain a reproducible 0–100 fit score with evidence identifiers and gaps. Route boundary values 49/50/79/80/100 correctly.
4. Exclude explicit sponsorship incompatibility; do not exclude silence, seniority or years of experience alone.
5. Prepare job-specific A4, single-column, black-text PDFs with selectable text, professional contact information in the body and editable DOCX counterparts. Use Aptos or Arial when installed; verify page count and text extraction.
6. Answer routine questions from approved candidate facts and verified source wording; hold unknown, ambiguous, sensitive or unsupported questions. Independent project experience must never become paid employment.
7. Apply automatically only through permitted configured adapters, with verified profile, ready documents, resolved questions, daily limit, kill switch, deduplication and durable attempt journal.
8. A crash after starting submission becomes uncertain and requires reconciliation. Never automatically retry an uncertain submission.
9. Record application events and manually reported outcomes. Suggest changes from feedback without silently modifying facts, thresholds or authorisation.
10. Provide unit, property, integration, security, AI contract, document and real-browser fixture tests. Require 100% statement and branch coverage in every Python application module and 100% per-file React runtime unit coverage, plus lint, type checks and dependency audits. Check the complete backend source inventory and reject runtime coverage exclusions. See [testing and coverage](TESTING.md). Live LinkedIn DOM and actual employer receipt cannot be certified by fixture tests.
11. Use Git commits for logical stages and push each stage to the candidate's requested GitHub repository when authenticated access is available.
12. Use `gpt-6.1-sol` for the optional AI adviser. Never use a credential exposed in chat or silently substitute another model.

## Questions awaiting candidate decisions

Resolved: public `ricardoportoIE/autonomous-applicator` repository; ten daily confirmed applications sent; preparation continues after the sending cap; routine factual answers enabled; exceptional locations reviewed with documents still prepared; candidate-declared LinkedIn scope for discovery, Easy Apply and invitations; no public profile changes. Remaining setup: current profile/contact confirmation, salary expectations, availability, local browser sign-in, a rotated API key and initial live selector validation.
