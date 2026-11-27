import { BRAND } from "./components/Brand";
import { Icon } from "./components/Icon";
import { Shell, type NavItem } from "./components/Shell";
import { Spinner } from "./components/ui";
import { useHashRoute, type Route } from "./lib/router";
import { LecturerProvider } from "./state/lecturer";
import { useSession } from "./state/session";
import { FoundDatesProvider } from "./state/foundDates";
import { StudentProvider, useStudent } from "./state/student";
import { Account } from "./views/Account";
import { AI } from "./views/student/AI";
import { Login } from "./views/Login";
import { LoginIntro, wantsIntro } from "./components/LoginIntro";
import { LecturerArea } from "./views/lecturer/LecturerArea";
import { Connections } from "./views/student/Connections";
import { Inbox } from "./views/student/Inbox";
import { Semester } from "./views/student/Semester";
import { Studies } from "./views/student/Studies";
import { FindDatesButton } from "./views/student/FoundDates";
import { Timeline } from "./views/student/Timeline";

const STUDENT_PATHS = ["", "inbox", "studies", "semester", "ai", "connections", "account"];
const LECTURER_PATHS = ["", "announce", "extracted", "cases"];

function StudentApp({ route, navigate, clearParams }: { route: Route; navigate: (p: string) => void; clearParams: () => void }) {
  const { unread, syncing, runSync } = useStudent();
  const path = STUDENT_PATHS.includes(route.path) ? route.path : "";
  const nav: NavItem[] = [
    { path: "", label: "Timeline", icon: "calendar" },
    { path: "inbox", label: "Inbox", icon: "inbox", badge: unread },
    { path: "studies", label: "Studies", icon: "cap" },
    { path: "semester", label: "Semester", icon: "map" },
    { path: "ai", label: "AI", icon: "sparkle" },
    { path: "connections", label: "Connect", icon: "link" },
  ];
  return (
    <Shell nav={nav} current={path} onNavigate={navigate}
      actions={<>
        <FindDatesButton onOpen={() => navigate("")} />
        <button className={`icon-btn sync ${syncing ? "spin" : ""}`} onClick={() => void runSync()} disabled={syncing} aria-label={syncing ? "Syncing" : "Sync all sources"} title="Sync all sources"><Icon name="sync" /></button>
      </>}
      fab={path !== "ai" && <button className="fab" onClick={() => navigate("ai")} aria-label="Open Ask Bro"><Icon name="sparkle" /></button>}>
      {path === "" && <Timeline onNavigate={navigate} />}
      {path === "inbox" && <Inbox />}
      {path === "studies" && <Studies onNavigate={navigate} />}
      {path === "semester" && <Semester />}
      {path === "ai" && <AI route={route} navigate={navigate} />}
      {path === "connections" && <Connections route={route} clearParams={clearParams} />}
      {path === "account" && <Account />}
    </Shell>
  );
}

function LecturerApp({ route, navigate }: { route: Route; navigate: (p: string) => void }) {
  const path = LECTURER_PATHS.includes(route.path) ? route.path : "";
  return <LecturerArea path={path} query={route.params} navigate={navigate} />;
}

export function App() {
  const { user, booting, justSignedIn, introDone } = useSession();
  const [route, navigate, clearParams] = useHashRoute();
  if (booting) return <div className="boot"><img className="boot-icon" src={BRAND.icon} alt="" /><Spinner label="Starting Remind Me Bro" /></div>;
  if (!user) return <Login />;
  // key={user.id}: switching account resets all per-user state
  const area = user.role === "professor"
    ? <LecturerProvider key={user.id}><LecturerApp route={route} navigate={navigate} /></LecturerProvider>
    : <StudentProvider key={user.id}><FoundDatesProvider><StudentApp route={route} navigate={navigate} clearParams={clearParams} /></FoundDatesProvider></StudentProvider>;
  // right after signing in, the intro plays over the app, which loads underneath and opens with the bell's wave
  return <>{area}{justSignedIn && wantsIntro() && <LoginIntro onDone={introDone} />}</>;
}
