import { useEffect, useState, useSyncExternalStore } from "react";
import {
  LayoutDashboard,
  BriefcaseBusiness,
  UserRound,
  UsersRound,
  SlidersHorizontal,
  ScrollText,
  LockKeyhole,
  CirclePause,
  Sparkles,
  ArrowUpRight,
} from "lucide-react";
import {
  AddButton,
  ApplicationTable,
  Badge,
  Events,
  Modal,
  Panel,
  WorkerMonitor,
} from "./components";
import { ApplicationDetails } from "./application-detail";
import {
  BoardForm,
  ContactForm,
  EvidenceForm,
  JobForm,
  ProfileForm,
  SettingsForm,
} from "./forms";
import { Networking } from "./networking";
import { filterApplications } from "./ui";
import { Workspace } from "./workspace";
import type { Application, Evidence, Profile, View } from "./contracts";

const navigation = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "applications", label: "Applications", icon: BriefcaseBusiness },
  { id: "profile", label: "Candidate profile", icon: UserRound },
  { id: "networking", label: "Networking", icon: UsersRound },
  { id: "settings", label: "Agent settings", icon: SlidersHorizontal },
  { id: "activity", label: "Activity log", icon: ScrollText },
] as const;
type Dialogue =
  | { kind: "contact" | "board" }
  | { kind: "profile"; profile: Profile | null; revision: number }
  | { kind: "job"; application: Application | null }
  | { kind: "evidence"; evidence: Evidence | null };

export function App({ workspace }: { workspace: Workspace }) {
  const state = useSyncExternalStore(
    workspace.subscribe,
    workspace.getSnapshot,
  );
  const [token, setToken] = useState("");
  const [modal, setModal] = useState<Dialogue | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("recent");
  const current = navigation.find((item) => item.id === state.view)!;
  useEffect(() => {
    const saved = sessionStorage.getItem("applicator-token");
    if (saved) void workspace.unlock(saved, true);
    return () => workspace.lock();
  }, [workspace]);
  useEffect(() => {
    if (!state.unlocked) {
      setModal(null);
      setToken("");
      setQuery("");
      setFilter("all");
      setSort("recent");
    }
  }, [state.unlocked]);
  const open = (value: Dialogue) => {
    workspace.message("");
    setModal(value);
  };
  const rows = filterApplications(state.applications, {
    query,
    state: filter,
    sort,
  });
  const openDetail = (id: number) =>
    void workspace.action(async () => {
      await workspace.openDetail(id);
      document
        .getElementById("application-detail")
        ?.scrollIntoView({ behavior: "instant", block: "start" });
    });
  const { settings, profile, usage } = state;
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#main-content">
          <span className="brand-mark">
            a<span>+</span>
          </span>
          <span>
            Autonomous
            <br />
            Applicator
          </span>
        </a>
        <p className="eyebrow">Your career workspace</p>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              type="button"
              key={item.id}
              data-view={item.id}
              className={state.view === item.id ? "active" : ""}
              aria-current={state.view === item.id ? "page" : undefined}
              onClick={() => workspace.navigate(item.id as View)}
            >
              <item.icon size={20} className="nav-icon" aria-hidden="true" />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local">
            <span className="local-dot" />
            Local by design
          </div>
          <p>
            Approved facts. Clear decisions.
            <br />
            One opportunity at a time.
          </p>
          <small>English UK · Europe/London</small>
        </div>
      </aside>
      <main id="main-content" className="main" tabIndex={-1}>
        <header className="topbar">
          <div>
            <p className="eyebrow">
              A little more clarity. A better next step.
            </p>
            <h1 id="page-title">{current.label}</h1>
          </div>
          <div className="topbar-actions">
            <button
              id="lock"
              className="secondary"
              hidden={!state.unlocked}
              type="button"
              onClick={() => {
                workspace.lock();
                workspace.message("Workspace locked on this tab.");
              }}
            >
              <LockKeyhole size={16} aria-hidden="true" />
              Lock workspace
            </button>
            <button
              id="pause"
              className="danger"
              type="button"
              disabled={!state.unlocked}
              onClick={() => void workspace.pause()}
            >
              <CirclePause size={16} aria-hidden="true" />
              {settings?.automation_enabled
                ? "Pause all automation"
                : "Automation paused"}
            </button>
          </div>
        </header>
        <div
          id="notice"
          role="status"
          aria-live="polite"
          className={state.error ? "error notice" : "notice"}
        >
          {state.notice}
        </div>
        <section
          id="login"
          className="panel lock-panel"
          hidden={state.unlocked}
        >
          <div className="lock-illustration">
            <LockKeyhole size={32} aria-hidden="true" />
          </div>
          <p className="eyebrow">Private, local, yours</p>
          <h2>Connect to your local workspace</h2>
          <p>
            Unlock your candidate record, application queue and agent controls
            with the local access token.
          </p>
          <form
            id="token-form"
            onSubmit={(event) => {
              event.preventDefault();
              void workspace.unlock(token).then(() => {
                if (workspace.getSnapshot().unlocked) setToken("");
              });
            }}
          >
            <label>
              Access token
              <input
                id="token"
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                required
                autoComplete="off"
              />
            </label>
            <button disabled={state.pending}>
              {state.pending ? "Unlocking…" : "Unlock workspace"}
            </button>
          </form>
        </section>
        <fieldset
          id="workspace"
          className="workspace"
          hidden={!state.unlocked}
          disabled={state.pending}
          aria-busy={state.pending || undefined}
        >
          <legend className="sr-only">Local career workspace</legend>
          <div id="readiness" className="readiness" role="status">
            {settings && usage && (
              <>
                <strong>
                  <span
                    className={
                      "status-dot " +
                      (settings.automation_enabled ? "enabled" : "")
                    }
                  />
                  {settings.automation_enabled
                    ? "Agent enabled"
                    : "Agent paused"}
                </strong>
                <Badge
                  state={settings.linkedin_authorised ? "ready" : "review"}
                >
                  {settings.linkedin_authorised
                    ? "LinkedIn scope configured"
                    : "LinkedIn scope needed"}
                </Badge>
                <Badge state={profile?.confirmed ? "ready" : "review"}>
                  {profile?.confirmed
                    ? "Profile confirmed"
                    : "Profile review needed"}
                </Badge>
                <Badge>{usage.remaining} sending slots remaining today</Badge>
              </>
            )}
          </div>
          {state.unlocked ? (
            <WorkerMonitor record={state.worker} error={state.workerError} />
          ) : (
            <>
              <div id="worker-status" />
              <div id="worker-clock" />
              <div id="worker-results" />
            </>
          )}
          <section data-section="overview" hidden={state.view !== "overview"}>
            <div className="overview-hero">
              <div>
                <p className="eyebrow">Your next chapter</p>
                <h2>Make every opportunity count.</h2>
                <p>
                  A thoughtful application starts with your real experience.
                  Track progress, review decisions and keep your next move in
                  focus.
                </p>
                <button
                  id="tick"
                  type="button"
                  onClick={() => void workspace.tick()}
                >
                  <Sparkles size={16} aria-hidden="true" />
                  Run agent cycle
                </button>
              </div>
              <div className="hero-orbit" aria-hidden="true">
                <span className="orbit-ring" />
                <span className="orbit-core">
                  <ArrowUpRight size={52} />
                </span>
                <span className="orbit-label">Clarity → opportunity</span>
              </div>
            </div>
            <div className="stats" id="stats">
              {state.unlocked &&
                [
                  ["Opportunities", state.applications.length],
                  [
                    "Ready",
                    state.applications.filter((a) => a.state === "ready")
                      .length,
                  ],
                  [
                    "For review",
                    state.applications.filter((a) => a.state === "review")
                      .length,
                  ],
                  [
                    "Submitted",
                    state.applications.filter((a) => a.state === "submitted")
                      .length,
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="stat">
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
            </div>
            <div className="two">
              <Panel
                title="Know your remaining capacity"
                eyebrow="Today’s budget"
              >
                <div id="daily-usage">
                  {usage && (
                    <>
                      <strong className="usage-number">
                        {usage.used} / {usage.limit} applications sent
                      </strong>
                      <p>
                        {usage.remaining} sending slots remaining · {usage.day}
                      </p>
                      {(usage.held ?? 0) > 0 && (
                        <p>
                          {usage.held} sending slots held for pending or
                          uncertain submissions.
                        </p>
                      )}
                      <progress
                        max={usage.limit}
                        value={Math.min(usage.used, usage.limit)}
                        aria-label="Daily confirmed application usage"
                      />
                    </>
                  )}
                </div>
                <p>
                  The limit applies to confirmed sends. Queue planning and
                  document preparation continue when full. Pending or uncertain
                  sends hold capacity separately. Limits reset at midnight in
                  Europe/London.
                </p>
              </Panel>
              <Panel
                title="Your application policy"
                eyebrow="A considered decision"
              >
                <div id="policy-bands" className="bands">
                  {settings &&
                    [
                      [
                        settings.auto_threshold + "–100",
                        "Automatic, when every gate passes",
                      ],
                      [
                        settings.review_threshold +
                          "–" +
                          (settings.auto_threshold - 1),
                        "Candidate review",
                      ],
                      [
                        "0–" + (settings.review_threshold - 1),
                        "Not prioritised",
                      ],
                    ].map(([range, label]) => (
                      <p key={range}>
                        <b>{range}</b>
                        <span>{label}</span>
                      </p>
                    ))}
                </div>
                <p>
                  Fit is a heuristic, not a hiring probability or an ATS score.
                  Eligibility and approved answers remain mandatory.
                </p>
              </Panel>
            </div>
            <Panel
              title="Recent opportunities"
              eyebrow="The next step is here"
              action={
                <button
                  id="view-queue"
                  type="button"
                  className="secondary"
                  onClick={() => workspace.navigate("applications")}
                >
                  View application queue
                </button>
              }
            >
              <div id="recent">
                {state.unlocked && (
                  <ApplicationTable
                    rows={state.applications.slice(0, 5)}
                    onOpen={openDetail}
                  />
                )}
              </div>
            </Panel>
            <Panel
              title="Learn from the record"
              eyebrow="Patterns with perspective"
            >
              <div id="insights">
                {state.insights && (
                  <>
                    <p>{state.insights.suggestion}</p>
                    <div className="insight-metrics">
                      {[
                        ["interview", "Interviews"],
                        ["offer", "Offers"],
                        ["rejected", "Rejections"],
                      ].map(([key, label]) => (
                        <div key={key}>
                          <strong>{state.insights!.outcomes[key]}</strong>
                          <small>{label}</small>
                        </div>
                      ))}
                    </div>
                    <p>
                      Suggestions never change your qualifications, immigration
                      answers or submission permissions automatically. Recorded
                      outcomes support candidate-approved improvements.
                    </p>
                  </>
                )}
              </div>
            </Panel>
          </section>
          <section
            data-section="applications"
            hidden={state.view !== "applications"}
          >
            <Panel
              title="Discover jobs"
              eyebrow="Find your next fit"
              action={
                <AddButton
                  onClick={() => open({ kind: "job", application: null })}
                >
                  Add opportunity
                </AddButton>
              }
            >
              <p>
                Use an employer’s public Greenhouse board identifier or your
                configured LinkedIn search.
              </p>
              <div className="discovery-actions">
                <button
                  id="linkedin-search"
                  type="button"
                  aria-busy={state.searchingJobs || undefined}
                  onClick={() => void workspace.discover("jobs")}
                >
                  {state.searchingJobs ? "Searching…" : "Search LinkedIn"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => open({ kind: "board" })}
                >
                  Import from Greenhouse
                </button>
              </div>
              <p
                id="linkedin-search-status"
                role="status"
                aria-live="polite"
                className="search-status"
              >
                {state.searchJobs}
              </p>
              <details className="help-details">
                <summary>Discovery and local browser access</summary>
                <p>
                  Sign in locally first with{" "}
                  <code>applicator browser-login</code>. Discovery does not
                  submit applications.
                </p>
                <p>
                  Search uses the keywords and location saved in Agent settings.
                </p>
              </details>
            </Panel>
            <Panel
              title="Application queue"
              eyebrow="An organised path forward"
            >
              <div className="queue-tools">
                <label>
                  Search opportunities
                  <input
                    id="queue-search"
                    type="search"
                    maxLength={200}
                    placeholder="Role, company or location"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </label>
                <label>
                  Application status
                  <select
                    id="queue-state"
                    aria-label="Application status"
                    value={filter}
                    onChange={(event) => setFilter(event.target.value)}
                  >
                    {[
                      ["all", "All statuses"],
                      ["ready", "Ready"],
                      ["review", "For review"],
                      ["skipped", "Not prioritised"],
                      ["submitting", "Submitting"],
                      ["submitted", "Submitted"],
                      ["uncertain", "Needs reconciliation"],
                    ].map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Sort opportunities
                  <select
                    id="queue-sort"
                    aria-label="Sort opportunities"
                    value={sort}
                    onChange={(event) => setSort(event.target.value)}
                  >
                    <option value="recent">Newest first</option>
                    <option value="fit">Highest fit first</option>
                    <option value="company">Company A–Z</option>
                  </select>
                </label>
                <button
                  id="queue-clear"
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                    setSort("recent");
                  }}
                >
                  Clear filters
                </button>
              </div>
              <p id="queue-count" role="status">
                {state.unlocked
                  ? `${rows.length} of ${state.applications.length} opportunities shown`
                  : ""}
              </p>
              <div id="application-list">
                {state.unlocked && (
                  <ApplicationTable
                    rows={rows}
                    onOpen={openDetail}
                    empty={
                      state.applications.length
                        ? "No opportunities match these filters. Try another search or clear the filters."
                        : undefined
                    }
                  />
                )}
              </div>
            </Panel>
            {state.detail ? (
              <ApplicationDetails
                key={state.detail.row.id}
                detail={state.detail}
                workspace={workspace}
                profile={profile}
                edit={(application) => open({ kind: "job", application })}
              />
            ) : (
              <article id="application-detail" hidden />
            )}
          </section>
          <section data-section="profile" hidden={state.view !== "profile"}>
            <Panel
              title="Your candidate record"
              eyebrow="The story only you can approve"
              action={
                <AddButton
                  onClick={() =>
                    open({ kind: "profile", profile, revision: state.revision })
                  }
                >
                  {profile ? "Edit candidate profile" : "Add candidate profile"}
                </AddButton>
              }
            >
              <p>
                Confirm facts before enabling automation. Editing the profile
                invalidates earlier documents.
              </p>
              {profile ? (
                <div className="profile-record">
                  <div className="profile-monogram" aria-hidden="true">
                    {profile.name
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((s) => s[0])
                      .join("")}
                  </div>
                  <div>
                    <h3>{profile.name}</h3>
                    <p>
                      {profile.location} · Revision {state.revision}
                    </p>
                    <Badge state={profile.confirmed ? "ready" : "review"}>
                      {profile.confirmed
                        ? "Facts confirmed"
                        : "Facts need review"}
                    </Badge>
                  </div>
                  <div className="profile-summary">
                    <p>{profile.summary}</p>
                    <dl>
                      <dt>E-mail</dt>
                      <dd>{profile.email || "Not provided"}</dd>
                      <dt>Phone</dt>
                      <dd>{profile.phone || "Not provided"}</dd>
                      <dt>Sponsorship</dt>
                      <dd>
                        {profile.sponsorship_required
                          ? "Required"
                          : "Not required"}
                      </dd>
                      <dt>Professional links</dt>
                      <dd>
                        {profile.links.map((link) => (
                          <p key={link}>{link}</p>
                        ))}
                      </dd>
                    </dl>
                    <details>
                      <summary>
                        Approved form answers (
                        {Object.keys(profile.answers).length})
                      </summary>
                      <dl>
                        {Object.entries(profile.answers).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                      <p>
                        Use an exact question label prefixed with “question:”,
                        in lower case. Unknown answers pause the application.
                      </p>
                    </details>
                  </div>
                </div>
              ) : (
                <p className="empty">Add your candidate profile to begin.</p>
              )}
            </Panel>
            <Panel
              title="Qualifications and evidence"
              eyebrow="Backed by your experience"
              action={
                <AddButton
                  onClick={() => open({ kind: "evidence", evidence: null })}
                >
                  Add evidence
                </AddButton>
              }
            >
              <div id="evidence-list">
                {state.unlocked && (
                  <>
                    {!profile?.evidence.length && (
                      <p className="empty">
                        Add a qualification, skill or project to build your
                        candidate record.
                      </p>
                    )}
                    {profile?.evidence.map((item) => (
                      <div key={item.id} className="entry evidence-card">
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.text}</p>
                          <small>
                            {item.category} · {item.dates} ·{" "}
                            {item.verified ? "Approved" : "Needs confirmation"}
                          </small>
                          <p className="evidence-source">
                            Source: {item.source}
                          </p>
                          <div className="tags">
                            {item.tags.map((tag) => (
                              <span key={tag}>{tag}</span>
                            ))}
                          </div>
                        </div>
                        <div className="actions">
                          <button
                            type="button"
                            className="secondary"
                            onClick={() =>
                              open({ kind: "evidence", evidence: item })
                            }
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="danger"
                            onClick={() =>
                              void workspace.action(() =>
                                workspace.mutate(
                                  "/evidence/" + encodeURIComponent(item.id),
                                  "DELETE",
                                  undefined,
                                  "Evidence removed; previous documents invalidated.",
                                ),
                              )
                            }
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </Panel>
          </section>
          <section
            data-section="networking"
            hidden={state.view !== "networking"}
          >
            <Networking
              state={state}
              workspace={workspace}
              add={() => open({ kind: "contact" })}
            />
          </section>
          <section data-section="settings" hidden={state.view !== "settings"}>
            {settings && (
              <SettingsForm
                key={JSON.stringify(settings)}
                settings={settings}
                workspace={workspace}
              />
            )}
          </section>
          <section data-section="activity" hidden={state.view !== "activity"}>
            <Panel
              title="Durable activity log"
              eyebrow="A clear record of every step"
            >
              <p>
                Latest 200 entries, newest first. Application details contain a
                journal scoped to that opportunity.
              </p>
              <div id="events">
                {state.unlocked && <Events events={state.events} />}
              </div>
            </Panel>
          </section>
        </fieldset>
        <footer className="footer">
          <span>Autonomous Applicator</span>
          <span>Local workspace · Approved evidence · English UK</span>
        </footer>
      </main>
      {state.unlocked && modal && (
        <Modal
          title={
            modal.kind === "profile"
              ? profile
                ? "Edit candidate profile"
                : "Add candidate profile"
              : modal.kind === "job"
                ? modal.application
                  ? "Edit opportunity"
                  : "Add an opportunity"
                : modal.kind === "evidence"
                  ? modal.evidence
                    ? "Edit evidence"
                    : "Add evidence"
                  : modal.kind === "contact"
                    ? "Queue a professional connection"
                    : "Import Greenhouse opportunities"
          }
          onClose={() => setModal(null)}
          busy={state.pending}
          notice={state.notice}
          error={state.error}
        >
          {modal.kind === "profile" ? (
            <ProfileForm
              profile={modal.profile}
              revision={modal.revision}
              workspace={workspace}
              done={() => setModal(null)}
            />
          ) : modal.kind === "job" ? (
            <JobForm
              application={modal.application}
              workspace={workspace}
              done={() => setModal(null)}
            />
          ) : modal.kind === "evidence" ? (
            <EvidenceForm
              evidence={modal.evidence}
              workspace={workspace}
              done={() => setModal(null)}
            />
          ) : modal.kind === "contact" ? (
            <ContactForm workspace={workspace} done={() => setModal(null)} />
          ) : (
            <BoardForm workspace={workspace} done={() => setModal(null)} />
          )}
        </Modal>
      )}
    </>
  );
}
