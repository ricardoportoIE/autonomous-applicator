import { ApiClient, ApiError } from "./api";
import type {
  Application,
  ApplicationDetail,
  ApplicationRecord,
  Connection,
  Event,
  Insights,
  Profile,
  Settings,
  Usage,
  View,
  WorkerRecord,
} from "./contracts";

export interface WorkspaceState {
  unlocked: boolean;
  pending: boolean;
  automationChanging: "starting" | "pausing" | null;
  view: View;
  notice: string;
  error: boolean;
  settings: Settings | null;
  profile: Profile | null;
  revision: number;
  applications: Application[];
  connections: Connection[];
  events: Event[];
  usage: Usage | null;
  insights: Insights | null;
  detail: ApplicationDetail | null;
  record: ApplicationRecord | null;
  worker: WorkerRecord | null;
  workerError: string;
  searchJobs: string;
  searchContacts: string;
  searchingJobs: boolean;
  searchingContacts: boolean;
  activeInvitation: number | null;
  feedback: Record<number, { run_status: string; run_message: string }>;
}
const empty = (): WorkspaceState => ({
  unlocked: false,
  pending: false,
  automationChanging: null,
  view: "overview",
  notice: "",
  error: false,
  settings: null,
  profile: null,
  revision: 0,
  applications: [],
  connections: [],
  events: [],
  usage: null,
  insights: null,
  detail: null,
  record: null,
  worker: null,
  workerError: "",
  searchJobs: "",
  searchContacts: "",
  searchingJobs: false,
  searchingContacts: false,
  activeInvitation: null,
  feedback: {},
});
const reason = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The operation could not be completed.";

/** Storage may be disabled by browser privacy settings; sessions still work in memory. */
export function savedToken() {
  try {
    return sessionStorage.getItem("applicator-token");
  } catch {
    return null;
  }
}
const views: View[] = [
  "overview",
  "applications",
  "profile",
  "networking",
  "settings",
  "activity",
];

/** React subscribes to immutable snapshots. Timers and asynchronous ownership live here. */
export class Workspace {
  private state = empty();
  private refreshSequence = 0;
  private recordSequence = 0;
  private detailSequence = 0;
  private recordLoading: number | null = null;
  private downloadUrls = new Set<string>();
  private listeners = new Set<() => void>();
  readonly api = new ApiClient((message) => {
    this.lock();
    this.message(message, true);
  });
  private workerTimer: ReturnType<typeof setTimeout> | undefined;
  private invitationTimer: ReturnType<typeof setTimeout> | undefined;
  private invitation: {
    id: number;
    session: number;
    responseFinished: boolean;
  } | null = null;
  private photos = new Map<number, string>();
  private photoRequests = new Map<number, Promise<string | null>>();
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private update(change: Partial<WorkspaceState>) {
    this.state = { ...this.state, ...change };
    this.listeners.forEach((fn) => fn());
  }
  message(notice: string, error = false) {
    this.update({ notice, error });
  }
  navigate(view: View, updateUrl = true) {
    this.recordSequence++;
    this.detailSequence++;
    this.recordLoading = null;
    if (updateUrl) history.pushState(null, "", "#" + view);
    this.update({ view });
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }
  lock() {
    this.recordSequence++;
    this.detailSequence++;
    this.recordLoading = null;
    this.api.setToken("");
    try {
      sessionStorage.removeItem("applicator-token");
    } catch {
      /* In-memory lock remains effective. */
    }
    clearTimeout(this.workerTimer);
    clearTimeout(this.invitationTimer);
    this.invitation = null;
    this.photos.forEach((url) => URL.revokeObjectURL(url));
    this.photos.clear();
    this.photoRequests.clear();
    this.downloadUrls.forEach((url) => URL.revokeObjectURL(url));
    this.downloadUrls.clear();
    this.state = empty();
    this.listeners.forEach((fn) => fn());
  }
  async action(callback: () => Promise<void>, duringBusy = false) {
    if (this.state.pending && !duringBusy) return;
    const owns = !this.state.pending;
    const session = this.api.session();
    if (owns) this.update({ pending: true });
    try {
      await callback();
    } catch (error) {
      // A lock or replacement session must never receive old notices or private data.
      if (this.api.session() === session) this.message(reason(error), true);
    } finally {
      if (owns && this.api.session() === session)
        this.update({ pending: false });
    }
  }
  async unlock(token: string, restored = false) {
    if (this.state.pending) return;
    this.api.setToken(token);
    const session = this.api.session();
    await this.action(async () => {
      await this.refresh();
      if (!this.api.isCurrent(session)) return;
      let remembered = true;
      try {
        sessionStorage.setItem("applicator-token", token);
      } catch {
        remembered = false;
      }
      this.update({ unlocked: true });
      await this.followRoute();
      if (!this.api.isCurrent(session)) return;
      if (!remembered)
        this.message(
          "Local workspace unlocked. Browser storage is unavailable; unlock again after reloading.",
        );
      else if (!restored) this.message("Local workspace unlocked.");
      this.pollWorker();
      const running = this.state.connections.find(
        (item) => item.state === "sending",
      );
      if (running) void this.sendInvitation(running.id, true);
    });
  }
  async followRoute() {
    if (!this.state.unlocked) return;
    const match = window.location.hash.match(/^#\/applications\/([1-9]\d*)$/);
    if (match && Number.isSafeInteger(Number(match[1]))) {
      const id = Number(match[1]);
      if (this.state.view === "record" && this.recordLoading === id) return;
      if (
        this.state.view !== "record" ||
        this.state.record?.application.id !== id
      )
        await this.openRecord(id, false);
    } else {
      const view = window.location.hash.slice(1) as View;
      if (views.includes(view) && this.state.view !== view)
        this.navigate(view, false);
    }
  }
  async refresh() {
    const session = this.api.session();
    const sequence = ++this.refreshSequence;
    const [
      settings,
      applications,
      usage,
      insights,
      events,
      connections,
      record,
    ] = await Promise.all([
      this.api.json<Settings>("/settings"),
      this.api.json<Application[]>("/applications"),
      this.api.json<Usage>("/usage"),
      this.api.json<Insights>("/insights"),
      this.api.json<Event[]>("/events"),
      this.api.json<Connection[]>("/connections"),
      this.api
        .json<{ profile: Profile; revision: number }>("/profile")
        .catch((error) => {
          if (reason(error).includes("Configure a candidate profile first"))
            return null;
          throw error;
        }),
    ]);
    if (this.api.isCurrent(session) && sequence === this.refreshSequence)
      this.update({
        settings,
        applications,
        usage,
        insights,
        events,
        connections,
        profile: record?.profile ?? null,
        revision: record?.revision ?? 0,
      });
  }
  private pollWorker() {
    clearTimeout(this.workerTimer);
    const session = this.api.session();
    const poll = async () => {
      try {
        const record = await this.api.json<WorkerRecord>("/worker/status");
        if (this.api.isCurrent(session))
          this.update({
            worker:
              JSON.stringify(record) === JSON.stringify(this.state.worker)
                ? this.state.worker
                : record,
            workerError: "",
          });
      } catch (error) {
        if (this.api.isCurrent(session))
          this.update({
            workerError: "Live status unavailable: " + reason(error),
          });
      }
      if (this.api.isCurrent(session))
        this.workerTimer = setTimeout(() => void poll(), 1000);
    };
    void poll();
  }
  async openDetail(id: number) {
    const sequence = ++this.detailSequence;
    const session = this.api.session();
    const profile_revision = this.state.revision;
    try {
      const [row, report, events] = await Promise.all([
        this.api.json<Application>(`/applications/${id}`),
        this.api.json<ApplicationDetail["report"]>(
          `/applications/${id}/preflight`,
        ),
        this.api.json<Event[]>(`/applications/${id}/events`),
      ]);
      if (sequence !== this.detailSequence || !this.api.isCurrent(session))
        return;
      this.recordSequence++;
      this.update({
        view: "applications",
        detail: { row, report, events, profile_revision },
      });
    } catch (error) {
      if (sequence === this.detailSequence && this.api.isCurrent(session))
        throw error;
    }
  }
  async openRecord(id: number, updateUrl = true) {
    const sequence = ++this.recordSequence;
    this.recordLoading = id;
    this.detailSequence++;
    const session = this.api.session();
    if (updateUrl) history.pushState(null, "", `#/applications/${id}`);
    this.update({ view: "record", record: null });
    try {
      const record = await this.api.json<ApplicationRecord>(
        `/applications/${id}/record`,
      );
      if (sequence === this.recordSequence && this.api.isCurrent(session))
        this.update({ record });
    } catch (error) {
      if (sequence === this.recordSequence && this.api.isCurrent(session))
        throw error;
    } finally {
      if (sequence === this.recordSequence) this.recordLoading = null;
    }
  }
  async olderRecordEvents() {
    const record = this.state.record;
    if (!record?.next_event) return;
    const session = this.api.session();
    const older = await this.api.json<ApplicationRecord>(
      `/applications/${record.application.id}/record?before=${record.next_event}`,
    );
    if (this.api.isCurrent(session) && this.state.record === record)
      this.update({
        record: {
          ...record,
          events: [...record.events, ...older.events],
          next_event: older.next_event,
        },
      });
  }
  async downloadSubmission(
    id: number,
    attempt: number,
    key: string,
    filename: string,
  ) {
    const session = this.api.session();
    const blob = await this.api.blob(
      `/applications/${id}/submissions/${attempt}/artifacts/${encodeURIComponent(key)}`,
    );
    if (this.api.isCurrent(session)) this.saveBlob(blob, filename);
  }
  private saveBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    this.downloadUrls.add(url);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    try {
      link.click();
    } finally {
      setTimeout(() => {
        if (this.downloadUrls.delete(url)) URL.revokeObjectURL(url);
      }, 1000);
    }
  }
  closeDetail() {
    this.detailSequence++;
    this.update({ detail: null });
  }
  async mutate(
    path: string,
    method: string,
    body: unknown,
    notice: string,
    detailId?: number,
    profileRevision = this.state.revision,
  ) {
    const session = this.api.session();
    const view = this.state.view;
    const detailSequence = this.detailSequence;
    const canRefreshDetail = () =>
      this.api.isCurrent(session) &&
      this.state.view === view &&
      this.detailSequence === detailSequence;
    try {
      await this.api.json(
        path,
        method,
        body,
        path === "/profile" || path.endsWith("/answer")
          ? profileRevision
          : undefined,
      );
    } catch (error) {
      // Preparation/submission may have recorded a review or receipt before failing.
      // Reconcile the displayed snapshot through reads, without repeating the action.
      if (
        detailId !== undefined &&
        this.api.isCurrent(session) &&
        this.state.unlocked
      ) {
        try {
          await this.refresh();
          if (canRefreshDetail()) await this.openDetail(detailId);
        } catch {
          /* Keep the original actionable diagnostic. */
        }
      }
      throw error;
    }
    if (!this.api.isCurrent(session)) return;
    await this.refresh();
    if (detailId !== undefined && canRefreshDetail())
      await this.openDetail(detailId);
    if (this.api.isCurrent(session)) this.message(notice);
  }
  pause() {
    return this.action(async () => {
      if (this.state.settings)
        await this.mutate(
          "/settings",
          "PUT",
          {
            ...this.state.settings,
            automation_enabled: false,
          },
          "Automation paused. An external action already in flight may finish.",
        );
    }, true);
  }
  async toggleAutomation() {
    if (this.state.automationChanging || !this.state.settings) return;
    const session = this.api.session();
    this.update({
      automationChanging: this.state.settings.automation_enabled
        ? "pausing"
        : "starting",
    });
    try {
      if (this.state.settings.automation_enabled) await this.pause();
      else
        await this.action(async () => {
          await this.mutate(
            "/worker/start",
            "POST",
            undefined,
            "Agent started. The FIFO queue will resume in the background.",
          );
        }, true);
    } finally {
      if (this.api.isCurrent(session))
        this.update({ automationChanging: null });
    }
  }
  tick() {
    return this.action(async () => {
      const result = await this.api.json("/worker/tick", "POST");
      await this.refresh();
      this.message("Agent cycle completed: " + JSON.stringify(result));
    });
  }
  discover(kind: "jobs" | "contacts") {
    return this.action(async () => {
      const session = this.api.session();
      const jobs = kind === "jobs";
      this.update(
        jobs
          ? {
              searchingJobs: true,
              searchJobs: "Searching LinkedIn and reading job details…",
            }
          : {
              searchingContacts: true,
              searchContacts: `Searching for up to ${this.state.settings?.daily_connection_limit} new European hiring contacts…`,
            },
      );
      try {
        const result = await this.api.json<{
          imported?: number;
          reviewed?: number;
          discarded?: number;
        }>("/discover/" + (jobs ? "linkedin" : "contacts"), "POST");
        await this.refresh();
        if (!this.api.isCurrent(session)) return;
        if (jobs) {
          const summary = result.imported
            ? `Search complete. ${result.imported} new opportunities imported.`
            : "Search complete. No new opportunities to import; results may already be in your queue or excluded by discovery screening.";
          this.update({
            searchJobs:
              summary +
              (result.discarded
                ? ` ${result.discarded} below-fit opportunities discarded (under 50/100).`
                : ""),
          });
          this.message(`Imported ${result.imported} LinkedIn opportunities.`);
        } else {
          this.update({
            searchContacts: result.reviewed
              ? `Search complete. ${result.reviewed} new European hiring contacts found.`
              : "Search complete. No new matching contacts were found in the available results.",
          });
          this.message(`Reviewed ${result.reviewed} European hiring contacts.`);
        }
      } catch (error) {
        if (this.api.isCurrent(session))
          this.update(
            jobs
              ? {
                  searchJobs:
                    "Search failed. Check the message above, then try again.",
                }
              : {
                  searchContacts:
                    "Search failed. Check the message above, then try again.",
                },
          );
        throw error;
      } finally {
        if (this.api.isCurrent(session))
          this.update(
            jobs ? { searchingJobs: false } : { searchingContacts: false },
          );
      }
    });
  }
  async photo(id: number): Promise<string | null> {
    if (this.photos.has(id)) return this.photos.get(id)!;
    if (this.photoRequests.has(id)) return this.photoRequests.get(id)!;
    const session = this.api.session();
    const request = this.api
      .photo(id)
      .then((blob) => {
        if (!this.api.isCurrent(session)) return null;
        const url = URL.createObjectURL(blob);
        this.photos.set(id, url);
        return url;
      })
      .catch(() => null)
      .finally(() => {
        if (this.photoRequests.get(id) === request)
          this.photoRequests.delete(id);
      });
    this.photoRequests.set(id, request);
    return request;
  }
  discardPhoto(id: number) {
    const url = this.photos.get(id);
    if (url) URL.revokeObjectURL(url);
    this.photos.delete(id);
  }
  async download(id: number, key: string, filename: string) {
    const session = this.api.session();
    let blob: Blob;
    try {
      blob = await this.api.blob(
        `/applications/${id}/documents/${encodeURIComponent(key)}`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      throw new Error("Document is missing or stale. Regenerate it.", {
        cause: error,
      });
    }
    if (this.api.isCurrent(session)) this.saveBlob(blob, filename);
  }
  async sendInvitation(id: number, observeOnly = false) {
    if (this.invitation) return;
    const operation = {
      id,
      session: this.api.session(),
      responseFinished: false,
    };
    this.invitation = operation;
    this.update({
      activeInvitation: id,
      feedback: observeOnly
        ? this.state.feedback
        : {
            ...this.state.feedback,
            [id]: {
              run_status: "started",
              run_message:
                "Starting this invitation in the visible LinkedIn browser.",
            },
          },
    });
    const current = () =>
      this.invitation === operation && this.api.isCurrent(operation.session);
    const apply = (item: Connection) => {
      const feedback = { ...this.state.feedback };
      if (item.run_status !== "idle") delete feedback[id];
      this.update({
        connections: this.state.connections.map((row) =>
          row.id === id ? item : row,
        ),
        feedback,
      });
    };
    const finish = () => {
      this.invitation = null;
      this.update({ activeInvitation: null });
    };
    const poll = async () => {
      try {
        const item = await this.api.json<Connection>(
          `/connections/${id}/status`,
        );
        if (!current()) return;
        if (item.run_status !== "idle") apply(item);
        if (operation.responseFinished && item.state !== "sending") {
          finish();
          return;
        }
      } catch {
        /* Observation failures never retry a send. */
      }
      if (current()) this.invitationTimer = setTimeout(() => void poll(), 700);
    };
    this.invitationTimer = setTimeout(() => void poll(), 300);
    try {
      if (!observeOnly) {
        await this.api.json(`/connections/${id}/send`, "POST");
        if (current())
          this.message("Invitation confirmed. Contact moved to Archived.");
      }
    } catch (error) {
      if (current()) {
        this.update({
          feedback: {
            ...this.state.feedback,
            [id]: {
              run_status:
                !(error instanceof ApiError) ||
                !error.status ||
                error.status >= 500
                  ? "uncertain"
                  : "failed",
              run_message: reason(error),
            },
          },
        });
        this.message(reason(error), true);
      }
    } finally {
      operation.responseFinished = true;
      clearTimeout(this.invitationTimer);
      if (current()) {
        let running =
          observeOnly ||
          this.state.connections.some(
            (row) => row.id === id && row.state === "sending",
          );
        try {
          const item = await this.api.json<Connection>(
            `/connections/${id}/status`,
          );
          if (current()) {
            apply(item);
            running = item.state === "sending";
          }
        } catch {
          /* Retain the last safe diagnostic. */
        }
        if (current()) {
          if (running)
            this.invitationTimer = setTimeout(() => void poll(), 700);
          else finish();
        }
      }
    }
  }
}
