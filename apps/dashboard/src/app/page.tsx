import Link from "next/link";

const FEATURES = [
  ["Code intelligence", "Connect a GitHub repository. Every push and pull request is analysed with Semgrep, Bandit, Ruff, ESLint, tsc, Gitleaks and dependency audits. Findings are deterministic; AI only explains them."],
  ["Runtime monitoring", "Instrument a Node.js/Express app with our OpenTelemetry SDK. Requests, latency, errors, logs and traces appear per application, with process metrics clearly separated from host metrics."],
  ["Evidence-grounded incidents", "Anomalies are detected statistically, then explained with hypotheses that must cite real evidence. Humans accept, reject or edit every conclusion."],
  ["Code ↔ runtime", "Register deployments with a commit SHA. Incidents show what shipped just before them - as a correlation to check, never as proof."],
];

export default function Landing() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <header className="flex items-center justify-between"><span className="font-semibold tracking-tight">Incident<span className="text-accent">/</span>Platform</span>
        <nav className="flex gap-3 text-sm"><Link href="/login" className="rounded border border-line px-3 py-1.5 hover:bg-raised">Sign in</Link><Link href="/signup" className="rounded bg-accent px-3 py-1.5 font-medium text-white">Get started</Link></nav></header>
      <section className="py-20 text-center">
        <h1 className="mx-auto max-w-3xl text-4xl font-semibold tracking-tight md:text-5xl">Find the bug in the code, and the cause behind the outage.</h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-muted">One workspace for repository security findings and live application incidents - every claim linked to evidence you can inspect.</p>
        <div className="mt-8 flex justify-center gap-3"><Link href="/signup" className="rounded bg-accent px-5 py-2.5 font-medium text-white">Create a workspace</Link><a href="#how" className="rounded border border-line px-5 py-2.5 hover:bg-raised">How it works</a></div>
      </section>
      <section id="how" className="grid gap-4 md:grid-cols-2">{FEATURES.map(([t, d]) => <div key={t} className="rounded-lg border border-line bg-panel p-5"><h2 className="font-semibold">{t}</h2><p className="mt-2 text-sm text-muted">{d}</p></div>)}</section>
      <section className="mt-10 rounded-lg border border-line bg-panel p-5 text-sm text-muted"><h2 className="mb-2 font-semibold text-ink">Honest by design</h2>
        <ul className="list-disc space-y-1 pl-5"><li>Integrations show <strong>Not configured</strong> until real credentials exist - nothing is faked.</li><li>Synthetic data is only ever shown in a workspace labelled <strong>DEMO</strong> and is never mixed with real telemetry.</li><li>Scanners read your code statically in a sandbox; repository code is never executed.</li><li>AI output is labelled, redacted going in, and optional - scanning and monitoring work without it.</li></ul></section>
    </div>
  );
}
