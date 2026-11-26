import { Assistant } from "../../components/Assistant";
import { Icon } from "../../components/Icon";
import { Paywall } from "../../components/Paywall";
import { PageHeader } from "../../components/ui";
import type { Route } from "../../lib/router";
import { useSession } from "../../state/session";
import { SmartNotes } from "./SmartNotes";

/** AI section: Ask Bro and Smart Notes. Both are Premium; Free users see the plan and the checkout. */
export function AI({ route, navigate }: { route: Route; navigate: (p: string) => void }) {
  const { user } = useSession();
  const tab = route.params.get("tab") === "notes" ? "notes" : "ask";
  const noteParam = Number(route.params.get("note"));
  const noteId = tab === "notes" && Number.isInteger(noteParam) && noteParam > 0 ? noteParam : null;
  const premium = user?.plan === "premium";
  return (
    <>
      <PageHeader eyebrow={premium ? <span className="plan-chip"><Icon name="sparkle" size={14} /> Premium</span> : "Premium features"} title="AI" />
      {!premium ? <Paywall /> : (
        <>
          <div className="seg" role="tablist" aria-label="AI tools">
            <button role="tab" aria-selected={tab === "ask"} onClick={() => navigate("ai")}><Icon name="chat" size={16} /> Ask Bro</button>
            <button role="tab" aria-selected={tab === "notes"} onClick={() => navigate("ai?tab=notes")}><Icon name="book" size={16} /> Smart Notes</button>
          </div>
          {tab === "ask" ? <Assistant variant="page" /> : (
            <SmartNotes noteId={noteId} openNote={(id) => navigate(id ? `ai?tab=notes&note=${id}` : "ai?tab=notes")} />
          )}
        </>
      )}
    </>
  );
}
