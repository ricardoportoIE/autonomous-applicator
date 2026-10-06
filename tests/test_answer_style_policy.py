"""Candidate-authorised technology defaults and field-aware factual presentation."""

from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

from applicator.answer_style import experience_target, format_known_answer, numeric_field
from applicator.browser import browser_options, collect_questions
from applicator.models import FormContext, Question, State
from applicator.policy import answer_compatible, answer_questions
from applicator.question_adviser import question_key
from applicator.routine_answers import RoutineSelection, known_experience_duration, routine_answer
from applicator.service import Service
from applicator.store import Store

JAVA_YEARS = "How many years of work experience do you have with Java (Programming Language)?"
JAVA_TEXT = "Describe your experience with Java"
JAVA_DEFAULT = (
    "I have no professional experience with Java. "
    "My experience is educational, and I am developing my skills in this area."
)


def observed(label, kind="text", **constraints):
    return Question(
        id="q",
        label=label,
        form_context=FormContext(control_type=kind, constraints=constraints, html="<input>"),
    )


@pytest.mark.parametrize(
    "label,kind,constraints,expected",
    [
        (JAVA_YEARS, "text", {}, "0"),
        ("How many years of Java experience?", "text", {}, "0"),
        (JAVA_TEXT, "number", {}, "0"),
        (JAVA_TEXT, "text", {"inputmode": "numeric"}, "0"),
        (JAVA_TEXT, "text", {"inputmode": "decimal"}, "0"),
        (JAVA_TEXT, "text", {"pattern": r"[0-9]+"}, "0"),
        (JAVA_TEXT, "text", {}, JAVA_DEFAULT),
        (JAVA_TEXT, "textarea", {}, JAVA_DEFAULT),
        ("Do you have professional experience with Java?", "textarea", {}, JAVA_DEFAULT),
        (
            "How many years of work experience do you have with Agile Software Development?",
            "text",
            {},
            "0",
        ),
        ("How many years of experience with Snowflake?", "number", {}, "0"),
        (
            "Describe your TensorFlow project experience",
            "textarea",
            {},
            JAVA_DEFAULT.replace("Java", "TensorFlow"),
        ),
    ],
)
def test_absent_unanswered_technology_uses_authorised_default(
    profile, job, label, kind, constraints, expected
):
    selector = Mock(side_effect=AssertionError("Defaults need no model call"))
    question = observed(label, kind, **constraints)
    result = routine_answer(profile, job, question, selector)
    assert result and result.answer == expected
    assert result.source == "candidate_technology_policy" and result.evidence_ids == []
    assert answer_compatible(question, result.answer)
    selector.assert_not_called()


@pytest.mark.parametrize("where", ["summary", "title", "text", "tag", "unverified", "answer"])
def test_profile_mentions_or_previous_answers_prevent_default(profile, job, where):
    if where == "summary":
        profile.summary = "I am studying Java."
    elif where == "answer":
        profile.answers["question:have you used java?"] = "No"
    elif where in {"tag", "unverified"}:
        profile.evidence[0].tags.append("Java")
        if where == "unverified":
            profile.evidence[0].verified = False
    else:
        setattr(profile.evidence[0], where, "Java")
    assert routine_answer(profile, job, observed(JAVA_YEARS, "number")) is None


@pytest.mark.parametrize(
    "tag,target",
    [
        ("AI", "Artificial Intelligence (AI)"),
        ("Artificial Intelligence", "AI"),
        ("Agile", "Agile Software Development"),
        ("RAG", "RAG pipelines"),
        ("GCP", "Google Cloud"),
        ("Google Cloud", "GCP"),
    ],
)
def test_alias_mentions_do_not_become_unknown_technology_zero(profile, job, tag, target):
    profile.evidence[0].tags.append(tag)
    question = observed(f"How many years of work experience do you have with {target}?")
    assert routine_answer(profile, job, question) is None


@pytest.mark.parametrize(
    "label,kind",
    [
        ("Expected salary?", "number"),
        ("Age", "number"),
        ("How many years of leadership experience?", "number"),
        ("How many years of experience with Java and Python?", "number"),
        ("How many years of experience with Java in production?", "number"),
        ("Do you have experience with Java and visa sponsorship?", "textarea"),
        ("Describe your experience with Java", "date"),
        ("Describe your experience with UnclassifiedFramework", "textarea"),
        ("Can you commute to Dublin?", "text"),
        ("Will you accept hybrid working?", "text"),
        ("Do you consent to sharing your Java experience?", "text"),
    ],
)
def test_non_technology_exceptional_and_ambiguous_fields_do_not_receive_default(
    profile, job, label, kind
):
    assert routine_answer(profile, job, observed(label, kind)) is None


@pytest.mark.parametrize("constraint", [{"min": "1"}, {"max": "-1"}, {"min": "0.5", "step": "1"}])
def test_incompatible_numeric_constraints_leave_review(profile, job, constraint):
    question = observed(JAVA_YEARS, "number", **constraint)
    assert not answer_compatible(question, "0")
    assert routine_answer(profile, job, question) is None


@pytest.mark.parametrize("kind", ["select-one", "radio", "checkbox", "combobox"])
def test_choices_are_exact_and_unknown_capability_is_not_a_prose_choice(profile, job, kind):
    question = observed("Do you have experience with Java?", kind)
    question.choices = ["Yes", "No"]
    assert routine_answer(profile, job, question) is None
    profile.answers[question_key(question)] = "No"
    result = routine_answer(profile, job, question)
    assert result.answer == "No" and result.source == "approved_answer"
    assert format_known_answer(question, "No") == "No"


@pytest.mark.parametrize("trusted", ["unconfirmed", "sensitive"])
def test_default_requires_confirmed_profile_and_non_sensitive_question(profile, job, trusted):
    question = observed(JAVA_YEARS, "number")
    if trusted == "unconfirmed":
        profile.confirmed = False
    else:
        question.sensitive = True
    assert routine_answer(profile, job, question) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("3", "3"),
        ("2.5", "2.5"),
        ("I have 3 years of professional experience with Java.", "3"),
        ("3 years of experience with Java.", "3"),
        ("Around 3 years of experience with Java.", None),
        ("I have no professional experience with Java.", None),
        ("From 2023 I used Java.", None),
        ("3 years of experience with Python.", None),
        ("3 years Java, including 1 year in production.", None),
    ],
)
def test_numeric_known_answers_are_exact_durations_not_number_extraction(value, expected):
    assert format_known_answer(observed(JAVA_YEARS, "number"), value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Yes", "Yes, I have experience with Java."),
        ("No", "No, I do not have experience with Java."),
    ],
)
def test_known_text_uses_simple_sentence_without_replacing_confirmed_fact(
    profile, job, value, expected
):
    question = observed("Do you have experience with Java?", "textarea")
    profile.answers[question_key(question)] = value
    result = routine_answer(profile, job, question)
    assert result.answer == expected and result.source == "approved_answer"
    assert profile.answers[question_key(question)] == value
    assert answer_questions(job.model_copy(update={"questions": [question]}), profile) == (
        {"q": expected},
        [],
    )


def test_known_project_prose_is_short_and_does_not_claim_paid_employment(profile, job):
    question = observed("Describe your Python project experience", "textarea")
    result = routine_answer(
        profile,
        job,
        question,
        lambda *_: RoutineSelection(evidence_ids=["python"], needs_review=False),
    )
    assert result.answer == "I have experience with Python through independent projects."
    assert result.evidence_ids == ["python"]


def test_explicit_text_qualifications_and_default_are_preserved_on_formatting():
    question = observed(JAVA_TEXT, "textarea")
    assert format_known_answer(question, JAVA_DEFAULT) == JAVA_DEFAULT
    qualified = "I have studied Java. I have no professional experience. I am still learning."
    assert format_known_answer(question, qualified) == qualified
    assert (
        format_known_answer(observed("Email address", "email"), "alex@example.test")
        == "alex@example.test"
    )
    assert format_known_answer(observed("Phone number", "tel"), "+353 00") == "+353 00"


def test_contact_text_fields_keep_values_suitable_for_the_provider():
    assert format_known_answer(observed("Full name"), "Alex Example") == "Alex Example"
    assert format_known_answer(observed("Current location"), "Dublin, Ireland") == "Dublin, Ireland"


def test_defaults_are_persisted_per_opportunity_and_reused_after_restart(data, profile, job):
    store = Store(data / "answers.sqlite3")
    revision = store.save_profile(profile)
    for index, label in enumerate([JAVA_YEARS, JAVA_TEXT]):
        question = observed(label, "text")
        vacancy = job.model_copy(
            update={
                "source_id": f"new-{index}",
                "url": f"http://127.0.0.1:9999/new/{index}",
                "questions": [Question(id="q", label=label)],
            }
        )
        app_id = store.add_job(vacancy)[0]
        service = Service(store, data)
        expected = "0" if index == 0 else JAVA_DEFAULT
        assert service.resolve_question(app_id, profile, revision, vacancy, question) == expected
        reopened = Store(store.path)
        row = reopened.application(app_id)
        assert row["routine_answers"][0]["source"] == "candidate_technology_policy"
        assert (
            Service(reopened, data).resolve_question(app_id, profile, revision, vacancy, question)
            == expected
        )
    assert store.profile() == (profile, revision)
    assert store.daily_usage().attempts == 0


def test_scoped_approval_wins_and_disabled_routine_answering_keeps_default_off(data, profile, job):
    store = Store(data / "scoped.sqlite3")
    revision = store.save_profile(profile)
    question = observed(JAVA_YEARS, "number")
    job.questions = [Question(id="q", label=JAVA_YEARS)]
    app_id = store.add_job(job)[0]
    store.approve_answer(app_id, "q", "2", revision, job)
    service = Service(store, data)
    assert service.resolve_question(app_id, profile, revision, job, question) == "2"
    second = job.model_copy(update={"source_id": "other", "url": "http://127.0.0.1:9999/other"})
    second_id = store.add_job(second)[0]
    assert service.resolve_question(second_id, profile, revision, second, question) == "0"
    settings = store.settings()
    settings.routine_answers_enabled = False
    store.set_settings(settings)
    assert service.resolve_question(second_id, profile, revision, second, question) is None
    assert store.profile() == (profile, revision)


def test_preparation_answers_unknown_technology_without_model_call(data, profile, job):
    question = observed(JAVA_YEARS)
    job.questions = [question]
    store = Store(data / "prepare.sqlite3")
    store.save_profile(profile)
    app_id = store.add_job(job)[0]
    selector = Mock(side_effect=AssertionError("No model required for this policy"))
    Service(store, data, question_selector=selector).prepare(app_id)
    row = store.application(app_id)
    assert row["state"] == State.READY
    assert row["routine_answers"][0]["answer"] == "0"
    assert row["manifest"]["files"]["cv_pdf"]
    selector.assert_not_called()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as instance:
        yield instance


@pytest.mark.browser
def test_real_controls_fill_zero_prose_and_known_numeric_then_stop_before_send(
    browser, data, profile, job
):
    known_label = "How many years of experience with Python?"
    profile.answers[question_key(Question(id="known", label=known_label))] = "3"
    store = Store(data / "browser.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    service = Service(store, data)
    page = browser.new_page()
    page.set_content(
        f'<dialog open><label>{JAVA_YEARS}<input id="java" required></label>'
        f'<label>{JAVA_TEXT}<textarea id="prose" required></textarea></label>'
        f'<label>{known_label}<input id="known" type="number" min="0" required></label>'
        '<button onclick="window.sent=true">Submit application</button></dialog>'
    )
    try:
        pending = {}
        assert collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=lambda q: service.resolve_question(app_id, profile, revision, job, q),
            progress=Mock(),
            memory=Mock(return_value=None),
        )
        assert pending == {}
        assert page.locator("#java").input_value() == "0"
        assert page.locator("#prose").input_value() == JAVA_DEFAULT
        assert page.locator("#known").input_value() == "3"
        assert page.evaluate("window.sent") is None
        assert store.daily_usage().attempts == 0
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("attributes", ['type="number" min="1"', 'pattern="[1-9]+"'])
def test_disallowed_zero_collects_review_and_never_inflates_experience(
    browser, profile, job, attributes
):
    page = browser.new_page()
    page.set_content(
        f'<dialog open><label>{JAVA_YEARS}<input id="years" {attributes} required></label>'
        '<button onclick="window.sent=true">Submit application</button></dialog>'
    )
    try:
        pending = {}
        collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=lambda q: (
                result.answer if (result := routine_answer(profile, job, q)) else None
            ),
            progress=Mock(),
            memory=Mock(return_value=None),
        )
        assert len(pending) == 1
        assert page.locator("#years").input_value() == ""
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


def test_narrow_target_and_numeric_detection():
    assert (
        experience_target(Question(id="q", label="How many years of experience with Java?"))
        == "Java"
    )
    assert experience_target(Question(id="q", label="Your expected salary")) is None
    assert numeric_field(observed("Years", "text", pattern=r"\d+"))
    assert not numeric_field(observed("Phone", "tel", inputmode="numeric"))


@pytest.mark.parametrize("pattern", [r"\d{1,2}", r"^[0-9]{1,3}$", r"[1-9]+", r"[0-9]*"])
def test_numeric_only_patterns_use_zero_or_hold_for_native_validation(profile, job, pattern):
    question = observed(JAVA_TEXT, pattern=pattern)
    assert numeric_field(question)
    assert routine_answer(profile, job, question).answer == "0"


@pytest.mark.parametrize(
    "label",
    [
        "How many years of professional experience with Python?",
        "How many years of commercial experience do you have with Python?",
        "How many years of Python experience?",
    ],
)
def test_known_duration_variants_use_only_explicit_numeric_evidence(profile, job, label):
    profile.evidence[0].text = "3 years Python."
    profile.evidence[0].category = "experience"
    assert routine_answer(profile, job, observed(label)).answer == "3"


@pytest.mark.parametrize("answer", ["Yes", "No"])
def test_professional_scope_is_retained_in_known_prose(profile, job, answer):
    question = observed("Do you have professional experience with Python?", "textarea")
    profile.answers[question_key(question)] = answer
    result = routine_answer(profile, job, question)
    assert "professional experience with Python" in result.answer
    assert result.answer.startswith(answer + ",")


@pytest.mark.parametrize(
    "text",
    [
        "I have no professional Python experience. I am studying Python.",
        "Built Python projects, but I have no professional experience.",
        "Built Python projects. However, I am still learning.",
    ],
)
def test_source_qualifications_are_not_deleted_to_make_a_shorter_answer(profile, job, text):
    profile.evidence[0].text = text
    result = routine_answer(
        profile,
        job,
        observed("Describe your Python project experience"),
        lambda *_: RoutineSelection(evidence_ids=["python"], needs_review=False),
    )
    assert result.answer == text


@pytest.mark.parametrize(
    "constraints,number,valid",
    [
        ({"min": "0", "max": "3", "step": "0.5"}, "2.5", True),
        ({"step": "any"}, "2.5", True),
        ({"step": "1"}, "2.5", False),
        ({"step": "0"}, "0", False),
        ({"step": "NaN"}, "0", False),
        ({"min": "invalid"}, "0", False),
        ({"min": "Infinity"}, "0", False),
        ({"max": "NaN"}, "0", False),
        ({"max": "2"}, "3", False),
    ],
)
def test_numeric_bounds_and_steps_never_change_a_confirmed_number(constraints, number, valid):
    assert answer_compatible(observed(JAVA_YEARS, "number", **constraints), number) is valid


def test_generated_defaults_do_not_override_a_later_scoped_approval(data, profile, job):
    store = Store(data / "override.sqlite3")
    revision = store.save_profile(profile)
    job.questions = [Question(id="years", label=JAVA_YEARS), Question(id="text", label=JAVA_TEXT)]
    app_id = store.add_job(job)[0]
    service = Service(store, data)
    assert service.resolve_question(app_id, profile, revision, job, observed(JAVA_YEARS)) == "0"
    store.approve_answer(app_id, "years", "2", revision, job)
    assert service.resolve_question(app_id, profile, revision, job, observed(JAVA_YEARS)) == "2"
    # The confirmed duration can answer the same subject in prose without the
    # absence default inventing zero or changing the original scoped approval.
    assert service.resolve_question(app_id, profile, revision, job, observed(JAVA_TEXT)) == (
        "I have 2 years of professional experience with Java."
    )


def test_cached_known_prose_duration_is_formatted_without_changing_candidate(data, profile, job):
    question = observed(JAVA_YEARS, "number")
    profile.answers[question_key(question)] = "I have 3 years of professional experience with Java."
    store = Store(data / "known-cache.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    assert Service(store, data).resolve_question(app_id, profile, revision, job, question) == "3"
    assert store.profile() == (profile, revision)
    assert not store.application(app_id)["routine_answers"]


@pytest.mark.parametrize("technology", ["Snowflake", "TensorFlow", "Agile Software Development"])
def test_common_technology_cannot_receive_unrelated_model_sources(profile, job, technology):
    profile.summary = f"I am studying {technology}."
    question = observed(f"Describe your experience with {technology}")
    answer = routine_answer(
        profile,
        job,
        question,
        lambda *_: RoutineSelection(evidence_ids=["python"], needs_review=False),
    )
    assert answer is None


@pytest.mark.parametrize("first_kind,second_kind", [("number", "textarea"), ("textarea", "number")])
def test_policy_cache_adapts_when_the_same_label_changes_control_type(
    data, profile, job, first_kind, second_kind
):
    store = Store(data / "kind-change.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    service = Service(store, data)
    values = {"number": "0", "textarea": JAVA_DEFAULT}
    assert (
        service.resolve_question(app_id, profile, revision, job, observed(JAVA_TEXT, first_kind))
        == values[first_kind]
    )
    effective = store.effective_profile(app_id, profile, job)
    if second_kind == "textarea":
        assert (
            format_known_answer(
                observed(JAVA_TEXT, second_kind),
                effective.answers[question_key(observed(JAVA_TEXT))],
            )
            is None
        )
    assert (
        service.resolve_question(app_id, profile, revision, job, observed(JAVA_TEXT, second_kind))
        == values[second_kind]
    )
    assert store.profile() == (profile, revision)


@pytest.mark.parametrize("kind", ["select-one", "radio", "combobox"])
def test_offered_exact_zero_is_valid_for_unknown_technology_years(profile, job, kind):
    question = observed(JAVA_YEARS, kind)
    question.choices = ["0", "1", "2"]
    assert routine_answer(profile, job, question).answer == "0"
    profile.answers[question_key(question)] = "2"
    assert routine_answer(profile, job, question).answer == "2"
    profile.answers.clear()
    question.choices = ["1", "2"]
    assert routine_answer(profile, job, question) is None


def test_numeric_capability_question_cannot_turn_supported_experience_into_one(profile, job):
    assert (
        routine_answer(profile, job, observed("Do you have experience with Python?", "number"))
        is None
    )


def test_existing_policy_zero_disallowed_by_new_range_remains_in_review(data, profile, job):
    store = Store(data / "range-change.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    service = Service(store, data)
    assert service.resolve_question(app_id, profile, revision, job, observed(JAVA_YEARS)) == "0"
    assert (
        service.resolve_question(
            app_id, profile, revision, job, observed(JAVA_YEARS, "number", min="1")
        )
        is None
    )
    assert store.profile() == (profile, revision)


def test_known_professional_narrative_uses_short_work_scope_template(profile, job):
    profile.evidence[0].category = "experience"
    profile.evidence[0].text = "Built Python APIs for an employer."
    result = routine_answer(
        profile,
        job,
        observed("Describe your professional experience with Python"),
        lambda *_: RoutineSelection(evidence_ids=["python"], needs_review=False),
    )
    assert result.answer == "I have professional experience with Python."


def test_mixed_verified_sources_keep_their_specific_factual_wording(profile, job):
    profile.evidence.append(
        profile.evidence[0].model_copy(
            update={"id": "skill", "category": "skill", "text": "Built Python test tools."}
        )
    )
    result = routine_answer(
        profile,
        job,
        observed("Describe your experience with Python"),
        lambda *_: RoutineSelection(evidence_ids=["python", "skill"], needs_review=False),
    )
    assert result.answer == profile.evidence[0].text + " " + profile.evidence[1].text


@pytest.mark.parametrize("choices,expected", [(["Yes", "No"], "Yes"), (["No"], None), ([], None)])
def test_confirmed_country_location_is_not_a_commuting_or_eligibility_fact(
    profile, job, choices, expected
):
    question = Question(
        id="q", label="Are you currently located and living in Ireland?", choices=choices
    )
    result = routine_answer(profile, job, question)
    assert (result.answer if result else None) == expected


def test_numeric_choice_needs_a_duration_question_not_a_capability_guess(profile, job):
    question = observed("Do you have experience with Java?", "select-one")
    question.choices = ["0", "1"]
    assert routine_answer(profile, job, question) is None


@pytest.mark.browser
@pytest.mark.parametrize("widget", ["select", "radio"])
def test_real_numeric_choice_fills_offered_zero_without_submission(browser, profile, job, widget):
    page = browser.new_page()
    if widget == "select":
        control = f'<label>{JAVA_YEARS}<select id="years" required><option>1</option><option>0</option></select></label>'
    else:
        control = f'<fieldset><legend>{JAVA_YEARS}</legend><label>1<input type="radio" name="years" value="1" required></label><label>0<input id="zero" type="radio" name="years" value="0" required></label></fieldset>'
    page.set_content(
        "<dialog open>"
        + control
        + '<button onclick="window.sent=true">Submit application</button></dialog>'
    )
    try:
        pending = {}
        collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=lambda q: value.answer if (value := routine_answer(profile, job, q)) else None,
            progress=Mock(),
            memory=Mock(return_value=None),
        )
        assert pending == {}
        if widget == "select":
            assert page.locator("#years").input_value() == "0"
        else:
            assert page.locator("#zero").is_checked()
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.parametrize(
    "value,label,expected",
    [
        ("3", JAVA_TEXT, "I have 3 years of professional experience with Java."),
        ("0", JAVA_TEXT, "I have 0 years of professional experience with Java."),
        ("2.5", JAVA_TEXT, "I have 2.5 years of professional experience with Java."),
        (
            "1",
            "Describe your professional experience with Java",
            "I have 1 year of professional experience with Java.",
        ),
        ("3", "How many years of professional experience with Java?", "3"),
        ("3", "How many years of experience with Java?", None),
        ("From 2023 I used Java.", JAVA_TEXT, None),
        ("Around 3 years of experience with Java.", JAVA_TEXT, None),
        ("0-2 years", JAVA_TEXT, None),
    ],
)
def test_known_duration_can_be_rephrased_but_not_rescoped_or_inferred(
    profile, job, value, label, expected
):
    profile.answers[question_key(Question(id="approved", label=JAVA_YEARS))] = value
    result = routine_answer(profile, job, observed(label))
    assert (result.answer if result else None) == expected
    if result:
        assert result.source == "approved_experience_duration"


@pytest.mark.parametrize(
    "label,kind,choices,constraints",
    [
        ("Expected salary", "text", [], {}),
        (JAVA_TEXT, "date", [], {}),
        (JAVA_TEXT, "number", [], {}),
        (JAVA_YEARS, "select-one", ["0", "1"], {}),
        ("How many years of professional experience with Java?", "number", [], {"max": "2"}),
    ],
)
def test_duration_reuse_checks_units_controls_choices_and_bounds(
    profile, label, kind, choices, constraints
):
    profile.answers[question_key(Question(id="source", label=JAVA_YEARS))] = "3"
    question = observed(label, kind, **constraints)
    question.choices = choices
    assert known_experience_duration(profile, question, frozenset()) is None


def test_general_experience_cannot_establish_professional_duration(profile, job):
    profile.answers["question:how many years of experience with java?"] = "1"
    assert (
        routine_answer(profile, job, observed("Describe your professional experience with Java"))
        is None
    )
    result = routine_answer(profile, job, observed(JAVA_TEXT))
    assert result.answer == "I have 1 year of experience with Java."


def test_conflicting_durations_and_other_subjects_are_not_resolved_by_guessing(profile, job):
    profile.answers[question_key(Question(id="source", label=JAVA_YEARS))] = "3"
    profile.answers["question:how many years of professional experience with java?"] = "4"
    assert routine_answer(profile, job, observed(JAVA_TEXT)) is None
    profile.answers = {
        "question:how many years married?": "3",
        "question:how many years of experience with python?": "3",
    }
    assert known_experience_duration(profile, observed(JAVA_TEXT), frozenset()) is None
