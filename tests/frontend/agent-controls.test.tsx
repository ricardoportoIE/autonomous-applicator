import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../frontend/src/App";
import { settings } from "./fixtures";
import { deferred, harness } from "./harness";

let h: ReturnType<typeof harness>;
beforeEach(() => {
  h = harness();
});
afterEach(() => h.stop());

it("starts immediately, suppresses duplicate starts, and switches to pause", async () => {
  render(<App workspace={h.workspace} />);
  expect(screen.getByRole("button", { name: "Start agent" })).toBeDisabled();
  await h.workspace.toggleAutomation();
  await h.unlock();
  const response = deferred<Response>();
  const original = h.fetch.getMockImplementation()!;
  h.fetch.mockImplementation((path) =>
    path === "/api/worker/start" ? response.promise : original(path),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start agent" }));
  expect(
    screen.getByRole("button", { name: "Starting agent…" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Starting agent…" }),
  ).toHaveAttribute("aria-busy", "true");
  await h.workspace.toggleAutomation();
  expect(
    h.fetch.mock.calls.filter(([path]) => path === "/api/worker/start"),
  ).toHaveLength(1);
  h.responses.set("/api/settings", { ...settings, automation_enabled: true });
  await act(async () =>
    response.resolve(Response.json({ ...settings, automation_enabled: true })),
  );
  await screen.findByRole("button", { name: "Pause agent" });
  expect(screen.getByRole("button", { name: "Pause agent" })).toBeEnabled();
  expect(document.getElementById("notice")).toHaveTextContent("Agent started.");
});

it("pauses during pending work, displays progress, and keeps the networking preference", async () => {
  h.responses.set("/api/settings", {
    ...settings,
    automation_enabled: true,
    connections_enabled: true,
  });
  render(<App workspace={h.workspace} />);
  await h.unlock();
  const work = deferred<void>();
  let running!: Promise<void>;
  act(() => {
    running = h.workspace.action(() => work.promise);
  });
  const response = deferred<Response>();
  const original = h.fetch.getMockImplementation()!;
  h.fetch.mockImplementation((path) =>
    path === "/api/settings" ? response.promise : original(path),
  );
  fireEvent.click(screen.getByRole("button", { name: "Pause agent" }));
  expect(screen.getByRole("button", { name: "Pausing agent…" })).toBeDisabled();
  const mutation = vi
    .mocked(fetch)
    .mock.calls.find(
      ([path, init]) => path === "/api/settings" && init?.method === "PUT",
    )!;
  expect(JSON.parse(mutation[1]!.body as string)).toMatchObject({
    automation_enabled: false,
    connections_enabled: true,
  });
  h.responses.set("/api/settings", {
    ...settings,
    automation_enabled: false,
    connections_enabled: true,
  });
  h.fetch.mockImplementation(original);
  await act(async () => response.resolve(Response.json(settings)));
  await screen.findByRole("button", { name: "Start agent" });
  expect(h.workspace.getSnapshot().pending).toBe(true);
  await act(async () => {
    work.resolve();
    await running;
  });
  expect(h.workspace.getSnapshot().pending).toBe(false);
});

it("reports failed starts without changing the enabled state and allows retry", async () => {
  render(<App workspace={h.workspace} />);
  await h.unlock();
  const original = h.fetch.getMockImplementation()!;
  h.fetch.mockImplementation(async (path) =>
    path === "/api/worker/start"
      ? Response.json(
          { detail: "Background worker unavailable" },
          { status: 503 },
        )
      : original(path),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start agent" }));
  await waitFor(() =>
    expect(document.getElementById("notice")).toHaveTextContent(
      "Background worker unavailable",
    ),
  );
  expect(screen.getByRole("button", { name: "Start agent" })).toBeEnabled();
  expect(h.workspace.getSnapshot().settings?.automation_enabled).toBe(false);
});

it("discards a late start response after locking the workspace", async () => {
  await h.unlock();
  const response = deferred<never>();
  vi.spyOn(h.workspace.api, "json").mockReturnValue(response.promise);
  const starting = h.workspace.toggleAutomation();
  expect(h.workspace.getSnapshot().automationChanging).toBe(true);
  h.workspace.lock();
  response.resolve({} as never);
  await starting;
  expect(h.workspace.getSnapshot()).toMatchObject({
    unlocked: false,
    automationChanging: false,
    settings: null,
    notice: "",
  });
});
