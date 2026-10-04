import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "../../frontend/src/workspace";
import { ApiError } from "../../frontend/src/api";
import { application, connection, payload, profile } from "./fixtures";
import type { Connection } from "../../frontend/src/contracts";

describe("workspace ownership and operations", () => {
  let workspace: Workspace;
  beforeEach(() => {
    sessionStorage.clear();
    workspace = new Workspace();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => Response.json(payload(url))),
    );
    vi.stubGlobal("scrollTo", vi.fn());
    URL.createObjectURL = vi.fn(() => "blob:fixture");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    workspace.lock();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("refreshes a changed application after failed preparation without repeating the mutation", async () => {
    await workspace.unlock("fixture");
    await workspace.openDetail(1);
    const json = vi
      .spyOn(workspace.api, "json")
      .mockImplementation(async (path) => {
        if (path.endsWith("/prepare"))
          throw new ApiError("AI preparation failed; review required", 503);
        if (path === "/applications/1")
          return { ...application, state: "review", manifest: {} } as never;
        return payload("/api" + path) as never;
      });
    await workspace.action(() =>
      workspace.mutate("/applications/1/prepare", "POST", {}, "Prepared", 1),
    );
    expect(workspace.getSnapshot().detail?.row).toMatchObject({
      state: "review",
      manifest: {},
    });
    expect(workspace.getSnapshot().notice).toContain("AI preparation failed");
    expect(
      json.mock.calls.filter(([path]) => path.endsWith("/prepare")),
    ).toHaveLength(1);
    json.mockRejectedValue(new Error("Status reads unavailable"));
    await expect(
      workspace.mutate("/applications/1/prepare", "POST", {}, "Prepared", 1),
    ).rejects.toThrow("Status reads unavailable");
  });
  it("retains the newer refresh when an older settings response arrives later", async () => {
    await workspace.unlock("fixture");
    let finish!: (value: unknown) => void;
    let hold = true;
    vi.spyOn(workspace.api, "json").mockImplementation(async (path) => {
      if (path === "/settings" && hold) {
        hold = false;
        return (await new Promise<unknown>((resolve) => {
          finish = resolve;
        })) as never;
      }
      return payload("/api" + path) as never;
    });
    const old = workspace.refresh();
    await workspace.refresh();
    finish({ ...workspace.getSnapshot().settings!, automation_enabled: true });
    await old;
    expect(workspace.getSnapshot().settings?.automation_enabled).toBe(false);
  });
  it("unlocks all records, restores tokens and clears every private record on lock", async () => {
    const listener = vi.fn();
    const unsubscribe = workspace.subscribe(listener);
    await workspace.unlock("fixture");
    expect(workspace.getSnapshot()).toMatchObject({
      unlocked: true,
      profile,
      revision: 1,
      pending: false,
      notice: "Local workspace unlocked.",
    });
    expect(sessionStorage.getItem("applicator-token")).toBe("fixture");
    await workspace.openDetail(1);
    expect(workspace.getSnapshot().detail?.row).toEqual(application);
    workspace.navigate("networking");
    expect(workspace.getSnapshot().view).toBe("networking");
    vi.spyOn(workspace.api, "photo").mockResolvedValue(new Blob(["png"]));
    await workspace.photo(1);
    workspace.lock();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fixture");
    expect(workspace.getSnapshot()).toMatchObject({
      unlocked: false,
      profile: null,
      detail: null,
      worker: null,
      connections: [],
      feedback: {},
    });
    expect(sessionStorage.length).toBe(0);
    unsubscribe();
    const count = listener.mock.calls.length;
    workspace.message("Done");
    expect(listener).toHaveBeenCalledTimes(count);
  });
  it("allows an empty candidate record and reports other profile failures", async () => {
    vi.spyOn(workspace.api, "json").mockImplementation(async (path) => {
      if (path === "/profile")
        throw new Error("Configure a candidate profile first");
      return payload("/api" + path) as never;
    });
    await workspace.unlock("fixture", true);
    expect(workspace.getSnapshot().profile).toBeNull();
    expect(workspace.getSnapshot().notice).toBe("");
    workspace.lock();
    vi.mocked(workspace.api.json).mockRejectedValue(
      new Error("Database unavailable"),
    );
    await workspace.unlock("fixture");
    expect(workspace.getSnapshot().unlocked).toBe(false);
    expect(workspace.getSnapshot().notice).toBe("Database unavailable");
  });
  it("suppresses duplicate actions while allowing global pause", async () => {
    await workspace.unlock("fixture");
    let complete!: () => void;
    const first = workspace.action(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        }),
    );
    const duplicate = vi.fn();
    await workspace.action(duplicate);
    await workspace.unlock("another");
    expect(duplicate).not.toHaveBeenCalled();
    await workspace.pause();
    expect(fetch).toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({
        body: expect.stringContaining('"automation_enabled":false'),
      }),
    );
    complete();
    await first;
    expect(workspace.getSnapshot().pending).toBe(false);
  });
  it("does not restore late mutation data or notices after a lock", async () => {
    await workspace.unlock("fixture");
    let finish!: () => void;
    const action = workspace.action(async () => {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      throw new Error("Old private diagnostic");
    });
    workspace.lock();
    finish();
    await action;
    expect(workspace.getSnapshot().notice).toBe("");
    expect(workspace.getSnapshot().pending).toBe(false);
    workspace.api.setToken("fixture");
    await workspace.action(async () => {
      throw "Unknown failure";
    });
    expect(workspace.getSnapshot().notice).toBe(
      "The operation could not be completed.",
    );
  });
  it("expires a session and explains authentication failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ detail: "Expired token" }, { status: 401 }),
      ),
    );
    await workspace.unlock("fixture");
    expect(workspace.getSnapshot()).toMatchObject({
      unlocked: false,
      notice: "Expired token",
      error: true,
    });
  });
  it("sends revision checks for profile edits and refreshes selected opportunity", async () => {
    await workspace.unlock("fixture");
    await workspace.mutate("/profile", "PUT", profile, "Saved", 1);
    expect(fetch).toHaveBeenCalledWith(
      "/api/profile",
      expect.objectContaining({
        headers: expect.objectContaining({ "If-Match": "1" }),
      }),
    );
    expect(workspace.getSnapshot().detail?.row.id).toBe(1);
    workspace.closeDetail();
    expect(workspace.getSnapshot().detail).toBeNull();
    await workspace.tick();
    expect(workspace.getSnapshot().notice).toBe("Agent cycle completed: {}");
  });
  it.each(["jobs", "contacts"] as const)(
    "reports discovery progress, successful imports, empty results and failures for %s",
    async (kind) => {
      await workspace.unlock("fixture");
      const json = vi.spyOn(workspace.api, "json");
      const base = json.getMockImplementation();
      json.mockImplementation(async (path, ...args) =>
        path.startsWith("/discover/")
          ? ({ imported: 2, reviewed: 3 } as never)
          : base
            ? base(path, ...args)
            : (payload("/api" + path) as never),
      );
      await workspace.discover(kind);
      expect(
        workspace.getSnapshot()[
          kind === "jobs" ? "searchJobs" : "searchContacts"
        ],
      ).toContain("Search complete.");
      json.mockImplementation(
        async (path) =>
          (path.startsWith("/discover/")
            ? { imported: 0, reviewed: 0 }
            : payload("/api" + path)) as never,
      );
      await workspace.discover(kind);
      expect(
        workspace.getSnapshot()[
          kind === "jobs" ? "searchJobs" : "searchContacts"
        ],
      ).toContain("No new");
      json.mockImplementation(async (path) => {
        if (path.startsWith("/discover/"))
          throw new Error("Provider unavailable");
        return payload("/api" + path) as never;
      });
      await workspace.discover(kind);
      expect(workspace.getSnapshot()).toMatchObject({
        pending: false,
        searchingJobs: false,
        searchingContacts: false,
        notice: "Provider unavailable",
      });
    },
  );
  it("never retains discovery progress from an expired session", async () => {
    await workspace.unlock("fixture");
    let finish!: (value: unknown) => void;
    vi.spyOn(workspace.api, "json").mockImplementation(async (path) =>
      path.startsWith("/discover/")
        ? ((await new Promise<unknown>((resolve) => {
            finish = resolve;
          })) as never)
        : (payload("/api" + path) as never),
    );
    const result = workspace.discover("jobs");
    workspace.lock();
    finish({ imported: 1 });
    await result;
    expect(workspace.getSnapshot().searchJobs).toBe("");
  });
  it("recovers monitoring failures and avoids replacing unchanged records", async () => {
    vi.useFakeTimers();
    let fail = false;
    vi.spyOn(workspace.api, "json").mockImplementation(async (path) => {
      if (path === "/worker/status" && fail) throw new Error("Offline");
      return payload("/api" + path) as never;
    });
    await workspace.unlock("fixture");
    await vi.advanceTimersByTimeAsync(10);
    const first = workspace.getSnapshot().worker;
    await vi.advanceTimersByTimeAsync(1000);
    expect(workspace.getSnapshot().worker).toBe(first);
    fail = true;
    await vi.advanceTimersByTimeAsync(1000);
    expect(workspace.getSnapshot().workerError).toContain(
      "Live status unavailable",
    );
    fail = false;
    await vi.advanceTimersByTimeAsync(1000);
    expect(workspace.getSnapshot().workerError).toBe("");
  });
  it("shares photo requests, caches valid content, revokes invalid images and ignores failures", async () => {
    await workspace.unlock("fixture");
    const photo = vi
      .spyOn(workspace.api, "photo")
      .mockResolvedValue(new Blob(["png"]));
    expect(await Promise.all([workspace.photo(1), workspace.photo(1)])).toEqual(
      ["blob:fixture", "blob:fixture"],
    );
    expect(await workspace.photo(1)).toBe("blob:fixture");
    expect(photo).toHaveBeenCalledOnce();
    workspace.discardPhoto(1);
    workspace.discardPhoto(2);
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    photo.mockRejectedValue(new Error("Missing"));
    expect(await workspace.photo(2)).toBeNull();
    let finish!: (value: Blob) => void;
    photo.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const late = workspace.photo(3);
    workspace.lock();
    finish(new Blob(["png"]));
    expect(await late).toBeNull();
  });
  it("downloads and releases object URLs, and explains stale files", async () => {
    vi.useFakeTimers();
    await workspace.unlock("fixture");
    vi.spyOn(workspace.api, "blob").mockResolvedValue(new Blob(["pdf"]));
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    await workspace.download(1, "cv_pdf", "CV.pdf");
    expect(click).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1000);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fixture");
    vi.mocked(workspace.api.blob).mockRejectedValue(new Error("Missing"));
    await expect(workspace.download(1, "cv_pdf", "CV.pdf")).rejects.toThrow(
      "Document is missing or stale",
    );
  });
  it("sends exactly one selected invitation and archives confirmed status", async () => {
    await workspace.unlock("fixture");
    const json = vi.spyOn(workspace.api, "json");
    let finish!: () => void;
    json.mockImplementation(async (path) => {
      if (path.endsWith("/send")) {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return {} as never;
      }
      if (path.endsWith("/status"))
        return {
          ...connection,
          state: "sent",
          run_status: "done",
          run_message: "Confirmed",
        } as never;
      return payload("/api" + path) as never;
    });
    const first = workspace.sendInvitation(1);
    expect(workspace.getSnapshot().feedback[1].run_status).toBe("started");
    await workspace.sendInvitation(2);
    finish();
    await first;
    expect(
      json.mock.calls.filter(([path]) => path.endsWith("/send")),
    ).toHaveLength(1);
    expect(workspace.getSnapshot()).toMatchObject({
      activeInvitation: null,
      notice: "Invitation confirmed. Contact moved to Archived.",
    });
    expect(workspace.getSnapshot().connections[0].state).toBe("sent");
  });
  it.each([
    new ApiError("Scope missing", 409),
    new ApiError("Provider unavailable", 502),
    new Error("Lost response"),
  ])("retains diagnostic without resending: %s", async (error) => {
    await workspace.unlock("fixture");
    const json = vi
      .spyOn(workspace.api, "json")
      .mockImplementation(async (path) => {
        if (path.endsWith("/send")) throw error;
        if (path.endsWith("/status")) throw new Error("Status unavailable");
        return payload("/api" + path) as never;
      });
    await workspace.sendInvitation(1);
    expect(workspace.getSnapshot().feedback[1].run_status).toBe(
      error instanceof ApiError && error.status === 409
        ? "failed"
        : "uncertain",
    );
    expect(
      json.mock.calls.filter(([path]) => path.endsWith("/send")),
    ).toHaveLength(1);
  });
  it("resumes observation after reload and recovers polling errors without sending", async () => {
    vi.useFakeTimers();
    let status: Connection = {
      ...connection,
      state: "sending",
      run_status: "running",
      run_message: "Checking identity",
    };
    let failure = false;
    const json = vi
      .spyOn(workspace.api, "json")
      .mockImplementation(async (path) => {
        if (path === "/connections") return [status] as never;
        if (path.endsWith("/status") && path !== "/worker/status") {
          if (failure) throw new Error("Transient");
          return status as never;
        }
        return payload("/api" + path) as never;
      });
    await workspace.unlock("fixture");
    await vi.advanceTimersByTimeAsync(300);
    expect(workspace.getSnapshot().activeInvitation).toBe(1);
    failure = true;
    await vi.advanceTimersByTimeAsync(700);
    expect(workspace.getSnapshot().activeInvitation).toBe(1);
    failure = false;
    status = { ...status, state: "uncertain", run_status: "uncertain" };
    await vi.advanceTimersByTimeAsync(700);
    expect(workspace.getSnapshot().activeInvitation).toBeNull();
    expect(json.mock.calls.some(([path]) => path.endsWith("/send"))).toBe(
      false,
    );
  });
  it("keeps observing a lost send response that is still running", async () => {
    vi.useFakeTimers();
    await workspace.unlock("fixture");
    let status: Connection = {
      ...connection,
      state: "sending",
      run_status: "running",
    };
    vi.spyOn(workspace.api, "json").mockImplementation(async (path) => {
      if (path.endsWith("/send")) throw new Error("Lost response");
      if (path.endsWith("/status") && path !== "/worker/status")
        return status as never;
      return payload("/api" + path) as never;
    });
    await workspace.sendInvitation(1);
    expect(workspace.getSnapshot().activeInvitation).toBe(1);
    status = { ...status, state: "sent", run_status: "done" };
    await vi.advanceTimersByTimeAsync(700);
    expect(workspace.getSnapshot().activeInvitation).toBeNull();
  });
});
