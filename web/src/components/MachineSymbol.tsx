// Symbole 2D d'une machine (dessiné dans le repère local de la machine, centre = 0,0, mètres).
// Forme choisie d'après la bibliothèque (shape) : tête de piqueuse, colonne, bras, surjeteuse,
// table de coupe, presse, mannequin, convoyeur, rack, chariot…
import { MACHINE_CATALOG } from "../lib/workshop";

const S = "#5b6878", F = "#cfd8e3";

export default function MachineSymbol({ type, w, d }: { type: string; w: number; d: number }) {
  const shape = MACHINE_CATALOG[type]?.shape ?? "table";
  const sw = 0.015;
  const head = (hw: number, hd: number, x = w / 2 - hw - 0.12) => (
    <rect x={x} y={-d / 2 + 0.08} width={hw} height={hd} fill={F} stroke={S} strokeWidth={sw} />
  );
  switch (shape) {
    case "sew_flat":
      return <g>{head(0.3, d * 0.42)}<circle cx={w / 2 - 0.36} cy={d * 0.05} r={0.025} fill={S} /></g>;
    case "sew_post":
      return <g>{head(0.3, d * 0.3)}<circle cx={w / 2 - 0.36} cy={d * 0.08} r={0.07} fill={F} stroke={S} strokeWidth={sw} /></g>;
    case "sew_arm":
      return <g>{head(0.28, d * 0.3)}<rect x={w / 2 - 0.75} y={-0.05} width={0.5} height={0.12} rx={0.06} fill={F} stroke={S} strokeWidth={sw} /></g>;
    case "sew_overlock":
      return <g>{head(0.26, 0.24)}<path d={`M${w / 2 - 0.44},${-d / 2 + 0.34} l0.1,0.1 l-0.1,0 z`} fill={S} /></g>;
    case "sew_auto":
      return <g>{head(0.32, d * 0.4)}<rect x={w / 2 - 0.5} y={0.02} width={0.22} height={0.12} fill="none" stroke={S} strokeWidth={sw} /></g>;
    case "sew_station":
      return <g>{head(0.34, 0.3)}<rect x={-w / 2 + 0.12} y={-d / 2 + 0.12} width={w * 0.55} height={d * 0.7} fill="none" stroke={S} strokeWidth={sw} strokeDasharray="0.06 0.04" /></g>;
    case "cutting_table":
      return <g>{Array.from({ length: Math.max(1, Math.floor(w / 1.2)) }, (_, i) => (
        <line key={i} x1={-w / 2 + (i + 1) * 1.2} y1={-d / 2} x2={-w / 2 + (i + 1) * 1.2} y2={d / 2} stroke={F} strokeWidth={0.02} />))}</g>;
    case "spreader":
      return <g><circle cx={0} cy={0} r={Math.min(w, d) * 0.3} fill={F} stroke={S} strokeWidth={sw} /><line x1={-w / 2} y1={0} x2={w / 2} y2={0} stroke={S} strokeWidth={sw} /></g>;
    case "cutter_cad":
      return <g><rect x={-w / 2 + 0.15} y={-d / 2 + 0.15} width={w - 0.3} height={d - 0.3} fill="none" stroke={F} strokeWidth={0.04} />
        <rect x={-0.1} y={-d / 2} width={0.2} height={d} fill={F} stroke={S} strokeWidth={sw} /></g>;
    case "bandknife":
      return <g><circle cx={w * 0.2} cy={-d * 0.2} r={0.22} fill="none" stroke={S} strokeWidth={0.03} /><line x1={w * 0.2} y1={-d * 0.2} x2={w * 0.2} y2={d * 0.3} stroke={S} strokeWidth={0.02} /></g>;
    case "fusing":
      return <g><rect x={-w * 0.25} y={-d / 2 + 0.06} width={w * 0.5} height={d - 0.12} fill={F} stroke={S} strokeWidth={sw} />
        {[-0.3, 0, 0.3].map((t) => <line key={t} x1={-w / 2} y1={t * d} x2={w / 2} y2={t * d} stroke={S} strokeWidth={0.01} strokeDasharray="0.05 0.05" />)}</g>;
    case "ironing":
      return <path d={`M${-w / 2 + 0.1},${-d / 2 + 0.1} H${w / 2 - 0.35} Q${w / 2 - 0.05},0 ${w / 2 - 0.35},${d / 2 - 0.1} H${-w / 2 + 0.1} Z`} fill={F} stroke={S} strokeWidth={sw} />;
    case "mannequin":
      return <g><ellipse cx={0} cy={0} rx={Math.min(w, d) * 0.22} ry={Math.min(w, d) * 0.16} fill={F} stroke={S} strokeWidth={sw} /><circle r={0.05} fill={S} /></g>;
    case "press":
      return <g><rect x={-w * 0.35} y={-d * 0.35} width={w * 0.7} height={d * 0.5} fill={F} stroke={S} strokeWidth={sw} /><rect x={-w * 0.3} y={-d * 0.3} width={w * 0.6} height={d * 0.4} fill="none" stroke={S} strokeWidth={sw} /></g>;
    case "inspection":
      return <line x1={-w / 2 + 0.1} y1={-d / 2 + 0.1} x2={w / 2 - 0.1} y2={-d / 2 + 0.1} stroke="#e8c547" strokeWidth={0.05} />;
    case "detector":
      return <g><rect x={-0.25} y={-d / 2} width={0.5} height={d} fill={F} stroke={S} strokeWidth={sw} />
        {[-0.6, -0.3, 0.3, 0.6].map((t) => <line key={t} x1={t * w / 1.4} y1={-d / 2 + 0.1} x2={t * w / 1.4} y2={d / 2 - 0.1} stroke={S} strokeWidth={0.01} />)}</g>;
    case "packing":
      return <g><rect x={w * 0.1} y={-d * 0.3} width={w * 0.3} height={d * 0.5} fill={F} stroke={S} strokeWidth={sw} /><line x1={w * 0.1} y1={-d * 0.05} x2={w * 0.4} y2={-d * 0.05} stroke={S} strokeWidth={sw} /></g>;
    case "rack":
      return <g>{[-0.25, 0, 0.25].map((t) => <line key={t} x1={-w / 2} y1={t * d} x2={w / 2} y2={t * d} stroke={S} strokeWidth={0.02} />)}</g>;
    case "cart":
      return <g>{[[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => <circle key={`${a}${b}`} cx={a * (w / 2 - 0.08)} cy={b * (d / 2 - 0.08)} r={0.04} fill={S} />)}</g>;
    case "conveyor":
      return <g><line x1={-w / 2} y1={0} x2={w / 2} y2={0} stroke={S} strokeWidth={0.04} strokeDasharray="0.12 0.06" />
        {[-0.3, 0, 0.3].map((t) => <circle key={t} cx={t * w} cy={0} r={0.05} fill={F} stroke={S} strokeWidth={sw} />)}</g>;
    case "pallet":
      return <g>{[-0.33, 0, 0.33].map((t) => <line key={t} x1={t * w} y1={-d / 2} x2={t * w} y2={d / 2} stroke={F} strokeWidth={0.05} />)}</g>;
    default:
      return null;
  }
}
