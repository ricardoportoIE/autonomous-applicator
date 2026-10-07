import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { X, Plus, ArrowUpRight } from "lucide-react";
import type { Event, Application, WorkerRecord } from "./contracts";
import { stateLabel } from "./ui";

export function Badge({
  state,
  children,
}: {
  state?: string;
  children?: ReactNode;
}) {
  return (
    <span className={"badge " + (state ?? "")}>
      {children ?? stateLabel(state)}
    </span>
  );
}
export function ApplicationBadge({ row }: { row: Application }) {
  if (row.trashed)
    return <Badge state="skipped">In Trash · {stateLabel(row.state)}</Badge>;
  const preparing =
    row.state === "review" &&
    (row.evaluation.preparation_pending || row.evaluation.score === undefined);
  return (
    <Badge state={row.state}>
      {preparing ? "Queued for preparation" : stateLabel(row.state)}
    </Badge>
  );
}
export function Panel({
  title,
  eyebrow,
  action,
  children,
  id,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
}) {
  const titleId = useId();
  return (
    <article className={"panel " + className} id={id} aria-labelledby={titleId}>
      <div className="panel-heading">
        <div>
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h2 id={titleId}>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </article>
  );
}
export function AddButton({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick}>
      <Plus size={16} aria-hidden="true" />
      {children}
    </button>
  );
}
export function ExternalLink({
  href,
  children,
  label,
}: {
  href: string;
  children: ReactNode;
  label?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      className="external-link"
    >
      {children}
      <ArrowUpRight size={16} aria-hidden="true" />
    </a>
  );
}
export function Modal({
  title,
  children,
  onClose,
  busy,
  notice,
  error,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy: boolean;
  notice: string;
  error: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.showModal();
    document.body.classList.add("modal-open");
    return () => {
      dialog.close();
      document.body.classList.remove("modal-open");
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={heading}
      className="modal"
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(
          ref.current!.querySelectorAll<HTMLElement>(
            "button, a[href], input, select, textarea, [tabindex]",
          ),
        ).filter(
          (el) =>
            el.tabIndex >= 0 &&
            !el.matches(":disabled") &&
            el.getClientRects().length > 0,
        );
        const first = controls[0],
          last = controls[controls.length - 1];
        if (!first) {
          event.preventDefault();
          return;
        }
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="modal-heading">
        <div>
          <p className="eyebrow">Local workspace</p>
          <h2 id={heading}>{title}</h2>
        </div>
        <button
          type="button"
          className="icon-button secondary"
          aria-label="Close dialogue"
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      <div className="modal-body">
        {notice && (
          <p
            role={error ? "alert" : "status"}
            className={error ? "error" : "modal-notice"}
          >
            {notice}
          </p>
        )}
        <fieldset disabled={busy} aria-busy={busy || undefined}>
          {children}
        </fieldset>
      </div>
    </dialog>
  );
}
export function Tabs({
  label,
  items,
  selected,
  onSelect,
  children,
  prefix,
}: {
  label: string;
  items: { id: string; label: string }[];
  selected: string;
  onSelect: (id: string) => void;
  children: (id: string) => ReactNode;
  prefix: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <>
      <div className="connection-tabs" role="tablist" aria-label={label}>
        {items.map((item, index) => (
          <button
            key={item.id}
            type="button"
            ref={(el) => {
              refs.current[index] = el;
            }}
            role="tab"
            id={`${prefix}-${item.id}-tab`}
            aria-controls={`${prefix}-${item.id}-panel`}
            aria-selected={selected === item.id}
            tabIndex={selected === item.id ? 0 : -1}
            onClick={() => onSelect(item.id)}
            onKeyDown={(event) => {
              const step =
                event.key === "ArrowRight"
                  ? 1
                  : event.key === "ArrowLeft"
                    ? -1
                    : 0;
              const next = step
                ? (index + step + items.length) % items.length
                : event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? items.length - 1
                    : null;
              if (next === null) return;
              event.preventDefault();
              onSelect(items[next].id);
              refs.current[next]?.focus();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${prefix}-${item.id}-panel`}
          aria-labelledby={`${prefix}-${item.id}-tab`}
          tabIndex={0}
          hidden={selected !== item.id}
        >
          {children(item.id)}
        </div>
      ))}
    </>
  );
}
export function Events({ events }: { events: Event[] }) {
  return (
    <>
      {!events.length && <p className="empty">No activity recorded yet.</p>}
      {events.map((event) => (
        <div className="entry" key={event.id}>
          <strong>{event.kind.replaceAll("_", " ")}</strong>
          <p>{event.detail}</p>
          <small>
            {new Date(event.created).toLocaleString("en-GB", {
              timeZone: "Europe/London",
            })}
          </small>
        </div>
      ))}
    </>
  );
}
export function ApplicationTable({
  rows,
  onOpen,
  empty = "No opportunities yet. Import a job to start.",
  onTrash,
  onRestore,
}: {
  rows: Application[];
  onOpen: (id: number) => void;
  empty?: string;
  onTrash?: (row: Application) => void;
  onRestore?: (row: Application) => void;
}) {
  return (
    <div className="table-wrap">
      {!rows.length ? (
        <p className="empty">{empty}</p>
      ) : (
        <table>
          <thead>
            <tr>
              {["Opportunity", "Fit", "Status", ""].map((label, i) => (
                <th key={i} scope="col">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <strong>{row.job.title}</strong>
                  <small>
                    {row.job.company} · {row.job.location}
                  </small>
                </td>
                <td className="score">{row.evaluation.score ?? "—"}</td>
                <td>
                  <ApplicationBadge row={row} />
                </td>
                <td>
                  <button
                    className="secondary"
                    type="button"
                    aria-label={`Open ${row.job.title} at ${row.job.company}`}
                    onClick={() => onOpen(row.id)}
                  >
                    Open
                  </button>
                  <a
                    className="record-link"
                    href={`#/applications/${row.id}`}
                    aria-label={`Full record for ${row.job.title} at ${row.job.company}`}
                  >
                    Full record
                  </a>
                  {row.trashed && onRestore ? (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => onRestore(row)}
                      aria-label={`Restore ${row.job.title} at ${row.job.company}`}
                    >
                      Restore
                    </button>
                  ) : (
                    !row.trashed &&
                    onTrash && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={["submitting", "uncertain"].includes(
                          row.state,
                        )}
                        onClick={() => onTrash(row)}
                        aria-label={`Move ${row.job.title} at ${row.job.company} to Trash`}
                      >
                        Move to Trash
                      </button>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
export function WorkerMonitor({
  record,
  error,
}: {
  record: WorkerRecord | null;
  error: string;
}) {
  const [, clock] = useState(0);
  const run = record?.run;
  useEffect(() => {
    if (!run || run.finished) return;
    const timer = setInterval(() => clock((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, [run]);
  const labels: Record<string, string> = {
    running: "Running",
    completed: "Completed",
    failed: "Failed",
    interrupted: "Interrupted — review before retrying",
    paused: "Paused",
    stopped: "Stopped",
    limit_reached: "Daily sending limit reached; preparation continues",
  };
  const end = run?.finished ? new Date(run.finished).getTime() : Date.now();
  const seconds = (date: string) =>
    Math.max(0, Math.floor((end - new Date(date).getTime()) / 1000));
  return (
    <section className="processing-panel" aria-labelledby="processing-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Live processing</p>
          <h2 id="processing-title">One opportunity at a time</h2>
        </div>
        <span
          className={
            "live-indicator " + (run?.status === "running" ? "is-running" : "")
          }
        >
          <span />
          {run?.status === "running" ? "Live" : "Monitoring"}
        </span>
      </div>
      <p>
        The agent completes preparation, submission checks and result recording
        for the current opportunity before starting the next.
      </p>
      <div
        id="worker-status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {error ||
          (!run ? (
            <p className="empty">
              Idle — no application processing has started.
            </p>
          ) : (
            <>
              <strong>{labels[run.status] ?? run.status}</strong>
              {run.job && (
                <p>
                  {run.job.title} · {run.job.company} · Application #
                  {run.application_id}
                </p>
              )}
              <p>
                {run.status === "running" ? "Current" : "Last"} stage:{" "}
                {run.stage.replaceAll("_", " ")}
              </p>
              <small>{run.detail}</small>
              {run.error_code && (
                <p className="error">
                  Failure at {run.stage.replaceAll("_", " ")}: {run.error_code}.
                  {run.application_id === null
                    ? " Check the last stage and the dedicated browser session before retrying."
                    : " Inspect the application activity log before retrying."}
                </p>
              )}
            </>
          ))}
      </div>
      <p id="worker-clock" className="worker-clock">
        {run
          ? `Total: ${seconds(run.started)}s · Stage: ${seconds(run.stage_started)}s · Run ${run.id}`
          : ""}
      </p>
      <details className="worker-history">
        <summary>Recent application results</summary>
        <p>
          Latest 50 results across runs, newest first. Full details remain in
          each application activity log.
        </p>
        <div id="worker-results">
          {record?.results.map((result, index) => (
            <div className="entry" key={index}>
              <strong>
                {result.job.title} · {result.error_code ? "Failed — " : ""}
                {stateLabel(result.outcome)}
              </strong>
              <small>
                Application #{result.application_id} ·{" "}
                {result.error_code ? "Failure at " : ""}
                {result.stage.replaceAll("_", " ")}
                {result.error_code ? " · " + result.error_code : ""}
              </small>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
