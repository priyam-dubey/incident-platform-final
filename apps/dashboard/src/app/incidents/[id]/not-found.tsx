export default function IncidentNotFound() {
  return (
    <div className="mx-auto max-w-lg px-6 py-24 text-center">
      <p className="font-mono text-sm text-critical">No incident found with that id.</p>
      <p className="mt-2 font-mono text-xs text-muted">
        It may belong to a different workspace, or the id was mistyped.
      </p>
    </div>
  );
}
