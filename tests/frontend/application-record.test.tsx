import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ApplicationRecordPage,
  recordedDate,
} from "../../frontend/src/application-record";
import type { ApplicationRecord } from "../../frontend/src/contracts";
import { Workspace } from "../../frontend/src/workspace";
import { application, payload, profile } from "./fixtures";

const makeRecord = (): ApplicationRecord => ({
  application: {
    ...application,
    state: "submitted",
    receipt: "fixture:confirmed",
  },
  dates: {
    imported_at: "2026-10-04T10:00:00Z",
    prepared_at: null,
    submitted_at: "2026-10-04T10:02:00Z",
    last_activity_at: null,
    event_count: 201,
  },
  events: [],
  next_event: 2,
  attempts: [
    {
      id: 1,
      status: "confirmed",
      started: "2026-10-04T10:01:00Z",
      sent_at: null,
      confirmed_at: "2026-10-04T10:02:00Z",
      receipt: "fixture:confirmed",
      fields: [
        {
          label: "Email",
          type: "text",
          value: "actually-sent@example.test",
          checked: null,
          observed_at: "2026-10-04T10:02:00Z",
          step: 1,
        },
        {
          label: "Follow employer",
          type: "checkbox",
          value: "",
          checked: false,
          observed_at: "2026-10-04T10:02:00Z",
        },
      ],
      snapshot: {
        job: application.job,
        candidate: {
          name: profile.name,
          email: profile.email,
          phone: profile.phone,
          location: profile.location,
          summary: profile.summary,
          links: profile.links,
          sponsorship_required: profile.sponsorship_required,
        },
        profile_revision: 1,
        manifest: application.manifest,
        provided_answers: [
          { id: "python", label: "Used Python?", answer: "Yes" },
        ],
        selected_evidence: profile.evidence,
      },
      confirmation: {
        name: "confirmation.png",
        captured_at: "2026-10-04T10:02:00Z",
        url: application.job.url,
      },
    },
  ],
});
let workspace: Workspace;
beforeEach(() => {
  sessionStorage.clear();
  workspace = new Workspace();
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      Response.json(path.includes("/record") ? makeRecord() : payload(path)),
    ),
  );
  URL.createObjectURL = vi.fn(() => "blob:confirmation");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  workspace.lock();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("formats British dates in London and retains truthful absent/invalid dates", () => {
  expect(recordedDate(null)).toBe("Not recorded");
  expect(recordedDate("invalid")).toBe("invalid");
  expect(recordedDate("2026-07-01T23:30:00Z")).toContain("2 Jul 2026");
});

it("renders sent values independently of the candidate snapshot and releases private image URLs", async () => {
  vi.spyOn(workspace.api, "blob").mockResolvedValue(new Blob(["fixture"]));
  const download = vi
    .spyOn(workspace, "downloadSubmission")
    .mockResolvedValue();
  const result = render(
    <ApplicationRecordPage record={makeRecord()} workspace={workspace} />,
  );
  expect(
    screen.getByRole("link", { name: "Open original opportunity" }),
  ).toHaveAttribute("href", application.job.url);
  expect(screen.getByText("actually-sent@example.test")).toBeInTheDocument();
  expect(screen.getByText("Email · Step 1")).toBeInTheDocument();
  expect(screen.getByText("Not selected")).toBeInTheDocument();
  expect(screen.getByText(profile.email)).toBeInTheDocument();
  expect(await screen.findByRole("img")).toHaveAttribute(
    "src",
    "blob:confirmation",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download confirmation screenshot" }),
  );
  await waitFor(() =>
    expect(download).toHaveBeenCalledWith(
      1,
      1,
      "confirmation",
      "application-1-attempt-1-confirmation.png",
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download Alex_Example_CV.pdf" }),
  );
  await waitFor(() =>
    expect(download).toHaveBeenCalledWith(
      1,
      1,
      "cv_pdf",
      "Alex_Example_CV.pdf",
    ),
  );
  result.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:confirmation");
});

it("shows image read failure without discarding the confirmed receipt", async () => {
  vi.spyOn(workspace.api, "blob").mockRejectedValue(new Error("Hash mismatch"));
  render(<ApplicationRecordPage record={makeRecord()} workspace={workspace} />);
  expect(
    await screen.findByText(/screenshot is unavailable or failed/),
  ).toBeInTheDocument();
  expect(screen.getByText("fixture:confirmed")).toBeInTheDocument();
  expect(screen.queryByRole("img")).toBeNull();
});

it("does not attach an image arriving after unmount", async () => {
  let finish!: (blob: Blob) => void;
  vi.spyOn(workspace.api, "blob").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const result = render(
    <ApplicationRecordPage record={makeRecord()} workspace={workspace} />,
  );
  result.unmount();
  finish(new Blob(["late"]));
  await Promise.resolve();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("does not attach an image error arriving after unmount", async () => {
  let reject!: (error: Error) => void;
  vi.spyOn(workspace.api, "blob").mockImplementation(
    () =>
      new Promise((_resolve, fail) => {
        reject = fail;
      }),
  );
  const view = render(
    <ApplicationRecordPage record={makeRecord()} workspace={workspace} />,
  );
  view.unmount();
  reject(new Error("Late unavailable image"));
  await Promise.resolve();
  expect(screen.queryByText(/screenshot is unavailable/)).toBeNull();
});

it("restores direct links after unlock and keeps the journal snapshot when loading older entries", async () => {
  history.replaceState(null, "", "#/applications/1");
  await workspace.unlock("fixture");
  expect(workspace.getSnapshot().view).toBe("record");
  const record = workspace.getSnapshot().record!;
  vi.spyOn(workspace.api, "json").mockResolvedValue({
    ...makeRecord(),
    application: {
      ...application,
      job: { ...application.job, title: "Changed live title" },
    },
    events: [
      {
        id: 1,
        created: "2026-10-04T09:00:00Z",
        kind: "imported",
        detail: "fixture",
        application_id: 1,
      },
    ],
    next_event: null,
  });
  await workspace.olderRecordEvents();
  expect(workspace.getSnapshot().record?.application).toBe(record.application);
  expect(workspace.getSnapshot().record?.events).toHaveLength(1);
  expect(workspace.getSnapshot().record?.next_event).toBeNull();
  await workspace.olderRecordEvents();
  workspace.lock();
  expect(workspace.getSnapshot().record).toBeNull();
});

it("rejects a stale record response after navigation or locking", async () => {
  await workspace.unlock("fixture");
  let finish!: (value: ApplicationRecord) => void;
  vi.spyOn(workspace.api, "json").mockImplementation(
    async () =>
      (await new Promise<ApplicationRecord>((resolve) => {
        finish = resolve;
      })) as never,
  );
  const old = workspace.openRecord(1);
  workspace.navigate("settings");
  finish(makeRecord());
  await old;
  expect(workspace.getSnapshot().record).toBeNull();
  const after = workspace.openRecord(1);
  workspace.lock();
  finish(makeRecord());
  await after;
  expect(workspace.getSnapshot().record).toBeNull();
});

it("downloads authenticated archived documents and revokes the temporary URL", async () => {
  await workspace.unlock("fixture");
  vi.useFakeTimers();
  vi.spyOn(workspace.api, "blob").mockResolvedValue(new Blob(["PDF"]));
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  await workspace.downloadSubmission(1, 2, "cv_pdf", "archived.pdf");
  expect(workspace.api.blob).toHaveBeenCalledWith(
    "/applications/1/submissions/2/artifacts/cv_pdf",
  );
  expect(click).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(1000);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:confirmation");
  vi.useRealTimers();
});
