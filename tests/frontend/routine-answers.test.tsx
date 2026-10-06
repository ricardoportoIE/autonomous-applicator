import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../frontend/src/App";
import { RoutineAnswers } from "../../frontend/src/routine-answers";
import type { QuestionInstruction } from "../../frontend/src/contracts";
import { payload } from "./fixtures";
import { deferred, harness } from "./harness";

let h: ReturnType<typeof harness>;
const entry: QuestionInstruction = {
  id: "python",
  question: {
    id: "years",
    answer_key: "",
    label: "How many years of Python experience?",
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
beforeEach(() => {
  h = harness();
  h.responses.set("/api/question-instructions", [entry]);
});
afterEach(() => h.stop());

async function library(rows: QuestionInstruction[] = [entry]) {
  h.responses.set("/api/question-instructions", rows);
  await h.unlock();
  render(<RoutineAnswers workspace={h.workspace} />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Refresh questions" }),
    ).toBeEnabled(),
  );
}
function edit(name = "Add instruction", index = 0) {
  fireEvent.click(screen.getAllByRole("button", { name })[index]);
  return within(screen.getByRole("dialog"));
}

it("organises Settings into General settings and Routine answers without removing controls", async () => {
  render(<App workspace={h.workspace} />);
  await h.unlock();
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name: "Agent settings" }),
  );
  expect(screen.getByRole("tab", { name: "General settings" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.getByLabelText("Daily sent-application limit"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Routine answers" }));
  await screen.findByText(entry.question.label);
  expect(screen.getByRole("tab", { name: "Routine answers" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  fireEvent.click(screen.getByRole("tab", { name: "General settings" }));
  expect(screen.getByLabelText("Daily sent-application limit")).toBeVisible();
  expect(screen.queryByText(entry.question.label)).toBeNull();
  await act(() => h.workspace.lock());
  expect(screen.queryByText(entry.question.label)).toBeNull();
});

it("captures the prompt in a modal and saves a versioned instruction", async () => {
  await library([
    entry,
    {
      ...entry,
      id: "other",
      question: { ...entry.question, label: "Another question" },
    },
  ]);
  const modal = edit();
  expect(
    modal.getByRole("button", { name: "Save instruction" }),
  ).toBeDisabled();
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: " I have 3 years of professional Python experience. " },
  });
  h.responses.set("/api/question-instructions/python", {
    ...entry,
    prompt: "I have 3 years of professional Python experience.",
    enabled: true,
    version: 2,
  });
  fireEvent.submit(
    modal.getByRole("button", { name: "Save instruction" }).closest("form")!,
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(
    screen.getByText("Enabled", { selector: ".badge" }),
  ).toBeInTheDocument();
  const call = h.fetch.mock.calls.find(
    (args) => args[0] === "/api/question-instructions/python",
  )!;
  const options = (call as unknown as [string, RequestInit])[1];
  expect(options.method).toBe("PUT");
  expect(JSON.parse(String(options.body))).toEqual({
    prompt: "I have 3 years of professional Python experience.",
    enabled: true,
    version: 1,
  });
  expect(h.workspace.getSnapshot().notice).toContain("re-preparation");
  expect(screen.getByText("Another question")).toBeInTheDocument();
});

it("keeps edits open and displays the API error without claiming a successful save", async () => {
  await library();
  const modal = edit();
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: "Use the confirmed facts." },
  });
  h.fetch.mockImplementation(async (path: string) =>
    path === "/api/question-instructions/python"
      ? Response.json(
          { detail: "Instruction changed. Refresh before saving." },
          { status: 409 },
        )
      : Response.json(payload(path)),
  );
  fireEvent.submit(
    modal.getByRole("button", { name: "Save instruction" }).closest("form")!,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Refresh before saving",
  );
  expect(screen.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
    "Use the confirmed facts.",
  );
  expect(
    screen.getByRole("button", { name: "Save instruction" }),
  ).toBeEnabled();
});

it("shows a saving status and blocks duplicate saves", async () => {
  await library();
  const modal = edit();
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: "Use my confirmed facts" },
  });
  const pending = deferred<Response>();
  h.fetch.mockImplementation(async (path: string) =>
    path === "/api/question-instructions/python"
      ? pending.promise
      : Response.json(payload(path)),
  );
  fireEvent.submit(
    modal.getByRole("button", { name: "Save instruction" }).closest("form")!,
  );
  expect(
    await screen.findByRole("button", { name: "Saving instruction…" }),
  ).toBeDisabled();
  await act(async () =>
    pending.resolve(
      Response.json({
        ...entry,
        prompt: "Use my confirmed facts",
        enabled: true,
        version: 2,
      }),
    ),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("filters all, enabled and awaiting instructions, and searches prompts or labels", async () => {
  const enabled = {
    ...entry,
    id: "enabled",
    question: {
      ...entry.question,
      label: "Python knowledge",
      control_type: undefined,
    },
    prompt: "Mention independent projects",
    enabled: true,
  };
  const disabled = {
    ...entry,
    id: "disabled",
    question: {
      ...entry.question,
      label: "Teamwork",
      control_type: undefined,
      choices: ["Yes", "No"],
    },
    prompt: "Be concise",
    enabled: false,
  };
  await library([entry, enabled, disabled]);
  expect(
    screen.getByText("Questions: 3 · Enabled instructions: 1"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Choice field", { exact: false }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Field not yet inspected", { exact: false }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Disabled", { selector: ".badge" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Instruction status"), {
    target: { value: "enabled" },
  });
  expect(screen.getByText("Python knowledge")).toBeInTheDocument();
  expect(screen.queryByText("Teamwork")).toBeNull();
  fireEvent.change(screen.getByLabelText("Search questions"), {
    target: { value: "PROJECTS" },
  });
  expect(screen.getByText("Python knowledge")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Search questions"), {
    target: { value: "missing" },
  });
  expect(
    screen.getByText("No questions match these filters."),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Search questions"), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText("Instruction status"), {
    target: { value: "new" },
  });
  expect(screen.getByText(entry.question.label)).toBeInTheDocument();
  expect(screen.queryByText("Python knowledge")).toBeNull();
});

it("edits and disables an existing instruction without losing its text", async () => {
  const saved = {
    ...entry,
    enabled: true,
    prompt: "Use my confirmed experience.",
    version: 3,
  };
  await library([saved]);
  const modal = edit("Edit instruction");
  expect(modal.getByLabelText("Instruction for GPT-6.1 Sol")).toHaveValue(
    saved.prompt,
  );
  expect(
    modal.getByLabelText("Use this instruction automatically"),
  ).toBeChecked();
  fireEvent.click(modal.getByLabelText("Use this instruction automatically"));
  h.responses.set("/api/question-instructions/python", {
    ...saved,
    enabled: false,
    version: 4,
  });
  fireEvent.submit(
    modal.getByRole("button", { name: "Save instruction" }).closest("form")!,
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(
    screen.getByText("Disabled", { selector: ".badge" }),
  ).toBeInTheDocument();
});

it("allows an instruction to be cleared while disabled and supports cancellation", async () => {
  await library([{ ...entry, prompt: "Previous instruction" }]);
  let modal = edit("Edit instruction");
  expect(
    modal.getByLabelText("Use this instruction automatically"),
  ).not.toBeChecked();
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: "" },
  });
  expect(modal.getByRole("button", { name: "Save instruction" })).toBeEnabled();
  fireEvent.click(modal.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  modal = edit("Edit instruction");
  fireEvent.click(modal.getByRole("button", { name: "Close dialogue" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    h.fetch.mock.calls.some(
      (call) => call[0] === "/api/question-instructions/python",
    ),
  ).toBe(false);
});

it("displays every observed choice and leaves sensitive questions under manual handling", async () => {
  await library([
    {
      ...entry,
      question: { ...entry.question, sensitive: true, choices: ["Yes", "No"] },
    },
  ]);
  const modal = edit();
  expect(modal.getByText("Observed answer options (2)")).toBeInTheDocument();
  expect(
    modal.getAllByRole("listitem").map((item) => item.textContent),
  ).toEqual(["Yes", "No"]);
  expect(
    modal.getByLabelText("Use this instruction automatically"),
  ).toBeDisabled();
  expect(
    modal.getByLabelText("Use this instruction automatically"),
  ).not.toBeChecked();
  expect(
    modal.getByText("Sensitive questions require manual handling."),
  ).toBeInTheDocument();
  fireEvent.change(modal.getByLabelText("Instruction for GPT-6.1 Sol"), {
    target: { value: "Handle manually" },
  });
  expect(modal.getByRole("button", { name: "Save instruction" })).toBeEnabled();
});

it("shows an empty catalogue and refreshes newly discovered questions", async () => {
  await library([]);
  expect(
    screen.getByText(
      "Questions will appear when opportunities and application forms are inspected.",
    ),
  ).toBeInTheDocument();
  h.responses.set("/api/question-instructions", [entry]);
  fireEvent.click(screen.getByRole("button", { name: "Refresh questions" }));
  await screen.findByText(entry.question.label);
});

it("reports load errors and successfully retries a refresh", async () => {
  await h.unlock();
  h.fetch.mockImplementation(async (path: string) =>
    path === "/api/question-instructions"
      ? Response.json({ detail: "Unavailable" }, { status: 500 })
      : Response.json(payload(path)),
  );
  render(<RoutineAnswers workspace={h.workspace} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Refresh to try again",
  );
  h.fetch.mockImplementation(async (path: string) =>
    Response.json(
      path === "/api/question-instructions" ? [entry] : payload(path),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh questions" }));
  await screen.findByText(entry.question.label);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("polls the library and ignores an older response which arrives after a newer one", async () => {
  await h.unlock();
  vi.useFakeTimers();
  const old = deferred<Response>();
  let calls = 0;
  h.fetch.mockImplementation(async (path: string) =>
    path === "/api/question-instructions"
      ? ++calls === 1
        ? old.promise
        : Response.json([entry])
      : Response.json(payload(path)),
  );
  const view = render(<RoutineAnswers workspace={h.workspace} />);
  expect(
    screen.getByRole("button", { name: "Loading questions…" }),
  ).toBeDisabled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(screen.getByText(entry.question.label)).toBeInTheDocument();
  await act(async () => old.resolve(Response.json([])));
  expect(screen.getByText(entry.question.label)).toBeInTheDocument();
  view.unmount();
  const before = calls;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30000);
  });
  expect(calls).toBe(before);
});

it.each([200, 500])(
  "ignores late catalogue responses after unmount (HTTP %s)",
  async (status) => {
    await h.unlock();
    const pending = deferred<Response>();
    h.fetch.mockImplementation(async (path: string) =>
      path === "/api/question-instructions"
        ? pending.promise
        : Response.json(payload(path)),
    );
    const view = render(<RoutineAnswers workspace={h.workspace} />);
    view.unmount();
    await act(async () =>
      pending.resolve(
        Response.json(status === 200 ? [entry] : { detail: "Late error" }, {
          status,
        }),
      ),
    );
    expect(screen.queryByText(entry.question.label)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  },
);

it("renders provider question text as text rather than executing HTML", async () => {
  await library([
    {
      ...entry,
      question: {
        ...entry.question,
        label: '<img src=x onerror="window.hacked=true">',
      },
    },
  ]);
  expect(
    screen.getByText('<img src=x onerror="window.hacked=true">'),
  ).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});
