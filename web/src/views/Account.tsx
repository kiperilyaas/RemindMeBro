import { API_BASE } from "../api/client";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/ui";
import { fmtLong } from "../lib/time";
import { useSession } from "../state/session";

export function Account() {
  const { user, health, offline, now, logout, refreshHealth } = useSession();
  if (!user) return null;
  const o = health?.ollama;
  return (
    <>
      <PageHeader eyebrow="Profile and system status" title="Account" />
      <div className="two-col">
        <section className="panel">
          <h2>Profile</h2>
          <dl className="kv">
            <dt>Name</dt><dd>{user.full_name}</dd>
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Role</dt><dd>{user.role === "professor" ? "Lecturer" : "Student"}</dd>
          </dl>
          <button className="btn" onClick={() => logout()}><Icon name="logout" size={16} /> Log out</button>
        </section>
        <section className="panel">
          <h2>System status</h2>
          <dl className="kv">
            <dt>Server</dt><dd>{offline ? <span className="flag">Not reachable</span> : <span className="okc">Connected</span>} <span className="mono muted">{API_BASE}</span></dd>
            <dt>Local AI</dt><dd>{o ? (o.model_available ? <span className="okc">{o.model} ready</span> : <span className="flag">{o.model ?? "llama3.2"} not available</span>) : "—"}</dd>
            <dt>Search index</dt><dd>{health ? `${health.vector_documents} messages indexed` : "—"}</dd>
            <dt>Demo date</dt><dd>{fmtLong(now)}</dd>
            <dt>Version</dt><dd>{health ? `${health.app} ${health.version}` : "—"}</dd>
          </dl>
          <div className="row-gap"><button className="btn" onClick={() => void refreshHealth()}><Icon name="sync" size={16} /> Refresh</button>
            <a className="btn ghost" href="/classic">Classic interface</a><a className="btn ghost" href="/docs" target="_blank" rel="noopener noreferrer">API docs</a></div>
        </section>
      </div>
    </>
  );
}
