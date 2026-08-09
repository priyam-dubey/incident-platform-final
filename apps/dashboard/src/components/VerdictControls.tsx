"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Verdict } from "@/lib/types";

/**
 * The one genuinely interactive piece of the incident detail page. Reviewer
 * identity is a plain text field rather than pulled from a session, because
 * this platform does not yet have real dashboard authentication (see
 * Phase 7's README note on this being a deliberate, documented scope cut -
 * this field is exactly where a real signed-in user's email would be
 * substituted once session auth exists, with no other code path changing).
 */
export function VerdictControls({
  hypothesisId,
  existingVerdict,
  reviewedBy,
}: {
  hypothesisId: string;
  existingVerdict: Verdict | null;
  reviewedBy: string | null;
}) {
  const router = useRouter();
  const [reviewerEmail, setReviewerEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [pending, setPending] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (existingVerdict) {
    return (
      <div className="font-mono text-xs text-muted">
        VERDICT: <span className="text-primary">{existingVerdict.toUpperCase()}</span>
        {reviewedBy ? <span> by {reviewedBy}</span> : null}
      </div>
    );
  }

  async function submit(verdict: Verdict) {
    if (!reviewerEmail.trim()) {
      setError("Enter your email to submit a verdict.");
      return;
    }
    setPending(verdict);
    setError(null);
    try {
      const response = await fetch(`/api/hypotheses/${hypothesisId}/verdict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict, notes: notes || undefined, reviewerEmail }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error ?? `Request failed (${response.status})`);
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit verdict.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-hairline pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="email"
          placeholder="your@company.com"
          value={reviewerEmail}
          onChange={(e) => setReviewerEmail(e.target.value)}
          className="border border-hairline bg-void px-2 py-1 font-mono text-xs text-primary placeholder:text-muted focus:border-ai"
        />
        <input
          type="text"
          placeholder="optional notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="min-w-[10rem] flex-1 border border-hairline bg-void px-2 py-1 font-mono text-xs text-primary placeholder:text-muted focus:border-ai"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => submit("accepted")}
          disabled={pending !== null}
          className="border border-resolved px-3 py-1 font-mono text-xs text-resolved transition-colors hover:bg-resolved hover:text-void disabled:opacity-50"
        >
          {pending === "accepted" ? "SUBMITTING..." : "ACCEPT"}
        </button>
        <button
          onClick={() => submit("edited")}
          disabled={pending !== null}
          className="border border-ai px-3 py-1 font-mono text-xs text-ai transition-colors hover:bg-ai hover:text-void disabled:opacity-50"
        >
          {pending === "edited" ? "SUBMITTING..." : "ACCEPT (EDITED)"}
        </button>
        <button
          onClick={() => submit("rejected")}
          disabled={pending !== null}
          className="border border-critical px-3 py-1 font-mono text-xs text-critical transition-colors hover:bg-critical hover:text-void disabled:opacity-50"
        >
          {pending === "rejected" ? "SUBMITTING..." : "REJECT"}
        </button>
      </div>
      {error ? <p className="font-mono text-xs text-critical">{error}</p> : null}
    </div>
  );
}
