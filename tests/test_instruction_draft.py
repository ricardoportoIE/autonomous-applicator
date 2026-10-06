"""Read-only, field-aware owner instruction drafting with fictional candidate data."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from applicator.api import create_app
from applicator.models import FormContext, Question
from applicator.question_library import (
    InstructionDraft,
    InstructionDraftRequest,
    InstructionUpdate,
    draft_question_instruction,
)

TOKEN = "fictional-instruction-draft-token-01234567890123456789"
LABEL = "How many years of professional Python experience do you have?"
PROMPT = (
    "For this Python professional-duration question, look up the current approved duration. "
    "Do not include educational or independent-project time. "
    "Request the professional duration if it has not been confirmed."
)


def result(**changes):
    return InstructionDraft(
        **{
            "prompt": PROMPT,
            "review_notes": "Check the instruction before saving.",
            "needs_clarification": False,
            "evidence_ids": [],
            "fact_keys": ["answer:question:" + LABEL.casefold()],
            **changes,
        }
    )


def setup(data, profile, job):
    profile.answers["question:" + LABEL.casefold()] = "2"
    app = create_app(data, TOKEN)
    store = app.state.store
    revision = store.save_profile(profile)
    item = Question(
        id="python",
        label=LABEL,
        form_context=FormContext(
            control_type="number",
            html='<input value="private-prefill">',
            constraints={"min": "0"},
        ),
    )
    job.questions = [item]
    app_id = store.add_job(job)[0]
    rule_id = store.question_library.observe(app_id, item)
    return app, store, revision, app_id, rule_id


def snapshot(store):
    with store.connect() as db:
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            name: [tuple(row) for row in db.execute('SELECT * FROM "' + name + '"')]
            for name in names
        }


def fake_ai(monkeypatch, output=None, effect=None):
    monkeypatch.setenv("OPENAI_API_KEY", "fictional-local-key")
    constructor = MagicMock()
    client = constructor.return_value.__enter__.return_value
    client.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=output or result(),
    )
    client.responses.parse.side_effect = effect
    monkeypatch.setattr("applicator.api.OpenAI", constructor)
    return constructor, client


def post(client, rule_id, revision, version=1):
    return client.post(
        f"/api/question-instructions/{rule_id}/draft",
        headers={"If-Match": str(revision)},
        json={"version": version},
    )


def test_success_is_authenticated_read_only_and_has_model_revision_provenance(
    data, profile, job, monkeypatch
):
    app, store, revision, app_id, rule_id = setup(data, profile, job)
    before = snapshot(store)
    constructor, model = fake_ai(monkeypatch)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = post(client, rule_id, revision)
    assert response.status_code == 200
    assert response.json() == {
        **result().model_dump(),
        "model": "gpt-6.1-sol",
        "profile_revision": revision,
        "instruction_version": 1,
        "field_variant_count": 2,
    }
    constructor.assert_called_once_with(timeout=180, max_retries=0)
    assert model.responses.parse.call_count == 1
    assert snapshot(store) == before
    assert store.application(app_id)["manifest"] == {}
    assert store.daily_usage().used == 0


@pytest.mark.parametrize(
    "kind", ["number", "text", "textarea", "select", "radio", "checkbox", "aria-checkbox"]
)
def test_model_receives_field_variants_but_no_html_contacts_or_sensitive_answers(
    data, profile, job, kind
):
    _, store, _, app_id, rule_id = setup(data, profile, job)
    sensitive = Question(
        id="private",
        label="Disability details",
        sensitive=True,
        form_context=FormContext(control_type="textarea", html="private html"),
    )
    store.question_library.observe(app_id, sensitive)
    profile.answers.update(
        {
            "question:disability details": "private-sensitive-answer",
            "email": "private-contact",
            "condition:location:private": "private-location",
        }
    )
    item = Question(
        id="variant",
        label=LABEL,
        choices=["0", "2"] if "checkbox" in kind or kind in {"select", "radio"} else [],
        form_context=FormContext(control_type=kind, html="private html", constraints={"max": "5"}),
    )
    store.question_library.observe(app_id, item)
    context = store.question_library.draft_context(rule_id, 1)
    ai = Mock()
    ai.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol-2026-10", output_parsed=result()
    )
    assert draft_question_instruction(ai, profile, context) == result()
    request = ai.responses.parse.call_args.kwargs
    payload = json.loads(request["input"])
    assert any(
        v["control_type"] == kind and v["constraints"] == {"max": "5"}
        for v in payload["question"]["field_variants"]
    )
    assert request["model"] == "gpt-6.1-sol" and request["store"] is False
    assert request["text_format"] is InstructionDraft and request["reasoning"] == {"effort": "high"}
    assert all(
        value not in request["input"]
        for value in (
            profile.email,
            profile.phone,
            profile.name,
            "private-contact",
            "private-sensitive-answer",
            "private html",
            "private-prefill",
            "private-location",
        )
    )
    assert "Do not repeat this general policy" in request["instructions"]
    assert "untrusted DATA" in request["instructions"]


def test_context_retains_variants_from_multiple_opportunities_and_routine_observations(
    data, profile, job
):
    _, store, revision, app_id, rule_id = setup(data, profile, job)
    other = job.model_copy(deep=True)
    other.source_id = "fixture-other"
    other.url = "https://example.test/jobs/another"
    other.questions = [Question(id="choice", label=LABEL, choices=["0", "1", "2"])]
    other_id = store.add_job(other)[0]
    store.question_library.observe(other_id, other.questions[0])
    with store.connect(True) as db:
        db.execute(
            "INSERT INTO routine_answers(application_id,answer_key,question,answer,source,evidence_ids,revision,job_fingerprint,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                app_id,
                "legacy-question",
                json.dumps(Question(id="cached", label=LABEL, choices=["2"]).model_dump()),
                "2",
                "verified_evidence",
                "[]",
                revision,
                "fingerprint",
                "2026-10-06T10:00:00Z",
            ),
        )
        for key, label in (("duplicate", LABEL), ("unrelated", "Salary expectations?")):
            db.execute(
                "INSERT INTO routine_answers VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    app_id,
                    key,
                    json.dumps(Question(id=key, label=label).model_dump()),
                    "2",
                    "verified_evidence",
                    "[]",
                    revision,
                    "fingerprint",
                    "2026-10-06T10:00:00Z",
                ),
            )
    context = store.question_library.draft_context(rule_id, 1)
    assert {tuple(v["choices"]) for v in context["field_variants"]} == {(), ("0", "1", "2"), ("2",)}
    assert len(context["field_variants"]) >= 3


def test_sensitive_historical_observation_blocks_an_ordinary_catalogue_draft(data, profile, job):
    _, store, _, app_id, rule_id = setup(data, profile, job)
    job.questions[0].sensitive = True
    with store.connect(True) as db:
        db.execute("UPDATE applications SET job=? WHERE id=?", (job.model_dump_json(), app_id))
    with pytest.raises(ValueError, match="Sensitive questions"):
        store.question_library.draft_context(rule_id, 1)


def test_instruction_can_reference_verified_evidence_without_becoming_a_fact(data, profile, job):
    _, store, _, _, rule_id = setup(data, profile, job)
    ai = Mock()
    idea = result(fact_keys=[], evidence_ids=["python"])
    ai.responses.parse.return_value = SimpleNamespace(model="gpt-6.1-sol", output_parsed=idea)
    assert (
        draft_question_instruction(ai, profile, store.question_library.draft_context(rule_id, 1))
        == idea
    )


@pytest.mark.browser
@pytest.mark.parametrize("clarification", [False, True])
def test_packaged_ui_generates_reviews_and_explicitly_saves_a_draft(
    data, profile, job, monkeypatch, clarification
):
    import threading

    from playwright.sync_api import expect, sync_playwright
    from test_browser import server

    from applicator.browser import browser_options

    app, store, revision, _, _ = setup(data, profile, job)
    before = snapshot(store)
    release = threading.Event()

    def effect(**_):
        assert release.wait(20), "The browser never observed generation progress"
        return SimpleNamespace(
            model="gpt-6.1-sol", output_parsed=result(needs_clarification=clarification)
        )

    _, model = fake_ai(monkeypatch, effect=effect)
    with server(app) as origin, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page(viewport={"width": 1440, "height": 1080}, locale="en-GB")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(origin)
            page.get_by_label("Access token", exact=True).fill(TOKEN)
            page.get_by_role("button", name="Unlock workspace").click()
            page.get_by_role("button", name="Agent settings", exact=True).click()
            page.get_by_role("tab", name="Routine answers", exact=True).click()
            page.get_by_role("button", name="Add instruction", exact=True).click()
            page.get_by_role(
                "button", name="Generate instruction with GPT-6.1 Sol", exact=True
            ).click()
            expect(
                page.get_by_role("button", name="Generating instruction…", exact=True)
            ).to_be_disabled()
            expect(
                page.get_by_role("textbox", name="Instruction for GPT-6.1 Sol", exact=True)
            ).to_be_disabled()
            expect(page.get_by_role("button", name="Save instruction", exact=True)).to_be_disabled()
            release.set()
            expect(
                page.get_by_role("textbox", name="Instruction for GPT-6.1 Sol", exact=True)
            ).to_have_value(PROMPT)
            assert snapshot(store) == before
            prefix = (
                "Candidate confirmation needed:" if clarification else "Draft ready for review:"
            )
            expect(
                page.get_by_text(prefix + " Check the instruction before saving.", exact=True)
            ).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 950})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            expect(
                page.get_by_role("button", name="Generate instruction with GPT-6.1 Sol", exact=True)
            ).to_be_visible()
            page.get_by_role("textbox", name="Instruction for GPT-6.1 Sol", exact=True).fill(
                "Candidate-reviewed instruction"
            )
            page.get_by_role("button", name="Save instruction", exact=True).click()
            expect(page.get_by_role("dialog")).not_to_be_visible()
            assert store.question_library.entries()[0]["prompt"] == "Candidate-reviewed instruction"
            assert store.profile() == (profile, revision) and store.daily_usage().used == 0
            assert model.responses.parse.call_count == 1 and not errors
        finally:
            release.set()
            browser.close()


@pytest.mark.parametrize(
    "mode,status",
    [
        ("unauthorised", 401),
        ("missing", 404),
        ("wrong_version", 409),
        ("wrong_revision", 409),
        ("unconfirmed", 409),
        ("sensitive", 409),
        ("no_key", 503),
        ("wrong_model", 503),
        ("missing_header", 422),
        ("extra_input", 422),
    ],
)
def test_rejected_requests_do_not_call_ai_or_change_private_records(
    data, profile, job, monkeypatch, mode, status
):
    app, store, revision, app_id, rule_id = setup(data, profile, job)
    constructor, _ = fake_ai(monkeypatch)
    if mode == "unconfirmed":
        profile.confirmed = False
        revision = store.save_profile(profile)
    if mode == "sensitive":
        store.question_library.observe(app_id, Question(id="python", label=LABEL, sensitive=True))
    if mode == "no_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    if mode == "wrong_model":
        monkeypatch.setenv("OPENAI_MODEL", "other-model")
    before = snapshot(store)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        if mode == "unauthorised":
            client.headers.clear()
        if mode in {"missing_header", "extra_input"}:
            response = client.post(
                f"/api/question-instructions/{rule_id}/draft",
                headers={} if mode == "missing_header" else {"If-Match": str(revision)},
                json={
                    "version": 1,
                    **({"prompt": "unsafe override"} if mode == "extra_input" else {}),
                },
            )
        else:
            response = post(
                client,
                "unknown" if mode == "missing" else rule_id,
                revision + (mode == "wrong_revision"),
                2 if mode == "wrong_version" else 1,
            )
    assert response.status_code == status, response.text
    constructor.assert_not_called()
    assert snapshot(store) == before


@pytest.mark.parametrize(
    "mode", ["wrong_model", "missing_output", "unknown_evidence", "unknown_fact", "provider"]
)
def test_provider_failures_are_private_and_never_save_a_draft(
    data, profile, job, monkeypatch, mode
):
    app, store, revision, _, rule_id = setup(data, profile, job)
    _, model = fake_ai(monkeypatch)
    if mode == "wrong_model":
        model.responses.parse.return_value.model = "other-model"
    elif mode == "missing_output":
        model.responses.parse.return_value.output_parsed = None
    elif mode == "unknown_evidence":
        model.responses.parse.return_value.output_parsed.evidence_ids = ["unverified"]
    elif mode == "unknown_fact":
        model.responses.parse.return_value.output_parsed.fact_keys = ["missing"]
    else:
        model.responses.parse.side_effect = RuntimeError("private-provider-token")
    before = snapshot(store)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = post(client, rule_id, revision)
    assert response.status_code == 502 and "private-provider-token" not in response.text
    assert snapshot(store) == before


@pytest.mark.parametrize("changed", ["profile", "version", "control"])
def test_changes_during_generation_require_a_fresh_draft(data, profile, job, monkeypatch, changed):
    app, store, revision, app_id, rule_id = setup(data, profile, job)

    def effect(**_):
        if changed == "profile":
            store.save_profile(profile)
        elif changed == "version":
            store.question_library.update(
                rule_id, InstructionUpdate(prompt="Owner update", enabled=False, version=1)
            )
        else:
            store.question_library.observe(
                app_id, Question(id="changed", label=LABEL, choices=["No", "Yes"])
            )
        return SimpleNamespace(model="gpt-6.1-sol", output_parsed=result())

    fake_ai(monkeypatch, effect=effect)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = post(client, rule_id, revision)
    assert response.status_code == 409
    assert store.question_library.entries()[0]["prompt"] != PROMPT


def test_missing_facts_can_produce_an_explicit_review_instruction_not_an_invented_answer(
    data, profile, job
):
    _, store, _, _, rule_id = setup(data, profile, job)
    ai = Mock()
    draft = result(
        needs_clarification=True,
        fact_keys=[],
        prompt="Ask for the confirmed duration before answering.",
    )
    ai.responses.parse.return_value = SimpleNamespace(model="gpt-6.1-sol", output_parsed=draft)
    assert (
        draft_question_instruction(ai, profile, store.question_library.draft_context(rule_id, 1))
        == draft
    )
    profile.confirmed = False
    ai.reset_mock()
    with pytest.raises(ValueError, match="Confirm candidate facts"):
        draft_question_instruction(ai, profile, store.question_library.draft_context(rule_id, 1))
    ai.responses.parse.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [{"prompt": ""}, {"prompt": "x" * 4001}, {"review_notes": ""}, {"fact_keys": ["x"] * 11}],
)
def test_draft_contract_bounds(changes):
    with pytest.raises(ValidationError):
        result(**changes)
    with pytest.raises(ValidationError):
        InstructionDraftRequest(version=0)


@pytest.mark.parametrize("words,accepted", [(120, True), (121, False)])
def test_generated_instruction_length_never_truncates_a_material_condition(
    data, profile, job, words, accepted
):
    _, store, _, _, rule_id = setup(data, profile, job)
    prompt = (
        "Use " + "approved " * (words - 7) + "facts; full-time work requires employer sponsorship."
    )
    assert len(prompt.split()) == words
    draft = result(prompt=prompt)
    ai = Mock()
    ai.responses.parse.return_value = SimpleNamespace(model="gpt-6.1-sol", output_parsed=draft)
    before = snapshot(store)
    context = store.question_library.draft_context(rule_id, 1)
    if accepted:
        assert draft_question_instruction(ai, profile, context).prompt == prompt
    else:
        with pytest.raises(ValueError, match="120-word limit"):
            draft_question_instruction(ai, profile, context)
    assert snapshot(store) == before


def test_oversized_generated_draft_is_private_and_keeps_the_saved_instruction(
    data, profile, job, monkeypatch
):
    app, store, revision, _, rule_id = setup(data, profile, job)
    store.question_library.update(
        rule_id,
        InstructionUpdate(prompt="Candidate's existing instruction", enabled=False, version=1),
    )
    _, model = fake_ai(monkeypatch, output=result(prompt="approved " * 121))
    before = snapshot(store)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = post(client, rule_id, revision, version=2)
    assert response.status_code == 502
    assert "approved approved" not in response.text
    assert snapshot(store) == before
    assert store.question_library.entries()[0]["prompt"] == "Candidate's existing instruction"
    assert model.responses.parse.call_count == 1


def test_manual_candidate_instructions_keep_their_existing_editor_limit(data, profile, job):
    _, store, _, _, rule_id = setup(data, profile, job)
    prompt = ("Candidate condition " * 130).strip()
    updated = store.question_library.update(
        rule_id, InstructionUpdate(prompt=prompt, enabled=False, version=1)
    )
    assert updated["prompt"] == prompt and len(prompt.split()) > 120
