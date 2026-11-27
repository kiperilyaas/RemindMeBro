import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Connection } from "../../api/types";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/ui";
import { parse, timeAgo } from "../../lib/time";
import type { Route } from "../../lib/router";
import { useSession } from "../../state/session";
import { useStudent } from "../../state/student";
import { useToast } from "../../state/toast";

// What a student needs here: what each system brings, whether it is connected, Connect / Disconnect, a link to open it. Nothing technical.

function Status({ c }: { c?: Connection }) {
  if (!c) return <span className="pill ok">Automatic</span>;
  if (c.status === "connected") return <span className="pill ok">Connected</span>;
  if (c.status === "expired") return <span className="pill warn">Connect again</span>;
  return <span className="pill">Not connected</span>;
}

function Card({ c, icon, color, title, what, children, actions }: {
  c?: Connection; icon: "cap" | "book" | "chat" | "inbox"; color: string; title: string; what: string; children?: ReactNode; actions?: ReactNode;
}) {
  const { now } = useSession();
  return (
    <article className="conn" style={{ ["--c" as string]: color }}>
      <div className="conn-ic"><Icon name={icon} /></div>
      <div className="conn-main">
        <div className="conn-h"><h2>{title}</h2><Status c={c} /></div>
        <p className="conn-what">{what}</p>
        {c?.status === "connected" && c.account && (
          <p className="conn-acc">Signed in as <b>{c.account}</b>{c.last_sync_at && <> · updated {timeAgo(parse(c.last_sync_at), now)}</>}</p>
        )}
        {c?.available === false && <p className="form-err">{title} is not available right now. Try again later.</p>}
        {children}
      </div>
      {(actions || c?.portal_url) && (
        <div className="conn-act">
          {actions}
          {c?.portal_url && <a className="btn ghost sm" href={c.portal_url} target="_blank" rel="noopener noreferrer">Open {title} <Icon name="external" size={14} /></a>}
        </div>
      )}
    </article>
  );
}

export function Connections({ route, clearParams }: { route: Route; clearParams: () => void }) {
  const toast = useToast();
  const { connection, reload, loading } = useStudent();
  const [pending, setPending] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const { user } = useSession();
  // the demo student has the UniLearn username giulia.esposito; everyone else signed up with their email
  const [ulUser, setUlUser] = useState(() => (user?.email === "student@demo.it" ? "giulia.esposito" : user?.email ?? ""));
  const [ulPass, setUlPass] = useState("");
  const [ulErr, setUlErr] = useState<string | null>(null);
  const unisis = connection("unisis"), unilearn = connection("moodle");

  // Coming back from the UniSIS consent page: #connections?unisis=connected|error&message=…
  useEffect(() => {
    const r = route.params.get("unisis");
    if (!r) return;
    if (r === "connected") toast("UniSIS connected", "Your timetable and exams are in your calendar.", "ok");
    else toast("UniSIS not connected", route.params.get("message") ?? "The sign-in was not completed.", "error");
    clearParams();
    void reload();
  }, [route.params, clearParams, reload, toast]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setPending(key);
    try { await fn(); } catch (e) { toast("Something went wrong", (e as Error).message, "error"); }
    finally { setPending(null); setConfirm(null); await reload(); }
  };

  const connectUnilearn = async (e: FormEvent) => {
    e.preventDefault();
    if (!ulUser.trim() || !ulPass) { setUlErr("Enter your UniLearn username and password."); return; }
    setUlErr(null); setPending("ul-connect");
    try {
      await api.connectMoodle(ulUser.trim(), ulPass);
      setUlPass("");
      toast("UniLearn connected", "Your assignments and course news are in Remind Me Bro.", "ok");
      await reload();
    } catch (err) { setUlErr((err as Error).message); }
    finally { setPending(null); }
  };

  const disconnect = (key: "ul" | "us", name: string, fn: () => Promise<unknown>) => confirm === key ? (
    <><button className="btn danger sm" onClick={() => void run(`${key}-off`, async () => { await fn(); toast(`${name} disconnected`); })}>Disconnect</button>
      <button className="btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></>
  ) : <button className="btn ghost sm" onClick={() => setConfirm(key)}>Disconnect</button>;

  return (
    <>
      <PageHeader eyebrow="Your university" title="Connections" />
      <div className="conns">
        {unilearn && (
          <Card c={unilearn} icon="book" color="#B5651D" title="UniLearn"
            what="Assignments, course files and news from your lecturers."
            actions={unilearn.status === "connected" && disconnect("ul", "UniLearn", api.disconnectMoodle)}>
            {unilearn.status !== "connected" && unilearn.available !== false && (
              <form className="inline-form" onSubmit={connectUnilearn}>
                <label className="field">UniLearn username<input value={ulUser} onChange={(e) => setUlUser(e.target.value)} autoComplete="off" required /></label>
                <label className="field">Password<input type="password" value={ulPass} onChange={(e) => setUlPass(e.target.value)} autoComplete="off" required /></label>
                <button className="btn primary" disabled={!!pending}>{pending === "ul-connect" ? "Connecting…" : "Connect"}</button>
                {ulErr && <p className="form-err" role="alert">{ulErr}</p>}
                <p className="hint">If you signed up here, use the same email and password.</p>
              </form>
            )}
          </Card>
        )}
        {unisis && (
          <Card c={unisis} icon="cap" color="#2F855A" title="UniSIS"
            what="Timetable, exams and grades."
            actions={unisis.status === "connected" ? disconnect("us", "UniSIS", api.disconnectUnisis) : (
              <button className="btn primary" disabled={!!pending || unisis.available === false} onClick={() => void run("us-connect", async () => {
                const r = await api.connectUnisis(); location.href = r.authorize_url;
              })}>{pending === "us-connect" ? "Opening UniSIS…" : "Connect"}</button>
            )} />
        )}
        {!loading && <Card icon="inbox" color="#2F69A3" title="Outlook and Teams"
          what="Emails and Teams posts from your lecturers arrive in your Inbox by themselves." />}
      </div>
    </>
  );
}
