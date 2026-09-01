import { useEffect, useState } from "react";
import { api, type Claim, type Edit } from "./api";
import Review from "./Review";
import Upload from "./Upload";

type Role = "user" | "reviewer";

export default function App() {
  const [role, setRole] = useState<Role>("user");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [claim, setClaim] = useState<Claim | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    api.stats().then((s) => setCounts(s.counts)).catch((e) => setError(String(e)));

  useEffect(() => { refresh(); }, []);

  // Polling, because a claim's status changes in a worker this page knows
  // nothing about. Server-sent events would be the grown-up answer.
  useEffect(() => {
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  async function takeNext() {
    setBusy(true); setError(null);
    try {
      setClaim(await api.nextReview());
    } catch (e) {
      setClaim(null);
      setError(String(e).includes("404") ? "Nothing waiting for review." : String(e));
    } finally {
      setBusy(false);
      refresh();
    }
  }

  async function submit(edits: Edit[]) {
    if (!claim) return;
    setBusy(true);
    try {
      await api.complete(claim.id, "web", edits);
      setClaim(null);
      await refresh();
      await takeNext();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function switchRole(next: Role) {
    setRole(next);
    setError(null);
    // Switching away from the reviewer seat abandons whatever is held. The
    // lease stays until it expires, then the reaper puts the claim back --
    // which is the same path a reviewer who closes their laptop takes.
    if (next === "user") setClaim(null);
  }

  const waiting = counts["pending_review"] ?? 0;

  return (
    <>
      <header>
        <h1>claim-loop</h1>

        <div className="roles">
          <button
            className={role === "user" ? "role on" : "role"}
            onClick={() => switchRole("user")}
          >
            Act as user
          </button>
          <button
            className={role === "reviewer" ? "role on" : "role"}
            onClick={() => switchRole("reviewer")}
          >
            Act as reviewer
            {waiting > 0 && <span className="badge">{waiting}</span>}
          </button>
        </div>

        <div className="counts">
          {Object.entries(counts).length === 0 && <span>no claims yet</span>}
          {Object.entries(counts).map(([k, v]) => (
            <span key={k}>{k} <b>{v}</b></span>
          ))}
        </div>
      </header>

      {error && <div className="err">{error}</div>}

      {role === "user" ? (
        <Upload onChanged={refresh} />
      ) : claim ? (
        <Review claim={claim} onSubmit={submit} busy={busy} />
      ) : (
        <div className="empty">
          <p>{busy ? "Loading…" : `${waiting} claim${waiting === 1 ? "" : "s"} waiting for review.`}</p>
          <button className="primary" onClick={takeNext} disabled={busy || waiting === 0}>
            Take next claim
          </button>
          <p className="muted note">
            Taking a claim puts a lease on it. Nobody else can review it until
            you finish or the lease expires — open this in two tabs and you will
            get two different claims.
          </p>
        </div>
      )}
    </>
  );
}
