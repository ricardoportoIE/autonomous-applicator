import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ApplicationTable,
  Modal,
  WorkerMonitor,
} from "../../frontend/src/components";
import { application } from "./fixtures";
import { harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(() => {
  h = harness();
});
afterEach(() => h.stop());
it("traps native dialogue focus at visible enabled controls and permits ordinary Tab movement", () => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue({
    length: 1,
  } as DOMRectList);
  const close = vi.fn();
  const view = render(
    <Modal
      title="Edit evidence"
      onClose={close}
      busy={false}
      notice="Saved"
      error={false}
    >
      <input aria-label="Value" />
      <input aria-label="Disabled" disabled />
      <a href="https://example.test" tabIndex={-1}>
        Hidden from keyboard
      </a>
      <button>Save</button>
    </Modal>,
  );
  const first = screen.getByRole("button", { name: "Close dialogue" }),
    last = screen.getByRole("button", { name: "Save" }),
    dialog = screen.getByRole("dialog");
  first.focus();
  fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(last, { key: "Tab" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: "Tab" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(first);
  expect(close).toHaveBeenCalledOnce();
  view.unmount();
  expect(dialog).not.toHaveAttribute("open");
});
it("prevents focus escape when layout offers no visible focusable controls", () => {
  render(
    <Modal title="Working" onClose={vi.fn()} busy notice="" error={false}>
      Waiting
    </Modal>,
  );
  const event = new KeyboardEvent("keydown", {
    key: "Tab",
    bubbles: true,
    cancelable: true,
  });
  fireEvent(screen.getByRole("dialog"), event);
  expect(event.defaultPrevented).toBe(true);
});

it("does not focus a modal trigger that was removed while the dialogue was open", () => {
  const trigger = document.createElement("button");
  document.body.append(trigger);
  trigger.focus();
  const focus = vi.spyOn(trigger, "focus");
  const view = render(
    <Modal title="Edit" onClose={vi.fn()} busy={false} notice="" error={false}>
      Content
    </Modal>,
  );
  trigger.remove();
  view.unmount();
  expect(focus).not.toHaveBeenCalled();
});
it("opens the selected table row and explains an unevaluated opportunity", () => {
  const open = vi.fn();
  render(
    <ApplicationTable
      rows={[{ ...application, evaluation: {} }]}
      onOpen={open}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /Open Backend Engineer/ }),
  );
  expect(open).toHaveBeenCalledWith(1);
  expect(screen.getByText("—")).toBeVisible();
});
it("updates a running worker clock, records both successful and failed results, and releases its timer", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-04T10:00:10Z"));
  const run = {
    id: "fixture",
    status: "running",
    application_id: 1,
    job: application.job,
    stage: "preparing_documents",
    detail: "Generating tailored documents",
    error_code: null,
    started: "2026-10-04T10:00:00Z",
    stage_started: "2026-10-04T10:00:05Z",
    finished: null,
  };
  const record = {
    run,
    results: [
      {
        job: application.job,
        application_id: 1,
        outcome: "submitted",
        stage: "confirmed",
        error_code: null,
      },
      {
        job: application.job,
        application_id: 2,
        outcome: "review",
        stage: "selecting_evidence",
        error_code: "PreparationError",
      },
    ],
  };
  const view = render(<WorkerMonitor record={record} error="" />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Current stage: preparing documents",
  );
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(
    screen.getByText("Total: 11s · Stage: 6s · Run fixture"),
  ).toBeVisible();
  expect(screen.getByText(/Backend Engineer · Failed/)).toBeInTheDocument();
  view.rerender(
    <WorkerMonitor
      record={{
        ...record,
        run: {
          ...run,
          status: "custom_provider_status",
          finished: "2026-10-04T10:00:12Z",
        },
      }}
      error=""
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "custom_provider_status",
  );
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
