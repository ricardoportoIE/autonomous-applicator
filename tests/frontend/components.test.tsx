import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ApplicationBadge,
  Modal,
  Tabs,
  WorkerMonitor,
} from "../../frontend/src/components";
import { App } from "../../frontend/src/App";
import { Workspace } from "../../frontend/src/workspace";
import { application, payload } from "./fixtures";
import type { WorkerRecord } from "../../frontend/src/contracts";

let workspace: Workspace;
it.each(["Scout", "Link", "Bridge", "Historical"])(
  "reports the %s role alongside the current vacancy and recovery stage",
  (agent) => {
    render(
      <WorkerMonitor
        error=""
        record={{
          run: {
            id: "role-run",
            status: "running",
            application_id: 1,
            job: {
              ...application.job,
              title: "Backend Engineer",
              company: "Example Employer",
            },
            stage: "diagnosing_runtime_error",
            detail: `${agent} · Checking the current form before recovery.`,
            error_code: null,
            started: "2026-10-08T10:00:00Z",
            stage_started: "2026-10-08T10:00:01Z",
            finished: null,
          },
          results: [],
        }}
      />,
    );
    const monitor = screen.getByRole("status");
    expect(monitor).toHaveTextContent(
      "Backend Engineer · Example Employer · Application #1",
    );
    expect(monitor).toHaveTextContent(
      "Current stage: diagnosing runtime error",
    );
    if (agent === "Historical") expect(monitor).not.toHaveTextContent("Agent:");
    else expect(monitor).toHaveTextContent(`Agent: ${agent}`);
  },
);
it("distinguishes preparation work from policy review and readiness", () => {
  const view = render(
    <ApplicationBadge
      row={{ ...application, state: "review", evaluation: {} }}
    />,
  );
  expect(screen.getByText("Queued for preparation")).toBeVisible();
  view.rerender(
    <ApplicationBadge
      row={{
        ...application,
        state: "review",
        evaluation: { score: 100, preparation_pending: true },
      }}
    />,
  );
  expect(screen.getByText("Queued for preparation")).toBeVisible();
  view.rerender(<ApplicationBadge row={{ ...application, state: "review" }} />);
  expect(screen.getByText("For review")).toBeVisible();
  view.rerender(<ApplicationBadge row={application} />);
  expect(screen.getByText("Ready")).toBeVisible();
});
beforeEach(() => {
  sessionStorage.clear();
  workspace = new Workspace();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => Response.json(payload(path))),
  );
  vi.stubGlobal("scrollTo", vi.fn());
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) {
      this.open = true;
    }),
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) {
      this.open = false;
    }),
  });
});
afterEach(() => {
  workspace.lock();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("uses accessible modal labelling, reports errors in the dialogue and restores focus", async () => {
  const trigger = document.createElement("button");
  document.body.append(trigger);
  trigger.focus();
  const close = vi.fn();
  const result = render(
    <Modal
      title="Add evidence"
      busy={false}
      notice="Save failed"
      error
      onClose={close}
    >
      <label>
        Title
        <input />
      </label>
    </Modal>,
  );
  expect(screen.getByRole("dialog", { name: "Add evidence" })).toBeVisible();
  expect(
    within(screen.getByRole("dialog")).getByRole("alert"),
  ).toHaveTextContent("Save failed");
  fireEvent(
    screen.getByRole("dialog"),
    new Event("cancel", { cancelable: true }),
  );
  expect(close).toHaveBeenCalledOnce();
  result.unmount();
  expect(trigger).toHaveFocus();
  expect(document.body).not.toHaveClass("modal-open");
  trigger.remove();
});
it("makes tabs discoverable and navigable using arrow keys, Home and End", async () => {
  const change = vi.fn();
  render(
    <Tabs
      prefix="example"
      label="Example tabs"
      selected="a"
      onSelect={change}
      items={[
        { id: "a", label: "First" },
        { id: "b", label: "Second" },
        { id: "c", label: "Third" },
      ]}
    >
      {(id) => <p>{id}</p>}
    </Tabs>,
  );
  const first = screen.getByRole("tab", { name: "First" });
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowLeft" });
  expect(screen.getByRole("tab", { name: "Third" })).toHaveFocus();
  expect(change).toHaveBeenLastCalledWith("c");
  fireEvent.keyDown(screen.getByRole("tab", { name: "Third" }), {
    key: "Home",
  });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: "End" });
  expect(change).toHaveBeenLastCalledWith("c");
  fireEvent.keyDown(first, { key: "ArrowRight" });
  expect(change).toHaveBeenLastCalledWith("b");
  fireEvent.keyDown(first, { key: "Escape" });
  expect(change).toHaveBeenCalledTimes(4);
  expect(screen.getByRole("tabpanel")).toHaveAttribute(
    "aria-labelledby",
    "example-a-tab",
  );
});
it("keeps idle, terminal failures and total/stage elapsed time visible without provider calls", () => {
  const record: WorkerRecord = {
    run: {
      id: "run-test",
      status: "failed",
      application_id: 1,
      job: null,
      stage: "selecting_evidence",
      detail: "Selection could not finish.",
      error_code: "PreparationError",
      started: "2026-10-04T10:00:00Z",
      stage_started: "2026-10-04T10:00:02Z",
      finished: "2026-10-04T10:00:10Z",
    },
    results: [],
  };
  const view = render(<WorkerMonitor record={null} error="" />);
  expect(screen.getByRole("status")).toHaveTextContent("Idle");
  view.rerender(<WorkerMonitor record={record} error="" />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Failure at selecting evidence: PreparationError",
  );
  expect(
    screen.getByText("Total: 10s · Stage: 8s · Run run-test"),
  ).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Inspect the application activity log before retrying.",
  );
  view.rerender(
    <WorkerMonitor
      record={{
        ...record,
        run: {
          ...record.run!,
          application_id: null,
          stage: "reading_job_results",
        },
      }}
      error=""
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Check the last stage and the dedicated browser session before retrying.",
  );
  expect(screen.getByRole("status")).not.toHaveTextContent(
    "Inspect the application activity log",
  );
  view.rerender(
    <WorkerMonitor record={record} error="Live status unavailable" />,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Live status unavailable",
  );
});
it.each([
  [
    "deferring_discovered_job",
    "running",
    "Read deferred until 2026-10-07T21:05:00+00:00; continuing with other opportunities.",
  ],
  [
    "waiting_for_discovery",
    "completed",
    "Automatic discovery is waiting until 2026-10-07T21:05:00+00:00 after a read failure. Existing queue work remains available; manual search can retry now.",
  ],
  [
    "waiting_for_review",
    "completed",
    "No new readable opportunities in this search. 5 applications await review; 0 are prepared. Next scheduled search in 60 seconds.",
  ],
])(
  "shows %s with the retry time and no application failure claim",
  (stage, status, detail) => {
    render(
      <WorkerMonitor
        record={{
          run: {
            id: "read-run",
            status,
            application_id: null,
            job: null,
            stage,
            detail,
            error_code: null,
            started: "2026-10-07T21:00:00Z",
            stage_started: "2026-10-07T21:00:01Z",
            finished: status === "completed" ? "2026-10-07T21:00:02Z" : null,
          },
          results: [],
        }}
        error=""
      />,
    );
    const monitor = screen.getByRole("status");
    expect(monitor).toHaveTextContent(stage.replaceAll("_", " "));
    expect(monitor).toHaveTextContent(detail);
    expect(monitor).not.toHaveTextContent("Failure at");
    expect(monitor).not.toHaveTextContent("Application #");
  },
);
it("authenticates the workspace and clears private data and open forms on lock", async () => {
  const user = userEvent.setup();
  render(<App workspace={workspace} />);
  await user.type(screen.getByLabelText("Access token"), "fixture");
  await user.click(screen.getByRole("button", { name: "Unlock workspace" }));
  await screen.findByText("Local workspace unlocked.");
  await user.click(screen.getByRole("button", { name: "Candidate profile" }));
  expect(screen.getByText("Alex Example")).toBeVisible();
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(
    screen.getByRole("button", { name: "Edit candidate profile" }),
  );
  expect(screen.getByRole("dialog")).toHaveAccessibleName(
    "Edit candidate profile",
  );
  expect(screen.getByLabelText("E-mail", { exact: true })).toHaveValue(
    "alex@example.test",
  );
  // Lock while a private form is open and require both data and form cleanup.
  fireEvent.click(screen.getByRole("button", { name: "Lock workspace" }));
  expect(screen.queryByText("Alex Example")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Unlock workspace" }),
  ).toBeVisible();
});

it("opens and closes only the requested opportunity form", async () => {
  const user = userEvent.setup();
  render(<App workspace={workspace} />);
  await user.type(screen.getByLabelText("Access token"), "fixture");
  await user.click(screen.getByRole("button", { name: "Unlock workspace" }));
  await screen.findByText("Local workspace unlocked.");
  await user.click(screen.getByRole("button", { name: "Applications" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Add opportunity" }));
  expect(screen.getByRole("dialog")).toHaveAccessibleName("Add an opportunity");
  await user.click(screen.getByRole("button", { name: "Close dialogue" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Lock workspace" }));
  expect(screen.queryByText("Alex Example")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Unlock workspace" }),
  ).toBeVisible();
});

it("keeps a candidate draft tied to its opening revision after another workspace refresh", async () => {
  const user = userEvent.setup();
  render(<App workspace={workspace} />);
  await user.type(screen.getByLabelText("Access token"), "fixture");
  await user.click(screen.getByRole("button", { name: "Unlock workspace" }));
  await screen.findByText("Local workspace unlocked.");
  await user.click(screen.getByRole("button", { name: "Candidate profile" }));
  await user.click(
    screen.getByRole("button", { name: "Edit candidate profile" }),
  );
  const draft = screen.getByLabelText(
    "Professional summary (approved wording)",
  );
  await user.clear(draft);
  await user.type(draft, "Candidate draft");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/profile" && options?.method === "PUT")
        return Response.json(
          { detail: "Candidate profile changed. Reload before saving." },
          { status: 409 },
        );
      if (path === "/api/profile")
        return Response.json({ ...(payload(path) as object), revision: 2 });
      return Response.json(payload(path));
    }),
  );
  // Another view's refresh must not silently rebase the open form onto revision 2.
  await workspace.refresh();
  await user.click(
    screen.getByRole("button", { name: "Save candidate profile" }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/profile",
    expect.objectContaining({
      headers: expect.objectContaining({ "If-Match": "1" }),
    }),
  );
  expect(draft).toHaveValue("Candidate draft");
  expect(
    within(screen.getByRole("dialog")).getByRole("alert"),
  ).toHaveTextContent("Candidate profile changed");
});
