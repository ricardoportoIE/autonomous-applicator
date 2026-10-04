import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Answer } from "../../frontend/src/application-detail";
import type { AnswerIdea, Question } from "../../frontend/src/contracts";
import { Workspace } from "../../frontend/src/workspace";
import { payload, profile } from "./fixtures";

const question: Question = {
  id: "python_example",
  label: "Describe your Python experience",
  answer_key: "",
  choices: [],
  required: true,
  sensitive: false,
};
const idea: AnswerIdea = {
  draft: "I built an independent Python API.",
  evidence_ids: ["python"],
  fact_keys: [],
  review_notes: "Check the relevance of this example.",
  needs_clarification: false,
  model: "gpt-6.1-sol",
  profile_revision: 1,
};
let workspace: Workspace;
let finish: (response: Response) => void;
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(async () => {
  workspace = new Workspace();
  vi.stubGlobal("scrollTo", vi.fn());
  fetcher = vi.fn((path: string) =>
    path.endsWith("/suggest")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : Promise.resolve(Response.json(payload(path))),
  );
  vi.stubGlobal("fetch", fetcher);
  await workspace.unlock("fictional-token");
});
afterEach(() => {
  workspace.lock();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const requests = () =>
  fetcher.mock.calls.filter(([path]) => String(path).endsWith("/suggest"));
const suggest = () =>
  screen.getByRole("button", { name: "Suggest with GPT-6.1 Sol" });
const answer = () => screen.getByRole("textbox", { name: question.label });
it("shows manual application approval ahead of an automatic candidate-fact answer", () => {
  const automatic = {
    answer_key: "question:describe your python experience",
    question,
    answer: "Automatic fact answer",
    source: "candidate",
    evidence_ids: [],
    revision: 1,
  };
  const view = render(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
      automatic={automatic}
    />,
  );
  expect(answer()).toHaveValue("Automatic fact answer");
  expect(screen.getByText(/Answered automatically from/)).toHaveTextContent(
    "approved candidate facts",
  );
  view.rerender(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
      automatic={automatic}
      approvedAnswer="My application answer"
    />,
  );
  expect(answer()).toHaveValue("My application answer");
  expect(screen.queryByText(/Answered automatically from/)).toBeNull();
});
const resolve = async (result = idea) => {
  await act(async () => {
    finish(Response.json(result));
  });
};

it("keeps a generated idea separate from the user's text until explicitly used and approved", async () => {
  const user = userEvent.setup();
  const mutate = vi.spyOn(workspace, "mutate").mockResolvedValue();
  render(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
    />,
  );
  await user.type(answer(), "My current draft");
  await user.click(suggest());
  expect(screen.getByRole("status")).toHaveTextContent("Generating an idea");
  const loading = screen.getByRole("button", {
    name: "Generating answer idea…",
  });
  expect(loading).toBeDisabled();
  fireEvent.click(loading);
  expect(requests()).toHaveLength(1);
  expect(requests()[0][1]).toMatchObject({
    method: "POST",
    headers: { "If-Match": "1" },
  });
  await resolve();
  expect(answer()).toHaveValue("My current draft");
  expect(
    screen.getByRole("region", { name: /AI answer idea/ }),
  ).toHaveTextContent("Independent API project");
  expect(mutate).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", { name: "Use as editable draft" }),
  );
  expect(answer()).toHaveValue(idea.draft);
  expect(mutate).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Approve answer" }));
  expect(mutate).toHaveBeenCalledWith(
    "/applications/1/questions/python_example/answer",
    "PUT",
    { answer: idea.draft },
    "Answer saved for this application. Readiness rechecked.",
    1,
    1,
  );
});

it("does not apply an unapproved binary suggestion and lets the candidate decide", async () => {
  const permission =
    "Stamp 2 permits part-time work only; full-time work requires sponsorship.";
  render(
    <Answer
      question={{ ...question, choices: ["Yes", "No"] }}
      profile={{ ...profile, answers: { work_permission_details: permission } }}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  await resolve({
    ...idea,
    draft: "Yes",
    needs_clarification: true,
    fact_keys: [
      "answer:work_permission_details",
      "sponsorship_required",
      "location",
    ],
  });
  expect(
    screen.getByText("work permission details: " + permission),
  ).toBeVisible();
  expect(screen.getByText("Employer sponsorship: required")).toBeVisible();
  expect(screen.getByText("Location: Dublin, Ireland")).toBeVisible();
  expect(screen.getByRole("combobox")).toHaveValue("");
  expect(
    screen.getByRole("button", { name: "Use as editable draft" }),
  ).toBeDisabled();
  expect(
    screen.getByText(
      "Review the explanation and choose the exact answer yourself.",
    ),
  ).toBeVisible();
  await userEvent.selectOptions(screen.getByRole("combobox"), "No");
  expect(screen.getByRole("combobox")).toHaveValue("No");
});

it("displays a provider failure without changing an approved answer or retrying", async () => {
  render(
    <Answer
      question={question}
      profile={{
        ...profile,
        answers: {
          "question:describe your python experience": "Approved example",
        },
      }}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  await act(async () => {
    finish(
      Response.json(
        { detail: "AI unavailable; no answer changed." },
        { status: 502 },
      ),
    );
  });
  expect(workspace.getSnapshot().notice).toBe(
    "AI unavailable; no answer changed.",
  );
  expect(workspace.getSnapshot().error).toBe(true);
  expect(answer()).toHaveValue("Approved example");
  expect(
    screen.queryByRole("region", { name: /AI answer idea/ }),
  ).not.toBeInTheDocument();
  expect(requests()).toHaveLength(1);
});

it("does not send sensitive questions or unconfirmed profiles to the model", () => {
  const view = render(
    <Answer
      question={{ ...question, sensitive: true }}
      profile={profile}
      workspace={workspace}
      id={1}
    />,
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.getByText(/requires manual handling/)).toBeVisible();
  view.rerender(
    <Answer
      question={question}
      profile={{ ...profile, confirmed: false }}
      workspace={workspace}
      id={1}
    />,
  );
  expect(suggest()).toBeDisabled();
  expect(requests()).toHaveLength(0);
});

it("discards an old result when the question or candidate changes during generation", async () => {
  const view = render(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  view.rerender(
    <Answer
      question={{ ...question, label: "Changed question" }}
      profile={{ ...profile, location: "London" }}
      workspace={workspace}
      id={2}
    />,
  );
  await resolve();
  expect(
    screen.queryByRole("region", { name: /AI answer idea/ }),
  ).not.toBeInTheDocument();
  expect(workspace.getSnapshot().notice).toBe("Local workspace unlocked.");
});

it("rejects a late response after locking and unlocking the same token", async () => {
  const view = render(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  view.unmount();
  await act(async () => {
    workspace.lock();
    await workspace.unlock("fictional-token");
  });
  await resolve();
  expect(workspace.getSnapshot().notice).toBe("Local workspace unlocked.");
  expect(workspace.getSnapshot().error).toBe(false);
  expect(requests()).toHaveLength(1);
});

it("does not display a draft for a different profile revision", async () => {
  render(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  await resolve({ ...idea, profile_revision: 2 });
  expect(
    screen.queryByRole("region", { name: /AI answer idea/ }),
  ).not.toBeInTheDocument();
  expect(workspace.getSnapshot().profile?.answers).toEqual({});
});

it("renders model text as text and makes a clarification with no draft unusable", async () => {
  render(
    <Answer
      question={question}
      profile={profile}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  await resolve({
    ...idea,
    draft: "<img src=x onerror=alert(1)>",
    review_notes: "<script>alert(1)</script>",
  });
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
  expect(document.querySelector("img,script")).toBeNull();
  await userEvent.click(suggest());
  await resolve({ ...idea, draft: "", needs_clarification: true });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use as editable draft" }),
    ).toBeDisabled(),
  );
});

it("requires a candidate before approval and accepts optional exact-choice drafts with cited facts", async () => {
  const optional = { ...question, required: false, choices: ["Yes", "No"] };
  const view = render(
    <Answer question={optional} profile={null} workspace={workspace} id={1} />,
  );
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "No" } });
  fireEvent.submit(
    screen.getByRole("button", { name: "Approve answer" }).closest("form")!,
  );
  await waitFor(() =>
    expect(workspace.getSnapshot().notice).toBe(
      "Configure the candidate profile first.",
    ),
  );
  view.rerender(
    <Answer
      question={optional}
      profile={{
        ...profile,
        sponsorship_required: false,
        answers: { "question:used_python": "Yes" },
      }}
      workspace={workspace}
      id={1}
    />,
  );
  await userEvent.click(suggest());
  await resolve({
    ...idea,
    draft: "Yes",
    evidence_ids: ["not-recorded"],
    fact_keys: [
      "sponsorship_required",
      "answer:question:used_python",
      "answer:missing",
    ],
  });
  expect(screen.getByText("Employer sponsorship: not required")).toBeVisible();
  expect(screen.getByText("used python: Yes")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Use as editable draft" }),
  );
  expect(screen.getByRole("combobox")).toHaveValue("Yes");
});
