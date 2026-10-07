import { useSyncExternalStore } from "react";
import { Trash2, RotateCcw } from "lucide-react";
import type { Application } from "./contracts";
import type { Workspace } from "./workspace";

export function restoreApplication(workspace: Workspace, row: Application) {
  return workspace.action(() =>
    workspace.mutate(
      `/applications/${row.id}/restore`,
      "POST",
      { job: row.job },
      "Opportunity restored. Pending work will be checked again before submission.",
      row.id,
    ),
  );
}

export function TrashForm({
  row,
  revision,
  workspace,
  done,
}: {
  row: Application;
  revision: number;
  workspace: Workspace;
  done: () => void;
}) {
  const { pending } = useSyncExternalStore(
    workspace.subscribe,
    workspace.getSnapshot,
  );
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const reason = String(
          new FormData(event.currentTarget).get("reason") || "",
        );
        void workspace.action(async () => {
          await workspace.mutate(
            `/applications/${row.id}/trash`,
            "POST",
            { job: row.job, reason },
            "Opportunity moved to Trash. It will not be processed or imported again whilst removed.",
            row.id,
            revision,
          );
          done();
        });
      }}
    >
      <p>
        <strong>{row.job.title}</strong> · {row.job.company}
      </p>
      <p>
        Remove this opportunity from the active queue. Its documents, answers
        and history remain available, and you can restore it later.
      </p>
      {row.state === "submitted" && (
        <p>
          This keeps the confirmed submission record. It does not withdraw the
          application from the employer.
        </p>
      )}
      <label>
        Reason for removal (optional)
        <textarea name="reason" maxLength={500} rows={3} />
      </label>
      <button className="danger" disabled={pending}>
        <Trash2 size={16} aria-hidden="true" />
        Move to Trash
      </button>
    </form>
  );
}

export function RestoreButton({
  row,
  workspace,
}: {
  row: Application;
  workspace: Workspace;
}) {
  const { pending } = useSyncExternalStore(
    workspace.subscribe,
    workspace.getSnapshot,
  );
  return (
    <button
      className="secondary"
      type="button"
      disabled={pending}
      onClick={() => void restoreApplication(workspace, row)}
    >
      <RotateCcw size={16} aria-hidden="true" />
      Restore opportunity
    </button>
  );
}
