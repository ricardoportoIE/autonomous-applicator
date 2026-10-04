import { useEffect, useState } from "react";
import { X, FileText, ShieldCheck } from "lucide-react";
import { Badge, Events, ExternalLink, Tabs } from "./components";
import type {
  Application,
  ApplicationDetail,
  Profile,
  Question,
} from "./contracts";
import type { Workspace } from "./workspace";

function Answer({
  question,
  profile,
  workspace,
  id,
}: {
  question: Question;
  profile: Profile | null;
  workspace: Workspace;
  id: number;
}) {
  const key =
    question.answer_key ||
    "question:" + question.label.toLowerCase().trim().replace(/\s+/g, " ");
  const approved = profile?.answers[key] ?? "";
  const [value, setValue] = useState(
    question.choices.length && !question.choices.includes(approved)
      ? ""
      : approved,
  );
  useEffect(
    () =>
      setValue(
        question.choices.length && !question.choices.includes(approved)
          ? ""
          : approved,
      ),
    [approved, question],
  );
  if (question.sensitive)
    return (
      <p className="review-note">{question.label}: requires manual handling.</p>
    );
  return (
    <form
      className="question-card"
      onSubmit={(event) => {
        event.preventDefault();
        void workspace.action(async () => {
          if (!profile)
            throw new Error("Configure the candidate profile first.");
          await workspace.mutate(
            "/profile",
            "PUT",
            { ...profile, answers: { ...profile.answers, [key]: value } },
            "Answer approved. Regenerate documents before submission.",
            id,
          );
        });
      }}
    >
      <label>
        {question.label}
        {question.choices.length ? (
          <select
            aria-label={question.label}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            required
          >
            <option value="">Choose an approved answer</option>
            {question.choices.map((choice) => (
              <option key={choice}>{choice}</option>
            ))}
          </select>
        ) : (
          <input
            aria-label={question.label}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            required
          />
        )}
      </label>
      <small>
        {question.required ? "Required" : "Optional"} · Exact approved answer
        only
      </small>
      <button className="secondary">Approve answer</button>
    </form>
  );
}
function Provenance({ row }: { row: Application }) {
  const generation = row.manifest.generation;
  return (
    <section className="document-origin" aria-label="Document preparation">
      <h3>
        <FileText size={18} aria-hidden="true" />
        Document preparation
      </h3>
      {generation ? (
        <>
          <p>
            {generation.method === "openai"
              ? "Evidence selected with " + generation.model
              : generation.method === "manual"
                ? "Evidence selected manually"
                : "Evidence selected using local rules"}
          </p>
          <p>
            Prepared for {row.job.title} at {row.job.company}. Profile revision{" "}
            {row.manifest.revision}.
          </p>
          <p>
            Selected evidence: {row.manifest.evidence_ids?.length ?? 0}.
            Approved factual text is preserved.
          </p>
        </>
      ) : (
        <p>
          Preparation origin is unavailable. Regenerate documents to record it.
        </p>
      )}
    </section>
  );
}
export function ApplicationDetails({
  detail,
  workspace,
  profile,
  edit,
}: {
  detail: ApplicationDetail;
  workspace: Workspace;
  profile: Profile | null;
  edit: (row: Application) => void;
}) {
  const { row, report, events } = detail;
  const [tab, setTab] = useState("summary");
  const [selected, setSelected] = useState<string[]>(
    row.manifest.evidence_ids ?? [],
  );
  const [outcome, setOutcome] = useState(row.outcome ?? "interview");
  useEffect(() => setOutcome(row.outcome ?? "interview"), [row.outcome]);
  const protectedState = ["submitted", "submitting", "uncertain"].includes(
    row.state,
  );
  const prepare = (body: object) =>
    void workspace.action(() =>
      workspace.mutate(
        `/applications/${row.id}/prepare`,
        "POST",
        body,
        "Documents prepared from approved evidence.",
        row.id,
      ),
    );
  const files = Object.entries(row.manifest.files ?? {});
  return (
    <article className="panel application-detail" id="application-detail">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Application #{row.id}</p>
          <h2>{row.job.title}</h2>
          <p>
            {row.job.company} · {row.job.location}
          </p>
        </div>
        <button
          className="secondary icon-button"
          type="button"
          onClick={() => workspace.closeDetail()}
          aria-label="Close application details"
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="detail-meta">
        <Badge state={row.state} />
        <ExternalLink href={row.job.url}>
          Open original opportunity
        </ExternalLink>
      </div>
      <Tabs
        prefix="application"
        label="Application details"
        selected={tab}
        onSelect={setTab}
        items={[
          { id: "summary", label: "Overview" },
          { id: "documents", label: `Documents (${files.length})` },
          { id: "questions", label: `Questions (${row.job.questions.length})` },
          { id: "history", label: "Activity & outcome" },
        ]}
      >
        {(section) =>
          section === "summary" ? (
            <>
              <section
                className="preflight"
                aria-label="Local submission checks"
              >
                <h3>
                  <ShieldCheck size={18} aria-hidden="true" />
                  Submission readiness
                </h3>
                <p>
                  {report.can_submit
                    ? "All local checks passed."
                    : "Resolve the blocked checks before automatic submission."}
                </p>
                <small>
                  Checked {new Date(report.checked_at).toLocaleString("en-GB")}.
                  This is a local snapshot. Provider sign-in, changed job
                  details and new questions are checked during submission.
                </small>
                <ul className="checklist">
                  {report.checks.map((check) => (
                    <li key={check.code}>
                      <Badge state={check.passed ? "ready" : "review"}>
                        {check.passed ? "Passed" : "Blocked"}
                      </Badge>
                      <div>
                        <strong>{check.label}</strong>
                        <p>{check.detail}</p>
                      </div>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    void workspace.action(() => workspace.openDetail(row.id))
                  }
                >
                  Recheck readiness
                </button>
              </section>
              {row.evaluation.score !== undefined && (
                <section className="fit-report">
                  <h3>
                    Fit: {row.evaluation.score}/100 · {row.state}
                  </h3>
                  {[
                    ...(row.evaluation.reasons ?? []),
                    ...(row.evaluation.blockers ?? []),
                  ].map((reason, index) => (
                    <p key={index}>{reason}</p>
                  ))}
                  <p>Matched: {row.evaluation.matched?.join(", ")}</p>
                  <p>Gaps: {row.evaluation.gaps?.join(", ")}</p>
                </section>
              )}
              <Provenance row={row} />
              <div className="actions">
                {!protectedState && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => edit(row)}
                  >
                    Edit job details
                  </button>
                )}
                <button
                  type="button"
                  className="secondary"
                  disabled={protectedState}
                  onClick={() => prepare({})}
                >
                  Prepare documents
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={protectedState}
                  onClick={() => prepare({ use_ai: true })}
                >
                  Select evidence with GPT-6.1 Sol
                </button>
                {row.state === "ready" && (
                  <button
                    type="button"
                    disabled={!report.can_submit}
                    onClick={() =>
                      void workspace.action(() =>
                        workspace.mutate(
                          `/applications/${row.id}/submit`,
                          "POST",
                          undefined,
                          "Provider receipt recorded.",
                          row.id,
                        ),
                      )
                    }
                  >
                    Run authorised submission
                  </button>
                )}
                {files.map(([key, file]) => (
                  <button
                    type="button"
                    className="secondary"
                    key={key}
                    onClick={() =>
                      void workspace.action(() =>
                        workspace.download(row.id, key, file.name),
                      )
                    }
                  >
                    Download {file.name}
                  </button>
                ))}
              </div>
              <details className="job-description">
                <summary>Full opportunity details</summary>
                <p className="whitespace-pre-wrap">{row.job.description}</p>
                <p>
                  Required technologies:{" "}
                  {row.job.requirements.join(", ") || "Not stated"}
                </p>
                <p>Sponsorship: {row.job.sponsorship.replaceAll("_", " ")}</p>
                <p>
                  Cover letter:{" "}
                  {row.job.cover_letter_required ? "Required" : "Not required"}
                </p>
                <p>
                  Source: {row.job.source} · {row.job.source_id}
                </p>
              </details>
            </>
          ) : section === "documents" ? (
            <>
              <h3>Documents for this opportunity</h3>
              <p>
                Each preparation uses this opportunity and the current approved
                candidate record. A preparation failure remains in review.
              </p>
              <ul className="document-list">
                {files.map(([key, file]) => (
                  <li key={key}>
                    <FileText aria-hidden="true" size={20} />
                    <span>{file.name}</span>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        void workspace.action(() =>
                          workspace.download(row.id, key, file.name),
                        )
                      }
                    >
                      Download {file.name}
                    </button>
                  </li>
                ))}
              </ul>
              {!files.length && (
                <p className="empty">
                  No current documents. Use Prepare documents in Overview.
                </p>
              )}
              <details>
                <summary>Choose approved evidence manually</summary>
                <p>
                  Manual selection records a distinct preparation origin. It
                  does not invent factual text.
                </p>
                {profile?.evidence
                  .filter((e) => e.verified)
                  .map((e) => (
                    <label key={e.id} className="check">
                      <input
                        type="checkbox"
                        checked={selected.includes(e.id)}
                        onChange={(event) =>
                          setSelected(
                            event.target.checked
                              ? [...selected, e.id]
                              : selected.filter((id) => id !== e.id),
                          )
                        }
                      />
                      {e.title}
                    </label>
                  ))}
                <button
                  type="button"
                  className="secondary"
                  disabled={protectedState || !selected.length}
                  onClick={() => prepare({ evidence_ids: selected })}
                >
                  Prepare with selected evidence
                </button>
              </details>
            </>
          ) : section === "questions" ? (
            <>
              <h3>Approved questionnaire answers</h3>
              <p>
                Unknown or sensitive answers hold the application for review. A
                prefilled provider field does not approve an answer.
              </p>
              {row.job.questions.length ? (
                row.job.questions.map((question) => (
                  <Answer
                    key={question.id}
                    question={question}
                    profile={profile}
                    workspace={workspace}
                    id={row.id}
                  />
                ))
              ) : (
                <p className="empty">
                  No questionnaire questions recorded yet. New provider
                  questions are checked during submission.
                </p>
              )}
            </>
          ) : (
            <>
              {row.receipt && (
                <p className="receipt">Recorded receipt: {row.receipt}</p>
              )}
              {["review", "ready", "uncertain"].includes(row.state) && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    const receipt = String(
                      new FormData(event.currentTarget).get("receipt"),
                    );
                    void workspace.action(() =>
                      workspace.mutate(
                        `/applications/${row.id}/receipt`,
                        "POST",
                        { receipt },
                        "Manual submission receipt recorded.",
                        row.id,
                      ),
                    );
                  }}
                >
                  <label>
                    Manual submission receipt or confirmation reference
                    <input name="receipt" required />
                  </label>
                  <button className="secondary">
                    Record confirmed manual submission
                  </button>
                </form>
              )}
              {row.state === "submitted" && (
                <div className="outcome-controls">
                  <label>
                    Record outcome
                    <select
                      aria-label="Record outcome"
                      value={outcome}
                      onChange={(event) => setOutcome(event.target.value)}
                    >
                      {[
                        "interview",
                        "offer",
                        "rejected",
                        "no_response",
                        "withdrawn",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      void workspace.action(() =>
                        workspace.mutate(
                          `/applications/${row.id}/outcome`,
                          "POST",
                          { outcome },
                          "Outcome saved.",
                          row.id,
                        ),
                      )
                    }
                  >
                    Save outcome
                  </button>
                </div>
              )}
              <details className="timeline">
                <summary>Activity for this application</summary>
                <small>Latest 200 entries, newest first.</small>
                <div>
                  <Events events={events} />
                </div>
              </details>
            </>
          )
        }
      </Tabs>
    </article>
  );
}
