"use client";

import { useRouter } from "next/navigation";

export function BackLink() {
  const router = useRouter();
  return (
    <button
      onClick={() => router.back()}
      className="font-mono text-xs text-muted hover:text-primary"
    >
      &larr; back
    </button>
  );
}
