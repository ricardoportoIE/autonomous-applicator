import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { RefreshCw, Search, Sparkles, MessageSquareText } from "lucide-react";
import { Badge, Modal, Panel } from "./components";
import type { QuestionInstruction } from "./contracts";
import type { Workspace } from "./workspace";

export function RoutineAnswers({ workspace }: { workspace: Workspace }) {
  const state = useSyncExternalStore(
    workspace.subscribe,
    workspace.getSnapshot,
  );
  const [entries, setEntries] = useState<QuestionInstruction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [editing, setEditing] = useState<QuestionInstruction | null>(null);
  const [prompt, setPrompt] = useState("");
  const [enabled, setEnabled] = useState(true);
  const generation = useRef(0);

  async function refresh() {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const rows = await workspace.api.json<QuestionInstruction[]>(
        "/question-instructions",
      );
      if (request === generation.current) setEntries(rows);
    } catch {
      if (request === generation.current)
        setError("Questions could not be loaded. Refresh to try again.");
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => {
      clearInterval(timer);
      generation.current++;
    };
    // The library is mounted only in an unlocked Settings tab.
  }, [workspace]);

  const shown = entries.filter(
    (item) =>
      (item.question.label + " " + item.prompt)
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "enabled" ? item.enabled : !item.prompt)),
  );

  function edit(item: QuestionInstruction) {
    workspace.message("");
    setEditing(item);
    setPrompt(item.prompt);
    setEnabled(
      item.question.sensitive ? false : item.prompt ? item.enabled : true,
    );
  }

  return (
    <Panel
      title="Routine answers"
      eyebrow="Your instructions, intelligently reused"
      action={
        <button
          className="secondary"
          type="button"
          disabled={loading || state.pending}
          onClick={() => void refresh()}
        >
          <RefreshCw size={16} aria-hidden="true" />
          {loading ? "Loading questions…" : "Refresh questions"}
        </button>
      }
    >
      <p>
        Every new question is saved here as it is discovered. Add an instruction
        for GPT-6.1 Sol to answer equivalent questions using your confirmed
        facts and the current field options.
      </p>
      <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-950 my-4">
        <Sparkles size={18} aria-hidden="true" className="inline mr-2" />
        Confirmed answers take priority. Enabled instructions authorise
        generated answers; missing facts, ambiguous matches and API failures
        remain for review. The routine answers switch in General settings
        controls automatic use.
      </div>
      <div className="form-grid">
        <label>
          <Search size={16} aria-hidden="true" /> Search questions
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Technology, location, experience…"
          />
        </label>
        <label>
          Instruction status
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="all">All questions</option>
            <option value="enabled">Enabled instructions</option>
            <option value="new">Awaiting an instruction</option>
          </select>
        </label>
      </div>
      <p className="muted" role="status">
        Questions: {entries.length} · Enabled instructions:{" "}
        {entries.filter((item) => item.enabled).length}
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!loading && !shown.length && (
        <p className="empty">
          {entries.length
            ? "No questions match these filters."
            : "Questions will appear when opportunities and application forms are inspected."}
        </p>
      )}
      <div className="grid gap-3 mt-4">
        {shown.map((item) => (
          <article
            key={item.id}
            className="rounded-xl border border-slate-200 p-4 bg-white"
          >
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold">
                  <MessageSquareText
                    size={16}
                    aria-hidden="true"
                    className="inline mr-2"
                  />
                  {item.question.label}
                </h3>
                <p className="muted text-sm">
                  {item.question.control_type ||
                    (item.question.choices.length
                      ? "Choice field"
                      : "Field not yet inspected")}
                  {" · "}
                  Applications: {item.application_count}
                  {" · Last seen "}
                  {new Date(item.last_seen).toLocaleDateString("en-GB", {
                    timeZone: "Europe/London",
                  })}
                </p>
              </div>
              <Badge state={item.enabled ? "ready" : "review"}>
                {item.enabled
                  ? "Enabled"
                  : item.prompt
                    ? "Disabled"
                    : "New question"}
              </Badge>
            </div>
            {item.prompt && (
              <p className="whitespace-pre-wrap text-sm mt-3 text-slate-600 break-words">
                {item.prompt}
              </p>
            )}
            <button
              className="secondary mt-3"
              type="button"
              disabled={state.pending}
              onClick={() => edit(item)}
            >
              {item.prompt ? "Edit instruction" : "Add instruction"}
            </button>
          </article>
        ))}
      </div>
      {editing && (
        <Modal
          title="Question instruction"
          onClose={() => setEditing(null)}
          busy={state.pending}
          notice={state.notice}
          error={state.error}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void workspace.action(async () => {
                const updated = await workspace.api.json<QuestionInstruction>(
                  `/question-instructions/${editing.id}`,
                  "PUT",
                  { prompt: prompt.trim(), enabled, version: editing.version },
                );
                setEntries((rows) =>
                  rows.map((item) => (item.id === updated.id ? updated : item)),
                );
                setEditing(null);
                await workspace.refresh();
                workspace.message(
                  "Question instruction saved. Affected applications are queued for re-preparation.",
                );
              });
            }}
          >
            <p className="font-semibold mb-3">{editing.question.label}</p>
            {editing.question.choices.length > 0 && (
              <details className="mb-4">
                <summary>
                  Observed answer options ({editing.question.choices.length})
                </summary>
                <ul>
                  {editing.question.choices.map((choice, index) => (
                    <li key={index}>{choice}</li>
                  ))}
                </ul>
              </details>
            )}
            <label>
              Instruction for GPT-6.1 Sol
              <textarea
                value={prompt}
                maxLength={4000}
                rows={7}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Example: I have 3 years of professional Python experience. Use 3 for a numeric field; for text, write a short polite sentence. Do not apply this instruction to other technologies."
              />
            </label>
            <p className="muted text-sm">
              State the facts, scope and preferred wording. Equivalent questions
              reuse this instruction; legal permission, consent, salary,
              relocation and availability require an instruction for the exact
              question. Pause the agent and wait for the current operation to
              finish before saving changes.
            </p>
            <label className="check">
              <input
                type="checkbox"
                checked={enabled}
                disabled={editing.question.sensitive}
                onChange={(event) => setEnabled(event.target.checked)}
              />{" "}
              Use this instruction automatically
            </label>
            {editing.question.sensitive && (
              <p className="muted">
                Sensitive questions require manual handling.
              </p>
            )}
            <div className="actions">
              <button
                type="submit"
                disabled={
                  enabled && (!prompt.trim() || editing.question.sensitive)
                }
              >
                {state.pending ? "Saving instruction…" : "Save instruction"}
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        </Modal>
      )}
    </Panel>
  );
}
