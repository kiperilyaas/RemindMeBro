import { useState, type FormEvent } from "react";
import type { Role } from "../api/types";
import { BrandLogo } from "../components/Brand";
import { Icon } from "../components/Icon";
import { useSession } from "../state/session";

export function Login() {
  const { login, register, demo, expiredNotice, offline } = useSession();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("student");
  const [busy, setBusy] = useState<string | null>(null);
  const local = !!demo?.local;   // lecturers sign in and sign up only on the computer that runs the demo
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); setBusy(null); }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (tab === "login") void run("form", () => login(email.trim(), password));
    else if (password.length < 6) setError("Use a password of at least 6 characters.");
    else void run("form", () => register({ email: email.trim(), password, full_name: name.trim(), role: local ? role : "student" }));
  };
  const students = demo?.accounts.filter((a) => a.role === "student") ?? [];
  const lecturers = demo?.accounts.filter((a) => a.role === "professor") ?? [];

  return (
    <div className="login">
      <section className="login-hero" aria-hidden={false}>
        <BrandLogo tone="dark" className="hero-logo" />
        <h1>All of uni in one timeline.</h1>
        <ul className="login-points">
          <li><Icon name="calendar" /> UniLearn assignments, UniSIS exams and your timetable, day by day</li>
          <li><Icon name="sparkle" /> A local AI reads Teams and email and finds the dates lecturers hide in messages</li>
          <li><Icon name="chat" /> Ask Bro anything about your week — it runs on your computer</li>
        </ul>
      </section>
      <section className="login-card">
        {expiredNotice && <div className="note warn" role="alert">{expiredNotice}</div>}
        {offline && <div className="note warn" role="alert">Can't reach the server. Keep the Run &amp; Go window open.</div>}
        <div className="seg" role="tablist" aria-label="Account">
          <button role="tab" aria-selected={tab === "login"} onClick={() => { setTab("login"); setError(null); }}>Sign in</button>
          <button role="tab" aria-selected={tab === "register"} onClick={() => { setTab("register"); setError(null); }}>Create account</button>
        </div>
        <form onSubmit={submit} className="form">
          {tab === "register" && (
            <>
              {local ? (
                <fieldset className="role-pick"><legend>I am a</legend>
                  {(["student", "professor"] as const).map((r) => (
                    <label key={r} className={role === r ? "on" : ""}><input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />{r === "student" ? "Student" : "Lecturer"}</label>
                  ))}
                </fieldset>
              ) : <p className="muted" style={{ margin: 0 }}>Student account. You also get a UniSIS and a UniLearn account with the same email and password, already connected.</p>}
              <label className="field">Full name<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required placeholder={role === "professor" ? "Prof. Anna Smith" : "Anna Smith"} /></label>
            </>
          )}
          <label className="field">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
          <label className="field">Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={tab === "login" ? "current-password" : "new-password"} required /></label>
          {error && <p className="form-err" role="alert">{error}</p>}
          <button className="btn primary block" disabled={!!busy}>{busy === "form" ? "Please wait…" : tab === "login" ? "Sign in" : "Create account"}</button>
        </form>
        {tab === "login" && demo && demo.accounts.length > 0 && (
          <div className="demo">
            {local
              ? <p className="demo-h">On this computer only · lecturer passwords are in <code>{demo.staff_passwords_file ?? "data/STAFF-PASSWORDS.txt"}</code></p>
              : <p className="demo-h">Just looking around? Sign in as the demo student</p>}
            {students.map((a) => (
              <button key={a.email} className="demo-acc main" disabled={!!busy}
                onClick={() => (a.password ? void run(a.email, () => login(a.email, a.password ?? "")) : (setEmail(a.email), setPassword("")))}>
                <span className="av sm">{a.full_name.split(" ").map((p) => p[0]).join("")}</span>
                <span><b>{a.full_name}</b><small>Student · {a.email}</small></span>
                <Icon name="arrow" size={18} />
              </button>
            ))}
            {local && lecturers.length > 0 && <div className="demo-grid">{lecturers.map((a) => (
              <button key={a.email} className="demo-acc" disabled={!!busy} onClick={() => { setEmail(a.email); setPassword(""); setError(null); }}>
                <span><b>{a.full_name}</b><small>Lecturer · type the password</small></span>
              </button>
            ))}</div>}
          </div>
        )}
      </section>
    </div>
  );
}
