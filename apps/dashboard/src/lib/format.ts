export const fmtMs = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
export const fmtPct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(v < 0.01 && v > 0 ? 2 : 1)}%`);
export const fmtNum = (v: number | null | undefined) => (v === null || v === undefined ? "–" : new Intl.NumberFormat().format(Math.round(v * 100) / 100));
export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
export const fmtTime = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
export const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : "–");
