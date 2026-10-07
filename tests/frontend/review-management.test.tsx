import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ReviewGuidance,
  reviewAdvice,
  experienceReviewable,
} from "../../frontend/src/review-guidance";
import {
  RestoreButton,
  TrashForm,
} from "../../frontend/src/application-controls";
import { App } from "../../frontend/src/App";
import {
  ApplicationDetails,
  Answer,
} from "../../frontend/src/application-detail";
import { application, payload, profile } from "./fixtures";
import { harness } from "./harness";
import type { ApplicationDetail } from "../../frontend/src/contracts";

let h: ReturnType<typeof harness>;
function requestOptions(suffix: string): RequestInit {
  const call = h.fetch.mock.calls.find(([path]) => path.endsWith(suffix))!;
  return (call as unknown as [string, RequestInit])[1];
}
beforeEach(() => {
  h = harness();
});
afterEach(() => h.stop());
const gap =
  "Required professional experience is below the stated minimum: Python (approved 3 years; requires at least 5).";
function detail(
  blockers: string[] = [gap],
  score: number | undefined = 100,
): ApplicationDetail {
  return {
    row: { ...application, state: "review", evaluation: { score, blockers } },
    report: {
      can_submit: false,
      checked_at: "2026-10-07T12:00:00Z",
      evaluation: { score, blockers },
      checks: [],
    },
    profile_revision: 1,
    events: [],
  };
}
function mount(value = detail()) {
  const callbacks = {
    onTab: vi.fn(),
    editProfile: vi.fn(),
    editJob: vi.fn(),
    moveToTrash: vi.fn(),
  };
  const view = render(
    <ReviewGuidance detail={value} workspace={h.workspace} {...callbacks} />,
  );
  return { ...callbacks, view };
}

it.each([
  [gap, "facts"],
  [
    "Required production machine learning experience is not met: no professional experience",
    "facts",
  ],
  ["Required question needs an approved answer: q", "questions"],
  ["Distance or country requires location review", "location"],
  ["Documents need preparation for this candidate", "documents"],
  ["Automation is paused.", "settings"],
  ["Daily capacity exhausted", "settings"],
  ["Explicit sponsorship incompatibility.", "job"],
  ["Required professional experience needs review: unknown", "facts"],
  ["Unclassified provider issue", "history"],
])("maps %s to an explicit next step", (value, destination) => {
  expect(reviewAdvice(value).destination).toBe(destination);
  expect(experienceReviewable(value)).toBe(
    value === gap || value.startsWith("Required production"),
  );
});

it("requires a deliberate truthful decision, sends exact gaps and revision, and changes no fact", async () => {
  await h.unlock();
  const before = h.workspace.getSnapshot().profile;
  const callbacks = mount();
  expect(screen.getByText("Why this application needs review")).toBeVisible();
  expect(screen.getByText(gap)).toBeVisible();
  const approve = screen.getByRole("button", {
    name: "Approve this opportunity for the queue",
  });
  expect(approve).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Review candidate facts" }),
  );
  expect(callbacks.editProfile).toHaveBeenCalledOnce();
  fireEvent.submit(approve.closest("form")!);
  expect(
    h.fetch.mock.calls.some(([path]) => path.endsWith("review-decision")),
  ).toBe(false);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(approve);
  await waitFor(() =>
    expect(h.workspace.getSnapshot().notice).toContain(
      "Other checks still apply",
    ),
  );
  const init = requestOptions("review-decision");
  expect(JSON.parse(String(init.body))).toEqual({
    job: application.job,
    blockers: [gap],
    accept_fit: false,
    answers_remain_truthful: true,
  });
  expect(new Headers(init.headers).get("If-Match")).toBe("1");
  expect(h.workspace.getSnapshot().profile).toEqual(before);
});

it.each([
  [
    "Required question needs an approved answer: q",
    "Answer questions",
    "questions",
  ],
  ["Documents need preparation", "Review documents", "documents"],
  ["Unclassified provider issue", "Inspect activity", "history"],
])("opens the right tab for %s", (value, action, tab) => {
  const callbacks = mount(detail([value]));
  fireEvent.click(screen.getByRole("button", { name: action }));
  expect(callbacks.onTab).toHaveBeenCalledWith(tab);
  expect(
    screen.queryByRole("button", {
      name: "Approve this opportunity for the queue",
    }),
  ).toBeNull();
});

it("routes settings, job and location issues and offers removal without inventing answers", () => {
  const location = document.createElement("div");
  location.id = "location-review";
  document.body.append(location);
  const callbacks = mount(
    detail([
      "Automation is paused",
      "Explicit sponsorship incompatibility.",
      "Location needs candidate confirmation.",
    ]),
  );
  fireEvent.click(screen.getByRole("button", { name: "Open Agent settings" }));
  expect(h.workspace.getSnapshot().view).toBe("settings");
  fireEvent.click(screen.getByRole("button", { name: "Review job details" }));
  expect(callbacks.editJob).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Review location" }));
  expect(location.scrollIntoView).toHaveBeenCalled();
  location.remove();
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  expect(callbacks.moveToTrash).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Open documents" }));
  expect(callbacks.onTab).toHaveBeenCalledWith("documents");
  fireEvent.click(screen.getByRole("button", { name: "Review location" })); // absent target remains harmless
});

it("accepts the review fit band without adding experience gaps and resets acknowledgement on refresh", async () => {
  await h.unlock();
  const initial = detail([], 65);
  delete initial.profile_revision;
  const callbacks = mount(initial);
  expect(screen.getByText(/Fit is 65\/100/)).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox"));
  callbacks.view.rerender(
    <ReviewGuidance
      detail={{ ...detail([], 65), profile_revision: undefined }}
      workspace={h.workspace}
      {...callbacks}
    />,
  );
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", {
      name: "Approve this opportunity for the queue",
    }),
  );
  await waitFor(() =>
    expect(
      h.fetch.mock.calls.some(([path]) => path.endsWith("review-decision")),
    ).toBe(true),
  );
  expect(
    JSON.parse(String(requestOptions("review-decision").body)),
  ).toMatchObject({
    blockers: [],
    accept_fit: true,
  });
});

it("explains missing preparation and honours current checks, unknown scores and terminal/trash states", () => {
  const value = detail([], undefined);
  delete value.row.evaluation.score;
  delete value.report.evaluation!.score;
  const callbacks = mount(value);
  expect(
    screen.getByText(
      /Preparation or a current readiness check is still needed/,
    ),
  ).toBeVisible();
  value.report.evaluation = null;
  value.row.evaluation.blockers = [
    "Required question needs an approved answer: q",
  ];
  value.report.checks = [
    {
      code: "documents",
      label: "Integrity",
      passed: false,
      detail: "Document hash mismatch",
    },
    {
      code: "state",
      label: "State",
      passed: false,
      detail: "Duplicate aggregate",
    },
  ];
  callbacks.view.rerender(
    <ReviewGuidance
      detail={value}
      workspace={h.workspace}
      {...callbacks}
      moveToTrash={undefined}
    />,
  );
  expect(screen.getByText("Document hash mismatch")).toBeVisible();
  expect(screen.queryByText("Duplicate aggregate")).toBeNull();
  expect(screen.queryByRole("button", { name: "Move to Trash" })).toBeNull();
  callbacks.view.rerender(
    <ReviewGuidance
      detail={{ ...value, row: { ...value.row, state: "submitted" } }}
      workspace={h.workspace}
      {...callbacks}
    />,
  );
  expect(screen.queryByText("Why this application needs review")).toBeNull();
  callbacks.view.rerender(
    <ReviewGuidance
      detail={{ ...value, row: { ...value.row, trashed: true } }}
      workspace={h.workspace}
      {...callbacks}
    />,
  );
  expect(screen.queryByText("Why this application needs review")).toBeNull();
});

it("moves a submitted record reversibly with reason and restores through versioned local requests", async () => {
  await h.unlock();
  const done = vi.fn();
  const row = { ...application, state: "submitted" as const };
  const view = render(
    <TrashForm row={row} revision={1} workspace={h.workspace} done={done} />,
  );
  expect(screen.getByText(/does not withdraw/)).toBeVisible();
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Not a suitable location" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(JSON.parse(String(requestOptions("/trash").body))).toEqual({
    job: row.job,
    reason: "Not a suitable location",
  });
  expect(new Headers(requestOptions("/trash").headers).get("If-Match")).toBe(
    "1",
  );
  view.rerender(
    <RestoreButton row={{ ...row, trashed: true }} workspace={h.workspace} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Restore opportunity" }));
  await waitFor(() =>
    expect(h.workspace.getSnapshot().notice).toContain("Opportunity restored"),
  );
});

it("keeps reason and dialog open on a failed move without retrying", async () => {
  await h.unlock();
  const done = vi.fn();
  h.fetch.mockImplementation(async (path) =>
    path.endsWith("/trash")
      ? Response.json(
          { detail: "Pause the active operation first" },
          { status: 409 },
        )
      : Response.json(h.responses.get(path) ?? payload(path)),
  );
  render(
    <TrashForm
      row={application}
      revision={1}
      workspace={h.workspace}
      done={done}
    />,
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Keep my reason" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  await waitFor(() => expect(h.workspace.getSnapshot().error).toBe(true));
  expect(done).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox")).toHaveValue("Keep my reason");
  expect(
    h.fetch.mock.calls.filter(([path]) => path.endsWith("/trash")),
  ).toHaveLength(1);
});

it("handles an unevaluated opportunity and an empty optional removal reason", async () => {
  await h.unlock();
  const value = detail([], undefined);
  delete value.profile_revision;
  value.row.evaluation = {};
  value.report.evaluation = null;
  const callbacks = mount(value);
  expect(
    screen.getByText(/Preparation or a current readiness check/),
  ).toBeVisible();
  callbacks.view.unmount();
  const done = vi.fn();
  render(
    <TrashForm
      row={application}
      revision={1}
      workspace={h.workspace}
      done={done}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Move to Trash" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(JSON.parse(String(requestOptions("/trash").body)).reason).toBe("");
});

it("organises active, archive and trash with preserved links, restore and removal controls", async () => {
  const removed = {
    ...application,
    id: 3,
    trashed: true,
    job: { ...application.job, title: "Removed opportunity" },
  };
  h.responses.set("/api/applications/3", removed);
  h.responses.set("/api/applications", [
    application,
    {
      ...application,
      id: 2,
      state: "submitted",
      job: { ...application.job, title: "Sent opportunity" },
    },
    removed,
  ]);
  render(<App workspace={h.workspace} />);
  await h.unlock();
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name: "Applications" }),
  );
  expect(screen.getByRole("tab", { name: "Active (1)" })).toBeVisible();
  expect(screen.getByRole("tab", { name: "Archive (1)" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "Trash (1)" }));
  const panel = screen.getByRole("tabpanel", { name: "Trash (1)" });
  expect(within(panel).getByText("Removed opportunity")).toBeVisible();
  expect(
    within(panel).getByRole("link", { name: /Full record/ }),
  ).toHaveAttribute("href", "#/applications/3");
  expect(
    within(panel).getByRole("button", { name: /Restore Removed/ }),
  ).toBeVisible();
  fireEvent.click(
    within(panel).getByRole("button", { name: /Restore Removed/ }),
  );
  await waitFor(() => expect(h.workspace.getSnapshot().pending).toBe(false));
  expect(h.fetch.mock.calls.some(([path]) => path.endsWith("/3/restore"))).toBe(
    true,
  );
  fireEvent.click(screen.getByRole("tab", { name: "Active (1)" }));
  fireEvent.click(
    screen.getByRole("button", {
      name: /Move Backend Engineer at Example Employer to Trash/,
    }),
  );
  expect(
    screen.getByRole("dialog", { name: "Move opportunity to Trash" }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Close dialogue" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("explains an empty Trash and completes removal from the queue modal", async () => {
  render(<App workspace={h.workspace} />);
  await h.unlock();
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name: "Applications" }),
  );
  fireEvent.click(screen.getByRole("tab", { name: "Trash (0)" }));
  expect(screen.getByText(/Trash is empty/)).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "Active (1)" }));
  fireEvent.click(
    screen.getByRole("button", {
      name: /Move Backend Engineer at Example Employer to Trash/,
    }),
  );
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Move to Trash",
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(h.fetch.mock.calls.some(([path]) => path.endsWith("/1/trash"))).toBe(
    true,
  );
});

it("opens corrective profile editing from a review and rechecks that opportunity after saving", async () => {
  h.responses.set("/api/applications/1", detail().row);
  h.responses.set("/api/applications/1/preflight", detail().report);
  render(<App workspace={h.workspace} />);
  await h.unlock();
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name: "Applications" }),
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: /Open Backend Engineer at Example Employer/,
    }),
  );
  await screen.findByText("Why this application needs review");
  fireEvent.click(
    screen.getByRole("button", { name: "Review candidate facts" }),
  );
  const dialog = screen.getByRole("dialog", { name: "Edit candidate profile" });
  const priorReads = h.fetch.mock.calls.filter(
    ([path]) => path === "/api/applications/1/preflight",
  ).length;
  fireEvent.submit(
    within(dialog)
      .getByRole("button", { name: "Save candidate profile" })
      .closest("form")!,
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() =>
    expect(
      h.fetch.mock.calls.filter(
        ([path]) => path === "/api/applications/1/preflight",
      ).length,
    ).toBeGreaterThan(priorReads),
  );
  fireEvent.click(
    screen.getAllByRole("button", {
      name: "Move to Trash",
    })[0],
  );
  expect(
    screen.getByRole("dialog", { name: "Move opportunity to Trash" }),
  ).toBeVisible();
});

it("uses standalone review actions and preserves a removed record without writable answers", async () => {
  await h.unlock();
  const edit = vi.fn();
  const initial = detail([
    "Required professional experience needs review: unknown",
    "Explicit sponsorship incompatibility.",
  ]);
  const view = render(
    <ApplicationDetails
      detail={initial}
      profile={profile}
      workspace={h.workspace}
      edit={edit}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Review candidate facts" }),
  );
  expect(h.workspace.getSnapshot().view).toBe("profile");
  fireEvent.click(screen.getByRole("button", { name: "Review job details" }));
  expect(edit).toHaveBeenCalledWith(initial.row);
  view.rerender(
    <ApplicationDetails
      detail={{
        ...initial,
        row: {
          ...initial.row,
          trashed: true,
          trash: { moved_at: "2026-10-07T12:00:00Z", reason: "Not suitable" },
        },
      }}
      profile={profile}
      workspace={h.workspace}
      edit={edit}
    />,
  );
  expect(screen.getByText("Reason: Not suitable")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Run authorised submission" }),
  ).toBeNull();
  view.rerender(
    <ApplicationDetails
      detail={{ ...initial, row: { ...initial.row, trashed: true } }}
      profile={profile}
      workspace={h.workspace}
      edit={edit}
    />,
  );
  expect(screen.queryByText("Reason: Not suitable")).toBeNull();
  view.unmount();
  const question = {
    id: "q",
    label: "Years of Python?",
    answer_key: "",
    kind: "number" as const,
    required: true,
    sensitive: false,
    choices: [],
  };
  render(
    <Answer
      question={question}
      profile={profile}
      workspace={h.workspace}
      id={1}
      disabled
    />,
  );
  const save = screen.getByRole("button", { name: "Approve answer" });
  expect(save).toBeDisabled();
  fireEvent.submit(save.closest("form")!);
  expect(h.fetch.mock.calls.some(([path]) => path.endsWith("/answer"))).toBe(
    false,
  );
});
