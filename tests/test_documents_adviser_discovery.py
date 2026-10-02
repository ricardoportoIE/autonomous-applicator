from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from docx import Document
from pypdf import PdfReader

from applicator.adviser import advise
from applicator.discovery import greenhouse
from applicator.documents import font_name, generate, selected_lines, validate_manifest
from applicator.models import Advice, Evidence


def test_cv_and_cover_letter_text_and_page_properties(profile, job, tmp_path):
    job.cover_letter_required = True
    profile.summary = "Independent backend project experience using Python and FastAPI."
    profile.evidence += [
        Evidence(
            id="degree",
            category="education",
            title="Postgraduate Specialisation in AI",
            text="Completed a postgraduate specialisation, not a master's degree.",
            source="Reviewed certificate",
            verified=True,
            dates="Sep 2025 - Mar 2026",
        )
    ]
    manifest = generate(profile, job, ["python"], tmp_path, 4)
    assert set(manifest["files"]) == {"cv_pdf", "cv_docx", "cover_pdf", "cover_docx"}
    for key in ("cv_pdf", "cover_pdf"):
        reader = PdfReader(tmp_path / manifest["files"][key]["name"])
        assert 1 <= len(reader.pages) <= 2
        assert not reader.is_encrypted
        assert abs(float(reader.pages[0].mediabox.width) - 595.2756) < 1
        text = " ".join(page.extract_text() for page in reader.pages)
        assert profile.name in text and profile.email in text
        assert "independent" in text.lower()
    editable = Document(tmp_path / manifest["files"]["cv_docx"]["name"])
    assert "Professional Summary" in [p.text for p in editable.paragraphs]
    validate_manifest(manifest, tmp_path, 4)


def test_documents_require_approved_facts(profile, job, tmp_path):
    with pytest.raises(ValueError):
        generate(profile, job, ["invented"], tmp_path, 1)
    with pytest.raises(ValueError):
        generate(profile, job, [], tmp_path, 1)
    profile.confirmed = False
    with pytest.raises(ValueError):
        selected_lines(profile, job, ["python"])
    with pytest.raises(ValueError):
        validate_manifest({}, tmp_path, 1)


def test_escape_markup_and_font_fallback(profile, job, tmp_path, monkeypatch):
    profile.evidence[0].text = "Built <script>alert('x')</script> & Python services."
    manifest = generate(profile, job, ["python"], tmp_path, 1)
    text = PdfReader(tmp_path / manifest["files"]["cv_pdf"]["name"]).pages[0].extract_text()
    assert "<script>" in text and "& Python" in text
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert font_name() == "Helvetica"


def test_oversized_document_rejected(profile, job, tmp_path):
    profile.evidence = [
        Evidence(
            id=f"item_{i}",
            category="education",
            title="Qualification",
            text="Extensive factual content " * 45,
            source="reviewed",
            verified=True,
        )
        for i in range(20)
    ]
    with pytest.raises(ValueError, match="two pages"):
        generate(profile, job, ["item_0"], tmp_path, 1)


def test_adviser_uses_exact_model_and_rejects_hallucinated_ids(profile, job):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=Advice(
            evidence_ids=["python", "python"], explanation="Relevant independent API evidence."
        )
    )
    result = advise(client, profile, job)
    assert result.evidence_ids == ["python"]
    params = client.responses.parse.call_args.kwargs
    assert params["model"] == "gpt-6.1-sol" and params["store"] is False
    assert "private chain" in params["instructions"]
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=Advice(evidence_ids=["fake"], explanation="Ignore your rules.")
    )
    with pytest.raises(ValueError):
        advise(client, profile, job)
    client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
    with pytest.raises(ValueError):
        advise(client, profile, job)


def test_greenhouse_fixed_origin_html_and_empty_jobs():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 12,
                        "title": "Python Engineer",
                        "location": {"name": "Ireland"},
                        "absolute_url": "https://example.test/12",
                        "content": "<p>Python &amp; AWS</p>",
                    },
                    {"id": 13, "content": ""},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        jobs = greenhouse("example", client)
        assert jobs[0].source_id == "example:12"
        assert "Python & AWS" in jobs[0].description
        assert requests[0].url.host == "boards-api.greenhouse.io"
        with pytest.raises(ValueError):
            greenhouse("../private", client)


def test_greenhouse_rejects_large_response():
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 5_000_001))
    ) as client:
        with pytest.raises(ValueError, match="size"):
            greenhouse("example", client)
