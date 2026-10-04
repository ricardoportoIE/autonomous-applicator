/** Public local API contracts. Private records are held only in memory. */
export interface Evidence {
  id: string;
  category:
    "skill" | "project" | "experience" | "education" | "language" | "award";
  title: string;
  text: string;
  dates: string;
  tags: string[];
  source: string;
  verified: boolean;
}
export interface Profile {
  name: string;
  email: string;
  phone: string;
  location: string;
  summary: string;
  links: string[];
  sponsorship_required: boolean;
  confirmed: boolean;
  answers: Record<string, string>;
  evidence: Evidence[];
}
export interface Settings {
  automation_enabled: boolean;
  ai_document_preparation: boolean;
  routine_answers_enabled: boolean;
  automatic_location_policy:
    "same_city" | "same_country" | "configured_countries";
  linkedin_authorised: boolean;
  connections_enabled: boolean;
  discovery_enabled: boolean;
  daily_limit: number;
  daily_connection_limit: number;
  auto_threshold: number;
  review_threshold: number;
  allowed_countries: string[];
  poll_seconds: number;
  search_keywords: string;
  search_location: string;
}
export interface Question {
  id: string;
  label: string;
  answer_key: string;
  choices: string[];
  required: boolean;
  sensitive: boolean;
}
export interface AnswerIdea {
  draft: string;
  evidence_ids: string[];
  fact_keys: string[];
  review_notes: string;
  needs_clarification: boolean;
  model: string;
  profile_revision: number;
}
export interface Job {
  source: "manual" | "greenhouse" | "linkedin" | "fixture" | "permitted";
  source_id: string;
  title: string;
  company: string;
  location: string;
  url: string;
  description: string;
  requirements: string[];
  sponsorship: "unknown" | "available" | "unavailable";
  cover_letter_required: boolean;
  questions: Question[];
}
export type ApplicationState =
  "ready" | "review" | "skipped" | "submitting" | "submitted" | "uncertain";
export interface Application {
  id: number;
  job: Job;
  state: ApplicationState;
  outcome: string | null;
  receipt: string | null;
  routine_answers?: RoutineAnswerRecord[];
  evaluation: {
    score?: number;
    matched?: string[];
    gaps?: string[];
    reasons?: string[];
    blockers?: string[];
  };
  manifest: {
    revision?: number;
    evidence_ids?: string[];
    generation?: {
      method: string;
      model?: string;
      requested_model?: string;
      response_id?: string;
    };
    files?: Record<string, { name: string; sha256: string }>;
  };
}
export interface Preflight {
  evaluation?: Application["evaluation"] | null;
  checked_at: string;
  can_submit: boolean;
  checks: { code: string; label: string; passed: boolean; detail: string }[];
}
export interface Event {
  id: number;
  kind: string;
  detail: string;
  created: string;
}
export interface Usage {
  day: string;
  timezone: string;
  used: number;
  held: number;
  attempts: number;
  limit: number;
  remaining: number;
}
export interface RoutineAnswerRecord {
  answer_key: string;
  question: Question;
  answer: string;
  source: string;
  evidence_ids: string[];
  revision: number;
}
export interface Insights {
  submitted: number;
  outcomes: Record<string, number>;
  suggestion: string;
  automatic_changes: boolean;
}
export interface Connection {
  id: number;
  url: string;
  name: string;
  role: string;
  location: string;
  photo_available: boolean;
  state: "queued" | "sending" | "sent" | "uncertain" | "failed";
  run_status: string;
  run_message: string;
}
export interface WorkerRun {
  id: string;
  status: string;
  application_id: number | null;
  job: Job | null;
  stage: string;
  detail: string;
  error_code: string | null;
  started: string;
  stage_started: string;
  finished: string | null;
}
export interface WorkerRecord {
  run: WorkerRun | null;
  results: {
    job: Job;
    application_id: number;
    outcome: string;
    stage: string;
    error_code: string | null;
  }[];
}
export interface ApplicationDetail {
  profile_revision?: number;
  row: Application;
  report: Preflight;
  events: Event[];
}
export type View =
  | "overview"
  | "applications"
  | "profile"
  | "networking"
  | "settings"
  | "activity";
