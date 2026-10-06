import {
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from "react";
import type { Application, Evidence, Profile, Settings } from "./contracts";
import { linkedinIdentity, parseAnswers, splitList } from "./ui";
import type { Workspace } from "./workspace";

function Field({
  label,
  name,
  value = "",
  type = "text",
  required = false,
  min,
  max,
  pattern,
  rows,
  children,
}: {
  label: string;
  name: string;
  value?: string | number;
  type?: string;
  required?: boolean;
  min?: number;
  max?: number;
  pattern?: string;
  rows?: number;
  children?: ReactNode;
}) {
  return (
    <label>
      {label}
      {children ? (
        <select
          name={name}
          aria-label={label}
          defaultValue={value}
          required={required}
        >
          {children}
        </select>
      ) : rows ? (
        <textarea
          name={name}
          aria-label={label}
          defaultValue={value}
          rows={rows}
          required={required}
          spellCheck={name !== "answers"}
        />
      ) : (
        <input
          name={name}
          aria-label={label}
          type={type}
          defaultValue={value}
          required={required}
          min={min}
          max={max}
          pattern={pattern}
        />
      )}
    </label>
  );
}
function Check({
  name,
  label,
  checked = false,
}: {
  name: string;
  label: string;
  checked?: boolean;
}) {
  return (
    <label className="check">
      <input name={name} type="checkbox" defaultChecked={checked} />
      {label}
    </label>
  );
}
function read(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();
  // Capture before React disables the form or an asynchronous identity hash yields.
  return new FormData(event.currentTarget);
}
const text = (form: FormData, name: string) => String(form.get(name) ?? "");
const checked = (form: FormData, name: string) => form.has(name);

export function ProfileForm({
  profile,
  revision,
  workspace,
  done,
}: {
  profile: Profile | null;
  revision: number;
  workspace: Workspace;
  done: () => void;
}) {
  return (
    <form
      id="profile-form"
      onSubmit={(event) => {
        const form = read(event);
        void workspace.action(async () => {
          const value: Profile = {
            name: text(form, "name"),
            email: text(form, "email"),
            phone: text(form, "phone"),
            location: text(form, "location"),
            summary: text(form, "summary"),
            links: splitList(text(form, "links"), "\n"),
            answers: parseAnswers(text(form, "answers")),
            confirmed: checked(form, "confirmed"),
            sponsorship_required: checked(form, "sponsorship_required"),
            evidence: profile?.evidence ?? [],
          };
          await workspace.mutate(
            "/profile",
            "PUT",
            value,
            "Profile saved. Earlier documents need regeneration.",
            undefined,
            revision,
          );
          done();
        });
      }}
    >
      <p>
        Confirm facts before enabling automation. Editing the profile
        invalidates earlier documents.
      </p>
      <div className="grid">
        <Field
          label="Professional name"
          name="name"
          value={profile?.name}
          required
        />
        <Field
          label="E-mail"
          name="email"
          type="email"
          value={profile?.email}
          required
        />
        <Field label="Phone" name="phone" value={profile?.phone} />
        <Field
          label="Location"
          name="location"
          value={profile?.location}
          required
        />
      </div>
      <Field
        label="Professional summary (approved wording)"
        name="summary"
        value={profile?.summary}
        rows={3}
      />
      <Field
        label="Professional links, one per line"
        name="links"
        value={profile?.links.join("\n")}
        rows={3}
      />
      <Check
        name="sponsorship_required"
        label="Sponsorship required"
        checked={profile?.sponsorship_required ?? true}
      />
      <Check
        name="confirmed"
        label="I have reviewed and confirmed the candidate facts"
        checked={profile?.confirmed}
      />
      <Field
        label="Approved form answers (JSON object)"
        name="answers"
        value={JSON.stringify(profile?.answers ?? {}, null, 2)}
        rows={6}
      />
      <small>
        Use an exact question label prefixed with “question:”, in lower case.
        Unknown answers pause the application.
      </small>
      <div className="form-actions">
        <button>Save candidate profile</button>
      </div>
    </form>
  );
}
export function EvidenceForm({
  evidence,
  workspace,
  done,
}: {
  evidence: Evidence | null;
  workspace: Workspace;
  done: () => void;
}) {
  return (
    <form
      id="evidence-form"
      onSubmit={(event) => {
        const form = read(event);
        void workspace.action(async () => {
          if (!workspace.getSnapshot().profile)
            throw new Error("Save your candidate profile first.");
          const value: Evidence = {
            id: text(form, "id"),
            category: text(form, "category") as Evidence["category"],
            title: text(form, "title"),
            text: text(form, "text"),
            dates: text(form, "dates"),
            source: text(form, "source"),
            tags: splitList(text(form, "tags")),
            verified: checked(form, "verified"),
          };
          await workspace.mutate(
            "/evidence/" + encodeURIComponent(value.id),
            "PUT",
            value,
            "Evidence saved.",
          );
          done();
        });
      }}
    >
      <div className="grid">
        <Field
          label="Evidence identifier"
          name="id"
          value={evidence?.id}
          required
          pattern="[a-zA-Z0-9_-]{1,64}"
        />
        <Field
          label="Category"
          name="category"
          value={evidence?.category ?? "skill"}
        >
          {[
            ["skill", "Skill"],
            ["project", "Independent / academic project"],
            ["experience", "Work experience"],
            ["education", "Qualification"],
            ["language", "Language"],
            ["award", "Award"],
          ].map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Field>
      </div>
      <Field label="Title" name="title" value={evidence?.title} required />
      <Field
        label="Factual description"
        name="text"
        value={evidence?.text}
        rows={4}
        required
      />
      <Field label="Dates as confirmed" name="dates" value={evidence?.dates} />
      <Field
        label="Technology tags, comma-separated"
        name="tags"
        value={evidence?.tags.join(", ")}
      />
      <Field
        label="Evidence source"
        name="source"
        value={evidence?.source}
        required
      />
      <Check
        name="verified"
        label="Reviewed and approved for applications"
        checked={evidence?.verified}
      />
      <div className="form-actions">
        <button>Save evidence</button>
      </div>
    </form>
  );
}
export function JobForm({
  application,
  workspace,
  done,
}: {
  application: Application | null;
  workspace: Workspace;
  done: () => void;
}) {
  const job = application?.job;
  const [fromLink, setFromLink] = useState(true);
  const state = useSyncExternalStore(
    workspace.subscribe,
    workspace.getSnapshot,
  );
  const mode = !job && (
    <div className="form-actions" aria-label="Opportunity entry method">
      <button
        type="button"
        className={fromLink ? "" : "secondary"}
        aria-pressed={fromLink}
        onClick={() => setFromLink(true)}
      >
        Import from link
      </button>
      <button
        type="button"
        className={fromLink ? "secondary" : ""}
        aria-pressed={!fromLink}
        onClick={() => setFromLink(false)}
      >
        Enter details manually
      </button>
    </div>
  );
  if (!job && fromLink)
    return (
      <>
        {mode}
        <form
          id="job-form"
          aria-busy={state.pending}
          onSubmit={(event) => {
            const form = read(event);
            const session = workspace.api.session();
            void workspace.action(async () => {
              const result = await workspace.api.json<{
                id: number;
                created: boolean;
              }>("/jobs/from-url", "POST", { url: text(form, "url") });
              if (!workspace.api.isCurrent(session)) return;
              await workspace.refresh();
              if (!workspace.api.isCurrent(session)) return;
              workspace.message(
                result.created
                  ? "Opportunity imported from LinkedIn. Added to the preparation queue."
                  : "This opportunity is already in your queue. Its saved details have been preserved.",
              );
              done();
            });
          }}
        >
          <p>
            Paste a LinkedIn job link. The agent reads the title, company,
            location and full description using your dedicated browser session.
          </p>
          <Field label="Job URL" name="url" type="url" required />
          <p className="muted">
            Other websites: use manual entry or the Greenhouse board importer.
            Application questions are discovered when the application form is
            opened.
          </p>
          <p role="status" aria-live="polite">
            {state.pending
              ? "Importing… Opening the opportunity, reading details and saving to the queue."
              : "Ready to import. Your declared LinkedIn authorisation and browser sign-in are required."}
          </p>
          <div className="form-actions">
            <button disabled={state.pending}>
              {state.pending ? "Importing…" : "Save opportunity"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={state.pending}
              onClick={done}
            >
              Cancel
            </button>
          </div>
        </form>
      </>
    );
  return (
    <>
      {mode}
      <form
        id="job-form"
        onSubmit={(event) => {
          const form = read(event);
          const session = workspace.api.session();
          void workspace.action(async () => {
            const url = text(form, "url");
            const identity = linkedinIdentity(url);
            const hash =
              !job && !identity
                ? Array.from(
                    new Uint8Array(
                      await crypto.subtle.digest(
                        "SHA-256",
                        new TextEncoder().encode(url),
                      ),
                    ),
                  )
                    .map((byte) => byte.toString(16).padStart(2, "0"))
                    .join("")
                : "";
            if (!workspace.api.isCurrent(session))
              throw new Error("Workspace locked. Unlock it before continuing.");
            const value = {
              title: text(form, "title"),
              company: text(form, "company"),
              location: text(form, "location"),
              url,
              description: text(form, "description"),
              requirements: splitList(text(form, "requirements")),
              sponsorship: text(form, "sponsorship"),
              cover_letter_required: checked(form, "cover_letter_required"),
              source: job?.source ?? (identity ? "linkedin" : "manual"),
              source_id: job?.source_id ?? identity ?? hash,
              questions: job?.questions ?? [],
            };
            await workspace.mutate(
              application ? `/applications/${application.id}/job` : "/jobs",
              application ? "PUT" : "POST",
              value,
              "Opportunity imported. Prepare it to evaluate the fit.",
              application?.id,
            );
            done();
          });
        }}
      >
        <div className="grid">
          <Field label="Job title" name="title" value={job?.title} required />
          <Field label="Company" name="company" value={job?.company} required />
          <Field
            label="Location"
            name="location"
            value={job?.location}
            required
          />
          <Field
            label="Job URL"
            name="url"
            value={job?.url}
            type="url"
            required
          />
        </div>
        <Field
          label="Job description"
          name="description"
          value={job?.description}
          rows={7}
          required
        />
        <Field
          label="Required technologies, comma-separated"
          name="requirements"
          value={job?.requirements.join(", ")}
        />
        <Field
          label="Sponsorship"
          name="sponsorship"
          value={job?.sponsorship ?? "unknown"}
        >
          <option value="unknown">Not stated</option>
          <option value="available">Available</option>
          <option value="unavailable">Explicitly unavailable</option>
        </Field>
        <Check
          name="cover_letter_required"
          label="Cover letter required"
          checked={job?.cover_letter_required}
        />
        <div className="form-actions">
          <button>
            {job ? "Save updated opportunity" : "Save opportunity"}
          </button>
          <button
            type="button"
            id="cancel-job-edit"
            className="secondary"
            onClick={done}
          >
            {job ? "Cancel editing" : "Cancel"}
          </button>
        </div>
      </form>
    </>
  );
}
export function ContactForm({
  workspace,
  done,
}: {
  workspace: Workspace;
  done: () => void;
}) {
  return (
    <form
      id="connection-form"
      onSubmit={(event) => {
        const form = read(event);
        void workspace.action(async () => {
          await workspace.mutate(
            "/connections",
            "POST",
            Object.fromEntries(form),
            "Contact queued within the networking policy.",
          );
          done();
        });
      }}
    >
      <p>
        Select a relevant European recruiter or hiring contact. The agent
        verifies the identity, role and location before sending an invitation
        without a note.
      </p>
      <Field label="LinkedIn profile URL" name="url" type="url" required />
      <Field label="Member's displayed name" name="name" required />
      <Field label="Displayed role / headline" name="role" required />
      <Field label="Displayed European location" name="location" required />
      <div className="form-actions">
        <button>Queue contact</button>
      </div>
    </form>
  );
}
export function BoardForm({
  workspace,
  done,
}: {
  workspace: Workspace;
  done: () => void;
}) {
  return (
    <form
      id="board-form"
      onSubmit={(event) => {
        const form = read(event);
        void workspace.action(async () => {
          const result = await workspace.api.json<{ imported: number }>(
            "/discover/greenhouse",
            "POST",
            { board: text(form, "board") },
          );
          await workspace.refresh();
          workspace.message(`Imported ${result.imported} new opportunities.`);
          done();
        });
      }}
    >
      <p>Use an employer’s public Greenhouse board identifier.</p>
      <Field label="Greenhouse board" name="board" required />
      <div className="form-actions">
        <button>Import board jobs</button>
      </div>
    </form>
  );
}
export function SettingsForm({
  settings,
  workspace,
}: {
  settings: Settings;
  workspace: Workspace;
}) {
  return (
    <form
      id="settings-form"
      onSubmit={(event) => {
        const form = read(event);
        void workspace.action(async () => {
          const value = { ...settings };
          for (const name of [
            "automation_enabled",
            "linkedin_authorised",
            "connections_enabled",
            "discovery_enabled",
            "ai_document_preparation",
            "routine_answers_enabled",
          ] as const)
            value[name] = checked(form, name);
          for (const name of [
            "daily_limit",
            "daily_connection_limit",
            "auto_threshold",
            "review_threshold",
            "poll_seconds",
          ] as const)
            value[name] = Number(text(form, name));
          value.allowed_countries = splitList(text(form, "allowed_countries"));
          value.search_keywords = text(form, "search_keywords");
          value.search_location = text(form, "search_location");
          value.automatic_location_policy = text(
            form,
            "automatic_location_policy",
          ) as Settings["automatic_location_policy"];
          await workspace.mutate(
            "/settings",
            "PUT",
            value,
            "Agent settings saved.",
          );
        });
      }}
    >
      <p>
        Choose where the agent searches and when it can act. Every application
        still needs approved evidence and answers.
      </p>
      <div className="two settings-grid">
        <section className="panel">
          <p className="eyebrow">Permissions & automation</p>
          <h2>Agent controls</h2>
          <Check
            name="automation_enabled"
            label="Enable application automation"
            checked={settings.automation_enabled}
          />
          <Check
            name="linkedin_authorised"
            label="My declared LinkedIn authorisation covers discovery, Easy Apply and connection invitations"
            checked={settings.linkedin_authorised}
          />
          <Check
            name="discovery_enabled"
            label="Discover and prepare new LinkedIn opportunities each cycle"
            checked={settings.discovery_enabled}
          />
          <Field
            label="Daily sent-application limit"
            name="daily_limit"
            type="number"
            min={1}
            max={50}
            value={settings.daily_limit}
            required
          />
          <Check
            name="routine_answers_enabled"
            label="Answer routine questions from approved facts"
            checked={settings.routine_answers_enabled}
          />
          <label>
            Automatic application locations
            <select
              name="automatic_location_policy"
              aria-label="Automatic application locations"
              defaultValue={settings.automatic_location_policy}
            >
              <option value="same_city">
                My current city or remote in my country
              </option>
              <option value="same_country">My current country</option>
              <option value="configured_countries">
                All configured target countries
              </option>
            </select>
          </label>
          <small>
            Other locations require review; interesting opportunities can still
            have documents prepared.
          </small>
          <Field
            label="Agent interval (seconds)"
            name="poll_seconds"
            type="number"
            min={10}
            max={3600}
            value={settings.poll_seconds}
            required
          />
          <Check
            name="ai_document_preparation"
            label="Use GPT-6.1 Sol for document preparation by default"
            checked={settings.ai_document_preparation}
          />
          <p>
            Applies to Prepare documents and new agent preparations. API or
            document validation failures remain in review. The model selects
            approved evidence; it cannot add qualifications or approve
            questionnaire answers.
          </p>
        </section>
        <div>
          <section className="panel">
            <p className="eyebrow">Search & fit</p>
            <h2>Opportunity policy</h2>
            <div className="grid">
              <Field
                label="Automatic threshold"
                name="auto_threshold"
                type="number"
                min={80}
                max={100}
                value={settings.auto_threshold}
                required
              />
              <Field
                label="Review threshold"
                name="review_threshold"
                type="number"
                min={50}
                max={79}
                value={settings.review_threshold}
                required
              />
            </div>
            <Field
              label="Target countries, comma-separated"
              name="allowed_countries"
              value={settings.allowed_countries.join(", ")}
              required
            />
            <Field
              label="LinkedIn search keywords"
              name="search_keywords"
              value={settings.search_keywords}
              required
            />
            <Field
              label="LinkedIn search location"
              name="search_location"
              value={settings.search_location}
              required
            />
          </section>
          <section className="panel">
            <p className="eyebrow">Professional network</p>
            <h2>Networking limits</h2>
            <Check
              name="connections_enabled"
              label="Enable background networking invitations"
              checked={settings.connections_enabled}
            />
            <Field
              label="Daily connection attempt limit"
              name="daily_connection_limit"
              type="number"
              min={1}
              max={10}
              value={settings.daily_connection_limit}
              required
            />
            <p>
              Networking has a separate daily limit and enable switch. The
              global pause stops both background queues.
            </p>
          </section>
        </div>
      </div>
      <div className="form-actions">
        <button>Save agent settings</button>
      </div>
    </form>
  );
}
