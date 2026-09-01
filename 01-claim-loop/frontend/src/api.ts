const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Field = {
  value: string | null;
  confidence: number;
  source: "model" | "human" | "blank" | "not_present";
};

export type Claim = {
  id: string;
  storage_uri: string;
  form_code: string;
  flagged: string[];
  always_escalate: string[];
  threshold: number;
  lease_seconds: number;
  extracted: Record<string, Field>;
};

export type Edit = {
  field_key: string;
  action: "confirmed" | "corrected" | "confirmed_blank";
  value?: string | null;
};

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  stats: () => json<{ counts: Record<string, number>; stuck: number; threshold: number }>("/stats"),
  nextReview: () => json<Claim>("/claims/next-review", { method: "POST" }),
  complete: (id: string, reviewer: string, edits: Edit[]) =>
    json<{ status: string; events: number }>(`/claims/${id}/complete`, {
      method: "POST",
      body: JSON.stringify({ reviewer, edits }),
    }),
  documentUrl: (id: string) => `${BASE}/claims/${id}/document`,
};
