import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApplicationDetails } from "../../frontend/src/application-detail";
import type { ApplicationDetail } from "../../frontend/src/contracts";
import { application, profile } from "./fixtures";
import { harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(async () => {
  h = harness();
  await h.unlock();
});
afterEach(() => h.stop());
function show(overrides: Partial<ApplicationDetail> = {}) {
  const detail: ApplicationDetail = {
    row: structuredClone(application),
    profile_revision: 1,
    report: {
      checked_at: "2026-10-04T10:00:00Z",
      can_submit: true,
      checks: [
        {
          code: "ok",
          label: "Documents intact",
          passed: true,
          detail: "Hashes match",
        },
        {
          code: "scope",
          label: "Authorisation",
          passed: false,
          detail: "Enable authorisation",
        },
      ],
    },
    events: [
      {
        id: 1,
        kind: "documents_prepared",
        detail: "Prepared safely",
        created: "2026-10-04T10:00:00Z",
      },
    ],
    ...overrides,
  };
  const edit = vi.fn();
  const view = render(
    <ApplicationDetails
      detail={detail}
      workspace={h.workspace}
      profile={profile}
      edit={edit}
    />,
  );
  return { detail, edit, view };
}

it("rechecks readiness, edits details, prepares by both routes and submits only once", async () => {
  const { edit } = show();
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  const read = vi.spyOn(h.workspace, "openDetail").mockResolvedValue();
  fireEvent.click(screen.getByRole("button", { name: "Recheck readiness" }));
  await waitFor(() => expect(read).toHaveBeenCalledWith(1));
  fireEvent.click(screen.getByRole("button", { name: "Edit job details" }));
  expect(edit).toHaveBeenCalledWith(application);
  for (const [label, body] of [
    ["Prepare documents", {}],
    ["Select evidence with GPT-6.1 Sol", { use_ai: true }],
  ] as const) {
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(h.workspace.getSnapshot().pending).toBe(false));
    expect(mutate).toHaveBeenLastCalledWith(
      "/applications/1/prepare",
      "POST",
      body,
      expect.any(String),
      1,
    );
  }
  fireEvent.click(
    screen.getByRole("button", { name: "Run authorised submission" }),
  );
  await waitFor(() =>
    expect(mutate).toHaveBeenLastCalledWith(
      "/applications/1/submit",
      "POST",
      undefined,
      "Provider receipt recorded.",
      1,
    ),
  );
  const download = vi.spyOn(h.workspace, "download").mockResolvedValue();
  fireEvent.click(
    screen.getByRole("button", { name: "Download Alex_Example_CV.pdf" }),
  );
  await waitFor(() =>
    expect(download).toHaveBeenCalledWith(1, "cv_pdf", "Alex_Example_CV.pdf"),
  );
  const close = vi.spyOn(h.workspace, "closeDetail");
  fireEvent.click(
    screen.getByRole("button", { name: "Close application details" }),
  );
  expect(close).toHaveBeenCalledOnce();
});

it("preserves manual evidence selection and downloads in the document tab", async () => {
  show();
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  const download = vi.spyOn(h.workspace, "download").mockResolvedValue();
  fireEvent.click(screen.getByRole("tab", { name: "Documents (1)" }));
  fireEvent.click(screen.getByText("Choose approved evidence manually"));
  const checked = screen.getByLabelText("Independent API project");
  fireEvent.click(checked);
  expect(
    screen.getByRole("button", { name: "Prepare with selected evidence" }),
  ).toBeDisabled();
  fireEvent.click(checked);
  fireEvent.click(
    screen.getByRole("button", { name: "Prepare with selected evidence" }),
  );
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/applications/1/prepare",
      "POST",
      { evidence_ids: ["python"] },
      expect.any(String),
      1,
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download Alex_Example_CV.pdf" }),
  );
  await waitFor(() => expect(download).toHaveBeenCalledOnce());
});

it.each(["manual", "local", undefined])(
  "explains provenance and absent evidence faithfully: %s",
  (method) => {
    const row = structuredClone(application);
    row.manifest = method ? { generation: { method }, revision: 2 } : {};
    row.evaluation = {};
    row.job.requirements = [];
    row.job.cover_letter_required = true;
    show({
      row,
      report: {
        can_submit: false,
        checked_at: "2026-10-04T10:00:00Z",
        checks: [],
      },
    });
    expect(
      screen.getByRole("button", { name: "Run authorised submission" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        method === "manual"
          ? "Evidence selected manually"
          : method
            ? "Evidence selected using local rules"
            : /Preparation origin is unavailable/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Documents (0)" }));
    expect(screen.getByText(/No current documents/)).toBeVisible();
  },
);

it.each([1, undefined])(
  "accepts a reviewed location using the displayed candidate revision: %s",
  async (revision) => {
    show({
      profile_revision: revision,
      report: {
        can_submit: false,
        checked_at: "2026-10-04T10:00:00Z",
        checks: [],
        evaluation: { blockers: ["Location needs candidate review"] },
      },
    });
    fireEvent.click(
      screen.getByLabelText("I accept this opportunity's location"),
    );
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Accept location for this opportunity" })
        .closest("form")!,
    );
    await waitFor(() =>
      expect(h.workspace.getSnapshot().notice).toContain("Location accepted"),
    );
    expect(h.fetch).toHaveBeenCalledWith(
      "/api/applications/1/location-review",
      expect.objectContaining({
        body: JSON.stringify({ location: application.job.location }),
        headers: expect.objectContaining({ "If-Match": "1" }),
      }),
    );
  },
);

it.each([1, undefined])(
  "reconciles an uncertain send only through explicit candidate confirmation: %s",
  async (revision) => {
    show({
      profile_revision: revision,
      row: { ...application, state: "uncertain" },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Activity & outcome" }));
    expect(
      screen.getByRole("button", { name: "Prepare documents", hidden: true }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByLabelText(
        "I checked the provider and this application was not sent",
      ),
    );
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Confirm application was not sent" })
        .closest("form")!,
    );
    await waitFor(() =>
      expect(h.workspace.getSnapshot().notice).toContain(
        "Confirmed as not sent",
      ),
    );
    expect(h.fetch).toHaveBeenCalledWith(
      "/api/applications/1/not-sent",
      expect.objectContaining({
        body: '{"checked":true}',
        headers: expect.objectContaining({ "If-Match": "1" }),
      }),
    );
  },
);

it("records a manual receipt and an outcome through separate explicit actions", async () => {
  const { detail, view } = show();
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  fireEvent.click(screen.getByRole("tab", { name: "Activity & outcome" }));
  fireEvent.change(
    screen.getByLabelText(
      "Manual submission receipt or confirmation reference",
    ),
    { target: { value: "example:receipt" } },
  );
  fireEvent.submit(
    screen
      .getByRole("button", { name: "Record confirmed manual submission" })
      .closest("form")!,
  );
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/applications/1/receipt",
      "POST",
      { receipt: "example:receipt" },
      expect.any(String),
      1,
    ),
  );
  view.rerender(
    <ApplicationDetails
      detail={{
        ...detail,
        row: {
          ...application,
          state: "submitted",
          receipt: "example:receipt",
          outcome: "offer",
        },
      }}
      workspace={h.workspace}
      profile={profile}
      edit={vi.fn()}
    />,
  );
  expect(screen.getByLabelText("Record outcome")).toHaveValue("offer");
  fireEvent.change(screen.getByLabelText("Record outcome"), {
    target: { value: "interview" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save outcome" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/applications/1/outcome",
      "POST",
      { outcome: "interview" },
      "Outcome saved.",
      1,
    ),
  );
  expect(screen.getByText("Recorded receipt: example:receipt")).toBeVisible();
});

it("includes newly observed routine questions without duplicating known questions", () => {
  const question = {
    id: "python",
    label: "Used Python?",
    answer_key: "question:used python?",
    type: "text",
    required: true,
    choices: [],
    sensitive: false,
  };
  show({
    row: {
      ...application,
      job: { ...application.job, questions: [question] },
      approved_answers: { [question.answer_key]: "Approved for this vacancy" },
      routine_answers: [
        {
          answer_key: question.answer_key,
          question,
          answer: "Yes",
          source: "candidate",
          revision: 1,
          evidence_ids: [],
        },
        {
          answer_key: "question:location?",
          question: {
            ...question,
            id: "location",
            label: "Location?",
            answer_key: "",
          },
          answer: "Dublin",
          source: "gpt-6.1-sol",
          revision: 1,
          evidence_ids: ["python"],
        },
      ],
    },
  });
  fireEvent.click(screen.getByRole("tab", { name: "Questions (2)" }));
  expect(screen.getAllByLabelText("Used Python?")).toHaveLength(1);
  expect(screen.getByLabelText("Used Python?")).toHaveValue(
    "Approved for this vacancy",
  );
  expect(screen.getByLabelText("Location?")).toHaveValue("Dublin");
});

it("renders detailed fit explanations and missing optional arrays", () => {
  const row = {
    ...application,
    evaluation: {
      score: 75,
      reasons: ["Technical evidence matched"],
      blockers: ["Location needs review"],
    },
  };
  show({ row });
  expect(screen.getByText("Technical evidence matched")).toBeVisible();
  expect(screen.getByText("Location needs review")).toBeVisible();
});

it("renders an evaluated opportunity with no recorded reasons or blockers", () => {
  show({ row: { ...application, evaluation: { score: 75 } } });
  expect(screen.getByText("Fit: 75/100 · ready")).toBeVisible();
});
