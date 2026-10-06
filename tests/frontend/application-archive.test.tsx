import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { App } from "../../frontend/src/App";
import { application } from "./fixtures";
import { harness } from "./harness";

let h: ReturnType<typeof harness>;
beforeEach(() => {
  h = harness();
});
afterEach(() => h.stop());
async function start() {
  render(<App workspace={h.workspace} />);
  await h.unlock();
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name: "Applications" }),
  );
}
function archive() {
  fireEvent.click(screen.getByRole("tab", { name: /^Archive/ }));
}
function queue() {
  return screen.getByRole("tabpanel", { name: /^Active/ });
}
function archivePanel() {
  return screen.getByRole("tabpanel", { name: /^Archive/ });
}

it("separates only confirmed submissions and retains full records and all unresolved states", async () => {
  h.responses.set("/api/applications/6", {
    ...application,
    id: 6,
    state: "submitted",
    job: { ...application.job, title: "submitted opportunity" },
  });
  h.responses.set("/api/applications", [
    application,
    ...["review", "uncertain", "submitting", "skipped", "submitted"].map(
      (state, i) => ({
        ...application,
        id: i + 2,
        state,
        job: { ...application.job, title: `${state} opportunity` },
      }),
    ),
  ]);
  await start();
  expect(screen.getByRole("tab", { name: "Active (5)" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(within(queue()).queryByText("submitted opportunity")).toBeNull();
  for (const state of ["review", "uncertain", "submitting", "skipped"])
    expect(within(queue()).getByText(`${state} opportunity`)).toBeVisible();
  archive();
  expect(
    within(archivePanel()).getByText("submitted opportunity"),
  ).toBeVisible();
  expect(
    within(archivePanel()).getByText("1 of 1 opportunities shown"),
  ).toBeVisible();
  expect(
    within(archivePanel()).getByRole("link", { name: /Full record/ }),
  ).toHaveAttribute("href", "#/applications/6");
  expect(h.workspace.getSnapshot().applications).toHaveLength(6);
  fireEvent.click(
    within(archivePanel()).getByRole("button", { name: /Open submitted/ }),
  );
  await screen.findByRole("button", { name: "Recheck readiness" });
  expect(
    h.fetch.mock.calls.some(([path]) => path === "/api/applications/6"),
  ).toBe(true);
});

it("retains search and sorting, resets incompatible status filters, and creates no duplicate controls", async () => {
  h.responses.set("/api/applications", [
    application,
    {
      ...application,
      id: 2,
      state: "submitted",
      job: { ...application.job, title: "Archived Python Engineer" },
    },
  ]);
  await start();
  fireEvent.change(
    screen.getByLabelText("Application status", { exact: true }),
    { target: { value: "ready" } },
  );
  fireEvent.change(screen.getByLabelText("Search opportunities"), {
    target: { value: "Python" },
  });
  fireEvent.change(screen.getByLabelText("Sort opportunities"), {
    target: { value: "company" },
  });
  archive();
  expect(
    screen.getByLabelText("Application status", { exact: true }),
  ).toHaveValue("all");
  expect(screen.getAllByLabelText("Search opportunities")).toHaveLength(1);
  expect(screen.getByLabelText("Search opportunities")).toHaveValue("Python");
  expect(screen.getByLabelText("Sort opportunities")).toHaveValue("company");
  expect(
    within(archivePanel()).getByText("Archived Python Engineer"),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByLabelText("Search opportunities")).toHaveValue("");
  fireEvent.click(screen.getByRole("tab", { name: "Active (1)" }));
  expect(within(queue()).getByText("Backend Engineer")).toBeVisible();
});

it("moves a newly confirmed row on refresh and restores active-only view after locking", async () => {
  await start();
  h.responses.set("/api/applications", [
    { ...application, state: "submitted" },
  ]);
  await act(() => h.workspace.refresh());
  expect(within(queue()).getByText(/No active opportunities/)).toBeVisible();
  expect(screen.getByRole("tab", { name: "Archive (1)" })).toBeVisible();
  archive();
  expect(within(archivePanel()).getByText("Backend Engineer")).toBeVisible();
  await act(() => h.workspace.lock());
  await h.unlock();
  expect(screen.getByRole("tab", { name: "Active (0)" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

it("supports keyboard navigation and explicit empty archive and unmatched search messages", async () => {
  await start();
  fireEvent.keyDown(screen.getByRole("tab", { name: "Active (1)" }), {
    key: "ArrowRight",
  });
  expect(screen.getByRole("tab", { name: "Archive (0)" })).toHaveFocus();
  expect(
    within(archivePanel()).getByText(/No completed applications yet/),
  ).toBeVisible();
  fireEvent.keyDown(screen.getByRole("tab", { name: "Archive (0)" }), {
    key: "Home",
  });
  fireEvent.change(screen.getByLabelText("Search opportunities"), {
    target: { value: "Unmatched" },
  });
  expect(within(queue()).getByText(/No opportunities match/)).toBeVisible();
});

it("explains below-fit discovery exclusions without discarding saved records", async () => {
  h.responses.set("/api/discover/linkedin", {
    imported: 1,
    discarded: 2,
    excluded: 0,
    duplicates: 0,
  });
  await start();
  fireEvent.click(screen.getByRole("button", { name: "Search LinkedIn" }));
  await waitFor(() =>
    expect(
      screen.getByText(/2 below-fit opportunities discarded/),
    ).toBeVisible(),
  );
  expect(h.workspace.getSnapshot().applications).toHaveLength(1);
});
