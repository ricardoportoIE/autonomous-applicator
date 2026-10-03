"use strict";
import {
  errorDetail,
  filterApplications,
  linkedinIdentity,
  parseAnswers,
  splitList,
  stateLabel,
} from "./ui.js";
const $ = (selector) => document.querySelector(selector);
const all = (selector) => [...document.querySelectorAll(selector)];
let token = sessionStorage.getItem("applicator-token") || "";
let editingJob = null;
let profileRevision = 0;
let pending = false;
let profile = null,
  settings = null,
  applications = [],
  connections = [];
let activeInvitation = null;
let connectionTab = "active";
const invitationFeedback = new Map();
const contactPhotoUrls = new Map();
const contactPhotoRequests = new Map();
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
  const requestToken = token;
  const response = await fetch("/api" + path, {
    method,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
      ...(path === "/profile" && method === "PUT"
        ? { "If-Match": String(profileRevision) }
        : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401) lockWorkspace();
    const error = await response.json().catch(() => null);
    const failure = new Error(errorDetail(error, response.status));
    failure.status = response.status;
    throw failure;
  }
  const result = await response.json();
  if (requestToken !== token)
    throw new Error("Workspace locked. Unlock it before continuing.");
  return result;
}
async function action(callback, allowDuringBusy = false) {
  if (pending && !allowDuringBusy) return;
  const ownsPending = !pending;
  if (ownsPending) {
    pending = true;
    $("#workspace").setAttribute("aria-busy", "true");
  }
  try {
    const result = callback();
    if (ownsPending) $("#workspace").disabled = true;
    await result;
  } catch (error) {
    message(error.message, true);
  } finally {
    if (ownsPending) {
      pending = false;
      $("#workspace").removeAttribute("aria-busy");
      $("#workspace").disabled = false;
    }
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
  all("[data-view]").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === name);
    if (el.dataset.view === name) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
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
function applicationTable(
  rows,
  target,
  emptyMessage = "No opportunities yet. Import a job to start.",
) {
  target.classList.add("table-wrap");
  target.replaceChildren();
  if (!rows.length) {
    target.append(node("p", emptyMessage, "empty"));
    return;
  }
  const table = node("table"),
    head = node("tr");
  ["Opportunity", "Fit", "Status", ""].forEach((text) =>
    head.append(node("th", text)),
  );
  const thead = node("thead"),
    tbody = node("tbody");
  thead.append(head);
  table.append(thead, tbody);
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
    status.append(node("span", stateLabel(row.state), "badge " + row.state));
    tr.append(status);
    const cell = node("td"),
      button = node("button", "Open", "secondary");
    button.setAttribute(
      "aria-label",
      "Open " + row.job.title + " at " + row.job.company,
    );
    button.onclick = () => action(() => detail(row.id));
    cell.append(button);
    tr.append(cell);
    tbody.append(tr);
  }
  target.append(table);
}
function renderQueue() {
  const rows = filterApplications(applications, {
    query: $("#queue-search").value,
    state: $("#queue-state").value,
    sort: $("#queue-sort").value,
  });
  $("#queue-count").textContent =
    `${rows.length} of ${applications.length} opportunities shown`;
  applicationTable(
    rows,
    $("#application-list"),
    applications.length
      ? "No opportunities match these filters. Try another search or clear the filters."
      : undefined,
  );
}
$("#queue-search").oninput = renderQueue;
$("#queue-state").onchange = renderQueue;
$("#queue-sort").onchange = renderQueue;
$("#queue-clear").onclick = () => {
  $("#queue-search").value = "";
  $("#queue-state").value = "all";
  $("#queue-sort").value = "recent";
  renderQueue();
};
function renderEvents(events, target) {
  target.replaceChildren();
  if (!events.length)
    target.append(node("p", "No activity recorded yet.", "empty"));
  for (const event of events) {
    const el = node("div", undefined, "entry");
    el.append(
      node("strong", event.kind.replaceAll("_", " ")),
      node("p", event.detail),
      node("small", new Date(event.created).toLocaleString("en-GB")),
    );
    target.append(el);
  }
}
async function refresh() {
  const records = await Promise.all([
    api("/settings"),
    api("/applications"),
    api("/usage"),
  ]);
  [settings, applications] = records;
  const usage = records[2];
  try {
    const record = await api("/profile");
    profile = record.profile;
    profileRevision = record.revision;
    fill($("#profile-form"), profile);
  } catch (error) {
    if (!error.message.includes("Configure a candidate profile first"))
      throw error;
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
  renderQueue();
  applicationTable(applications.slice(0, 5), $("#recent"));
  renderEvidence();
  const insights = await api("/insights");
  $("#insights").replaceChildren(node("p", insights.suggestion));
  const outcomes = node("div", undefined, "grid grid-cols-3 gap-3 mt-5 mb-5");
  for (const [key, label] of [
    ["interview", "Interviews"],
    ["offer", "Offers"],
    ["rejected", "Rejections"],
  ]) {
    const metric = node("div", undefined, "rounded-xl bg-slate-50 p-3");
    metric.append(
      node(
        "strong",
        insights.outcomes[key],
        "block text-2xl font-semibold tabular-nums",
      ),
      node("small", label),
    );
    outcomes.append(metric);
  }
  $("#insights").append(outcomes);
  $("#policy-bands").replaceChildren();
  for (const [range, label] of [
    [settings.auto_threshold + "–100", "Automatic, when every gate passes"],
    [
      settings.review_threshold + "–" + (settings.auto_threshold - 1),
      "Candidate review",
    ],
    ["0–" + (settings.review_threshold - 1), "Not prioritised"],
  ]) {
    const band = node("p");
    band.append(node("b", range), node("span", label));
    $("#policy-bands").append(band);
  }
  const events = await api("/events");
  renderEvents(events, $("#events"));
  connections = await api("/connections");
  renderConnections();
  renderReadiness(usage);
}
function updateConnectionTabs() {
  for (const tab of all("[data-connection-tab]")) {
    const archived = tab.dataset.connectionTab === "archived";
    const count = connections.filter(
      (item) => (item.state === "sent") === archived,
    ).length;
    tab.textContent = `${archived ? "Archived" : "Active"} (${count})`;
    const selected = tab.dataset.connectionTab === connectionTab;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $("#" + tab.getAttribute("aria-controls")).hidden = !selected;
  }
  loadContactPhotos();
}

function loadContactPhotos() {
  all(`#connections-${connectionTab}-panel img[data-photo-id]`).forEach(
    (image) => {
      if (image.dataset.requested) return;
      image.dataset.requested = "true";
      void loadContactPhoto(image);
    },
  );
}
async function loadContactPhoto(image) {
  const id = image.dataset.photoId;
  const requestToken = token;
  let request = contactPhotoRequests.get(id);
  try {
    if (!contactPhotoUrls.has(id)) {
      if (!request) {
        request = fetch(`/api/connections/${id}/photo`, {
          headers: { Authorization: "Bearer " + requestToken },
        }).then(async (response) => {
          if (response.status === 401 && token === requestToken)
            lockWorkspace();
          if (
            !response.ok ||
            response.headers.get("Content-Type") !== "image/png"
          )
            throw new Error("Profile photo unavailable");
          const blob = await response.blob();
          if (!blob.size || blob.size > 512000)
            throw new Error("Profile photo unavailable");
          return blob;
        });
        contactPhotoRequests.set(id, request);
      }
      const blob = await request;
      if (token !== requestToken || !image.isConnected) return;
      if (!contactPhotoUrls.has(id))
        contactPhotoUrls.set(id, URL.createObjectURL(blob));
    }
    if (token !== requestToken || !image.isConnected) return;
    const url = contactPhotoUrls.get(id);
    image.onload = () => {
      image.hidden = false;
      image.parentElement.querySelector(".contact-initials").hidden = true;
    };
    image.onerror = () => {
      image.hidden = true;
      image.parentElement.querySelector(".contact-initials").hidden = false;
      if (contactPhotoUrls.get(id) === url) {
        URL.revokeObjectURL(url);
        contactPhotoUrls.delete(id);
      }
    };
    image.src = url;
  } catch {
    // Missing or unavailable optional photos leave the initials visible.
  } finally {
    if (request && contactPhotoRequests.get(id) === request)
      contactPhotoRequests.delete(id);
  }
}
all("[data-connection-tab]").forEach((tab) => {
  tab.onclick = () => {
    connectionTab = tab.dataset.connectionTab;
    updateConnectionTabs();
  };
  tab.onkeydown = (event) => {
    const tabs = all("[data-connection-tab]");
    let next;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft")
      next = tabs[(tabs.indexOf(tab) + 1) % tabs.length];
    else if (event.key === "Home") next = tabs[0];
    else if (event.key === "End") next = tabs[tabs.length - 1];
    else return;
    event.preventDefault();
    next.click();
    next.focus();
  };
});
function renderConnections() {
  $("#connections").replaceChildren();
  $("#archived-connections").replaceChildren();
  updateConnectionTabs();
  if (!connections.some((item) => item.state !== "sent"))
    $("#connections").append(
      node(
        "p",
        "No active contacts. Add a recruiter or use discovery to begin.",
        "empty",
      ),
    );
  if (!connections.some((item) => item.state === "sent"))
    $("#archived-connections").append(
      node(
        "p",
        "No archived invitations yet. Confirmed invitations will appear here automatically.",
        "empty",
      ),
    );
  for (const item of connections) {
    const el = node("div", undefined, "entry");
    el.dataset.connectionId = item.id;
    const header = node("div", undefined, "contact-header");
    const avatar = node("div", undefined, "contact-avatar");
    const initials =
      item.name
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0])
        .join("")
        .toUpperCase() || "?";
    const fallback = node("span", initials, "contact-initials");
    fallback.setAttribute("aria-hidden", "true");
    avatar.append(fallback);
    if (item.photo_available) {
      const image = node("img");
      image.alt = `Profile photo of ${item.name}`;
      image.width = 64;
      image.height = 64;
      image.hidden = true;
      image.dataset.photoId = item.id;
      avatar.append(image);
    }
    const identity = node("div", undefined, "contact-identity");
    identity.append(
      node("strong", item.name),
      node("p", item.role, "contact-role"),
      node("p", item.location, "contact-location"),
      node("span", stateLabel(item.state), "badge " + item.state),
    );
    header.append(avatar, identity);
    el.append(header);
    const controls = node("div", undefined, "connection-actions");
    const link = node("a", "Open LinkedIn profile", "profile-link secondary");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute(
      "aria-label",
      `Open LinkedIn profile for ${item.name} (opens in a new tab)`,
    );
    controls.append(link);
    if (item.state === "queued") {
      const button = node("button", "Send queued invitation", "secondary");
      button.disabled = Boolean(activeInvitation);
      button.onclick = () => sendInvitation(item.id);
      controls.append(button);
    }
    el.append(controls);
    const progress = node("div", undefined, "invitation-progress");
    progress.setAttribute("role", "status");
    progress.setAttribute("aria-live", "polite");
    progress.setAttribute("aria-atomic", "true");
    el.append(progress);
    $(item.state === "sent" ? "#archived-connections" : "#connections").append(
      el,
    );
    renderInvitationProgress(item);
  }
  loadContactPhotos();
  const running = connections.find((item) => item.state === "sending");
  if (running && !activeInvitation) void sendInvitation(running.id, true);
}
function renderInvitationProgress(item) {
  const card = $(`[data-connection-id="${item.id}"]`);
  const panel = card?.querySelector(".invitation-progress");
  if (!panel) return;
  const badge = card.querySelector(".badge");
  badge.textContent = stateLabel(item.state);
  badge.className = "badge " + item.state;
  const feedback = invitationFeedback.get(item.id) || item;
  const labels = {
    started: "Started",
    running: "Running",
    done: "Done",
    failed: "Failed",
    uncertain: "Needs review",
  };
  panel.hidden = !labels[feedback.run_status];
  panel.className = "invitation-progress " + feedback.run_status;
  panel.replaceChildren(
    node("strong", labels[feedback.run_status] || ""),
    node("p", feedback.run_message || ""),
  );
}
async function sendInvitation(id, observeOnly = false) {
  if (activeInvitation) return;
  const operation = { id, token, timer: null, responseFinished: false };
  activeInvitation = operation;
  if (!observeOnly)
    invitationFeedback.set(id, {
      run_status: "started",
      run_message: "Starting this invitation in the visible LinkedIn browser.",
    });
  renderConnections();
  const current = () =>
    activeInvitation === operation && token === operation.token;
  async function poll() {
    try {
      const item = await api(`/connections/${id}/status`);
      if (!current()) return;
      if (item.run_status !== "idle") {
        invitationFeedback.delete(id);
        connections = connections.map((row) => (row.id === id ? item : row));
        renderInvitationProgress(item);
      }
      if (operation.responseFinished && item.state !== "sending") {
        activeInvitation = null;
        renderConnections();
        return;
      }
    } catch {
      // A status failure never retries the invitation.
    }
    if (current()) operation.timer = setTimeout(poll, 700);
  }
  operation.timer = setTimeout(poll, 300);
  try {
    if (!observeOnly) {
      await api(`/connections/${id}/send`, "POST");
      if (current())
        message("Invitation confirmed. Contact moved to Archived.");
    }
  } catch (error) {
    if (current()) {
      invitationFeedback.set(id, {
        run_status:
          !error.status || error.status >= 500 ? "uncertain" : "failed",
        run_message: error.message,
      });
      message(error.message, true);
    }
  } finally {
    operation.responseFinished = true;
    clearTimeout(operation.timer);
    if (current()) {
      let running =
        observeOnly ||
        connections.some((row) => row.id === id && row.state === "sending");
      try {
        const item = await api(`/connections/${id}/status`);
        if (current()) {
          connections = connections.map((row) => (row.id === id ? item : row));
          if (item.run_status !== "idle") invitationFeedback.delete(id);
          running = item.state === "sending";
        }
      } catch {
        // Retain the last diagnostic when the status endpoint is unavailable.
      }
      if (current()) {
        if (running) operation.timer = setTimeout(poll, 700);
        else {
          activeInvitation = null;
          renderConnections();
        }
      }
    }
  }
}
function renderReadiness(usage) {
  $("#pause").textContent = settings.automation_enabled
    ? "Pause all automation"
    : "Automation paused";
  $("#pause").disabled = false;
  $("#lock").hidden = false;
  $("#readiness").replaceChildren(
    node(
      "strong",
      settings.automation_enabled ? "Agent enabled" : "Agent paused",
    ),
    node(
      "span",
      settings.linkedin_authorised
        ? "LinkedIn scope configured"
        : "LinkedIn scope needed",
      "badge " + (settings.linkedin_authorised ? "ready" : "review"),
    ),
    node(
      "span",
      profile?.confirmed ? "Profile confirmed" : "Profile review needed",
      "badge " + (profile?.confirmed ? "ready" : "review"),
    ),
    node("span", usage.remaining + " attempts remaining today", "badge"),
  );
  const progress = node("progress");
  progress.max = usage.limit;
  progress.value = Math.min(usage.used, usage.limit);
  progress.setAttribute("aria-label", "Daily application attempt usage");
  $("#daily-usage").replaceChildren(
    node(
      "strong",
      `${usage.used} / ${usage.limit} attempts used`,
      "text-2xl font-semibold tabular-nums",
    ),
    node("p", `${usage.remaining} remaining · ${usage.day}`, "my-3"),
    progress,
  );
}
function renderEvidence() {
  const target = $("#evidence-list");
  target.replaceChildren();
  if (!profile?.evidence.length)
    target.append(
      node(
        "p",
        "Add a qualification, skill or project to build your candidate record.",
        "empty",
      ),
    );
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
    edit.onclick = () => {
      fill($("#evidence-form"), item);
      $("#evidence-form").scrollIntoView({ behavior: "smooth" });
    };
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
  const [row, report, events] = await Promise.all([
      api("/applications/" + id),
      api("/applications/" + id + "/preflight"),
      api("/applications/" + id + "/events"),
    ]),
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
  const preflight = node("section", undefined, "preflight");
  preflight.setAttribute("aria-label", "Local submission checks");
  preflight.append(
    node("h3", "Submission readiness"),
    node(
      "p",
      report.can_submit
        ? "All local checks passed."
        : "Resolve the blocked checks before automatic submission.",
    ),
    node(
      "small",
      "Checked " +
        new Date(report.checked_at).toLocaleString("en-GB") +
        ". This is a local snapshot. Provider sign-in, changed job details and new questions are checked during submission.",
    ),
  );
  const checklist = node("ul", undefined, "checklist");
  for (const check of report.checks) {
    const item = node("li");
    item.append(
      node(
        "span",
        check.passed ? "Passed" : "Blocked",
        "badge " + (check.passed ? "ready" : "review"),
      ),
    );
    const copy = node("div");
    copy.append(node("strong", check.label), node("p", check.detail));
    item.append(copy);
    checklist.append(item);
  }
  const recheck = node("button", "Recheck readiness", "secondary");
  recheck.onclick = () => action(() => detail(id));
  preflight.append(checklist, recheck);
  target.append(preflight);
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
    if (question.sensitive) {
      target.append(node("p", question.label + ": requires manual handling."));
      continue;
    }
    const answerKey =
      question.answer_key ||
      "question:" + question.label.toLowerCase().trim().replace(/\s+/g, " ");
    const form = node("form"),
      label = node("label", question.label),
      input = node(question.choices?.length ? "select" : "input"),
      button = node("button", "Approve answer", "secondary");
    if (question.choices?.length) {
      const placeholder = node("option", "Choose an approved answer");
      placeholder.value = "";
      input.append(placeholder);
      for (const choice of question.choices) {
        const option = node("option", choice);
        option.value = choice;
        input.append(option);
      }
    }
    input.required = true;
    input.setAttribute("aria-label", question.label);
    input.value = profile?.answers[answerKey] || "";
    label.append(input);
    form.append(label, button);
    form.onsubmit = (event) => {
      event.preventDefault();
      action(async () => {
        if (!profile) throw new Error("Configure the candidate profile first.");
        await api("/profile", "PUT", {
          ...profile,
          answers: { ...profile.answers, [answerKey]: input.value },
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
      $("#cancel-job-edit").hidden = false;
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
    submit.disabled = !report.can_submit;
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
    select.setAttribute("aria-label", "Record outcome");
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
    if (row.outcome) select.value = row.outcome;
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
  const timeline = node("details", undefined, "timeline");
  timeline.append(
    node("summary", "Activity for this application"),
    node("small", "Latest 200 entries, newest first."),
  );
  const entries = node("div");
  renderEvents(events, entries);
  timeline.append(entries);
  target.append(timeline);
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
    $("#token").value = "";
    message("Local workspace unlocked.");
  });
};
$("#profile-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const form = event.target,
      obj = read(form);
    obj.links = splitList(obj.links, "\n");
    obj.answers = parseAnswers(obj.answers);
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
    obj.tags = splitList(obj.tags);
    obj.verified = event.target.elements.verified.checked;
    await api("/evidence/" + encodeURIComponent(obj.id), "PUT", obj);
    event.target.reset();
    await refresh();
    message("Evidence saved.");
  });
};
$("#job-form").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const obj = read(event.target);
    obj.requirements = splitList(obj.requirements);
    obj.cover_letter_required =
      event.target.elements.cover_letter_required.checked;
    const match = linkedinIdentity(obj.url);
    obj.source = editingJob
      ? editingJob.job.source
      : match
        ? "linkedin"
        : "manual";
    obj.source_id = editingJob
      ? editingJob.job.source_id
      : match
        ? match
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
    $("#cancel-job-edit").hidden = true;
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
    const requestToken = token;
    const button = $("#linkedin-search");
    const status = $("#linkedin-search-status");
    button.textContent = "Searching…";
    button.setAttribute("aria-busy", "true");
    status.textContent = "Searching LinkedIn and reading job details…";
    try {
      const result = await api("/discover/linkedin", "POST");
      await refresh();
      if (token !== requestToken) return;
      status.textContent = result.imported
        ? `Search complete. ${result.imported} new opportunities imported.`
        : "Search complete. No new opportunities to import; results may already be in your queue.";
      message("Imported " + result.imported + " LinkedIn opportunities.");
    } catch (error) {
      if (token === requestToken)
        status.textContent =
          "Search failed. Check the message above, then try again.";
      throw error;
    } finally {
      button.textContent = "Search LinkedIn";
      button.removeAttribute("aria-busy");
    }
  });
$("#contact-search").onclick = () =>
  action(async () => {
    const requestToken = token;
    const button = $("#contact-search");
    const status = $("#contact-search-status");
    button.textContent = "Searching…";
    button.setAttribute("aria-busy", "true");
    status.textContent = `Searching for up to ${settings.daily_connection_limit} new European hiring contacts…`;
    try {
      const result = await api("/discover/contacts", "POST");
      connectionTab = "active";
      await refresh();
      if (token !== requestToken) return;
      status.textContent = result.reviewed
        ? `Search complete. ${result.reviewed} new European hiring contacts found.`
        : "Search complete. No new matching contacts were found in the available results.";
      message("Reviewed " + result.reviewed + " European hiring contacts.");
    } catch (error) {
      if (token === requestToken)
        status.textContent =
          "Search failed. Check the message above, then try again.";
      throw error;
    } finally {
      button.textContent = "Find European recruiters";
      button.removeAttribute("aria-busy");
    }
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
    obj.allowed_countries = splitList(obj.allowed_countries);
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
  }, true);
$("#tick").onclick = () =>
  action(async () => {
    const result = await api("/worker/tick", "POST");
    await refresh();
    message("Agent cycle completed: " + JSON.stringify(result));
  });
function lockWorkspace() {
  token = "";
  sessionStorage.removeItem("applicator-token");
  profile = null;
  profileRevision = 0;
  settings = null;
  applications = [];
  connections = [];
  connectionTab = "active";
  updateConnectionTabs();
  $("#contact-search-status").textContent = "";
  $("#linkedin-search-status").textContent = "";
  $("#linkedin-search").textContent = "Search LinkedIn";
  $("#linkedin-search").removeAttribute("aria-busy");
  $("#contact-search").textContent = "Find European recruiters";
  $("#contact-search").removeAttribute("aria-busy");
  clearTimeout(activeInvitation?.timer);
  activeInvitation = null;
  invitationFeedback.clear();
  contactPhotoUrls.forEach((url) => URL.revokeObjectURL(url));
  contactPhotoUrls.clear();
  contactPhotoRequests.clear();
  $("#workspace").hidden = true;
  $("#login").hidden = false;
  $("#pause").disabled = true;
  $("#lock").hidden = true;
  $("#profile-form").reset();
  $("#evidence-form").reset();
  $("#job-form").reset();
  $("#connection-form").reset();
  $("#settings-form").reset();
  $("#queue-search").value = "";
  $("#queue-state").value = "all";
  $("#queue-sort").value = "recent";
  editingJob = null;
  $("#job-form button").textContent = "Save opportunity";
  $("#cancel-job-edit").hidden = true;
  [
    "#recent",
    "#application-list",
    "#application-detail",
    "#evidence-list",
    "#connections",
    "#archived-connections",
    "#events",
    "#insights",
    "#readiness",
    "#stats",
    "#daily-usage",
    "#queue-count",
  ].forEach((selector) => $(selector).replaceChildren());
  $("#token").value = "";
  view("overview");
}
$("#lock").onclick = () => {
  lockWorkspace();
  message("Workspace locked on this tab.");
};
$("#view-queue").onclick = () => view("applications");
$("#cancel-job-edit").onclick = () => {
  editingJob = null;
  $("#job-form").reset();
  $("#job-form button").textContent = "Save opportunity";
  $("#cancel-job-edit").hidden = true;
};
if (token)
  action(async () => {
    await api("/settings");
    $("#login").hidden = true;
    $("#workspace").hidden = false;
    await refresh();
  });
