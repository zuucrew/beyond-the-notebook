import { useMemo, useState } from "react";
import { api, type Claim, type Edit } from "./api";

type Draft = { value: string; blank: boolean };

export default function Review({
  claim, onSubmit, busy,
}: { claim: Claim; onSubmit: (edits: Edit[]) => void; busy: boolean }) {
  const [draft, setDraft] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(
      claim.flagged.map((k) => [
        k,
        { value: claim.extracted[k]?.value ?? "", blank: false },
      ])
    )
  );

  const changed = useMemo(
    () =>
      claim.flagged.filter((k) => {
        const d = draft[k];
        return d.blank || d.value !== (claim.extracted[k]?.value ?? "");
      }).length,
    [draft, claim]
  );

  function edits(): Edit[] {
    return claim.flagged.map((k) => {
      const d = draft[k];
      const original = claim.extracted[k]?.value ?? "";
      if (d.blank) return { field_key: k, action: "confirmed_blank", value: null };
      if (d.value !== original) return { field_key: k, action: "corrected", value: d.value };
      return { field_key: k, action: "confirmed" };
    });
  }

  return (
    <div className="split">
      <div className="doc">
        {/* The source document, beside the values taken from it. Checking a
            field against the page is the whole job -- reading a table of
            values in isolation is guesswork. */}
        <iframe src={api.documentUrl(claim.id)} title="source document" />
      </div>

      <div className="panel">
        <p className="muted" style={{ marginTop: 0, fontSize: 12.5 }}>
          {claim.form_code} · {claim.flagged.length} field
          {claim.flagged.length === 1 ? "" : "s"} need checking · lease{" "}
          {Math.round(claim.lease_seconds / 60)} min
        </p>

        {claim.flagged.map((key) => {
          const field = claim.extracted[key];
          const d = draft[key];
          const escalated = claim.always_escalate.includes(key);
          const conf = field?.confidence ?? 0;
          return (
            <div className="field" key={key}>
              <div className="field-head">
                <span className="key">{key}</span>
                <span className={`conf ${conf < 0.5 ? "low" : "mid"}`}>
                  {conf.toFixed(2)}
                </span>
                <span className="why">
                  {escalated ? "always escalated" : `below ${claim.threshold}`}
                </span>
              </div>

              <input
                type="text"
                className={d.value !== (field?.value ?? "") ? "changed" : ""}
                value={d.blank ? "" : d.value}
                disabled={d.blank}
                placeholder={d.blank ? "blank on the form" : ""}
                onChange={(e) =>
                  setDraft({ ...draft, [key]: { ...d, value: e.target.value } })
                }
              />

              <div className="row">
                <button
                  className={`blank ${d.blank ? "on" : ""}`}
                  onClick={() => setDraft({ ...draft, [key]: { ...d, blank: !d.blank } })}
                >
                  {d.blank ? "✓ blank on form" : "Mark blank"}
                </button>
                <button
                  onClick={() =>
                    setDraft({
                      ...draft,
                      [key]: { value: field?.value ?? "", blank: false },
                    })
                  }
                >
                  Reset
                </button>
              </div>
            </div>
          );
        })}

        <div className="bar">
          <button className="primary" onClick={() => onSubmit(edits())} disabled={busy}>
            Submit review
          </button>
          <span className="muted" style={{ fontSize: 12.5 }}>
            {changed} changed · {claim.flagged.length - changed} confirmed as-is
          </span>
        </div>
      </div>
    </div>
  );
}
