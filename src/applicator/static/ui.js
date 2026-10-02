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
});

export function stateLabel(value) {
  return Object.hasOwn(stateLabels, value)
    ? stateLabels[value]
    : "Unknown status";
}

export function splitList(value, separator = ",") {
  return [
    ...new Set(
      value
        .split(separator)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
}

export function parseAnswers(value) {
  let answers;
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
  return answers;
}

export function errorDetail(body, status) {
  if (typeof body?.detail === "string") return body.detail;
  if (Array.isArray(body?.detail)) {
    return body.detail
      .map(
        (item) =>
          `${item.loc?.slice(1).join(" / ") || "Input"}: ${item.msg || "Invalid value"}`,
      )
      .join("; ");
  }
  return `The request failed (${status}). Please try again.`;
}

export function linkedinIdentity(value) {
  const url = new URL(value);
  const match = url.pathname.match(/^\/jobs\/view\/(\d+)\/?$/);
  return url.origin === "https://www.linkedin.com" &&
    !url.username &&
    !url.password &&
    match
    ? match[1]
    : null;
}
