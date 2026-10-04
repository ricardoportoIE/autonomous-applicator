import { useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { AddButton, Badge, ExternalLink, Panel, Tabs } from "./components";
import type { Connection } from "./contracts";
import type { Workspace, WorkspaceState } from "./workspace";

function Avatar({
  item,
  workspace,
  active,
}: {
  item: Connection;
  workspace: Workspace;
  active: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let current = true;
    if (item.photo_available && active)
      void workspace.photo(item.id).then((value) => {
        if (current) setUrl(value);
      });
    return () => {
      current = false;
    };
  }, [item.id, item.photo_available, workspace, active]);
  const initials =
    item.name
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?";
  return (
    <div className="contact-avatar">
      <span className="contact-initials" aria-hidden="true" hidden={loaded}>
        {initials}
      </span>
      {item.photo_available && (
        <img
          src={url ?? undefined}
          alt={`Profile photo of ${item.name}`}
          width={64}
          height={64}
          hidden={!loaded}
          onLoad={() => setLoaded(true)}
          onError={() => {
            setLoaded(false);
            workspace.discardPhoto(item.id);
            setUrl(null);
          }}
        />
      )}
    </div>
  );
}
export function Networking({
  state,
  workspace,
  add,
}: {
  state: WorkspaceState;
  workspace: Workspace;
  add: () => void;
}) {
  const [tab, setTab] = useState("active");
  useEffect(() => {
    if (state.searchingContacts || !state.unlocked) setTab("active");
  }, [state.searchingContacts, state.unlocked]);
  const active = state.connections.filter((c) => c.state !== "sent");
  const archived = state.connections.filter((c) => c.state === "sent");
  const labels: Record<string, string> = {
    started: "Started",
    running: "Running",
    done: "Done",
    failed: "Failed",
    uncertain: "Needs review",
  };
  return (
    <>
      <Panel
        title="Networking controls"
        eyebrow="Meet your next opportunity"
        action={<AddButton onClick={add}>Add contact</AddButton>}
      >
        <div className="discovery-actions">
          <button
            id="contact-search"
            type="button"
            aria-busy={state.searchingContacts || undefined}
            onClick={() => void workspace.discover("contacts")}
          >
            {state.searchingContacts
              ? "Searching…"
              : "Find European recruiters"}
          </button>
          <span className="subtle-chip">
            Up to {state.settings?.daily_connection_limit ?? 0} new profiles per
            search
          </span>
        </div>
        <p
          id="contact-search-status"
          className="search-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {state.searchContacts}
        </p>
        <p>
          Each search finds up to your daily connection limit in new contacts.
          The daily invitation quota is tracked separately.
        </p>
        <details className="help-details">
          <summary>How networking works</summary>
          <p>
            Send queued invitation runs only the selected contact in a visible
            browser. It opens their profile, checks their identity and uses
            Connect to send an invitation without a note.
          </p>
          <p>
            Manual invitations use the declared LinkedIn scope and daily
            networking limit. They run independently of candidate CV
            confirmation and background automation settings. Queue-wide
            invitations remain controlled by Agent settings.
          </p>
          <p>
            Networking has a separate daily limit and enable switch in Agent
            settings. The global pause stops both background queues.
          </p>
          <p>
            No public profile edits are supported. An uncertain invitation is
            held for manual reconciliation.
          </p>
        </details>
      </Panel>
      <Panel title="Connection queue" eyebrow="People, not just profiles">
        <Tabs
          label="Connection queue"
          prefix="connections"
          selected={tab}
          onSelect={setTab}
          items={[
            { id: "active", label: `Active (${active.length})` },
            { id: "archived", label: `Archived (${archived.length})` },
          ]}
        >
          {(section) => (
            <>
              {section === "archived" && (
                <p>
                  Confirmed invitations are kept here with their profile links
                  and delivery status.
                </p>
              )}
              <div
                id={
                  section === "active" ? "connections" : "archived-connections"
                }
              >
                {state.unlocked && (
                  <>
                    {!(section === "active" ? active : archived).length && (
                      <p className="empty">
                        {section === "active"
                          ? "No active contacts. Add a recruiter or use discovery to begin."
                          : "No archived invitations yet. Confirmed invitations will appear here automatically."}
                      </p>
                    )}
                    {(section === "active" ? active : archived).map((item) => {
                      const feedback = state.feedback[item.id] ?? item;
                      return (
                        <div
                          key={item.id}
                          className="entry contact-card"
                          data-connection-id={item.id}
                        >
                          <div className="contact-header">
                            <Avatar
                              item={item}
                              workspace={workspace}
                              active={
                                state.view === "networking" && tab === section
                              }
                            />
                            <div className="contact-identity">
                              <strong>{item.name}</strong>
                              <p className="contact-role">{item.role}</p>
                              <p className="contact-location">
                                <MapPin size={14} aria-hidden="true" />
                                {item.location}
                              </p>
                              <Badge state={item.state} />
                            </div>
                          </div>
                          <div className="connection-actions">
                            <ExternalLink
                              href={item.url}
                              label={`Open LinkedIn profile for ${item.name} (opens in a new tab)`}
                            >
                              Open LinkedIn profile
                            </ExternalLink>
                            {item.state === "queued" && (
                              <button
                                type="button"
                                className="secondary"
                                disabled={state.activeInvitation !== null}
                                onClick={() =>
                                  void workspace.sendInvitation(item.id)
                                }
                              >
                                Send queued invitation
                              </button>
                            )}
                          </div>
                          <div
                            className={
                              "invitation-progress " + feedback.run_status
                            }
                            hidden={!labels[feedback.run_status]}
                            role="status"
                            aria-live="polite"
                            aria-atomic="true"
                          >
                            <strong>{labels[feedback.run_status] ?? ""}</strong>
                            <p>{feedback.run_message}</p>
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </>
          )}
        </Tabs>
      </Panel>
    </>
  );
}
