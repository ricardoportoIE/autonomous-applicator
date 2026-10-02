"use strict";
const $ = (selector) => document.querySelector(selector);
const all = (selector) => [...document.querySelectorAll(selector)];
let token = sessionStorage.getItem("applicator-token") || "";
let editingJob = null;
let profile = null,
  settings = null,
  applications = [];
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function message(text, error = false) {
  $("#notice").textContent = text;
  $("#notice").className = error ? "error" : "";
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
async function action(callback) {
  try {
    await callback();
  } catch (error) {
    message(error.message, true);
  }
}
function read(form) {
  return Object.fromEntries(new FormData(form));
}
function fill(form, object) {
  for (const [key, value] of Object.entries(object)) {
    const input = form.elements.namedItem(key);
    if (!input) continue;
    if (input.type === "checkbox") input.checked = value;
    else
      input.value = Array.isArray(value)
        ? value.join(key === "links" ? "\n" : ", ")
        : typeof value === "object"
          ? JSON.stringify(value, null, 2)
          : value;
  }
}
function view(name) {
  all("[data-section]").forEach(
    (el) => (el.hidden = el.dataset.section !== name),
  );
  all("[data-view]").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === name),
  );
  $("#page-title").textContent = {
    overview: "Overview",
    applications: "Applications",
    profile: "Candidate profile",
    networking: "Networking",
    settings: "Agent settings",
    activity: "Activity log",
  }[name];
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
}
all("[data-view]").forEach(
  (button) => (button.onclick = () => view(button.dataset.view)),
);
function applicationTable(rows, target) {
  target.replaceChildren();
  if (!rows.length) {
    target.append(
      node("p", "No opportunities yet. Import a job to start.", "empty"),
    );
    return;
  }
  const table = node("table"),
    head = node("tr");
  ["Opportunity", "Fit", "Status", ""].forEach((text) =>
    head.append(node("th", text)),
  );
  table.append(head);
  for (const row of rows) {
    const tr = node("tr"),
      job = node("td");
    job.append(
      node("strong", row.job.title),
      node("small", row.job.company + " · " + row.job.location),
    );
    tr.append(
      job,
      node(
        "td",
        row.evaluation.score === undefined ? "—" : row.evaluation.score,
        "score",
      ),
    );
    const status = node("td");
    status.append(node("span", row.state, "badge " + row.state));
    tr.append(status);
    const cell = node("td"),
      button = node("button", "Open", "secondary");
    button.onclick = () => action(() => detail(row.id));
    cell.append(button);
    tr.append(cell);
    table.append(tr);
  }
  target.append(table);
}
async function refresh() {
  settings = await api("/settings");
  applications = await api("/applications");
  try {
    profile = (await api("/profile")).profile;
    fill($("#profile-form"), profile);
  } catch (error) {
    profile = null;
  }
  fill($("#settings-form"), settings);
  $("#stats").replaceChildren();
  const stats = [
    ["Opportunities", applications.length],
    ["Ready", applications.filter((a) => a.state === "ready").length],
    ["For review", applications.filter((a) => a.state === "review").length],
    ["Submitted", applications.filter((a) => a.state === "submitted").length],
  ];
  for (const [label, value] of stats) {
    const el = node("div", undefined, "stat");
    el.append(node("span", label), node("strong", String(value)));
    $("#stats").append(el);
  }
  applicationTable(applications, $("#application-list"));
  applicationTable(applications.slice(0, 5), $("#recent"));
  renderEvidence();
  const insights = await api("/insights");
  $("#insights").replaceChildren(node("p", insights.suggestion));
  const events = await api("/events");
  $("#events").replaceChildren();
  for (const event of events) {
    const el = node("div", undefined, "entry");
    el.append(
      node("strong", event.kind),
      node("p", event.detail),
      node("small", new Date(event.created).toLocaleString("en-GB")),
    );
    $("#events").append(el);
  }
  const connections = await api("/connections");
  $("#connections").replaceChildren();
  for (const item of connections) {
    const el = node("div", undefined, "entry");
    el.append(
      node("strong", item.name),
      node("p", item.role + " · " + item.location),
      node("span", item.state, "badge " + item.state),
    );
    if (item.state === "queued") {
      const button = node("button", "Send queued invitation", "secondary");
      button.onclick = () =>
        action(async () => {
          await api("/connections/" + item.id + "/send", "POST");
          message("Invitation confirmed.");
          await refresh();
        });
      el.append(button);
    }
    $("#connections").append(el);
  }
  $("#pause").textContent = settings.automation_enabled
    ? "Pause all automation"
    : "Automation paused";
}
function renderEvidence() {
  const target = $("#evidence-list");
  target.replaceChildren();
  for (const item of profile?.evidence || []) {
    const el = node("div", undefined, "entry");
    el.append(
      node("strong", item.title),
      node("p", item.text),
      node(
        "small",
        item.category +
          " · " +
          item.dates +
          " · " +
          (item.verified ? "Approved" : "Needs confirmation"),
      ),
    );
    const edit = node("button", "Edit", "secondary");
    edit.onclick = () => fill($("#evidence-form"), item);
    const remove = node("button", "Remove", "danger");
    remove.onclick = () =>
      action(async () => {
        await api("/evidence/" + encodeURIComponent(item.id), "DELETE");
        await refresh();
        message("Evidence removed; previous documents invalidated.");
      });
    el.append(edit, remove);
    target.append(el);
  }
}
async function detail(id) {
  view("applications");
  const row = await api("/applications/" + id),
    target = $("#application-detail");
  target.hidden = false;
  target.replaceChildren(
    node("h2", row.job.title),
    node("p", row.job.company + " · " + row.job.location),
  );
  const link = node("a", "Open original opportunity");
  link.href = row.job.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  target.append(link);
  if (row.evaluation.score !== undefined) {
    target.append(
      node("p", "Fit: " + row.evaluation.score + "/100 · " + row.state),
    );
    for (const reason of [
      ...row.evaluation.reasons,
      ...row.evaluation.blockers,
    ])
      target.append(node("p", reason));
    target.append(
      node("p", "Matched: " + row.evaluation.matched.join(", ")),
      node("p", "Gaps: " + row.evaluation.gaps.join(", ")),
    );
  }
  for (const question of row.job.questions || []) {
    const form = node("form"),
      label = node("label", question.label),
      input = node("input"),
      button = node("button", "Approve answer", "secondary");
    input.required = true;
    input.value = profile?.answers[question.answer_key] || "";
    label.append(input);
    form.append(label, button);
    form.onsubmit = (event) => {
      event.preventDefault();
      action(async () => {
        if (!profile) throw new Error("Configure the candidate profile first.");
        await api("/profile", "PUT", {
          ...profile,
          answers: { ...profile.answers, [question.answer_key]: input.value },
        });
        await refresh();
        await detail(id);
        message("Answer approved. Regenerate documents before submission.");
      });
    };
    target.append(form);
  }
  const actions = node("div", undefined, "actions");
  if (!["submitted", "submitting", "uncertain"].includes(row.state)) {
    const edit = node("button", "Edit job details", "secondary");
    edit.onclick = () => {
      editingJob = row;
      fill($("#job-form"), row.job);
      $("#job-form button").textContent = "Save updated opportunity";
      $("#job-form").scrollIntoView({ behavior: "smooth" });
    };
    actions.append(edit);
  }
  for (const [label, ai] of [
    ["Prepare documents", false],
    ["Select evidence with GPT-6.1 Sol", true],
  ]) {
    const button = node("button", label, "secondary");
    button.disabled = ["submitted", "submitting", "uncertain"].includes(
      row.state,
    );
    button.onclick = () =>
      action(async () => {
        await api("/applications/" + id + "/prepare", "POST", { use_ai: ai });
        await refresh();
        await detail(id);
        message("Documents prepared from approved evidence.");
      });
    actions.append(button);
  }
  if (row.state === "ready") {
    const submit = node("button", "Run authorised submission");
    submit.onclick = () =>
      action(async () => {
        await api("/applications/" + id + "/submit", "POST");
        await refresh();
        await detail(id);
        message("Provider receipt recorded.");
      });
    actions.append(submit);
  }
  target.append(actions);
  for (const [key, item] of Object.entries(row.manifest.files || {})) {
    const button = node("button", "Download " + item.name, "secondary");
    button.onclick = () =>
      action(async () => {
        const response = await fetch(
          "/api/applications/" + id + "/documents/" + key,
          { headers: { Authorization: "Bearer " + token } },
        );
        if (!response.ok)
          throw new Error("Document is missing or stale. Regenerate it.");
        const url = URL.createObjectURL(await response.blob()),
          anchor = node("a");
        anchor.href = url;
        anchor.download = item.name;
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    actions.append(button);
  }
  if (["review", "ready", "uncertain"].includes(row.state)) {
    const form = node("form"),
      label = node(
        "label",
        "Manual submission receipt or confirmation reference",
      ),
      input = node("input"),
      button = node(
        "button",
        "Record confirmed manual submission",
        "secondary",
      );
    input.required = true;
    label.append(input);
    form.append(label, button);
    form.onsubmit = (event) => {
      event.preventDefault();
      action(async () => {
        await api("/applications/" + id + "/receipt", "POST", {
          receipt: input.value,
        });
        await refresh();
        await detail(id);
      });
    };
    target.append(form);
  }
  if (row.state === "submitted") {
    const label = node("label", "Record outcome"),
      select = node("select");
    for (const value of [
      "interview",
      "offer",
      "rejected",
      "no_response",
      "withdrawn",
    ]) {
      const option = node("option", value);
      option.value = value;
      select.append(option);
    }
    label.append(select);
    const button = node("button", "Save outcome", "secondary");
    button.onclick = () =>
      action(async () => {
        await api("/applications/" + id + "/outcome", "POST", {
          outcome: select.value,
        });
        await refresh();
        message("Outcome saved.");
      });
    target.append(label, button);
  }
  target.scrollIntoView({ behavior: "smooth" });
}
$("#token-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    token = $("#token").value;
    await api("/settings");
    sessionStorage.setItem("applicator-token", token);
    $("#login").hidden = true;
    $("#workspace").hidden = false;
    await refresh();
    message("Local workspace unlocked.");
  });
};
$("#profile-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const form = event.target,
      obj = read(form);
    obj.links = obj.links
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    obj.answers = JSON.parse(obj.answers || "{}");
    obj.confirmed = form.elements.confirmed.checked;
    obj.sponsorship_required = form.elements.sponsorship_required.checked;
    obj.evidence = profile?.evidence || [];
    await api("/profile", "PUT", obj);
    await refresh();
    message("Profile saved. Earlier documents need regeneration.");
  });
};
$("#evidence-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    if (!profile) throw new Error("Save your candidate profile first.");
    const obj = read(event.target);
    obj.tags = obj.tags
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    obj.verified = event.target.elements.verified.checked;
    const updated = {
      ...profile,
      evidence: [...profile.evidence.filter((item) => item.id !== obj.id), obj],
    };
    await api("/profile", "PUT", updated);
    event.target.reset();
    await refresh();
    message("Evidence saved.");
  });
};
$("#job-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const obj = read(event.target);
    obj.requirements = obj.requirements
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    obj.cover_letter_required =
      event.target.elements.cover_letter_required.checked;
    const linkedin = new URL(obj.url);
    const match =
      linkedin.hostname === "www.linkedin.com" &&
      linkedin.pathname.match(/^\/jobs\/view\/(\d+)\/?$/);
    obj.source = editingJob
      ? editingJob.job.source
      : match
        ? "linkedin"
        : "manual";
    obj.source_id = editingJob
      ? editingJob.job.source_id
      : match
        ? match[1]
        : Array.from(
            new Uint8Array(
              await crypto.subtle.digest(
                "SHA-256",
                new TextEncoder().encode(obj.url),
              ),
            ),
          )
            .map((byte) => byte.toString(16).padStart(2, "0"))
            .join("");
    obj.questions = editingJob ? editingJob.job.questions : [];
    if (editingJob)
      await api("/applications/" + editingJob.id + "/job", "PUT", obj);
    else await api("/jobs", "POST", obj);
    editingJob = null;
    $("#job-form button").textContent = "Save opportunity";
    event.target.reset();
    await refresh();
    message("Opportunity imported. Prepare it to evaluate the fit.");
  });
};
$("#board-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const result = await api(
      "/discover/greenhouse",
      "POST",
      read(event.target),
    );
    await refresh();
    message("Imported " + result.imported + " new opportunities.");
  });
};
$("#linkedin-search").onclick = () =>
  action(async () => {
    const result = await api("/discover/linkedin", "POST");
    await refresh();
    message("Imported " + result.imported + " LinkedIn opportunities.");
  });
$("#contact-search").onclick = () =>
  action(async () => {
    const result = await api("/discover/contacts", "POST");
    await refresh();
    message("Reviewed " + result.reviewed + " European hiring contacts.");
  });
$("#connection-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    await api("/connections", "POST", read(event.target));
    event.target.reset();
    await refresh();
    message("Contact queued within the networking policy.");
  });
};
$("#settings-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const form = event.target,
      obj = read(form);
    for (const key of [
      "automation_enabled",
      "linkedin_authorised",
      "connections_enabled",
      "discovery_enabled",
    ])
      obj[key] = form.elements.namedItem(key).checked;
    for (const key of [
      "daily_limit",
      "auto_threshold",
      "review_threshold",
      "poll_seconds",
      "daily_connection_limit",
    ])
      obj[key] = Number(obj[key]);
    obj.allowed_countries = obj.allowed_countries
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    await api("/settings", "PUT", obj);
    await refresh();
    message("Agent settings saved.");
  });
};
$("#pause").onclick = () =>
  action(async () => {
    if (!settings) return;
    await api("/settings", "PUT", {
      ...settings,
      automation_enabled: false,
      connections_enabled: false,
    });
    await refresh();
    message(
      "Automation paused. An external action already in flight may finish.",
    );
  });
$("#tick").onclick = () =>
  action(async () => {
    const result = await api("/worker/tick", "POST");
    await refresh();
    message("Agent cycle completed: " + JSON.stringify(result));
  });
if (token)
  action(async () => {
    await api("/settings");
    $("#login").hidden = true;
    $("#workspace").hidden = false;
    await refresh();
  });
