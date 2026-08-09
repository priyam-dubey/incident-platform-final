import { NextRequest, NextResponse } from "next/server";
import { submitVerdict } from "@/lib/api";
import { Verdict } from "@/lib/types";

export async function POST(request: NextRequest, { params }: { params: { id: string } }) {
  const body = (await request.json()) as {
    verdict: Verdict;
    notes?: string;
    reviewerEmail: string;
  };

  if (!body.reviewerEmail || !body.reviewerEmail.trim()) {
    return NextResponse.json(
      { error: "reviewerEmail is required to attribute this verdict to a human." },
      { status: 400 },
    );
  }

  try {
    const result = await submitVerdict(params.id, body.verdict, body.notes, body.reviewerEmail);
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
