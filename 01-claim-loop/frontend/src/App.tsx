import { useEffect, useState } from "react";
import { api, type Claim, type Edit } from "./api";
import Review from "./Review";

export default function App() {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [claim, setClaim] = useState<Claim | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    api.stats().then((s) => setCounts(s.counts)).catch((e) => setError(String(e)));

  useEffect(() => { refresh(); }, []);

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

  return (
    <>
      <header>
        <h1>claim-loop</h1>
        <button onClick={takeNext} disabled={busy}>
          {claim ? "Skip to next" : "Take next claim"}
        </button>
        <div className="counts">
          {Object.entries(counts).map(([k, v]) => (
            <span key={k}>{k} <b>{v}</b></span>
          ))}
        </div>
      </header>

      {error && <div className="err">{error}</div>}

      {claim ? (
        <Review claim={claim} onSubmit={submit} busy={busy} />
      ) : (
        <div className="empty">
          {busy ? "Loading…" : "No claim held. Take the next one from the queue."}
          <p className="muted" style={{ fontSize: 12.5, marginTop: 14 }}>
            Taking a claim puts a lease on it. Nobody else can review it until you
            finish or the lease expires.
          </p>
        </div>
      )}
    </>
  );
}
