import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { savedToken } from "../../frontend/src/workspace";
import { errorDetail } from "../../frontend/src/ui";
import { ApiError } from "../../frontend/src/api";
import type {
  ApplicationRecord,
  Connection,
} from "../../frontend/src/contracts";
import { connection } from "./fixtures";
import { application, payload } from "./fixtures";
import { deferred, harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(async () => {
  h = harness();
  await h.unlock();
});
afterEach(() => h.stop());
it("tolerates malformed validation errors and retains useful field locations", () => {
  expect(
    errorDetail(
      {
        detail: [
          null,
          "invalid",
          { loc: ["body", "answers", 2, {}], msg: "Required" },
          { loc: "wrong", msg: 42 },
          {},
        ],
      },
      422,
    ),
  ).toBe(
    "Input: Invalid value; Input: Invalid value; answers / 2: Required; Input: Invalid value; Input: Invalid value",
  );
  expect(errorDetail({ detail: [] }, 500)).toContain("500");
  expect(errorDetail("invalid", 502)).toContain("502");
});
it("unlocks and locks safely when browser storage is unavailable", async () => {
  h.workspace.lock();
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  expect(savedToken()).toBeNull();
  await h.workspace.unlock("fixture");
  expect(h.workspace.getSnapshot().unlocked).toBe(true);
  expect(h.workspace.getSnapshot().notice).toContain("storage is unavailable");
  h.workspace.lock();
  expect(h.workspace.getSnapshot().unlocked).toBe(false);
});
it.each(["navigate", "close", "lock", "newer"])(
  "ignores an obsolete detail response or error after %s",
  async (operation) => {
    const old = deferred<unknown>();
    let held = true;
    vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) => {
      if (path === "/applications/1" && held) {
        held = false;
        return (await old.promise) as never;
      }
      return payload("/api" + path) as never;
    });
    const read = h.workspace.openDetail(1);
    if (operation === "navigate") h.workspace.navigate("settings");
    else if (operation === "close") h.workspace.closeDetail();
    else if (operation === "lock") h.workspace.lock();
    else await h.workspace.openDetail(1);
    old.resolve(application);
    await read;
    expect(h.workspace.getSnapshot().detail).toEqual(
      operation === "newer"
        ? expect.objectContaining({ row: application })
        : null,
    );
  },
);
it("suppresses a stale record failure but surfaces a current failure", async () => {
  const old = deferred<never>();
  vi.spyOn(h.workspace.api, "json").mockReturnValue(old.promise);
  const read = h.workspace.action(() => h.workspace.openRecord(1));
  h.workspace.navigate("settings");
  old.reject(new Error("Old private error"));
  await read;
  expect(h.workspace.getSnapshot().notice).not.toContain("Old private error");
  await h.workspace.action(() => h.workspace.openRecord(1));
  expect(h.workspace.getSnapshot().notice).toBe("Old private error");
});
it("suppresses an obsolete detail failure but retains a current diagnostic", async () => {
  const old = deferred<never>();
  vi.spyOn(h.workspace.api, "json").mockReturnValue(old.promise);
  const read = h.workspace.openDetail(1);
  h.workspace.closeDetail();
  old.reject(new Error("Obsolete"));
  await read;
  await expect(h.workspace.openDetail(1)).rejects.toThrow("Obsolete");
});
it("does not reopen a detail when its mutation finishes after navigation", async () => {
  await h.workspace.openDetail(1);
  const mutation = deferred<unknown>();
  const original = h.workspace.api.json.bind(h.workspace.api);
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path, ...args) =>
    path.endsWith("/prepare")
      ? ((await mutation.promise) as never)
      : original(path, ...args),
  );
  const work = h.workspace.mutate(
    "/applications/1/prepare",
    "POST",
    {},
    "Prepared",
    1,
  );
  h.workspace.navigate("settings");
  mutation.resolve({});
  await work;
  expect(h.workspace.getSnapshot().view).toBe("settings");
});
it("never downloads late private blobs after locking and preserves authentication failures", async () => {
  const blob = deferred<Blob>();
  vi.spyOn(h.workspace.api, "blob").mockReturnValue(blob.promise);
  const download = h.workspace.download(1, "cv_pdf", "CV.pdf");
  const archive = h.workspace.downloadSubmission(1, 1, "cv_pdf", "CV.pdf");
  h.workspace.lock();
  blob.resolve(new Blob(["private"]));
  await Promise.all([download, archive]);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  vi.mocked(h.workspace.api.blob).mockRejectedValue(
    new ApiError("Session expired", 401),
  );
  await expect(h.workspace.download(1, "cv_pdf", "CV.pdf")).rejects.toThrow(
    "Session expired",
  );
});
it("revokes a downloaded blob even if clicking the download fails", async () => {
  vi.useFakeTimers();
  vi.spyOn(h.workspace.api, "blob").mockResolvedValue(new Blob(["PDF"]));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
    throw new Error("Blocked");
  });
  await expect(h.workspace.download(1, "cv_pdf", "CV.pdf")).rejects.toThrow(
    "Blocked",
  );
  h.workspace.lock();
  await vi.advanceTimersByTimeAsync(1000);
  expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
});

const emptyRecord: ApplicationRecord = {
  application,
  dates: { imported_at: null, last_activity_at: null, event_count: 1 },
  attempts: [],
  events: [],
  next_event: 1,
};
it("ignores locked and oversized routes, deduplicates history events, and accepts focus anchors during reads", async () => {
  h.workspace.lock();
  await h.workspace.followRoute();
  await h.workspace.pause();
  await h.unlock();
  history.replaceState(null, "", "#/applications/99999999999999999999");
  await h.workspace.followRoute();
  expect(h.workspace.getSnapshot().view).toBe("overview");
  const result = deferred<unknown>();
  const json = vi
    .spyOn(h.workspace.api, "json")
    .mockReturnValue(result.promise as Promise<never>);
  history.replaceState(null, "", "#/applications/1");
  const read = h.workspace.followRoute();
  await h.workspace.followRoute();
  history.replaceState(null, "", "#main-content");
  await h.workspace.followRoute();
  result.resolve(emptyRecord);
  await read;
  expect(json).toHaveBeenCalledTimes(1);
  expect(h.workspace.getSnapshot().record).toBe(emptyRecord);
  history.replaceState(null, "", "#/applications/1");
  await h.workspace.followRoute();
  expect(json).toHaveBeenCalledTimes(1);
  history.replaceState(null, "", "#/applications/2");
  await h.workspace.followRoute();
  expect(json).toHaveBeenCalledTimes(2);
});
it("never restores an unlock or late worker diagnostic belonging to an earlier session", async () => {
  h.workspace.lock();
  const refreshed = deferred<void>();
  vi.spyOn(h.workspace, "refresh").mockReturnValue(refreshed.promise);
  const unlock = h.workspace.unlock("old");
  h.workspace.lock();
  refreshed.resolve();
  await unlock;
  expect(h.workspace.getSnapshot().unlocked).toBe(false);
  vi.restoreAllMocks();
  const status = deferred<unknown>();
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) =>
    path === "/worker/status"
      ? ((await status.promise) as never)
      : (payload("/api" + path) as never),
  );
  await h.workspace.unlock("fixture");
  h.workspace.lock();
  status.reject(new Error("Late worker failure"));
  await status.promise.catch(() => {});
  await Promise.resolve();
  expect(h.workspace.getSnapshot().workerError).toBe("");
});
it("does not resume polling if the session locks during direct-record restoration", async () => {
  h.workspace.lock();
  history.replaceState(null, "", "#/applications/1");
  const record = deferred<unknown>();
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) =>
    path.endsWith("/record")
      ? ((await record.promise) as never)
      : (payload("/api" + path) as never),
  );
  const unlock = h.workspace.unlock("fixture");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  h.workspace.lock();
  record.resolve(emptyRecord);
  await unlock;
  expect(h.workspace.getSnapshot().unlocked).toBe(false);
});
it("discards an older journal page after a newer record replaces it", async () => {
  h.responses.set("/api/applications/1/record", emptyRecord);
  await h.workspace.openRecord(1);
  const older = deferred<unknown>();
  vi.spyOn(h.workspace.api, "json").mockReturnValue(
    older.promise as Promise<never>,
  );
  const read = h.workspace.olderRecordEvents();
  h.workspace.lock();
  older.resolve({
    ...emptyRecord,
    events: [
      {
        id: 1,
        kind: "imported",
        created: "2026-10-04T10:00:00Z",
        detail: "Old",
      },
    ],
  });
  await read;
  expect(h.workspace.getSnapshot().record).toBeNull();
});
it.each(["after-write", "after-refresh", "error-after-navigation"])(
  "does not republish mutation results: %s",
  async (phase) => {
    await h.workspace.openDetail(1);
    const result = deferred<unknown>();
    const json = vi
      .spyOn(h.workspace.api, "json")
      .mockImplementation(async (path) =>
        path.endsWith("/prepare")
          ? ((await result.promise) as never)
          : (payload("/api" + path) as never),
      );
    if (phase === "after-refresh")
      vi.spyOn(h.workspace, "refresh").mockImplementation(async () =>
        h.workspace.lock(),
      );
    const work = h.workspace.mutate(
      "/applications/1/prepare",
      "POST",
      {},
      "Private success",
      1,
    );
    if (phase === "after-write") {
      h.workspace.lock();
      result.resolve({});
    } else if (phase === "error-after-navigation") {
      h.workspace.navigate("settings");
      result.reject(new Error("Provider stopped"));
    } else result.resolve({});
    await work.catch(() => {});
    expect(h.workspace.getSnapshot().notice).not.toBe("Private success");
    expect(
      json.mock.calls.filter(([path]) => path.endsWith("/prepare")),
    ).toHaveLength(1);
  },
);
it("ignores a late detail and late search success after the token epoch changes", async () => {
  const result = deferred<unknown>();
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) =>
    path === "/applications/1"
      ? ((await result.promise) as never)
      : (payload("/api" + path) as never),
  );
  const read = h.workspace.openDetail(1);
  h.workspace.api.setToken("replacement");
  result.resolve(application);
  await read;
  expect(h.workspace.getSnapshot().detail).toBeNull();
  vi.restoreAllMocks();
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) =>
    path.startsWith("/discover")
      ? ({ imported: 1 } as never)
      : (payload("/api" + path) as never),
  );
  vi.spyOn(h.workspace, "refresh").mockImplementation(async () =>
    h.workspace.lock(),
  );
  await h.workspace.discover("jobs");
  expect(h.workspace.getSnapshot().searchJobs).toBe("");
});
it("polls a selected invitation during a slow send without disturbing another contact or resending", async () => {
  h.workspace.lock();
  vi.useFakeTimers();
  h.responses.set("/api/connections", [connection, { ...connection, id: 2 }]);
  await h.workspace.unlock("fixture");
  const send = deferred<unknown>();
  let status: Connection = connection;
  const json = vi
    .spyOn(h.workspace.api, "json")
    .mockImplementation(async (path) =>
      path.endsWith("/send")
        ? ((await send.promise) as never)
        : path === "/connections/1/status"
          ? (status as never)
          : (payload("/api" + path) as never),
    );
  const work = h.workspace.sendInvitation(1);
  await vi.advanceTimersByTimeAsync(300);
  expect(h.workspace.getSnapshot().activeInvitation).toBe(1);
  status = { ...connection, state: "sending", run_status: "running" };
  await vi.advanceTimersByTimeAsync(700);
  expect(h.workspace.getSnapshot().connections[1].id).toBe(2);
  expect(h.workspace.getSnapshot().connections[0].state).toBe("sending");
  status = { ...connection, state: "sent", run_status: "done" };
  send.resolve({});
  await work;
  expect(h.workspace.getSnapshot().activeInvitation).toBeNull();
  expect(
    json.mock.calls.filter(([path]) => path.endsWith("/send")),
  ).toHaveLength(1);
});
it.each([
  "send-success",
  "send-failure",
  "poll-success",
  "poll-failure",
  "final-status",
])(
  "drops obsolete invitation observations after locking: %s",
  async (phase) => {
    h.workspace.lock();
    vi.useFakeTimers();
    await h.workspace.unlock("fixture");
    const sending = deferred<unknown>();
    const status = deferred<unknown>();
    let statusCalls = 0;
    vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) => {
      if (path.endsWith("/send")) return (await sending.promise) as never;
      if (path === "/connections/1/status") {
        statusCalls++;
        return (await status.promise) as never;
      }
      return payload("/api" + path) as never;
    });
    const work = h.workspace.sendInvitation(1);
    if (phase.startsWith("poll")) await vi.advanceTimersByTimeAsync(300);
    if (phase === "final-status") {
      sending.resolve({});
      await Promise.resolve();
      await Promise.resolve();
      expect(statusCalls).toBe(1);
    }
    h.workspace.lock();
    if (phase === "send-failure")
      sending.reject(new ApiError("Late send failure"));
    else sending.resolve({});
    if (phase === "poll-failure")
      status.reject(new Error("Late observation failure"));
    else status.resolve(connection);
    await work;
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.workspace.getSnapshot()).toMatchObject({
      connections: [],
      notice: "",
      feedback: {},
      activeInvitation: null,
    });
  },
);
it("retains idle status feedback when the provider has not started the invitation", async () => {
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) => {
    if (path.endsWith("/send")) throw new ApiError("Unavailable");
    return payload("/api" + path) as never;
  });
  await h.workspace.sendInvitation(1);
  expect(h.workspace.getSnapshot().feedback[1].run_status).toBe("uncertain");
});

it("does not show a discovery error after locking the session that requested it", async () => {
  const result = deferred<never>();
  vi.spyOn(h.workspace.api, "json").mockImplementation(async (path) =>
    path.startsWith("/discover")
      ? result.promise
      : (payload("/api" + path) as never),
  );
  const search = h.workspace.discover("jobs");
  h.workspace.lock();
  result.reject(new Error("Old discovery failure"));
  await search;
  expect(h.workspace.getSnapshot()).toMatchObject({
    notice: "",
    searchJobs: "",
    searchingJobs: false,
  });
});
