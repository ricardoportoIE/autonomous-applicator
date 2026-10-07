import { useEffect, useState, useSyncExternalStore } from "react";
import { AlertCircle, ArrowRight, CheckCircle2 } from "lucide-react";
import type { ApplicationDetail } from "./contracts";
import type { Workspace } from "./workspace";
import { ExternalLink } from "./components";

export function experienceReviewable(value: string) {
  return (
    value.startsWith(
      "Required professional experience is below the stated minimum: ",
    ) ||
    value.startsWith("Required professional experience needs review: ") ||
    value.startsWith(
      "Required production machine learning experience is not met: ",
    )
  );
}

type Destination =
  | "questions"
  | "documents"
  | "history"
  | "facts"
  | "settings"
  | "job"
  | "location";
export function reviewAdvice(value: string): {
  title: string;
  guidance: string;
  action: string;
  destination: Destination;
} {
  if (experienceReviewable(value))
    return {
      title: "Experience requirement needs your decision",
      guidance:
        "The vacancy requests experience your profile may not fully establish. You can approve applying despite this requirement without claiming to meet it. Keep your real experience and truthful answers, correct an inaccurate fact if needed, or move the opportunity to Trash.",
      action: "Review candidate facts",
      destination: "facts",
    };
  if (
    /Required question|approved answer|Approve answers|sensitive/i.test(value)
  )
    return {
      title: "Questionnaire answer needed",
      guidance:
        "Open Questions, review the exact question and save a truthful answer. Sensitive questions require manual handling in the original application.",
      action: "Answer questions",
      destination: "questions",
    };
  if (/Location needs|Distance or country/i.test(value))
    return {
      title: "Location decision needed",
      guidance:
        "Review the stated location and use the location acceptance form below if you are willing to work there.",
      action: "Review location",
      destination: "location",
    };
  if (
    /Document|material|manifest|hash|preparation|Prepared revision|Processing failed/i.test(
      value,
    )
  )
    return {
      title: "Preparation or technical issue",
      guidance:
        "Inspect Activity for the failed step, then prepare the vacancy-specific documents or recheck readiness after resolving it. A retry keeps the existing factual checks.",
      action: "Review documents",
      destination: "documents",
    };
  if (/Automation|authorisation scope|sending slot|daily|capacity/i.test(value))
    return {
      title: "Agent setting or sending capacity",
      guidance:
        "Review Agent settings. Preparation can continue whilst sending is paused or the daily allowance is exhausted.",
      action: "Open Agent settings",
      destination: "settings",
    };
  if (
    /sponsorship incompatibility|Opportunity identity|URL|No assessable requirements|Role relevance/i.test(
      value,
    )
  )
    return {
      title: "Vacancy details need review",
      guidance:
        "Compare the original opportunity with the saved details. Correct a parsing mistake only if the provider supports the correction; otherwise move an unsuitable opportunity to Trash.",
      action: "Review job details",
      destination: "job",
    };
  if (/Candidate|confirmation|seniority|machine learning/i.test(value))
    return {
      title: "Confirmed fact or responsibility needed",
      guidance:
        "Review the candidate facts and vacancy responsibilities. Add only facts you can confirm; do not increase experience to satisfy a requirement. Recheck readiness after saving.",
      action: "Review candidate facts",
      destination: "facts",
    };
  return {
    title: "Manual investigation needed",
    guidance:
      "Inspect the recorded activity and original opportunity to identify the missing condition. Resolve it and recheck readiness, or move the opportunity to Trash.",
    action: "Inspect activity",
    destination: "history",
  };
}

export function ReviewGuidance({
  detail,
  workspace,
  onTab,
  editProfile,
  editJob,
  moveToTrash,
}: {
  detail: ApplicationDetail;
  workspace: Workspace;
  onTab: (tab: string) => void;
  editProfile: () => void;
  editJob: () => void;
  moveToTrash?: () => void;
}) {
  const state = useSyncExternalStore(
    workspace.subscribe,
    workspace.getSnapshot,
  );
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => setConfirmed(false), [detail]);
  const { row, report } = detail;
  const blockers = report.evaluation?.blockers ?? row.evaluation.blockers ?? [];
  const accepted = blockers.filter(experienceReviewable);
  const score = report.evaluation?.score ?? row.evaluation.score;
  const fitReview =
    score !== undefined &&
    score >= (state.settings?.review_threshold ?? 50) &&
    score < (state.settings?.auto_threshold ?? 80);
  const failed = report.checks.filter(
    (check) =>
      !check.passed &&
      !["state", "policy", "questions", "trash"].includes(check.code),
  );
  const issues = [
    ...new Set([...blockers, ...failed.map((check) => check.detail)]),
  ];
  if (row.trashed || row.state !== "review") return null;
  const navigate = (destination: Destination) => {
    if (destination === "facts") editProfile();
    else if (destination === "job") editJob();
    else if (destination === "settings") workspace.navigate("settings");
    else if (destination === "location")
      document
        .getElementById("location-review")
        ?.scrollIntoView({ behavior: "instant" });
    else onTab(destination);
  };
  return (
    <section
      className="review-guidance"
      aria-labelledby="review-guidance-title"
    >
      <div className="review-heading">
        <AlertCircle size={22} aria-hidden="true" />
        <div>
          <p className="eyebrow">Your next decision</p>
          <h3 id="review-guidance-title">Why this application needs review</h3>
          <p>
            Each issue below has its own next step. Questions may already be
            complete.
          </p>
        </div>
      </div>
      <div className="review-issues">
        {issues.map((value) => {
          const advice = reviewAdvice(value);
          return (
            <article className="review-issue" key={value}>
              <h4>{advice.title}</h4>
              <p className="review-detail">{value}</p>
              <p>{advice.guidance}</p>
              <button
                className="secondary"
                type="button"
                disabled={state.pending}
                onClick={() => navigate(advice.destination)}
              >
                {advice.action}
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            </article>
          );
        })}
      </div>
      {!issues.length && !fitReview && (
        <p>
          Preparation or a current readiness check is still needed. Open
          Documents to prepare this opportunity, then recheck readiness.
        </p>
      )}
      {fitReview && (
        <article className="review-issue">
          <h4>Fit needs your decision</h4>
          <p>
            Fit is {score}/100, within your candidate-review band. Review the
            opportunity and decide whether to accept this fit or move it to
            Trash.
          </p>
        </article>
      )}
      {(accepted.length > 0 || fitReview) && (
        <form
          className="review-decision"
          onSubmit={(event) => {
            event.preventDefault();
            if (!confirmed) return;
            void workspace.action(() =>
              workspace.mutate(
                `/applications/${row.id}/review-decision`,
                "POST",
                {
                  job: row.job,
                  blockers: accepted,
                  accept_fit: fitReview,
                  answers_remain_truthful: true,
                },
                "Review decision saved for this opportunity. Other checks still apply; your answers are unchanged.",
                row.id,
                detail.profile_revision ?? state.revision,
              ),
            );
          }}
        >
          <h4>
            <CheckCircle2 size={17} aria-hidden="true" />
            Your decision for this opportunity
          </h4>
          <p>
            Accept the listed experience shortfalls
            {fitReview ? " and fit score" : ""} for this vacancy. This preserves
            your confirmed experience and expires if the candidate facts or
            opportunity change. Submission still requires documents, truthful
            answers and all other checks.
          </p>
          <label className="check">
            <input
              type="checkbox"
              required
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I have reviewed this opportunity and want to apply with my truthful
            profile.
          </label>
          <button disabled={state.pending || !confirmed}>
            Approve this opportunity for the queue
          </button>
        </form>
      )}
      <div className="actions">
        <button
          className="secondary"
          type="button"
          disabled={state.pending}
          onClick={() => onTab("documents")}
        >
          Open documents
        </button>
        <ExternalLink href={row.job.url}>
          Inspect original opportunity
        </ExternalLink>
        {moveToTrash && (
          <button
            className="danger"
            type="button"
            disabled={state.pending}
            onClick={moveToTrash}
          >
            Move to Trash
          </button>
        )}
      </div>
    </section>
  );
}
