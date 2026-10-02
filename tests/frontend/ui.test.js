import assert from "node:assert/strict";
import { test } from "node:test";
import {
  errorDetail,
  linkedinIdentity,
  parseAnswers,
  splitList,
  stateLabel,
  stateLabels,
} from "../../src/applicator/static/ui.js";

test("every application and networking status has a readable label", () => {
  for (const [value, expected] of Object.entries(stateLabels))
    assert.equal(stateLabel(value), expected);
  for (const value of ["toString", "__proto__", "invented", null])
    assert.equal(stateLabel(value), "Unknown status");
});

test("comma-separated and newline values are trimmed and deduplicated", () => {
  assert.deepEqual(splitList("Python, FastAPI,Python, , PostgreSQL,"), [
    "Python",
    "FastAPI",
    "PostgreSQL",
  ]);
  assert.deepEqual(
    splitList(" https://example.test \n\n https://example.test", "\n"),
    ["https://example.test"],
  );
  assert.deepEqual(splitList(""), []);
});

test("approved answers preserve factual strings and reject malformed shapes", () => {
  assert.deepEqual(parseAnswers(""), {});
  assert.deepEqual(parseAnswers('{"question:salary?":"To be discussed"}'), {
    "question:salary?": "To be discussed",
  });
  for (const value of [
    "{",
    "null",
    "[]",
    "1",
    '"text"',
    '{"salary":123}',
    '{"nested":{}}',
  ])
    assert.throws(() => parseAnswers(value), /Approved answers/);
});

test("validation errors are readable even when the server returns an empty or non-JSON body", () => {
  assert.equal(
    errorDetail({ detail: "Automation is paused" }, 409),
    "Automation is paused",
  );
  assert.equal(
    errorDetail(
      {
        detail: [
          { loc: ["body", "daily_limit"], msg: "Must be at least 1" },
          {},
        ],
      },
      422,
    ),
    "daily_limit: Must be at least 1; Input: Invalid value",
  );
  for (const body of [null, {}, { detail: {} }])
    assert.equal(
      errorDetail(body, 502),
      "The request failed (502). Please try again.",
    );
});

test("LinkedIn recognition requires the approved HTTPS origin and an exact job path", () => {
  assert.equal(
    linkedinIdentity("https://www.linkedin.com/jobs/view/123/?tracking=abc"),
    "123",
  );
  for (const url of [
    "http://www.linkedin.com/jobs/view/123/",
    "https://www.linkedin.com:8443/jobs/view/123/",
    "https://user@www.linkedin.com/jobs/view/123/",
    "https://user:secret@www.linkedin.com/jobs/view/123/",
    "https://www.linkedin.com/in/person/",
    "https://example.test/jobs/view/123/",
    "https://www.linkedin.com/jobs/view/123/extra",
  ])
    assert.equal(linkedinIdentity(url), null);
  assert.throws(() => linkedinIdentity("invalid"), TypeError);
});
