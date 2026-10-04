import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  BoardForm,
  ContactForm,
  EvidenceForm,
  JobForm,
  ProfileForm,
  SettingsForm,
} from "../../frontend/src/forms";
import { application, profile, settings } from "./fixtures";
import { deferred, harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(async () => {
  h = harness();
  await h.unlock();
});
afterEach(() => h.stop());
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: true }), {
    target: { value },
  });
}
function submit(button: string) {
  fireEvent.submit(
    screen.getByRole("button", { name: button }).closest("form")!,
  );
}

it.each([true, false])(
  "saves all candidate facts with the opening revision; existing=%s",
  async (existing) => {
    const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
    const done = vi.fn();
    render(
      <ProfileForm
        profile={existing ? profile : null}
        revision={7}
        workspace={h.workspace}
        done={done}
      />,
    );
    fill("Professional name", "Alex Example");
    (screen.getByLabelText("Phone") as HTMLInputElement).disabled = true;
    fill("E-mail", "alex@example.test");
    fill("Location", "Dublin, Ireland");
    fill("Professional summary (approved wording)", "Approved facts");
    fill(
      "Professional links, one per line",
      "https://example.test\nhttps://example.test",
    );
    fill("Approved form answers (JSON object)", '{"question:python?":"Yes"}');
    submit("Save candidate profile");
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(mutate).toHaveBeenCalledWith(
      "/profile",
      "PUT",
      expect.objectContaining({
        name: "Alex Example",
        links: ["https://example.test"],
        answers: { "question:python?": "Yes" },
        evidence: existing ? profile.evidence : [],
      }),
      expect.any(String),
      undefined,
      7,
    );
  },
);

it("keeps an invalid JSON candidate draft open without making a mutation", async () => {
  const mutate = vi.spyOn(h.workspace, "mutate");
  const done = vi.fn();
  render(
    <ProfileForm
      profile={profile}
      revision={1}
      workspace={h.workspace}
      done={done}
    />,
  );
  fill("Approved form answers (JSON object)", "invalid");
  submit("Save candidate profile");
  await waitFor(() => expect(h.workspace.getSnapshot().error).toBe(true));
  expect(mutate).not.toHaveBeenCalled();
  expect(done).not.toHaveBeenCalled();
});

it.each([true, false])(
  "saves approved evidence with exact source text; existing=%s",
  async (existing) => {
    const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
    const done = vi.fn();
    render(
      <EvidenceForm
        evidence={existing ? profile.evidence[0] : null}
        workspace={h.workspace}
        done={done}
      />,
    );
    fill("Evidence identifier", "python-example");
    fill("Title", "Verified project");
    fill("Factual description", "Built a tested API.");
    fill("Technology tags, comma-separated", "Python, SQL, Python");
    fill("Evidence source", "Candidate-approved record");
    submit("Save evidence");
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(mutate).toHaveBeenCalledWith(
      "/evidence/python-example",
      "PUT",
      expect.objectContaining({
        text: "Built a tested API.",
        tags: ["Python", "SQL"],
      }),
      expect.any(String),
    );
  },
);

it("requires a candidate profile before saving evidence", async () => {
  h.responses.set("/api/profile", { profile: null, revision: 0 });
  await h.workspace.refresh();
  const done = vi.fn();
  render(<EvidenceForm evidence={null} workspace={h.workspace} done={done} />);
  submit("Save evidence");
  await waitFor(() =>
    expect(h.workspace.getSnapshot().notice).toContain("candidate profile"),
  );
  expect(done).not.toHaveBeenCalled();
});

it.each([
  "https://www.linkedin.com/jobs/view/123/",
  "https://example.test/jobs/new",
])("imports an opportunity using a stable identity: %s", async (url) => {
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  const done = vi.fn();
  render(<JobForm application={null} workspace={h.workspace} done={done} />);
  fill("Job title", "Backend Engineer");
  fill("Company", "Example Employer");
  fill("Location", "Dublin, Ireland");
  fill("Job URL", url);
  fill("Job description", "Build a Python API.");
  fill("Required technologies, comma-separated", "Python, SQL");
  submit("Save opportunity");
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  const body = mutate.mock.calls[0][2];
  expect(body).toMatchObject({
    source: url.includes("linkedin") ? "linkedin" : "manual",
    requirements: ["Python", "SQL"],
    questions: [],
  });
  expect(body).toHaveProperty(
    "source_id",
    url.includes("linkedin") ? "123" : expect.stringMatching(/^[a-f0-9]{64}$/),
  );
});

it("edits an opportunity without changing its source identity or known questions and supports cancellation", async () => {
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  const done = vi.fn();
  render(
    <JobForm application={application} workspace={h.workspace} done={done} />,
  );
  fill("Job title", "Updated title");
  submit("Save updated opportunity");
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(mutate).toHaveBeenCalledWith(
    "/applications/1/job",
    "PUT",
    expect.objectContaining({ source_id: "test", title: "Updated title" }),
    expect.any(String),
    1,
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel editing" }));
  expect(done).toHaveBeenCalledTimes(2);
});

it("does not import a manual opportunity if the session locks during identity calculation", async () => {
  const hash = deferred<ArrayBuffer>();
  vi.spyOn(crypto.subtle, "digest").mockReturnValue(hash.promise);
  const mutate = vi.spyOn(h.workspace, "mutate");
  const done = vi.fn();
  render(<JobForm application={null} workspace={h.workspace} done={done} />);
  fill("Job URL", "https://example.test/new");
  submit("Save opportunity");
  h.workspace.lock();
  hash.resolve(new ArrayBuffer(32));
  await hash.promise;
  await Promise.resolve();
  expect(mutate).not.toHaveBeenCalled();
  expect(done).not.toHaveBeenCalled();
});

it("queues exactly the contact entered in the form", async () => {
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  const done = vi.fn();
  render(<ContactForm workspace={h.workspace} done={done} />);
  fill("LinkedIn profile URL", "https://www.linkedin.com/in/example/");
  fill("Member's displayed name", "Example Recruiter");
  fill("Displayed role / headline", "Recruiter");
  fill("Displayed European location", "Ireland");
  submit("Queue contact");
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(mutate).toHaveBeenCalledWith(
    "/connections",
    "POST",
    {
      url: "https://www.linkedin.com/in/example/",
      name: "Example Recruiter",
      role: "Recruiter",
      location: "Ireland",
    },
    expect.any(String),
  );
});

it("imports a public board once and keeps failures editable", async () => {
  const done = vi.fn();
  render(<BoardForm workspace={h.workspace} done={done} />);
  fill("Greenhouse board", "example");
  h.responses.set("/api/discover/greenhouse", { imported: 3 });
  submit("Import board jobs");
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(h.workspace.getSnapshot().notice).toContain("3 new opportunities");
  h.fetch.mockRejectedValueOnce(new Error("Unavailable"));
  submit("Import board jobs");
  await waitFor(() => expect(h.workspace.getSnapshot().error).toBe(true));
  expect(done).toHaveBeenCalledOnce();
});

it("saves every settings control without dropping policy fields", async () => {
  const mutate = vi.spyOn(h.workspace, "mutate").mockResolvedValue();
  render(<SettingsForm settings={settings} workspace={h.workspace} />);
  fill("Daily sent-application limit", "7");
  fill("Daily connection attempt limit", "4");
  fill("Target countries, comma-separated", "Ireland, France, Ireland");
  fill("Automatic application locations", "configured_countries");
  fireEvent.click(screen.getByLabelText("Enable application automation"));
  submit("Save agent settings");
  await waitFor(() => expect(mutate).toHaveBeenCalledOnce());
  expect(mutate).toHaveBeenCalledWith(
    "/settings",
    "PUT",
    {
      ...settings,
      automation_enabled: true,
      daily_limit: 7,
      daily_connection_limit: 4,
      allowed_countries: ["Ireland", "France"],
      automatic_location_policy: "configured_countries",
    },
    "Agent settings saved.",
  );
});
