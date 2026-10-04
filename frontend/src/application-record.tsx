import { useEffect, useState } from "react";
import {
  ArrowLeft,
  RefreshCw,
  Camera,
  FileCheck2,
  History,
  ExternalLink as LinkIcon,
} from "lucide-react";
import { Badge, Events, ExternalLink, Panel } from "./components";
import type { ApplicationRecord, SubmissionAttempt } from "./contracts";
import type { Workspace } from "./workspace";

export function recordedDate(value?: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/London",
  }).format(date);
}

function ConfirmationImage({
  id,
  attempt,
  workspace,
}: {
  id: number;
  attempt: SubmissionAttempt;
  workspace: Workspace;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    void workspace.api
      .blob(
        `/applications/${id}/submissions/${attempt.id}/artifacts/confirmation`,
      )
      .then((blob) => {
        if (active) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id, attempt.id, workspace]);
  return (
    <div className="confirmation-preview">
      {url ? (
        <img
          src={url}
          alt={`Provider submission confirmation for application ${id}, attempt ${attempt.id}`}
        />
      ) : (
        <p role="status">
          {failed
            ? "The confirmation screenshot is unavailable or failed its integrity check."
            : "Loading confirmation screenshot…"}
        </p>
      )}
      {url && (
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void workspace.action(() =>
              workspace.downloadSubmission(
                id,
                attempt.id,
                "confirmation",
                `application-${id}-attempt-${attempt.id}-confirmation.png`,
              ),
            )
          }
        >
          Download confirmation screenshot
        </button>
      )}
    </div>
  );
}

export function ApplicationRecordPage({
  record,
  workspace,
}: {
  record: ApplicationRecord;
  workspace: Workspace;
}) {
  const row = record.application;
  const [selected, setSelected] = useState(record.attempts[0]?.id ?? 0);
  const attempt = record.attempts.find((item) => item.id === selected);
  const snapshot = attempt?.snapshot;
  const files = Object.entries(snapshot?.manifest.files ?? {});
  return (
    <div className="application-record" id="application-record">
      <div className="record-navigation">
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void workspace.action(() => workspace.openRecord(row.id, false))
          }
        >
          <RefreshCw size={16} aria-hidden="true" />
          Refresh record
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => workspace.navigate("applications")}
        >
          <ArrowLeft size={16} aria-hidden="true" />
          Back to application queue
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() =>
            void workspace.action(async () => {
              workspace.navigate("applications");
              await workspace.openDetail(row.id);
            })
          }
        >
          Manage this application
        </button>
      </div>
      <article className="record-hero">
        <p className="eyebrow">Application #{row.id} · Your complete record</p>
        <h2>{row.job.title}</h2>
        <p>
          {row.job.company} · {row.job.location}
        </p>
        <div className="detail-meta">
          <Badge state={row.state} />
          <ExternalLink href={row.job.url}>
            Open original opportunity
          </ExternalLink>
        </div>
        <p className="record-url">
          <LinkIcon size={15} aria-hidden="true" />
          {row.job.url}
        </p>
        <div className="record-dates">
          {[
            ["Imported", record.dates.imported_at],
            ["Last prepared", record.dates.prepared_at],
            ["Submitted", record.dates.submitted_at],
            ["Last activity", record.dates.last_activity_at],
          ].map(([label, value]) => (
            <div key={label}>
              <small>{label}</small>
              <strong>{recordedDate(value)}</strong>
            </div>
          ))}
        </div>
        <small>Dates and times shown in Europe/London.</small>
      </article>
      <div className="record-grid">
        <Panel title="Opportunity and decision" eyebrow="The original context">
          <dl className="record-facts">
            <dt>Source</dt>
            <dd>
              {row.job.source} · {row.job.source_id}
            </dd>
            <dt>Recorded outcome</dt>
            <dd>{row.outcome ?? "Not recorded"}</dd>
            <dt>Fit</dt>
            <dd>
              {row.evaluation.score === undefined
                ? "Not evaluated"
                : `${row.evaluation.score}/100`}
            </dd>
            <dt>Sponsorship</dt>
            <dd>{row.job.sponsorship}</dd>
            <dt>Cover letter required</dt>
            <dd>{row.job.cover_letter_required ? "Yes" : "No"}</dd>
          </dl>
          <p>Fit is a heuristic, not a hiring probability or an ATS score.</p>
          <p>
            Required technologies:{" "}
            {row.job.requirements.join(", ") || "Not recorded"}
          </p>
          <p>
            Matched: {row.evaluation.matched?.join(", ") || "None recorded"}
          </p>
          <p>Gaps: {row.evaluation.gaps?.join(", ") || "None recorded"}</p>
          {[
            ...(row.evaluation.reasons ?? []),
            ...(row.evaluation.blockers ?? []),
          ].map((text, index) => (
            <p key={index}>{text}</p>
          ))}
          <details>
            <summary>Full opportunity description</summary>
            <p className="whitespace-pre-wrap">{row.job.description}</p>
          </details>
          {row.job.questions.length > 0 && (
            <details>
              <summary>Recorded application questions</summary>
              {row.job.questions.map((question) => (
                <p key={question.id}>
                  {question.label} ·{" "}
                  {question.required ? "Required" : "Optional"}
                  {question.choices.length
                    ? ` · ${question.choices.join(" / ")}`
                    : ""}
                </p>
              ))}
            </details>
          )}
        </Panel>
        <Panel title="Submission history" eyebrow="Every attempt retained">
          <p>
            {record.attempts.length} recorded attempts ·{" "}
            {record.dates.event_count} journal entries
          </p>
          {record.attempts.length ? (
            <label>
              Submission attempt
              <select
                aria-label="Submission attempt"
                value={selected}
                onChange={(event) => setSelected(Number(event.target.value))}
              >
                {record.attempts.map((item) => (
                  <option key={item.id} value={item.id}>
                    Attempt #{item.id} · {item.status} ·{" "}
                    {recordedDate(item.started)}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="empty">No submission attempt has been started.</p>
          )}
          {attempt && (
            <dl className="record-facts">
              <dt>Sending state</dt>
              <dd>
                {attempt.status === "confirmed"
                  ? "Confirmed submission"
                  : attempt.status === "released"
                    ? "Stopped before sending or confirmed as not sent"
                    : "Pending or uncertain; reconcile before retrying"}
              </dd>
              <dt>Started</dt>
              <dd>{recordedDate(attempt.started)}</dd>
              <dt>Send initiated</dt>
              <dd>{recordedDate(attempt.sent_at)}</dd>
              <dt>Confirmed</dt>
              <dd>{recordedDate(attempt.confirmed_at)}</dd>
              <dt>Provider receipt</dt>
              <dd>{attempt.receipt ?? "No confirmed receipt"}</dd>
            </dl>
          )}
          {row.receipt && !attempt?.receipt && (
            <p>Application receipt: {row.receipt}</p>
          )}
          {attempt && !snapshot && (
            <p className="review-note">
              Historical attempt: no submission snapshot or screenshot was
              captured. Current candidate facts are available in the candidate
              profile.
            </p>
          )}
        </Panel>
      </div>
      {attempt && snapshot && (
        <>
          <div className="record-grid">
            <Panel
              title="Candidate snapshot"
              eyebrow="Facts reviewed for this attempt"
            >
              <dl className="record-facts">
                {Object.entries(snapshot.candidate).map(([key, value]) => (
                  <div className="record-fact" key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>
                      {Array.isArray(value)
                        ? value.join(" · ")
                        : typeof value === "boolean"
                          ? value
                            ? "Yes"
                            : "No"
                          : value || "Not recorded"}
                    </dd>
                  </div>
                ))}
              </dl>
              <p>Profile revision {snapshot.profile_revision}</p>
              {snapshot.selected_evidence?.length ? (
                <details>
                  <summary>Reviewed evidence used in these documents</summary>
                  {snapshot.selected_evidence.map((item) => (
                    <div key={item.id}>
                      <strong>{item.title}</strong>
                      <p className="whitespace-pre-wrap">{item.text}</p>
                      <small>{item.source}</small>
                    </div>
                  ))}
                </details>
              ) : null}
              <details>
                <summary>Opportunity snapshot for this attempt</summary>
                <p>
                  {snapshot.job.title} · {snapshot.job.company} ·{" "}
                  {snapshot.job.location}
                </p>
                <p className="whitespace-pre-wrap">
                  {snapshot.job.description}
                </p>
              </details>
            </Panel>
            <Panel
              title="Archived documents for this attempt"
              eyebrow="Preserved copies"
            >
              <p>
                <FileCheck2 size={17} aria-hidden="true" />
                Evidence selection:{" "}
                {snapshot.manifest.generation?.model ??
                  snapshot.manifest.generation?.method ??
                  "Not recorded"}
              </p>
              <p>
                Evidence references:{" "}
                {snapshot.manifest.evidence_ids?.join(", ") || "Not recorded"}
              </p>
              {files.map(([key, file]) => (
                <div className="record-document" key={key}>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      void workspace.action(() =>
                        workspace.downloadSubmission(
                          row.id,
                          attempt.id,
                          key,
                          file.name,
                        ),
                      )
                    }
                  >
                    Download {file.name}
                  </button>
                  <details>
                    <summary>Recorded document hash</summary>
                    <code>{file.sha256}</code>
                  </details>
                </div>
              ))}
              {snapshot.provided_answers.length > 0 && (
                <details>
                  <summary>Approved answers supplied to the adapter</summary>
                  {snapshot.provided_answers.map((answer) => (
                    <div key={answer.id}>
                      <strong>{answer.label}</strong>
                      <p className="whitespace-pre-wrap">{answer.answer}</p>
                    </div>
                  ))}
                </details>
              )}
              <details>
                <summary>Complete preparation metadata</summary>
                <pre className="whitespace-pre-wrap break-all">
                  {JSON.stringify(snapshot.manifest, null, 2)}
                </pre>
              </details>
            </Panel>
          </div>
          <Panel
            title="Observed application form"
            eyebrow={
              attempt.status === "confirmed"
                ? "Values present before confirmed submission"
                : "Values observed during this attempt"
            }
          >
            {attempt.fields?.length ? (
              <dl className="record-facts">
                {attempt.fields.map((field, index) => (
                  <div className="record-fact" key={index}>
                    <dt>
                      {field.label}
                      {field.step ? ` · Step ${field.step}` : ""}
                    </dt>
                    <dd className="whitespace-pre-wrap">
                      {field.type === "checkbox"
                        ? field.checked
                          ? "Selected"
                          : "Not selected"
                        : field.value || "Empty"}
                      <small>Observed {recordedDate(field.observed_at)}</small>
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p>
                No provider form observations were recorded for this attempt.
              </p>
            )}
          </Panel>
        </>
      )}
      <Panel
        title="Provider confirmation"
        eyebrow="A visible record of submission"
      >
        <p>
          <Camera size={17} aria-hidden="true" />A screenshot is saved when the
          supported provider displays a submission confirmation.
        </p>
        {attempt?.status === "confirmed" && attempt.confirmation?.url && (
          <>
            <ExternalLink href={attempt.confirmation.url}>
              Open recorded confirmation page
            </ExternalLink>
            <p>
              The recorded URL is the page shown at confirmation time. The
              provider may change what it displays when you reopen it.
            </p>
          </>
        )}
        {attempt?.status === "confirmed" && attempt.confirmation?.name ? (
          <>
            <p>Captured {recordedDate(attempt.confirmation.captured_at)}</p>
            <ConfirmationImage
              key={attempt.id}
              id={row.id}
              attempt={attempt}
              workspace={workspace}
            />
          </>
        ) : (
          <p className="empty">
            No confirmation screenshot is available for this attempt.
            {attempt?.confirmation?.capture_error &&
              ` Capture issue: ${attempt.confirmation.capture_error}. The confirmed receipt remains recorded.`}
          </p>
        )}
      </Panel>
      <Panel title="Application activity" eyebrow="The complete journal">
        <p>
          <History size={17} aria-hidden="true" />
          {record.events.length} of {record.dates.event_count} entries loaded,
          newest first.
        </p>
        <Events events={record.events} />
        {record.next_event && (
          <button
            type="button"
            className="secondary"
            onClick={() =>
              void workspace.action(() => workspace.olderRecordEvents())
            }
          >
            Load older activity
          </button>
        )}
      </Panel>
    </div>
  );
}
