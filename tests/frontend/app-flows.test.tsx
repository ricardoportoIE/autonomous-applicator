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
import { application, profile, settings } from "./fixtures";
import { deferred, harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(() => {
  h = harness();
});
afterEach(() => h.stop());
async function start() {
  render(<App workspace={h.workspace} />);
  await h.unlock();
}
function nav(name: string) {
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", { name }),
  );
}
function fill(name: string, value: string) {
  fireEvent.change(screen.getByLabelText(name, { exact: true }), {
    target: { value },
  });
}
async function saveModal(button: string) {
  fireEvent.submit(
    within(screen.getByRole("dialog"))
      .getByRole("button", { name: button })
      .closest("form")!,
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}
it("restores a saved session and tab on mount, follows history, and removes route listeners on unmount", async () => {
  history.replaceState(null, "", "#settings");
  sessionStorage.setItem("applicator-token", "fixture");
  const view = render(<App workspace={h.workspace} />);
  await screen.findByText("Alex Example");
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Agent settings",
    ),
  );
  await act(async () => {
    history.replaceState(null, "", "#profile");
    window.dispatchEvent(new Event("popstate"));
  });
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Candidate profile",
  );
  await act(async () => {
    history.replaceState(null, "", "#main-content");
    window.dispatchEvent(new Event("hashchange"));
  });
  expect(h.workspace.getSnapshot().view).toBe("profile");
  view.unmount();
  window.dispatchEvent(new Event("popstate"));
  expect(h.workspace.getSnapshot().unlocked).toBe(false);
});

it("filters, sorts and clears opportunities without changing their records", async () => {
  h.responses.set("/api/applications", [
    application,
    {
      ...application,
      id: 2,
      state: "review",
      job: { ...application.job, title: "Frontend Engineer" },
    },
  ]);
  await start();
  nav("Applications");
  fill("Search opportunities", "Frontend");
  expect(screen.getByText("1 of 2 opportunities shown")).toBeVisible();
  fill("Application status", "ready");
  expect(screen.getByText(/No opportunities match/)).toBeVisible();
  fill("Sort opportunities", "company");
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByLabelText("Search opportunities")).toHaveValue("");
  expect(screen.getByText("2 of 2 opportunities shown")).toBeVisible();
  expect(h.workspace.getSnapshot().applications).toHaveLength(2);
});

it("opens and updates only the requested opportunity through its detail form", async () => {
  await start();
  nav("Applications");
  fireEvent.click(
    screen.getByRole("button", {
      name: "Open Backend Engineer at Example Employer",
    }),
  );
  await screen.findByRole("button", { name: "Recheck readiness" });
  fireEvent.click(screen.getByRole("button", { name: "Edit job details" }));
  expect(
    screen.getByRole("dialog", { name: "Edit opportunity" }),
  ).toBeVisible();
  await saveModal("Save updated opportunity");
});

it("creates a manual opportunity and imports a board through focused dialogues", async () => {
  await start();
  nav("Applications");
  fireEvent.click(screen.getByRole("button", { name: "Add opportunity" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Enter details manually" }),
  );
  fill("Job URL", "https://example.test/new");
  fill("Job title", "API Engineer");
  fill("Company", "Example");
  fill("Location", "Dublin");
  fill("Job description", "Python services");
  await saveModal("Save opportunity");
  fireEvent.click(
    screen.getByRole("button", { name: "Import from Greenhouse" }),
  );
  fill("Greenhouse board", "example");
  h.responses.set("/api/discover/greenhouse", { imported: 2 });
  await saveModal("Import board jobs");
  expect(screen.getByText("Imported 2 new opportunities.")).toBeVisible();
});

it("adds, updates and removes evidence without losing the candidate facts", async () => {
  await start();
  nav("Candidate profile");
  const mutate = vi.spyOn(h.workspace, "mutate");
  fireEvent.click(screen.getByRole("button", { name: "Add evidence" }));
  fill("Evidence identifier", "api");
  fill("Title", "API project");
  fill("Factual description", "Created an API.");
  fill("Evidence source", "Candidate");
  await saveModal("Save evidence");
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByRole("dialog", { name: "Edit evidence" })).toBeVisible();
  await saveModal("Save evidence");
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith(
      "/evidence/python",
      "DELETE",
      undefined,
      expect.any(String),
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Edit candidate profile" }),
  );
  await saveModal("Save candidate profile");
});

it("supports a first candidate profile and displays incomplete facts and unverified evidence", async () => {
  h.responses.set("/api/profile", { profile: null, revision: 0 });
  h.responses.set("/api/applications", []);
  await start();
  nav("Candidate profile");
  expect(
    screen.getByText("Add your candidate profile to begin."),
  ).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Add candidate profile" }),
  );
  fill("Professional name", "Alex Example");
  fill("E-mail", "alex@example.test");
  fill("Location", "Dublin");
  await saveModal("Save candidate profile");
  h.responses.set("/api/profile", {
    profile: {
      ...profile,
      email: "",
      phone: "+3530000000",
      confirmed: false,
      sponsorship_required: false,
      links: ["https://example.test"],
      answers: { "question:python?": "Yes" },
      evidence: [{ ...profile.evidence[0], verified: false }],
    },
    revision: 2,
  });
  await act(() => h.workspace.refresh());
  expect(screen.getByText("Facts need review")).toBeVisible();
  expect(screen.getByText("Not provided")).toBeVisible();
  expect(
    screen.getByText("Needs confirmation", { exact: false }),
  ).toBeVisible();
});

it("shows real discovery progress and preserves failure diagnostics without retrying a mutation", async () => {
  await start();
  nav("Applications");
  const result = deferred<Response>();
  h.fetch.mockImplementation(async (path) =>
    path === "/api/discover/linkedin"
      ? result.promise
      : Response.json(
          h.responses.get(path) ?? (await import("./fixtures")).payload(path),
        ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Search LinkedIn" }));
  expect(screen.getByRole("button", { name: "Searching…" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  await act(async () =>
    result.resolve(
      Response.json({ detail: "Provider layout changed" }, { status: 500 }),
    ),
  );
  await screen.findByText("Provider layout changed");
  expect(screen.getByText(/Search failed/)).toBeVisible();
  expect(
    h.fetch.mock.calls.filter(([path]) => path === "/api/discover/linkedin"),
  ).toHaveLength(1);
});

it("creates a contact, exposes networking discovery progress and keeps archived contacts separate", async () => {
  await start();
  nav("Networking");
  fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
  fill("LinkedIn profile URL", "https://www.linkedin.com/in/example/");
  fill("Member's displayed name", "Example Recruiter");
  fill("Displayed role / headline", "Recruiter");
  fill("Displayed European location", "Ireland");
  await saveModal("Queue contact");
  const search = vi.spyOn(h.workspace, "discover");
  fireEvent.click(
    screen.getByRole("button", { name: "Find European recruiters" }),
  );
  await waitFor(() => expect(search).toHaveBeenCalledWith("contacts"));
});

it("keeps the global pause available while work is pending and displays held sending capacity", async () => {
  h.responses.set("/api/settings", { ...settings, automation_enabled: true });
  h.responses.set("/api/usage", {
    day: "2026-10-04",
    used: 2,
    held: 1,
    limit: 10,
    remaining: 7,
  });
  await start();
  expect(screen.getByText(/1 sending slots held/)).toBeVisible();
  const tick = vi.spyOn(h.workspace, "tick");
  fireEvent.click(screen.getByRole("button", { name: /Run agent cycle/i }));
  await waitFor(() => expect(tick).toHaveBeenCalledOnce());
  const pause = vi.spyOn(h.workspace, "toggleAutomation");
  fireEvent.click(screen.getByRole("button", { name: "Pause agent" }));
  await waitFor(() => expect(pause).toHaveBeenCalledOnce());
});

it("shows missing record errors and returns to the queue", async () => {
  await start();
  h.fetch.mockImplementation(async (path) =>
    path.endsWith("/record")
      ? Response.json({ detail: "Record not found" }, { status: 404 })
      : Response.json((await import("./fixtures")).payload(path)),
  );
  await act(async () => {
    history.replaceState(null, "", "#/applications/404");
    window.dispatchEvent(new Event("hashchange"));
  });
  expect(screen.getByText(/Application record unavailable/)).toBeVisible();
  expect(screen.getByText("Record not found")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Back to application queue" }),
  );
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Applications",
  );
});

it("retains an invalid login token for correction without unlocking", async () => {
  h.fetch.mockImplementation(async () =>
    Response.json({ detail: "Invalid local token" }, { status: 401 }),
  );
  render(<App workspace={h.workspace} />);
  fill("Access token", "wrong");
  fireEvent.submit(
    screen.getByRole("button", { name: "Unlock workspace" }).closest("form")!,
  );
  await screen.findByText("Invalid local token");
  expect(h.workspace.getSnapshot().unlocked).toBe(false);
});
it("opens the overview queue shortcut and renders missing authorisation and unknown capacity", async () => {
  h.responses.set("/api/settings", { ...settings, linkedin_authorised: false });
  h.responses.set("/api/usage", {
    day: "2026-10-04",
    used: 0,
    limit: 10,
    remaining: 10,
  });
  await start();
  expect(screen.getByText("LinkedIn scope needed")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "View application queue" }),
  );
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Applications",
  );
});
it("shows record loading before presenting the correct complete record", async () => {
  await start();
  const response = deferred<Response>();
  h.fetch.mockImplementation(async (path) =>
    path.endsWith("/record")
      ? response.promise
      : Response.json((await import("./fixtures")).payload(path)),
  );
  act(() => {
    history.replaceState(null, "", "#/applications/1");
    window.dispatchEvent(new Event("hashchange"));
  });
  expect(screen.getByText("Loading application record…")).toBeVisible();
  await act(async () =>
    response.resolve(
      Response.json({
        application,
        dates: { imported_at: null, last_activity_at: null, event_count: 0 },
        attempts: [],
        events: [],
        next_event: null,
      }),
    ),
  );
  expect(screen.getByRole("button", { name: "Refresh record" })).toBeVisible();
});
