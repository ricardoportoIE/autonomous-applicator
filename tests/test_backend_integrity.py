"""Fault boundaries must preserve approved facts, immutable records and sending controls."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_api import client
from test_store_service import setup

from applicator import documents, submission_records, workspace
from applicator import service as service_module
from applicator.location_policy import location_needs_review
from applicator.models import Evidence, Question, Settings, State
from applicator.networking import Networking
from applicator.operations import OperationBusy
from applicator.routine_answers import routine_answer


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("busy", [False, True])
def test_workspace_lock_protocol_releases_only_an_acquired_lock(data, monkeypatch, platform, busy):
    calls = []

    def acquire(fd, mode, *size):
        calls.append((mode, size))
        if busy:
            raise OSError("Already locked")

    unlock = Mock(side_effect=lambda fd, mode, *size: calls.append((mode, size)))
    if platform == "win32":

        def locking(fd, mode, size):
            (unlock if mode == 0 else acquire)(fd, mode, size)

        module = SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=0)
        monkeypatch.setitem(sys.modules, "msvcrt", module)
    else:

        def flock(fd, mode):
            (unlock if mode == 0 else acquire)(fd, mode)

        module = SimpleNamespace(flock=flock, LOCK_EX=1, LOCK_NB=2, LOCK_UN=0)
        monkeypatch.setitem(sys.modules, "fcntl", module)
    monkeypatch.setattr(workspace, "sys", SimpleNamespace(platform=platform))
    if busy:
        with pytest.raises(OperationBusy, match="Another server"):
            with workspace.server_owner(data):
                pytest.fail("A busy workspace must not be entered")
        unlock.assert_not_called()
    else:
        with pytest.raises(RuntimeError, match="Worker failed"):
            with workspace.server_owner(data):
                assert (data / ".server-lock").read_bytes() == b"\0"
                raise RuntimeError("Worker failed")
        assert unlock.call_count == 1
    assert calls == ([(1, (1,))] if platform == "win32" else [(3, ())]) + (
        [] if busy else [(0, (1,))] if platform == "win32" else [(0, ())]
    )


def test_module_entry_point_imports_only_the_requested_fictitious_profile(
    data, profile, monkeypatch, capsys
):
    import applicator.cli as cli

    data.mkdir(parents=True)
    source = data / "profile.json"
    source.write_text(profile.model_dump_json(), encoding="utf-8")
    monkeypatch.setenv("APPLICATOR_DATA_DIR", str(data))
    monkeypatch.setattr(sys, "argv", ["applicator", "import-profile", str(source)])
    monkeypatch.setattr(cli, "load_dotenv", Mock())
    monkeypatch.setattr("dotenv.load_dotenv", Mock())
    monkeypatch.delitem(sys.modules, "applicator.cli")
    runpy.run_module("applicator.cli", run_name="__main__")
    assert "Imported local profile revision 1" in capsys.readouterr().out
    from applicator.store import Store

    assert Store(data / "applicator.sqlite3").profile()[0] == profile


def test_regular_font_remains_available_when_optional_bold_font_is_missing(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda path: path.name == "aptos.ttf")
    monkeypatch.setattr(documents.pdfmetrics, "getRegisteredFontNames", lambda: [])
    factory, register = Mock(return_value=object()), Mock()
    monkeypatch.setattr(documents, "TTFont", factory)
    monkeypatch.setattr(documents.pdfmetrics, "registerFont", register)
    assert documents.font_name() == "CandidateFont"
    factory.assert_called_once_with("CandidateFont", str(Path("C:/Windows/Fonts/aptos.ttf")))
    register.assert_called_once_with(factory.return_value)


@pytest.mark.parametrize("font", ["aptos.ttf", "arial.ttf"])
@pytest.mark.parametrize("registered", [False, True])
def test_font_registration_is_portable_and_idempotent(monkeypatch, font, registered):
    bold = "arialbd.ttf" if font == "arial.ttf" else "aptos-bold.ttf"
    monkeypatch.setattr(Path, "is_file", lambda path: path.name in {font, bold})
    monkeypatch.setattr(
        documents.pdfmetrics,
        "getRegisteredFontNames",
        lambda: ["CandidateFont"] if registered else [],
    )
    factory, register = Mock(side_effect=lambda name, path: name), Mock()
    monkeypatch.setattr(documents, "TTFont", factory)
    monkeypatch.setattr(documents.pdfmetrics, "registerFont", register)
    assert documents.font_name() == "CandidateFont"
    assert factory.call_count == register.call_count == (0 if registered else 2)
    if not registered:
        assert [call.args[0] for call in factory.call_args_list] == [
            "CandidateFont",
            "CandidateFont-Bold",
        ]


def test_explicitly_selected_skill_preserves_its_approved_text(profile, job):
    profile.evidence = [
        Evidence(
            id="sql",
            category="skill",
            title="Database work",
            text="Built SQL queries.",
            tags=["SQL"],
            source="Candidate-approved record",
            verified=True,
        )
    ]
    job.requirements = ["Python"]
    assert ("body", "Built SQL queries.") in documents.selected_lines(profile, job, ["sql"])


@pytest.mark.parametrize("extracted", [None, "", "Another person's document"])
def test_pdf_without_extractable_candidate_identity_cannot_be_accepted(
    tmp_path, monkeypatch, extracted
):
    monkeypatch.setattr(
        documents,
        "PdfReader",
        lambda path: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: extracted)]),
    )
    with pytest.raises(ValueError, match="text extraction"):
        documents.write_pair([("name", "Alex Example")], tmp_path / "CV.pdf", tmp_path / "CV.docx")
    assert (tmp_path / "CV.pdf").read_bytes().startswith(b"%PDF")


def test_overlong_cover_letter_is_rejected_without_a_manifest(tmp_path, profile, job, monkeypatch):
    job.cover_letter_required = True
    write = documents.write_pair

    def oversized_letter(lines, pdf, docx):
        pages = write(lines, pdf, docx)
        return 3 if "Cover_Letter" in pdf.name else pages

    monkeypatch.setattr(documents, "write_pair", oversized_letter)
    with pytest.raises(ValueError, match="Cover letter is too long"):
        documents.generate(profile, job, ["python"], tmp_path, 1)


@pytest.mark.parametrize("location", ["Ireland", ", Ireland"])
def test_country_only_candidate_location_never_implies_a_home_city(profile, job, location):
    profile.location = location
    job.location = "Remote, Ireland"
    assert location_needs_review(job, profile, Settings())


@pytest.mark.parametrize(
    "label",
    [
        "How many years experience with Python and SQL?",
        "Is Python your strongest skill?",
        "Do you have experience with managing people?",
        "Have you used Python every day?",
    ],
)
def test_ambiguous_capability_and_combined_duration_require_review(profile, job, label):
    profile.evidence[0].text = "3 years Python experience."
    choices = [] if label.startswith("How many") else ["Yes", "No"]
    assert routine_answer(profile, job, Question(id="q", label=label, choices=choices)) is None


@pytest.mark.parametrize(
    "change", ["missing", "revision", "job", "state", "empty", "long", "sensitive", "choice"]
)
def test_routine_answer_write_rechecks_identity_state_and_question_contract(
    data, profile, job, change
):
    store, _, app_id = setup(data, profile, job)
    question = Question(id="q", label="Experience with Python?", choices=["Yes", "No"])
    revision, expected, answer = 1, job, "Yes"
    if change == "missing":
        app_id += 100
    elif change == "revision":
        revision += 1
    elif change == "job":
        expected = job.model_copy(update={"title": "Changed opportunity"})
    elif change == "state":
        attempt = store.reserve(app_id, revision)
        store.finish(app_id, attempt, "fixture:confirmed")
    elif change == "empty":
        answer = ""
    elif change == "long":
        answer = "x" * 3001
    elif change == "sensitive":
        question.sensitive = True
    else:
        answer = "Maybe"
    with pytest.raises(ValueError):
        store.save_routine_answer(
            app_id, question, answer, "verified_evidence", ["python"], revision, expected
        )
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM routine_answers").fetchone()[0] == 0
    assert store.profile() == (profile, 1)


def test_location_review_cannot_create_an_unknown_application(data, profile, job):
    store, _, app_id = setup(data, profile, job)
    with pytest.raises(KeyError):
        store.confirm_location(app_id + 1, 1, job.location)
    assert store.application(app_id)["state"] == State.READY


def test_recovery_of_discovery_run_without_application_is_idempotent(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    with service.operations.run("cycle") as operation:
        operation.progress("discovering_jobs", "Discovery was interrupted.")
        assert store.recover() == 0
        assert service.operations.status()["run"]["error_code"] == "ProcessInterrupted"
        assert store.recover() == 0
        assert store.application(app_id)["state"] == State.READY
        with pytest.raises(ValueError, match="no longer owns"):
            operation.finish()
        # Context cleanup must not overwrite the recovered run with completion.
    assert service.operations.status()["run"]["status"] == "interrupted"


def test_inconsistent_ready_evaluation_without_evidence_is_held_for_review(
    data, profile, job, monkeypatch
):
    store, service, app_id = setup(data, profile, job)
    original = service_module.evaluate(job, profile, store.settings())
    original.evidence_ids = []
    monkeypatch.setattr(
        "applicator.application_management.evaluate", lambda *args: original.model_copy(deep=True)
    )
    service.prepare(app_id)
    row = store.application(app_id)
    assert row["state"] == State.REVIEW and row["manifest"] == {}
    assert "Documents require verified evidence" in row["evaluation"]["blockers"][-1]


def test_last_moment_unresolved_answer_cannot_reserve_a_sending_slot(
    data, profile, job, monkeypatch
):
    store, service, app_id = setup(data, profile, job)
    monkeypatch.setattr(service_module, "answer_questions", lambda *args: ({}, ["New question"]))
    with pytest.raises(ValueError, match="remain unanswered"):
        service.submit(app_id)
    assert store.application(app_id)["state"] == State.READY
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


@pytest.mark.parametrize("enabled", ["automation_enabled", "connections_enabled"])
def test_automatic_networking_cannot_reserve_while_disabled(data, profile, enabled):
    from applicator.store import Store

    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    store.set_settings(
        Settings(
            automation_enabled=True, connections_enabled=True, linkedin_authorised=True
        ).model_copy(update={enabled: False})
    )
    network = Networking(store, data)
    network.add("https://www.linkedin.com/in/example/", "Example Recruiter", "Recruiter", "Ireland")
    with pytest.raises(ValueError, match="paused"):
        network.reserve(1)
    assert network.list()[0]["state"] == "queued"
    assert network.remaining() == store.settings().daily_connection_limit


def test_global_pause_stops_the_remaining_connection_queue(data, profile, monkeypatch):
    app, session = client(data)
    store, network = app.state.store, app.state.network
    store.save_profile(profile)
    store.set_settings(
        Settings(automation_enabled=True, connections_enabled=True, linkedin_authorised=True)
    )
    for slug in ["first", "second"]:
        network.add(f"https://www.linkedin.com/in/{slug}/", slug, "Recruiter", "Ireland")
    calls = []

    def send(app_id):
        calls.append(app_id)
        store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
        return "fixture:sent"

    monkeypatch.setattr(network, "send", send)
    assert session.post("/api/worker/tick").status_code == 200
    assert len(calls) == 1
    assert all(row["state"] == "queued" for row in network.list())


@pytest.mark.parametrize("fault", ["escape", "tamper", "existing", "unreserved"])
def test_archiving_rejects_path_races_tampering_overwrites_and_unreserved_attempts(
    data, profile, job, monkeypatch, fault
):
    store, service, app_id = setup(data, profile, job)
    manifest = store.application(app_id)["manifest"]
    attempt = store.reserve(app_id, 1) if fault != "unreserved" else 999
    archive = service.records.folder(app_id, attempt) / "documents"
    original = data / "documents" / str(app_id) / manifest["files"]["cv_pdf"]["name"]
    expected = {
        "escape": "Unsupported document archive",
        "tamper": "changed while archiving",
        "existing": "cannot be replaced",
        "unreserved": "reserved submission",
    }[fault]
    if fault == "escape":
        resolve = Path.resolve
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda path, *a, **k: (
                data.parent / "outside" if path == archive else resolve(path, *a, **k)
            ),
        )
    elif fault == "tamper":
        validate = submission_records.validate_manifest

        def change_after_validation(*args):
            validate(*args)
            original.write_bytes(b"tampered after validation")

        monkeypatch.setattr(submission_records, "validate_manifest", change_after_validation)
    elif fault == "existing":
        archive.mkdir(parents=True)
        (archive / original.name).write_bytes(b"immutable previous archive")
    with pytest.raises(ValueError, match=expected):
        service.records.begin(app_id, attempt, profile, 1, job, manifest, {})
    assert (
        service.records.read(app_id)["attempts"] == []
        or not service.records.read(app_id)["attempts"][0]["snapshot"]
    )
    if fault == "existing":
        assert (archive / original.name).read_bytes() == b"immutable previous archive"


def test_artifact_download_rejects_a_retargeted_archive(data, profile, job, monkeypatch):
    _, service, app_id = setup(data, profile, job)
    service.submit(app_id)
    attempt = service.records.read(app_id)["attempts"][0]["id"]
    artifact = service.records.artifact(app_id, attempt, "cv_pdf")
    resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **k: (
            data.parent / "outside.pdf" if path == artifact else resolve(path, *a, **k)
        ),
    )
    with pytest.raises(ValueError, match="Unsupported artifact path"):
        service.records.artifact(app_id, attempt, "cv_pdf")
