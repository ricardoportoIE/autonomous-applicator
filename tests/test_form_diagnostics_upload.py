"""Private inert form evidence and vacancy-specific uploads against fictional providers."""

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright
from test_application_dialog import resume_html
from test_question_collection import provider_html

from applicator.browser import (
    LinkedInBrowser,
    QuestionnaireReview,
    ReviewRequired,
    application_dialog,
    browser_options,
    capture_form_diagnostic,
    upload_resume,
    validate_upload_document,
)
from applicator.documents import filename_stem, generate
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store


@pytest.fixture
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as instance:
        yield instance


@pytest.mark.browser
def test_diagnostic_retains_structure_options_and_errors_without_values_or_active_content(
    browser, data
):
    with browser.new_page() as page:
        page.set_content("""<p>OUTSIDE PRIVATE CONTENT</p><dialog open data-token="SECRET_TOKEN">
          <label for="SECRET_ID">Experience</label><input id="SECRET_ID" value="SECRET_INPUT" aria-invalid="true" required>
          <textarea>SECRET_PROSE</textarea><div contenteditable="true">SECRET_EDITABLE</div>
          <button role="combobox" aria-label="Country">SECRET_SELECTION</button>
          <label>Country<select><option selected value="SECRET_OPTION">Ireland</option><option>United Kingdom</option></select></label>
          <input type="hidden" value="SECRET_HIDDEN"><input type="checkbox" checked>
          <p role="alert">Enter a whole number</p><a href="https://example.test/SECRET_URL" onclick="alert(1)">Help</a>
          <img src="https://example.test/SECRET_IMAGE"><!--SECRET_COMMENT--><script>window.secret='SECRET_SCRIPT'</script>
          </dialog>""")
        evidence = capture_form_diagnostic(page, data, "123", 4, "answering_questions")
        content = (data / evidence["path"]).read_text(encoding="utf-8")
        assert "SECRET" not in content and "OUTSIDE PRIVATE" not in content
        assert 'aria-invalid="true"' in content and "Enter a whole number" in content
        assert "Ireland" in content and "United Kingdom" in content
        assert 'for="field-0"' in content and 'id="field-0"' in content
        assert "onclick" not in content and "<script" not in content and "href=" not in content
        assert " checked" not in content and " selected" not in content
        assert "default-src 'none'" in content
        assert "<dialog open" in content
        assert evidence["step"] == 4 and evidence["stage"] == "answering_questions"
        assert hashlib.sha256(content.encode()).hexdigest() == evidence["sha256"]
        # Capture never changes the actual form or its candidate values.
        assert page.locator("#SECRET_ID").input_value() == "SECRET_INPUT"
        assert page.locator("input[type=checkbox]").is_checked()
        again = capture_form_diagnostic(page, data, "123", 4, "answering_questions")
        assert again["path"] != evidence["path"]


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    ["no_dialog", "ambiguous", "nodes", "bytes", "write_error", "unsafe_path", "escaping_path"],
)
def test_capture_failure_is_bounded_and_does_not_expose_raw_errors(
    browser, data, monkeypatch, case
):
    html = "<dialog open><label>Salary<input required></label></dialog>"
    if case == "no_dialog":
        html = "<p>Signed out</p>"
    elif case == "ambiguous":
        html += "<dialog open><input></dialog>"
    elif case == "nodes":
        html = "<dialog open>" + "<span>x</span>" * 5001 + "</dialog>"
    elif case == "bytes":
        html = "<dialog open><p>" + "x" * 256001 + "</p></dialog>"
    elif case == "write_error":
        monkeypatch.setattr(Path, "open", Mock(side_effect=OSError("SECRET_FILESYSTEM_ERROR")))
    elif case == "unsafe_path":
        original = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda path: path.name == "questionnaire-diagnostics" or original(path),
        )
    else:
        original = Path.resolve
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda path, **kwargs: (
                data.parent / "outside.html" if path.suffix == ".html" else original(path, **kwargs)
            ),
        )
    with browser.new_page() as page:
        page.set_content(html)
        evidence = capture_form_diagnostic(page, data, "123", 2, "advancing_form")
    assert "capture_error" in evidence and "path" not in evidence
    assert "SECRET" not in json.dumps(evidence)
    assert not list(data.glob("questionnaire-diagnostics/*.html"))


@pytest.mark.parametrize(
    "step,submitted,capture", [(1, False, True), (0, False, False), (2, True, False)]
)
def test_diagnostic_guard_retains_the_original_failure_and_pre_send_boundary(
    data, job, monkeypatch, step, submitted, capture
):
    adapter = LinkedInBrowser(data)
    adapter.report("answering_questions", "Completing the form")
    recorder = Mock(return_value={"path": "questionnaire-diagnostics/fixture.html"})
    monkeypatch.setattr("applicator.browser.capture_form_diagnostic", recorder)
    error = ValueError("Original field failure")
    with pytest.raises(ValueError) as raised:
        with adapter.form_diagnostics(
            Mock(), job, {"step": step, "submitted": submitted, "pending": {}}
        ):
            raise error
    assert raised.value is error and recorder.called == capture
    assert bool(adapter.form_diagnostic) == capture


def test_a_successful_form_guard_does_not_capture(data, job, monkeypatch):
    recorder = Mock()
    monkeypatch.setattr("applicator.browser.capture_form_diagnostic", recorder)
    with LinkedInBrowser(data).form_diagnostics(
        Mock(), job, {"step": 1, "submitted": False, "pending": {}}
    ):
        pass
    assert not recorder.called


@pytest.mark.parametrize(
    "suffix,size,allowed",
    [
        (".pdf", 1, True),
        (".PDF", 1_999_999, True),
        (".doc", 5, True),
        (".docx", 5, True),
        (".pdf", 0, False),
        (".pdf", 2_000_000, False),
        (".pdf", 2_000_001, False),
        (".txt", 10, False),
        (".pdf", None, False),
    ],
)
def test_document_contract_requires_supported_non_empty_files_strictly_below_2mb(
    tmp_path, suffix, size, allowed
):
    document = tmp_path / ("Vacancy_CV" + suffix)
    if size is not None:
        document.write_bytes(b"x" * size)
    if allowed:
        validate_upload_document(document)
    else:
        with pytest.raises(ValueError):
            validate_upload_document(document)


@pytest.mark.browser
def test_oversized_resume_stops_before_opening_the_file_chooser(browser, tmp_path):
    document = tmp_path / "Vacancy_CV.pdf"
    document.write_bytes(b"x" * 2_000_000)
    with browser.new_page() as page:
        page.set_content(resume_html("custom"))
        page.locator("button", has_text="Upload resume").evaluate(
            "el=>el.onclick=()=>window.clicked=true"
        )
        with pytest.raises(ValueError, match="less than 2 MB"):
            upload_resume(page, application_dialog(page), document)
        assert page.evaluate("window.clicked") is None
        assert page.locator("#picker").evaluate("el=>el.files.length") == 0


@pytest.mark.browser
@pytest.mark.parametrize("shape", ["visible_name", "accessible_name"])
def test_each_vacancy_uploads_its_own_prepared_pdf_bytes_and_reuses_only_the_proved_selection(
    browser, profile, job, tmp_path, shape
):
    hashes = []
    for index, title in enumerate(["Python Engineer", "Backend Developer"], 1):
        vacancy = job.model_copy(update={"title": title, "source_id": str(index)}, deep=True)
        folder = tmp_path / str(index)
        generate(profile, vacancy, ["python"], folder, 1)
        document = folder / (filename_stem(profile, vacancy) + "_CV.pdf")
        hashes.append(hashlib.sha256(document.read_bytes()).hexdigest())
        html = (
            resume_html("custom")
            .replace(
                "<h3>Resume*</h3>",
                "<h3>Resume*</h3><p>Select or upload a resume in DOC, DOCX, or PDF format that is less than 2MB</p>",
            )
            .replace(
                "const card=document.createElement",
                "window.uploads=(window.uploads||0)+1;const card=document.createElement",
            )
        )
        if shape == "accessible_name":
            html = html.replace(
                "card.append(label);",
                "label.textContent='';card.setAttribute('aria-label',e.target.files[0].name);card.append(input);const name=document.createElement('span');name.textContent=e.target.files[0].name;document.querySelector('#new').append(name);",
            )
        with browser.new_page() as page:
            page.set_content(html)
            verified = {}
            assert upload_resume(page, application_dialog(page), document, verified=verified) == {
                "old",
                "uploaded",
            }
            actual = bytes(
                page.locator("#picker").evaluate(
                    "async el=>Array.from(new Uint8Array(await el.files[0].arrayBuffer()))"
                )
            )
            assert hashlib.sha256(actual).hexdigest() == hashes[-1]
            assert page.locator("#picker").evaluate("el=>el.files[0].name") == document.name
            assert page.locator("#uploaded").is_checked() and not page.locator("#old").is_checked()
            upload_resume(page, application_dialog(page), document, verified=verified)
            assert page.evaluate("window.uploads") == 1
    assert hashes[0] != hashes[1]


@pytest.mark.browser
@pytest.mark.parametrize("scenario", ["single", "prefill", "pages"])
def test_a_real_adapter_question_hold_records_private_html_and_releases_capacity(
    data, profile, job, monkeypatch, scenario
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(
        Settings(automation_enabled=True, linkedin_authorised=True, routine_answers_enabled=False)
    )
    ident, _ = store.add_job(job)
    adapter = LinkedInBrowser(data, profile)
    service = Service(store, data, {"linkedin": adapter})
    service.prepare(ident)
    pages = ["<label>Salary<input required></label><label>Email<input required></label>"]
    if scenario == "prefill":
        pages = [
            '<label>Salary<input value="UNAPPROVED_SECRET" required></label>',
            "<label>Later question<input required></label>",
        ]
    elif scenario == "pages":
        pages = [
            "<label>First unknown<input required></label>",
            "<label>Last unknown<input required></label>",
        ]
    html = provider_html(pages, validate=scenario != "pages")
    sends = []

    def context(self, playwright, **_):
        session = playwright.chromium.launch_persistent_context(
            str(data / "fictional-browser"), headless=True, **browser_options()
        )
        session.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        session.expose_binding("sendObserved", lambda *_: sends.append(True))
        session.add_init_script(
            "document.addEventListener('click',e=>{if(e.target.id==='submit')window.sendObserved();},true)"
        )
        return session

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    with pytest.raises(QuestionnaireReview):
        service.submit(ident)
    assert store.application(ident)["state"] == State.REVIEW
    with store.connect() as db:
        snapshots = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT detail FROM events WHERE kind='form_diagnostic' AND application_id=? ORDER BY id",
                (ident,),
            )
        ]
        evidence = snapshots[0]
        assert db.execute("SELECT status FROM attempts").fetchone()[0] == "released"
    assert evidence["stage"] == "answering_questions" and evidence["step"] == 1
    content = (data / evidence["path"]).read_text(encoding="utf-8")
    assert ("First unknown" if scenario == "pages" else "Salary") in content
    assert profile.email not in content
    assert "UNAPPROVED_SECRET" not in content
    assert [item["step"] for item in snapshots] == ([1, 2, 2] if scenario == "pages" else [1, 1])
    if scenario == "pages":
        later = (data / snapshots[1]["path"]).read_text(encoding="utf-8")
        assert "Last unknown" in later and "First unknown" not in later
    assert not sends


@pytest.mark.parametrize("record_error", [False, True])
def test_failed_diagnostic_journalling_cannot_replace_the_review_outcome(
    data, profile, job, monkeypatch, record_error
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    ident, _ = store.add_job(job)
    adapter = LinkedInBrowser(data, profile)
    service = Service(store, data, {"linkedin": adapter})
    service.prepare(ident)
    error = ReviewRequired("Original questionnaire hold")

    def submit(*_):
        adapter.form_diagnostic = {
            "stage": "answering_questions",
            "step": 2,
            "capture_error": "Error",
        }
        raise error

    monkeypatch.setattr(adapter, "submit", submit)
    original_event = store.event

    def event(db, kind, detail, application_id=None):
        if kind == "form_diagnostic" and record_error:
            raise OSError("Private journal failure")
        return original_event(db, kind, detail, application_id)

    monkeypatch.setattr(store, "event", event)
    with pytest.raises(ReviewRequired) as raised:
        service.submit(ident)
    assert raised.value is error and store.application(ident)["state"] == State.REVIEW
