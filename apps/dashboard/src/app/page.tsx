/**
 * Workspace entry point. This platform doesn't have real dashboard
 * authentication yet (documented scope cut - see the root README's Phase 7
 * notes), so instead of pretending a login exists, this is honest about
 * what it actually is: a way to jump into a known workspace id. A real
 * auth/session layer would replace this page with a redirect, not add a
 * form on top of it.
 */
export default function HomePage() {
  return (
    <div className="mx-auto max-w-lg px-6 py-24">
      <h1 className="font-display text-2xl font-medium">Open a workspace</h1>
      <p className="mt-2 text-sm text-muted">
        Enter a workspace id to view its incident feed. (No auth layer yet -
        see the platform README for why, and what replaces this later.)
      </p>
      <form action="/incidents" method="GET" className="mt-6 flex gap-2">
        <input
          type="text"
          name="workspace_id"
          placeholder="11111111-1111-1111-1111-111111111111"
          required
          className="flex-1 border border-hairline bg-panel px-3 py-2 font-mono text-sm text-primary placeholder:text-muted focus:border-ai"
        />
        <button
          type="submit"
          className="border border-ai px-4 py-2 font-mono text-sm text-ai transition-colors hover:bg-ai hover:text-void"
        >
          OPEN
        </button>
      </form>
    </div>
  );
}
