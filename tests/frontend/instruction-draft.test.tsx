import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { RoutineAnswers } from "../../frontend/src/routine-answers";
import type {
  InstructionDraft,
  QuestionInstruction,
} from "../../frontend/src/contracts";
import { payload, profile } from "./fixtures";
import { deferred, harness } from "./harness";

const entry: QuestionInstruction = {
  id: "python",
  question: {
    id: "years",
    answer_key: "",
    label: "Professional Python years?",
    required: true,
    choices: [],
    sensitive: false,
    control_type: "number",
  },
  prompt: "",
  enabled: false,
  version: 1,
  first_seen: "2026-10-06T10:00:00Z",
  last_seen: "2026-10-06T10:00:00Z",
  application_count: 2,
};
const draft: InstructionDraft = {
  prompt:
    "Use approved Python duration. Use digits for numbers, short polite text, or an exact enabled choice. Review unknown facts.",
  review_notes: "Check the facts and field rules before saving.",
  needs_clarification: false,
  evidence_ids: [],
  fact_keys: [],
  model: "gpt-6.1-sol",
  profile_revision: 1,
  instruction_version: 1,
  field_variant_count: 2,
};
const path = "/api/question-instructions/python/draft";
const button = "Generate instruction with GPT-6.1 Sol";
let h: ReturnType<typeof harness>;
beforeEach(() => {
  h = harness();
  h.responses.set("/api/question-instructions", [entry]);
  h.responses.set(path, draft);
});
afterEach(() => h.stop());

async function open(item = entry) {
  h.responses.set("/api/question-instructions", [item]);
  await h.unlock();
  render(<RoutineAnswers workspace={h.workspace} />);
  fireEvent.click(
    await screen.findByRole("button", {
      name: item.prompt ? "Edit instruction" : "Add instruction",
    }),
  );
  return within(screen.getByRole("dialog"));
}

it("generates an editable draft with the profile revision without saving or enabling a rule", async () => {
  const modal = await open();
  fireEvent.click(modal.getByRole("button", { name: button }));
  await waitFor(() =>
    expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
      draft.prompt,
    ),
  );
  expect(
    modal.getByText("Draft ready for review: " + draft.review_notes),
  ).toBeVisible();
  const call = h.fetch.mock.calls.find((args) => args[0] === path)!;
  const options = (call as unknown as [string, RequestInit])[1];
  expect(options.method).toBe("POST");
  expect(JSON.parse(String(options.body))).toEqual({ version: 1 });
  expect(options.headers).toMatchObject({ "If-Match": "1" });
  expect(
    h.fetch.mock.calls.some(
      (args) => args[0] === "/api/question-instructions/python",
    ),
  ).toBe(false);
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: "Candidate-edited instruction" },
  });
  h.responses.set("/api/question-instructions/python", {
    ...entry,
    prompt: "Candidate-edited instruction",
    enabled: true,
    version: 2,
  });
  fireEvent.submit(
    modal.getByRole("button", { name: "Save instruction" }).closest("form")!,
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  const saved = h.fetch.mock.calls.find(
    (args) => args[0] === "/api/question-instructions/python",
  )!;
  expect(
    JSON.parse(String((saved as unknown as [string, RequestInit])[1].body)),
  ).toEqual({
    prompt: "Candidate-edited instruction",
    enabled: true,
    version: 1,
  });
});

it("shows generation progress and prevents duplicate requests, edits and saves", async () => {
  const modal = await open({ ...entry, prompt: "Existing instruction" });
  const pending = deferred<Response>();
  h.fetch.mockImplementation(async (url: string) =>
    url === path ? pending.promise : Response.json(payload(url)),
  );
  fireEvent.click(modal.getByRole("button", { name: button }));
  expect(
    await modal.findByRole("button", { name: "Generating instruction…" }),
  ).toBeDisabled();
  expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toBeDisabled();
  expect(
    modal.getByRole("button", { name: "Save instruction" }),
  ).toBeDisabled();
  fireEvent.click(
    modal.getByRole("button", { name: "Generating instruction…" }),
  );
  expect(h.fetch.mock.calls.filter((args) => args[0] === path)).toHaveLength(1);
  await act(async () => pending.resolve(Response.json(draft)));
  await waitFor(() =>
    expect(modal.getByRole("button", { name: button })).toBeEnabled(),
  );
  expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
    draft.prompt,
  );
});

it("displays missing-fact guidance while leaving explicit save under candidate control", async () => {
  h.responses.set(path, {
    ...draft,
    needs_clarification: true,
    review_notes: "Confirm the professional duration.",
  });
  const modal = await open();
  fireEvent.click(modal.getByRole("button", { name: button }));
  expect(
    await modal.findByText(
      "Candidate confirmation needed: Confirm the professional duration.",
    ),
  ).toBeVisible();
  expect(modal.getByRole("button", { name: "Save instruction" })).toBeEnabled();
});

it("preserves editor text on API failure and supports a deliberate retry", async () => {
  const modal = await open();
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: "Keep my draft" },
  });
  h.fetch.mockImplementation(async (url: string) =>
    url === path
      ? Response.json(
          { detail: "Set OPENAI_API_KEY locally to generate an instruction" },
          { status: 503 },
        )
      : Response.json(payload(url)),
  );
  fireEvent.click(modal.getByRole("button", { name: button }));
  expect(await modal.findByRole("alert")).toHaveTextContent(
    "Set OPENAI_API_KEY",
  );
  expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
    "Keep my draft",
  );
  h.fetch.mockImplementation(async (url: string) =>
    Response.json(url === path ? draft : payload(url)),
  );
  fireEvent.click(modal.getByRole("button", { name: button }));
  await waitFor(() =>
    expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
      draft.prompt,
    ),
  );
  expect(modal.queryByRole("alert")).toBeNull();
});

it.each(["text", "textarea", "number", "select", "radio", "checkbox"])(
  "offers field-aware generation for %s without sending raw HTML from the browser",
  async (kind) => {
    const modal = await open({
      ...entry,
      question: {
        ...entry.question,
        control_type: kind,
        choices: kind === "select" ? ["0", "2"] : [],
      },
    });
    fireEvent.click(modal.getByRole("button", { name: button }));
    await waitFor(() =>
      expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
        draft.prompt,
      ),
    );
    expect(
      JSON.parse(
        String(
          (
            h.fetch.mock.calls.find((args) => args[0] === path)! as unknown as [
              string,
              RequestInit,
            ]
          )[1].body,
        ),
      ),
    ).toEqual({ version: 1 });
  },
);

it("disables generation for sensitive questions", async () => {
  const modal = await open({
    ...entry,
    question: { ...entry.question, sensitive: true },
  });
  expect(modal.getByRole("button", { name: button })).toBeDisabled();
});

it("disables generation until candidate facts are confirmed", async () => {
  h.responses.set("/api/profile", {
    profile: { ...profile, confirmed: false },
    revision: 1,
  });
  const modal = await open();
  expect(modal.getByRole("button", { name: button })).toBeDisabled();
});

it.each([false, true])(
  "ignores late generation after closing the editor (failed=%s)",
  async (failed) => {
    const modal = await open();
    const pending = deferred<Response>();
    h.fetch.mockImplementation(async (url: string) =>
      url === path ? pending.promise : Response.json(payload(url)),
    );
    fireEvent.click(modal.getByRole("button", { name: button }));
    fireEvent.click(modal.getByRole("button", { name: "Close dialogue" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () =>
      pending.resolve(
        failed
          ? Response.json({ detail: "Old request failed" }, { status: 502 })
          : Response.json(draft),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add instruction" }));
    expect(screen.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
      "",
    );
    expect(screen.queryByText(/Draft ready for review/)).toBeNull();
    expect(h.workspace.getSnapshot().notice).toBe("");
  },
);

it("ignores late generation after locking the workspace", async () => {
  const modal = await open();
  const pending = deferred<Response>();
  h.fetch.mockImplementation(async (url: string) =>
    url === path ? pending.promise : Response.json(payload(url)),
  );
  fireEvent.click(modal.getByRole("button", { name: button }));
  await act(async () => h.workspace.lock());
  await act(async () => pending.resolve(Response.json(draft)));
  expect(screen.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue("");
  expect(h.workspace.getSnapshot().notice).toBe("");
});
