import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApplicationRecordPage } from "../../frontend/src/application-record";
import type {
  ApplicationRecord,
  SubmissionAttempt,
} from "../../frontend/src/contracts";
import { application, profile } from "./fixtures";
import { harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(async () => {
  h = harness();
  await h.unlock();
});
afterEach(() => h.stop());
const attempt = (
  id: number,
  status: SubmissionAttempt["status"],
): SubmissionAttempt => ({
  id,
  status,
  started: "2026-10-04T10:00:00Z",
  receipt: null,
  sent_at: null,
  confirmed_at: null,
  snapshot: null,
  fields: null,
  confirmation: null,
});
const record = (attempts: SubmissionAttempt[] = []): ApplicationRecord => ({
  application: {
    ...application,
    evaluation: {},
    job: {
      ...application.job,
      requirements: [],
      cover_letter_required: true,
      questions: [
        {
          id: "known",
          label: "Used Python?",
          answer_key: "question:python?",
          required: true,
          choices: ["Yes", "No"],
          sensitive: false,
        },
        {
          id: "optional",
          label: "Comment",
          answer_key: "question:comment",
          required: false,
          choices: [],
          sensitive: false,
        },
      ],
    },
    receipt: "manual:confirmed",
  },
  dates: { imported_at: null, last_activity_at: null, event_count: 0 },
  attempts,
  events: [],
  next_event: 1,
});

it("renders legacy records and multiple sending states without claiming missing proof", () => {
  const data = record([attempt(1, "released"), attempt(2, "held")]);
  render(<ApplicationRecordPage record={data} workspace={h.workspace} />);
  expect(
    screen.getByText("Stopped before sending or confirmed as not sent"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Historical attempt/)).toBeInTheDocument();
  expect(
    screen.getByText("Application receipt: manual:confirmed"),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Submission attempt"), {
    target: { value: "2" },
  });
  expect(
    screen.getByText("Pending or uncertain; reconcile before retrying"),
  ).toBeInTheDocument();
});
it("renders an untouched opportunity without inventing attempt dates or evidence", () => {
  render(<ApplicationRecordPage record={record()} workspace={h.workspace} />);
  expect(
    screen.getByText("No submission attempt has been started."),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Submission attempt")).toBeNull();
});

it("retains fit explanations and gaps in the complete opportunity record", () => {
  const data = record();
  data.application.evaluation = {
    score: 75,
    reasons: ["Verified Python"],
    blockers: ["Location review"],
    matched: ["Python"],
    gaps: ["Kubernetes"],
  };
  render(<ApplicationRecordPage record={data} workspace={h.workspace} />);
  expect(screen.getByText("Verified Python")).toBeInTheDocument();
  expect(screen.getByText("Location review")).toBeInTheDocument();
  expect(screen.getByText("Gaps: Kubernetes")).toBeInTheDocument();
});
it.each(["manual", undefined])(
  "shows sparse snapshots and capture failures faithfully: %s",
  (method) => {
    const item = attempt(1, "confirmed");
    item.confirmation = {
      url: application.job.url,
      capture_error: "TimeoutError",
    };
    item.snapshot = {
      job: application.job,
      profile_revision: 1,
      candidate: {
        name: profile.name,
        email: profile.email,
        phone: "",
        location: profile.location,
        summary: profile.summary,
        links: [],
        sponsorship_required: false,
      },
      manifest: method ? { generation: { method }, evidence_ids: [] } : {},
      provided_answers: [],
    };
    item.fields = [
      {
        label: "Consent",
        type: "checkbox",
        value: "",
        checked: true,
        observed_at: "2026-10-04T10:00:00Z",
      },
      {
        label: "Optional comment",
        type: "text",
        value: "",
        checked: null,
        observed_at: "2026-10-04T10:00:00Z",
      },
    ];
    render(
      <ApplicationRecordPage record={record([item])} workspace={h.workspace} />,
    );
    expect(screen.getByText("Selected")).toBeInTheDocument();
    expect(screen.getByText("Empty")).toBeInTheDocument();
    expect(screen.getByText(/Capture issue: TimeoutError/)).toBeInTheDocument();
  },
);
it("shows no observations if a snapshot predates form capture", () => {
  const item = attempt(1, "held");
  item.snapshot = {
    job: application.job,
    profile_revision: 1,
    candidate: {
      name: profile.name,
      email: profile.email,
      phone: "",
      location: profile.location,
      summary: profile.summary,
      links: [],
      sponsorship_required: true,
    },
    manifest: {},
    selected_evidence: [],
    provided_answers: [],
  };
  render(
    <ApplicationRecordPage record={record([item])} workspace={h.workspace} />,
  );
  expect(screen.getByText(/No provider form observations/)).toBeInTheDocument();
});
it("refreshes records and older journal pages using reads, and opens management deliberately", async () => {
  const data = record();
  h.responses.set("/api/applications/1/record", data);
  render(<ApplicationRecordPage record={data} workspace={h.workspace} />);
  const read = vi.spyOn(h.workspace, "openRecord").mockResolvedValue();
  const older = vi.spyOn(h.workspace, "olderRecordEvents").mockResolvedValue();
  const detail = vi.spyOn(h.workspace, "openDetail").mockResolvedValue();
  fireEvent.click(screen.getByRole("button", { name: "Refresh record" }));
  await waitFor(() => expect(read).toHaveBeenCalledWith(1, false));
  fireEvent.click(screen.getByRole("button", { name: "Load older activity" }));
  await waitFor(() => expect(older).toHaveBeenCalledOnce());
  fireEvent.click(
    screen.getByRole("button", { name: "Manage this application" }),
  );
  await waitFor(() => expect(detail).toHaveBeenCalledWith(1));
  expect(h.workspace.getSnapshot().view).toBe("applications");
  fireEvent.click(
    screen.getByRole("button", { name: "Back to application queue" }),
  );
  expect(h.workspace.getSnapshot().view).toBe("applications");
});
