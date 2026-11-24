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

function Status({ c }: { c: Connection }) {
  if (c.status === "connected") return <span className="pill ok">Connected</span>;
  if (c.status === "expired") return <span className="pill warn">{c.provider === "moodle" ? "Token deleted" : "Access revoked"}</span>;
  if (c.status === "demo") return <span className="pill">Demo data</span>;
  return <span className="pill">Not connected</span>;
}

function Card({ c, icon, color, title, what, how, children, actions }: {
  c: Connection; icon: "cap" | "book" | "chat" | "inbox"; color: string; title: string; what: string; how: string; children?: ReactNode; actions?: ReactNode;
}) {
  const { now } = useSession();
  return (
    <article className="conn" style={{ ["--c" as string]: color }}>
      <div className="conn-ic"><Icon name={icon} /></div>
      <div className="conn-main">
        <div className="conn-h"><h2>{title}</h2><Status c={c} /></div>
        <p className="conn-what">{what}</p>
        {c.status === "connected" && c.account && (
          <p className="conn-acc">Signed in as <b>{c.account}</b>{c.account_id && <> · <span className="mono">{c.account_id}</span></>}{c.last_sync_at && <> · synced {timeAgo(parse(c.last_sync_at), now)}</>}</p>
        )}
        {c.status === "connected" && !!c.scopes?.length && <div className="scopes">{c.scopes.map((s) => <span key={s} className="scope">{s}</span>)}</div>}
        {c.status === "expired" && c.last_error && <p className="form-err">{c.last_error}</p>}
        {c.available === false && <p className="form-err">Not running at {c.portal_url}. Start everything with the Run &amp; Go launcher.</p>}
        {children}
        <p className="conn-how"><Icon name="info" size={14} /> {how}</p>
      </div>
      <div className="conn-act">
        {actions}
        {c.portal_url && <a className="btn ghost" href={c.portal_url} target="_blank" rel="noopener noreferrer">Open {title.split(" ")[0]} <Icon name="external" size={14} /></a>}
      </div>
    </article>
  );
}

export function Connections({ route, clearParams }: { route: Route; clearParams: () => void }) {
  const toast = useToast();
  const { connection, reload, runSync, syncing } = useStudent();
  const [pending, setPending] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const { user } = useSession();
  // the demo student has the UniLearn username giulia.esposito; everyone else signed up with their email
  const [ulUser, setUlUser] = useState(() => (user?.email === "student@demo.it" ? "giulia.esposito" : user?.email ?? ""));
  const [ulPass, setUlPass] = useState("");
  const [ulErr, setUlErr] = useState<string | null>(null);
  const unisis = connection("unisis"), unilearn = connection("moodle");
  const demo = [connection("teams"), connection("email")].filter((x): x is Connection => !!x);

  // Coming back from the UniSIS consent page: #connections?unisis=connected|error&message=…
  useEffect(() => {
    const r = route.params.get("unisis");
    if (!r) return;
    if (r === "connected") toast("UniSIS connected", "Your timetable, exams and registration windows were imported.", "ok");
    else toast("UniSIS not connected", route.params.get("message") ?? "The authorization was not completed.", "error");
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
      const r = await api.connectMoodle(ulUser.trim(), ulPass);
      setUlPass("");
      toast("UniLearn connected", `${r.assignments} assignments (${r.submitted} already submitted), ${r.events} events and ${r.posts} announcements imported. Press Sync to let the AI read the announcements.`, "ok");
      await reload();
    } catch (err) { setUlErr((err as Error).message); }
    finally { setPending(null); }
  };

  return (
    <>
      <PageHeader eyebrow="Your university systems" title="Connections"
        actions={<button className="btn primary" disabled={syncing} onClick={() => void runSync()}><Icon name="sync" size={16} /> {syncing ? "Syncing…" : "Sync everything"}</button>} />
      <div className="conns">
        {unilearn && (
          <Card c={unilearn} icon="book" color="#B5651D" title="UniLearn · learning platform"
            what="Assignments, submission status, course events and lecturer announcements."
            how="Real connection through the Moodle web-service API: your password is used once to get a personal token, only the encrypted token is stored."
            actions={unilearn.status === "connected" && (
              <>
                <button className="btn" disabled={!!pending} onClick={() => void run("ul-sync", async () => {
                  const r = await api.syncMoodle();
                  const ai = (r.ai_details ?? []).filter((d) => d.status === "deadline_extracted").length;
                  toast("UniLearn synced", `${r.assignments} assignments, ${r.events} events, ${r.posts} announcements${ai ? `, ${ai} new date(s) found by AI` : ""}.`, "ok");
                })}>{pending === "ul-sync" ? "Syncing…" : "Sync now"}</button>
                {confirm === "ul" ? (
                  <><button className="btn danger" onClick={() => void run("ul-off", async () => { await api.disconnectMoodle(); toast("UniLearn disconnected", "The token was removed. You can also delete it in UniLearn → Security keys."); })}>Confirm</button>
                    <button className="btn ghost" onClick={() => setConfirm(null)}>Keep</button></>
                ) : <button className="btn ghost" onClick={() => setConfirm("ul")}>Disconnect</button>}
              </>
            )}>
            {unilearn.status !== "connected" && unilearn.available !== false && (
              <form className="inline-form" onSubmit={connectUnilearn}>
                <label className="field">UniLearn username<input value={ulUser} onChange={(e) => setUlUser(e.target.value)} autoComplete="off" required /></label>
                <label className="field">Password<input type="password" value={ulPass} onChange={(e) => setUlPass(e.target.value)} autoComplete="off" required /></label>
                <button className="btn primary" disabled={!!pending}>{pending === "ul-connect" ? "Getting token…" : unilearn.status === "expired" ? "Reconnect" : "Connect"}</button>
                {ulErr && <p className="form-err" role="alert">{ulErr}</p>}
                <p className="hint">If you created your account here, use the same email and password.</p>
              </form>
            )}
          </Card>
        )}
        {unisis && (
          <Card c={unisis} icon="cap" color="#2F855A" title="UniSIS · student information system"
            what="Timetable, exam registration, course registration and grades."
            how="Real connection with OAuth 2.0: you sign in and give consent on UniSIS, Remind Me Bro never sees your UniSIS password."
            actions={unisis.status === "connected" ? (
              <>
                <button className="btn" disabled={!!pending} onClick={() => void run("us-sync", async () => {
                  const r = await api.syncUnisis(); toast("UniSIS synced", `${r.events} timetable entries and ${r.deadlines} reminders imported.`, "ok");
                })}>{pending === "us-sync" ? "Syncing…" : "Sync now"}</button>
                {confirm === "us" ? (
                  <><button className="btn danger" onClick={() => void run("us-off", async () => { await api.disconnectUnisis(); toast("UniSIS disconnected", "Tokens revoked, your UniSIS data was removed from Remind Me Bro."); })}>Confirm</button>
                    <button className="btn ghost" onClick={() => setConfirm(null)}>Keep</button></>
                ) : <button className="btn ghost" onClick={() => setConfirm("us")}>Disconnect</button>}
              </>
            ) : (
              <button className="btn primary" disabled={!!pending || unisis.available === false} onClick={() => void run("us-connect", async () => {
                const r = await api.connectUnisis(); location.href = r.authorize_url;
              })}>{pending === "us-connect" ? "Opening UniSIS…" : unisis.status === "expired" ? "Reconnect" : "Connect"}</button>
            )}>
            {unisis.status !== "connected" && <p className="hint">You'll sign in on UniSIS and click “Allow access”.</p>}
          </Card>
        )}
        {demo.map((c) => (
          <Card key={c.provider} c={c} icon={c.provider === "teams" ? "chat" : "inbox"} color={c.provider === "teams" ? "#5B5FC7" : "#2F69A3"}
            title={c.name} what={c.provider === "teams" ? "Course channels and chats with your lecturers." : "Messages from lecturers and the Student Office."}
            how="Demo data for now: messages are simulated, the local AI reads them for real to find hidden dates." />
        ))}
      </div>
    </>
  );
}
