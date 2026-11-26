"use client";
import { useRef, useState } from "react";

export interface Series { name: string; color: string; values: (number | null)[]; fmt?: (v: number) => string }

/** Minimal accessible SVG line/area chart with crosshair tooltip. Gaps (null) are drawn as gaps - no data is not zero. */
export function LineChart({ times, series, height = 180, area = false, yFmt }: { times: string[]; series: Series[]; height?: number; area?: boolean; yFmt?: (v: number) => string }) {
  const W = 640, H = height, L = 44, R = 8, T = 8, B = 22;
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const nums = series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  if (times.length < 2 || nums.length === 0) {
    return <div className="flex items-center justify-center rounded border border-dashed border-line text-sm text-muted" style={{ height }}>No data in this range</div>;
  }
  const max = Math.max(...nums, 0) * 1.1 || 1;
  const x = (i: number) => L + (i / (times.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / max) * (H - T - B);
  const fy = yFmt ?? ((v: number) => String(Math.round(v * 100) / 100));
  const paths = series.map((s) => {
    const segs: string[] = []; let cur = "";
    s.values.forEach((v, i) => { if (v === null) { if (cur) segs.push(cur); cur = ""; } else cur += `${cur ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
    if (cur) segs.push(cur);
    return segs;
  });
  const ticks = [0, 0.5, 1].map((f) => f * max);
  const onMove = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(times.length - 1, Math.round(((px - L) / (W - L - R)) * (times.length - 1)))));
  };
  const lbl = (t: string) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="relative">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Line chart: ${series.map((s) => s.name).join(", ")}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="rgb(var(--line))" strokeWidth="1" /><text x={L - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="rgb(var(--muted))">{fy(t)}</text></g>)}
        {[0, Math.floor((times.length - 1) / 2), times.length - 1].map((i) => <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === times.length - 1 ? "end" : "middle"} fontSize="10" fill="rgb(var(--muted))">{lbl(times[i])}</text>)}
        {series.map((s, si) => paths[si].map((d, k) => (
          <g key={`${si}-${k}`}>
            {area && <path d={`${d}L${x(times.length - 1)},${y(0)}L${L},${y(0)}Z`} fill={s.color} opacity="0.12" />}
            <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          </g>)))}
        {hover !== null && <g><line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="rgb(var(--muted))" strokeDasharray="3 3" />
          {series.map((s) => s.values[hover] !== null && <circle key={s.name} cx={x(hover)} cy={y(s.values[hover] as number)} r="4" fill={s.color} stroke="rgb(var(--panel))" strokeWidth="2" />)}</g>}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-1 rounded border border-line bg-panel px-2 py-1 text-xs shadow" style={{ left: `${(x(hover) / W) * 100}%`, transform: `translateX(${hover > times.length / 2 ? "-105%" : "5%"})` }}>
          <p className="text-muted">{new Date(times[hover]).toLocaleString()}</p>
          {series.map((s) => <p key={s.name} className="flex items-center gap-2 text-ink"><span className="h-2 w-2 rounded-full" style={{ background: s.color }} />{s.name}: {s.values[hover] === null ? "no data" : (s.fmt ?? fy)(s.values[hover] as number)}</p>)}
        </div>)}
      {series.length > 1 && <div className="mt-1 flex gap-4 text-xs text-soft">{series.map((s) => <span key={s.name} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: s.color }} />{s.name}</span>)}</div>}
      <details className="mt-1 text-xs text-muted"><summary className="cursor-pointer">Table view</summary>
        <div className="max-h-40 overflow-auto"><table className="w-full"><thead><tr><th className="text-left">Time</th>{series.map((s) => <th key={s.name} className="text-right">{s.name}</th>)}</tr></thead>
          <tbody>{times.map((t, i) => <tr key={t}><td>{lbl(t)}</td>{series.map((s) => <td key={s.name} className="text-right tabular-nums">{s.values[i] === null ? "–" : (s.fmt ?? fy)(s.values[i] as number)}</td>)}</tr>)}</tbody></table></div></details>
    </div>
  );
}

export function BarList({ items, color = "rgb(var(--s1))" }: { items: { label: string; value: number; sub?: string }[]; color?: string }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return <ul className="space-y-2">{items.map((i) => (
    <li key={i.label} className="text-sm"><div className="flex justify-between"><span className="truncate text-soft">{i.label}</span><span className="tabular-nums text-ink">{i.sub ?? i.value}</span></div>
      <div className="mt-1 h-1.5 rounded bg-raised"><div className="h-1.5 rounded" style={{ width: `${(i.value / max) * 100}%`, background: color }} /></div></li>))}</ul>;
}
