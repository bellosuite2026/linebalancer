// Tableaux de bord type FlexSim (SVG, sans bibliothèque) : barres d'états, camembert, courbes,
// histogramme, Gantt.
import { OP_COLOR, OP_LABEL, OP_STATES, STATE_COLOR, STATE_LABEL, STATION_STATES, type OperatorRes, type StationRes } from "../lib/des";

const n1 = (v: number) => v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });

export function Legend({ keys, labels, colors }: { keys: readonly string[]; labels: Record<string, string>; colors: Record<string, string> }) {
  return <div className="chart-legend">{keys.map((k) => <span key={k}><i style={{ background: colors[k] }} />{labels[k]}</span>)}</div>;
}

/** Barres empilées des états de chaque poste (« State Bar »). */
export function StateBars({ stations, bottleneck, onPick, picked }: { stations: StationRes[]; bottleneck?: string; onPick?: (id: string) => void; picked?: string | null }) {
  const row = 18, lw = 70, W = 640, H = stations.length * row + 6;
  return (
    <div className="chart-scroll">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="États des postes">
        {stations.map((s, i) => {
          let x = lw;
          return (
            <g key={s.id} transform={`translate(0,${i * row + 3})`} onClick={() => onPick?.(s.id)} style={{ cursor: onPick ? "pointer" : undefined }}>
              <text x={lw - 6} y={row / 2} textAnchor="end" dominantBaseline="middle" fontSize={10} fontWeight={s.id === bottleneck || s.id === picked ? 700 : 400}
                fill={s.id === bottleneck ? "#d64541" : "#1d2b38"}>{s.id === bottleneck ? "⚑ " : ""}{s.label.replace("Station ", "St. ")}</text>
              {STATION_STATES.map((k) => {
                const w = ((W - lw - 4) * (s.states[k] || 0)) / 100;
                const r = <rect key={k} x={x} y={1} width={Math.max(0, w)} height={row - 4} fill={STATE_COLOR[k]}><title>{`${STATE_LABEL[k]} : ${n1(s.states[k] || 0)} %`}</title></rect>;
                x += w; return r;
              })}
              {s.id === picked && <rect x={lw - 1} y={0} width={W - lw - 2} height={row - 2} fill="none" stroke="#1f4e79" strokeWidth={1.5} />}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Camembert des états d'un poste (« State Pie »). */
export function StatePie({ states, size = 150 }: { states: Record<string, number>; size?: number }) {
  const r = size / 2 - 4, c = size / 2;
  let a0 = -Math.PI / 2;
  const parts = STATION_STATES.filter((k) => (states[k] || 0) > 0.05);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label="Répartition des états">
      {parts.length === 1 ? <circle cx={c} cy={c} r={r} fill={STATE_COLOR[parts[0]]} /> : parts.map((k) => {
        const a1 = a0 + (2 * Math.PI * (states[k] || 0)) / 100;
        const large = a1 - a0 > Math.PI ? 1 : 0;
        const d = `M${c},${c} L${c + r * Math.cos(a0)},${c + r * Math.sin(a0)} A${r},${r} 0 ${large} 1 ${c + r * Math.cos(a1)},${c + r * Math.sin(a1)} Z`;
        a0 = a1;
        return <path key={k} d={d} fill={STATE_COLOR[k]} stroke="#fff" strokeWidth={1}><title>{`${STATE_LABEL[k]} : ${n1(states[k])} %`}</title></path>;
      })}
    </svg>
  );
}

export interface Series { name: string; color: string; points: [number, number][]; dash?: boolean }

/** Courbes (encours, débit cumulé vs objectif). x en minutes. */
export function LineChart({ series, xMax, yLabel, height = 190, breaks = [] }: { series: Series[]; xMax: number; yLabel: string; height?: number; breaks?: { start_min: number; minutes: number }[] }) {
  const W = 640, H = height, L = 44, B = 22, T = 8, R = 8;
  const yMax = Math.max(1, ...series.flatMap((s) => s.points.map((p) => p[1]))) * 1.08;
  const X = (x: number) => L + ((W - L - R) * x) / Math.max(1, xMax), Y = (y: number) => H - B - ((H - B - T) * y) / yMax;
  const ticks = Array.from({ length: 5 }, (_, i) => (yMax * i) / 4);
  const hours = Array.from({ length: Math.floor(xMax / 60) + 1 }, (_, i) => i * 60);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={yLabel}>
      {breaks.map((b, i) => <rect key={i} x={X(b.start_min)} y={T} width={X(b.start_min + b.minutes) - X(b.start_min)} height={H - B - T} fill="#95a5a6" opacity={0.15} />)}
      {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} stroke="#e3e6ea" /><text x={L - 4} y={Y(t)} fontSize={9} textAnchor="end" dominantBaseline="middle" fill="#6b7682">{Math.round(t)}</text></g>)}
      {hours.map((h) => <text key={h} x={X(h)} y={H - 6} fontSize={9} textAnchor="middle" fill="#6b7682">{h / 60} h</text>)}
      <text x={4} y={T + 2} fontSize={9} fill="#6b7682">{yLabel}</text>
      {series.map((s) => <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dash ? "5 4" : undefined}
        points={s.points.map(([x, y]) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(" ")} />)}
    </svg>
  );
}

export function Histogram({ edges, counts, color = "#3b7dd8", unit = "min" }: { edges: number[]; counts: number[]; color?: string; unit?: string }) {
  const W = 640, H = 170, L = 34, B = 26, T = 8;
  if (!counts.length) return <p className="muted small">Aucun paquet terminé sur la durée simulée.</p>;
  const m = Math.max(...counts), bw = (W - L - 8) / counts.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Histogramme du temps de traversée">
      {counts.map((c, i) => {
        const h = ((H - B - T) * c) / m;
        return <g key={i}><rect x={L + i * bw + 1} y={H - B - h} width={bw - 2} height={h} fill={color}><title>{`${n1(edges[i])}–${n1(edges[i + 1])} ${unit} : ${c} paquet(s)`}</title></rect>
          {i % 2 === 0 && <text x={L + i * bw} y={H - 10} fontSize={9} fill="#6b7682">{Math.round(edges[i])}</text>}</g>;
      })}
      <text x={W - 8} y={H - 10} fontSize={9} fill="#6b7682" textAnchor="end">{Math.round(edges[edges.length - 1])} {unit}</text>
      <text x={4} y={T + 2} fontSize={9} fill="#6b7682">paquets</text>
    </svg>
  );
}

export function Bars({ values, target, label }: { values: number[]; target?: number | null; label: string }) {
  const W = 640, H = 160, L = 34, B = 22, T = 8;
  const m = Math.max(1, ...values, target ?? 0) * 1.1, bw = (W - L - 8) / Math.max(1, values.length);
  const Y = (v: number) => H - B - ((H - B - T) * v) / m;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={label}>
      {values.map((v, i) => <g key={i}><rect x={L + i * bw + 3} y={Y(v)} width={bw - 6} height={H - B - Y(v)} fill={target && v < target * 0.9 ? "#f08a24" : "#2e9e5b"} />
        <text x={L + i * bw + bw / 2} y={Y(v) - 3} fontSize={9} textAnchor="middle">{v}</text><text x={L + i * bw + bw / 2} y={H - 8} fontSize={9} textAnchor="middle" fill="#6b7682">{i + 1}e h</text></g>)}
      {target ? <><line x1={L} x2={W - 8} y1={Y(target)} y2={Y(target)} stroke="#1f4e79" strokeDasharray="5 4" /><text x={W - 8} y={Y(target) - 3} fontSize={9} textAnchor="end" fill="#1f4e79">objectif {n1(target)}/h</text></> : null}
    </svg>
  );
}

/** Gantt des opérateurs (états dans le temps). */
export function Gantt({ operators, T, now }: { operators: OperatorRes[]; T: number; now?: number }) {
  const row = 16, L = 110, W = 640, H = operators.length * row + 22;
  const X = (t: number) => L + ((W - L - 6) * t) / Math.max(1, T);
  return (
    <div className="chart-scroll">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Gantt des opérateurs">
        {operators.map((o, i) => (
          <g key={o.id} transform={`translate(0,${i * row})`}>
            <text x={L - 6} y={row / 2} fontSize={9.5} textAnchor="end" dominantBaseline="middle">{o.name.slice(0, 18)}</text>
            <rect x={L} y={2} width={W - L - 6} height={row - 4} fill={OP_COLOR.idle} />
            {o.gantt.filter(([, , s]) => s !== 0).map(([a, b, s], k) => <rect key={k} x={X(a)} y={2} width={Math.max(0.4, X(b) - X(a))} height={row - 4} fill={OP_COLOR[OP_STATES[s]]} />)}
          </g>
        ))}
        {Array.from({ length: Math.floor(T / 60) + 1 }, (_, h) => <text key={h} x={X(h * 60)} y={H - 6} fontSize={9} textAnchor="middle" fill="#6b7682">{h} h</text>)}
        {now != null && <line x1={X(now)} x2={X(now)} y1={0} y2={H - 16} stroke="#d64541" strokeWidth={1.5} />}
      </svg>
      <Legend keys={OP_STATES} labels={OP_LABEL} colors={OP_COLOR} />
    </div>
  );
}
