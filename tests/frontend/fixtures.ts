import type {
  Application,
  Connection,
  Profile,
  Settings,
} from "../../frontend/src/contracts";
export const profile: Profile = {
  name: "Alex Example",
  email: "alex@example.test",
  phone: "",
  location: "Dublin, Ireland",
  summary: "Approved summary",
  links: [],
  confirmed: true,
  sponsorship_required: true,
  answers: {},
  evidence: [
    {
      id: "python",
      category: "project",
      title: "Independent API project",
      text: "Built a Python API.",
      tags: ["Python"],
      dates: "2025",
      source: "Candidate-approved project",
      verified: true,
    },
  ],
};
export const settings: Settings = {
  automation_enabled: false,
  ai_document_preparation: true,
  linkedin_authorised: true,
  connections_enabled: false,
  discovery_enabled: false,
  daily_limit: 10,
  daily_connection_limit: 5,
  auto_threshold: 80,
  review_threshold: 50,
  allowed_countries: ["Ireland", "United Kingdom"],
  poll_seconds: 60,
  search_keywords: "Python",
  search_location: "Ireland",
};
export const application: Application = {
  id: 1,
  state: "ready",
  outcome: null,
  receipt: null,
  job: {
    source: "manual",
    source_id: "test",
    title: "Backend Engineer",
    company: "Example Employer",
    location: "Dublin, Ireland",
    url: "https://example.test/jobs/1",
    description: "Build an API.",
    requirements: ["Python"],
    sponsorship: "available",
    questions: [],
    cover_letter_required: false,
  },
  evaluation: {
    score: 100,
    reasons: [],
    blockers: [],
    matched: ["python"],
    gaps: [],
  },
  manifest: {
    revision: 1,
    evidence_ids: ["python"],
    generation: { method: "openai", model: "gpt-6.1-sol" },
    files: { cv_pdf: { name: "Alex_Example_CV.pdf", sha256: "fixture" } },
  },
};
export const connection: Connection = {
  id: 1,
  url: "https://www.linkedin.com/in/example/",
  name: "Example Recruiter",
  role: "Technical recruiter",
  location: "Dublin, Ireland",
  photo_available: true,
  state: "queued",
  run_status: "idle",
  run_message: "",
};
export function payload(path: string): unknown {
  if (path === "/api/settings") return settings;
  if (path === "/api/profile") return { profile, revision: 1 };
  if (path === "/api/applications") return [application];
  if (path === "/api/connections") return [connection];
  if (path === "/api/usage")
    return {
      day: "2026-10-04",
      timezone: "Europe/London",
      used: 0,
      limit: 10,
      remaining: 10,
    };
  if (path === "/api/insights")
    return {
      submitted: 0,
      outcomes: { interview: 0, offer: 0, rejected: 0 },
      suggestion: "Insufficient outcome evidence.",
      automatic_changes: false,
    };
  if (path.endsWith("/events")) return [];
  if (path === "/api/worker/status") return { run: null, results: [] };
  if (path.endsWith("/preflight"))
    return {
      checked_at: "2026-10-04T10:00:00Z",
      can_submit: false,
      checks: [],
    };
  if (path === "/api/applications/1") return application;
  if (path.endsWith("/status")) return connection;
  return {};
}
