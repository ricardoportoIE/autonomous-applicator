"""Large country dropdowns retain exact choices without inventing contact facts."""

from html import escape
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_question_collection import chromium as chromium
from test_question_collection import collect

from applicator.api import create_app
from applicator.browser import fill_questions, form_questions, question_context
from applicator.models import Job, Question, State
from applicator.question_adviser import question_key
from applicator.store import Store


def dialling_choices():
    choices = [f"Example region {i} (+{9000 + i})" for i in range(247)]
    # Both relevant countries occur after the former 100-option cut-off.
    choices.insert(180, "Ireland (+353)")
    choices.append("United Kingdom (+44)")
    return choices


def phone_form(choices):
    options = '<option value="">Choose a country</option>' + "".join(
        f'<option value="{i}">{escape(choice)}</option>' for i, choice in enumerate(choices)
    )
    return (
        '<dialog open><label for="country">Phone country code</label>'
        f'<select id="country" required>{options}</select>'
        '<label for="phone">Mobile phone number</label><input id="phone" type="tel" required>'
        '<label for="salary">Salary</label><input id="salary" required>'
        '<button type="button" onclick="window.sent=true">Submit application</button></dialog>'
    )


@pytest.mark.parametrize("count", [100, 249, 500])
def test_large_question_choices_survive_prompt_and_job_serialisation(job, count):
    choices = [f"Region {i}" for i in range(count)]
    question = Question(id="region", label="Preferred region", choices=choices)
    job.questions = [question]
    restored = Job.model_validate_json(job.model_dump_json())
    assert restored.questions[0].choices == choices
    assert restored.questions[0].prompt_payload()["choices"][-1] == choices[-1]


def test_choice_expansion_retains_question_count_and_html_bounds(job):
    with pytest.raises(ValidationError) as error:
        Question(id="too_many", label="Region", choices=[f"Region {i}" for i in range(501)])
    assert error.value.errors()[0]["loc"] == ("choices",)
    assert error.value.errors()[0]["type"] == "too_long"
    oversized = job.model_dump()
    oversized["questions"] = [
        Question(id=f"q{i}", label=f"Question {i}").model_dump() for i in range(101)
    ]
    with pytest.raises(ValidationError) as error:
        Job.model_validate(oversized)
    assert error.value.errors()[0]["loc"] == ("questions",)
    with pytest.raises(ValidationError) as error:
        question_context(
            {"type": "select-one", "tag": "select", "required": True},
            "Region",
            ["x" * 12001],
        )
    assert error.value.errors()[0]["loc"] == ("html",)


@pytest.mark.browser
@pytest.mark.parametrize("flow", ["direct", "collection"])
@pytest.mark.parametrize("country", ["Ireland (+353)", "United Kingdom (+44)"])
def test_a_249_option_phone_dropdown_uses_the_approved_prefix_beyond_option_100(
    chromium, profile, flow, country
):
    profile.phone = "+3535550100" if country.startswith("Ireland") else "+4455501000"
    profile.answers["question:salary"] = "50000"
    choices = dialling_choices()
    resolver = Mock(side_effect=AssertionError("Approved contact facts need no model request"))
    with chromium.new_page() as page:
        page.set_content(phone_form(choices))
        assert len(form_questions(page)[0]["choices"]) == 249
        if flow == "direct":
            fill_questions(page, profile, resolver=resolver)
        else:
            pending, safe, _ = collect(page, profile, resolver=resolver)
            assert pending == {} and safe
        assert page.locator("#country option:checked").inner_text() == country
        assert page.locator("#phone").input_value() == (
            "5550100" if country.startswith("Ireland") else "55501000"
        )
        assert page.locator("#country").evaluate("el=>el.checkValidity()")
        assert page.locator("#salary").input_value() == "50000"
        assert not resolver.called and page.evaluate("window.sent") is None


@pytest.mark.browser
def test_an_unknown_phone_with_249_choices_retains_the_whole_list_and_other_gaps(
    chromium, data, profile, job
):
    profile.phone = ""
    choices = dialling_choices()
    with chromium.new_page() as page:
        page.set_content(phone_form(choices))
        pending, safe, _ = collect(page, profile)
        assert [q.label for q in pending.values()] == [
            "Phone country code",
            "Mobile phone number",
            "Salary",
        ]
        assert pending["question:phone country code"].choices == choices
        assert page.locator("#country").input_value() == ""
        assert page.locator("#phone").input_value() == "" and safe
        assert page.evaluate("window.sent") is None
    store = Store(data / "large-choices.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    store.hold(
        app_id, "Questionnaire review: phone facts need approval", questions=list(pending.values())
    )
    reloaded = Store(store.path).application(app_id)
    country = reloaded["job"]["questions"][0]
    assert country["choices"] == choices and reloaded["state"] == State.REVIEW
    assert "form_context" not in country
    store.approve_answer(
        app_id, country["id"], choices[-1], revision, Job.model_validate(reloaded["job"])
    )
    assert (
        store.application(app_id)["approved_answers"][
            question_key(Question.model_validate(country))
        ]
        == choices[-1]
    )


@pytest.mark.parametrize("count", [249, 500, 501])
def test_the_authenticated_api_accepts_bounded_large_lists_and_rejects_excess(data, job, count):
    token = "large-list-fixture-token-01234567890123456789"
    app = create_app(data, token)
    payload = job.model_dump()
    payload["questions"] = [
        {"id": "region", "label": "Region", "choices": [f"Region {i}" for i in range(count)]}
    ]
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as session:
        response = session.post("/api/jobs", json=payload)
    if count == 501:
        assert response.status_code == 422 and app.state.store.applications() == []
    else:
        assert response.status_code == 200
        row = app.state.store.application(response.json()["id"])
        assert row["job"]["questions"][0]["choices"] == payload["questions"][0]["choices"]
