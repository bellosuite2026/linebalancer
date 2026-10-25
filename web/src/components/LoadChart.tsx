import type { StationDetail } from "../lib/types";

/** Charge de chaque station (min) comparée à la cadence cible. */
export default function LoadChart({ stations, cycle }: { stations: StationDetail[]; cycle: number }) {
  if (!stations.length) return null;
  const max = Math.max(cycle * 1.15, ...stations.map((s) => s.total_time / Math.max(1, s.parallel ?? 1)));
  const W = Math.max(560, stations.length * 34), H = 240, pad = { l: 40, r: 10, t: 14, b: 28 };
  const bw = (W - pad.l - pad.r) / stations.length;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const ticks = [0, cycle / 2, cycle, max].filter((v, i, a) => a.indexOf(v) === i);
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Charge par station">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{t.toFixed(2)}</text>
          </g>
        ))}
        {stations.map((s, i) => {
          const v = s.total_time / Math.max(1, s.parallel ?? 1);
          const ratio = v / cycle;
          const cls = ratio > 1.0001 ? "bar over" : ratio >= 0.85 ? "bar good" : ratio >= 0.6 ? "bar mid" : "bar low";
          return (
            <g key={s.station}>
              <rect x={pad.l + i * bw + bw * 0.15} width={bw * 0.7} y={y(v)} height={Math.max(0, y(0) - y(v))} className={cls}>
                <title>{`Station ${s.station} : ${v.toFixed(2)} min (${s.load_pct}%)\n${s.operations.join(", ")}`}</title>
              </rect>
              <text x={pad.l + i * bw + bw / 2} y={H - 10} textAnchor="middle" className="axis">{s.station}</text>
            </g>
          );
        })}
        <line x1={pad.l} x2={W - pad.r} y1={y(cycle)} y2={y(cycle)} className="target" />
        <text x={W - pad.r} y={y(cycle) - 5} textAnchor="end" className="target-label">Cadence {cycle} min</text>
      </svg>
      <div className="legend">
        <span><i className="good" />≥ 85 %</span><span><i className="mid" />60–85 %</span><span><i className="low" />&lt; 60 %</span><span><i className="over" />dépasse</span>
      </div>
    </div>
  );
}
