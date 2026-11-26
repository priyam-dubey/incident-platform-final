"use client";
import { AuthProvider } from "@/lib/auth";
import Link from "next/link";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="flex min-h-screen flex-col items-center justify-center px-4">
        <Link href="/" className="mb-6 text-lg font-semibold tracking-tight">Incident<span className="text-accent">/</span>Platform</Link>
        <div className="w-full max-w-sm rounded-lg border border-line bg-panel p-6">{children}</div>
      </div>
    </AuthProvider>
  );
}
