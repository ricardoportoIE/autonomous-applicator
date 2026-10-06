/** Pure presentation helpers, shared with the frontend unit tests. */
export const stateLabels = Object.freeze({
  ready: "Ready",
  review: "For review",
  skipped: "Not prioritised",
  submitting: "Submitting",
  submitted: "Submitted",
  uncertain: "Needs reconciliation",
  queued: "Queued",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  imported: "Opportunity imported",
  already_imported: "Already in the queue",
});

export function stateLabel(value: unknown) {
  return typeof value === "string" && Object.hasOwn(stateLabels, value)
    ? stateLabels[value as keyof typeof stateLabels]
    : "Unknown status";
}

export function splitList(value: string, separator = ",") {
  return [
    ...new Set(
      value
        .split(separator)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
}

export function parseAnswers(value: string): Record<string, string> {
  let answers: unknown;
  try {
    answers = JSON.parse(value || "{}");
  } catch {
    throw new Error(
      'Approved answers must be valid JSON, for example {"question:salary?":"To be discussed"}.',
    );
  }
  if (
    !answers ||
    Array.isArray(answers) ||
    typeof answers !== "object" ||
    Object.values(answers).some((v) => typeof v !== "string")
  ) {
    throw new Error(
      "Approved answers must be a JSON object containing text values.",
    );
  }
  return answers as Record<string, string>;
}

export function errorDetail(value: unknown, status: number) {
  const detail =
    value && typeof value === "object" && "detail" in value
      ? value.detail
      : undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item: unknown) => {
        if (!item || typeof item !== "object") return "Input: Invalid value";
        const loc =
          "loc" in item && Array.isArray(item.loc)
            ? item.loc
                .slice(1)
                .filter(
                  (part: unknown) =>
                    typeof part === "string" || typeof part === "number",
                )
                .join(" / ")
            : "";
        const msg =
          "msg" in item && typeof item.msg === "string" && item.msg
            ? item.msg
            : "Invalid value";
        return `${loc || "Input"}: ${msg}`;
      })
      .join("; ");
  }
  return `The request failed (${status}). Please try again.`;
}

export function linkedinIdentity(value: string) {
  const url = new URL(value);
  const match = url.pathname.match(/^\/jobs\/view\/(\d+)\/?$/);
  return url.origin === "https://www.linkedin.com" &&
    !url.username &&
    !url.password &&
    match
    ? match[1]
    : null;
}

export function filterApplications<
  T extends {
    id: number;
    state: string;
    evaluation: { score?: number };
    job: { title: string; company: string; location: string };
  },
>(rows: T[], { query = "", state = "all", sort = "recent" } = {}) {
  const terms = query
    .trim()
    .toLocaleLowerCase("en-GB")
    .split(/\s+/)
    .filter(Boolean);
  const filtered = rows.filter((row) => {
    const text = [row.job.title, row.job.company, row.job.location]
      .join(" ")
      .toLocaleLowerCase("en-GB");
    return (
      (state === "all" || row.state === state) &&
      terms.every((term) => text.includes(term))
    );
  });
  return filtered.sort((a, b) => {
    if (sort === "fit")
      return (
        (b.evaluation.score ?? -1) - (a.evaluation.score ?? -1) || b.id - a.id
      );
    if (sort === "company")
      return a.job.company.localeCompare(b.job.company, "en-GB") || b.id - a.id;
    return b.id - a.id;
  });
}
