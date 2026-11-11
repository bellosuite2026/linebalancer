// Logique personnalisée par blocs (type Process Flow de FlexSim) : éditeur visuel de graphe (@xyflow/react,
// licence MIT), génération depuis la gamme, validation, sauvegarde, exécution par le moteur à événements
// discrets et animation des jetons sur le graphe + états des postes liés sur le plan.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  addEdge, Background, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState,
  type Connection, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { DesModel, Frame, CI } from "../lib/des";
import { fmtClock, STATE_COLOR, STATE_LABEL, STATION_STATES } from "../lib/des";
import type { WorkshopPlan } from "../lib/workshop";
import SimCanvas2D from "../components/SimCanvas2D";
import ErrorBoundary from "../components/ErrorBoundary";
import { Legend } from "../components/SimCharts";

type BType = "source" | "queue" | "operation" | "delay" | "decision" | "split" | "join" | "inspect" | "batch" | "unbatch" | "acquire" | "release" | "attribute" | "sink";
interface Block { id: string; type: BType; label: string; params: Record<string, any>; x?: number; y?: number }
interface Graph {
  name: string; shift?: { minutes: number; breaks: { start_min: number; minutes: number; label?: string }[] };
  settings?: { seed?: number; dist?: { kind: string; cv?: number }; efficiency?: number };
  resources: { name: string; kind: string; capacity: number }[]; blocks: Block[]; edges: { from: string; port: number; to: string }[];
}
interface Issue { msg: string; blocks: string[] }
interface Validation { ok: boolean; errors: Issue[]; warnings: Issue[] }
interface BlockRes { id: string; type: string; label: string; entered: number; exited: number; wip_avg: number; wip_max: number; utilization_pct?: number; defects?: number; lead_avg?: number | null; waiting?: number; servers?: number }
interface FlowRes {
  kpis: { pieces: number; per_hour: number; lead_time_avg: number | null; wip_avg: number; wip_max: number; bottleneck: string | null; launched: number };
  blocks: BlockRes[]; resources: { name: string; capacity: number; utilization_pct: number }[];
  conservation: { ok: boolean; launched: number; done: number; in_system: number };
  trace?: { events: number[][]; blocks: string[]; stations: string[]; truncated: boolean; until: number };
  replications?: { n: number; kpis: Record<string, CI> }; shift_minutes: number;
}
interface FlowSim { id: string; name: string; status: string; error?: string; created_at: string; results?: { replications: number; result: FlowRes }; layout?: { graph: Graph; model: DesModel } }
interface AutoResp { graph: Graph; validation: Validation; model: DesModel; workshop_plan: WorkshopPlan | null; problem_name: string;
  flows: { id: string; name: string; updated_at: string }[]; simulations: FlowSim[] }

const META: Record<BType, { label: string; color: string; icon: string; outs: number | "n"; hint: string }> = {
  source: { label: "Source", color: "#1f4e79", icon: "▶", outs: 1, hint: "Lance les paquets de l'ordre de coupe (lots modèle / taille / couleur)." },
  queue: { label: "File", color: "#8a7a5a", icon: "☰", outs: 1, hint: "File d'attente FIFO (capacité 0 = illimitée)." },
  operation: { label: "Opération", color: "#2e9e5b", icon: "⚙", outs: 1, hint: "Temps par pièce, serveurs, lien vers un poste du plan." },
  delay: { label: "Retard", color: "#7f8c8d", icon: "⏱", outs: 1, hint: "Attente sans capacité (séchage, repos…)." },
  decision: { label: "Décision", color: "#e67e22", icon: "◇", outs: "n", hint: "Probabilité, attribut ou condition." },
  split: { label: "Séparation", color: "#8e44ad", icon: "⑃", outs: "n", hint: "Sépare en sous-composants (devant, dos, manches…)." },
  join: { label: "Assemblage", color: "#c0392b", icon: "⊕", outs: 1, hint: "Attend une pièce de chaque branche (même produit, lot ou taille)." },
  inspect: { label: "Contrôle", color: "#16a085", icon: "✓", outs: 2, hint: "Contrôle : sortie 1 = conforme, sortie 2 = retouche." },
  batch: { label: "Groupage", color: "#2c3e50", icon: "▣", outs: 1, hint: "Regroupe N jetons (même attribut)." },
  unbatch: { label: "Dégroupage", color: "#2c3e50", icon: "▢", outs: 1, hint: "Rend les jetons d'un groupe." },
  acquire: { label: "Prendre ressource", color: "#3b7dd8", icon: "✋", outs: 1, hint: "Prend un opérateur, une machine, un chariot…" },
  release: { label: "Libérer ressource", color: "#3b7dd8", icon: "↩", outs: 1, hint: "Rend la ressource prise." },
  attribute: { label: "Attribut", color: "#d35400", icon: "#", outs: 1, hint: "Fixe taille / couleur / modèle (ou au hasard)." },
  sink: { label: "Sortie", color: "#27ae60", icon: "■", outs: 0, hint: "Produits finis (comptage, traversée)." },
};
const TYPES = Object.keys(META) as BType[];
const nOuts = (b: Block) => (META[b.type].outs === "n" ? Math.max(2, Number(b.params.outs) || 2) : (META[b.type].outs as number));
const portLabel = (b: Block, i: number) => b.type === "inspect" ? (i === 0 ? "conforme" : "retouche")
  : b.type === "split" ? (b.params.components?.[i] ?? `composant ${i + 1}`) : b.type === "decision" ? (b.params.mode === "cond" ? (i === 0 ? "vrai" : "faux") : `sortie ${i + 1}`) : "";

function summary(b: Block): string {
  const p = b.params;
  switch (b.type) {
    case "source": return `paquets de ${p.bundle_size ?? 10}${p.interval_min ? ` · 1 / ${p.interval_min} min` : " · tiré"}${p.wip_cap ? ` · ≤ ${p.wip_cap} en cours` : ""}`;
    case "operation": case "inspect": return `${fmt.n(p.minutes ?? 0, 3)} min/pc · ${p.servers ?? 1} serv.${p.station ? ` · poste ${p.station}` : ""}${b.type === "inspect" ? ` · ${p.defect_pct ?? 0} % défauts` : ""}`;
    case "queue": return p.capacity ? `capacité ${p.capacity}` : "illimitée";
    case "delay": return `${p.minutes ?? 0} min`;
    case "decision": return p.mode === "attr" ? `selon ${p.attr ?? "?"}` : p.mode === "cond" ? `${p.attr ?? "?"} ${p.op ?? "=="} ${p.value ?? ""}` : `probabilités ${(p.probs ?? []).join(" / ")}`;
    case "split": return (p.components ?? []).join(" · ") || "composants";
    case "join": return `par ${({ product: "produit", lot: "lot", size: "taille" } as Record<string, string>)[p.match ?? "product"] ?? p.match}`;
    case "batch": return `par ${p.size ?? 2}${p.key ? ` (même ${p.key})` : ""}`;
    case "acquire": case "release": return `${p.qty ?? 1} × ${p.resource ?? "?"}`;
    case "attribute": return p.attr ? `${p.attr} au hasard` : Object.entries(p.set ?? {}).map(([k, v]) => `${k} = ${v}`).join(", ");
    default: return "";
  }
}

// ------------------------------------------------------------------ nœud
type NodeData = { block: Block; stat?: BlockRes; live?: number; bad?: boolean; bottleneck?: boolean };
function BlockNode({ data, selected }: NodeProps<Node<NodeData>>) {
  const b = data.block, m = META[b.type], n = nOuts(b);
  return (
    <div className={`pf-node ${selected ? "sel" : ""} ${data.bad ? "bad" : ""} ${data.bottleneck ? "bott" : ""}`} style={{ borderColor: m.color }}>
      {b.type !== "source" && <Handle type="target" position={Position.Left} id="in" />}
      <div className="pf-head" style={{ background: m.color }}><span>{m.icon}</span> {m.label}{data.live ? <b className="pf-live">● {data.live}</b> : null}</div>
      <div className="pf-body"><div className="pf-label">{b.label}</div><div className="pf-sum">{summary(b)}</div>
        {data.stat && <div className="pf-stat">{data.stat.entered} entrés · encours moy. {fmt.n(data.stat.wip_avg, 1)}{data.stat.utilization_pct != null ? ` · ${fmt.n(data.stat.utilization_pct, 0)} %` : ""}{data.stat.defects ? ` · ${data.stat.defects} retouches` : ""}</div>}
      </div>
      {Array.from({ length: n }, (_, i) => (
        <Handle key={i} type="source" position={Position.Right} id={`o${i}`} style={{ top: `${((i + 1) / (n + 1)) * 100}%` }}>
          {n > 1 && <span className="pf-port">{portLabel(b, i)}</span>}
        </Handle>))}
    </div>
  );
}
const nodeTypes = { block: BlockNode };

const toFlow = (g: Graph): { nodes: Node<NodeData>[]; edges: Edge[] } => ({
  nodes: g.blocks.map((b, i) => ({ id: b.id, type: "block", position: { x: b.x ?? i * 220, y: b.y ?? 60 }, data: { block: b } })),
  edges: g.edges.map((e, i) => ({ id: `e${i}-${e.from}-${e.port}-${e.to}`, source: e.from, sourceHandle: `o${e.port}`, target: e.to, targetHandle: "in", animated: false })),
});
const fromFlow = (g: Graph, nodes: Node<NodeData>[], edges: Edge[]): Graph => ({
  ...g, blocks: nodes.map((n) => ({ ...n.data.block, x: Math.round(n.position.x), y: Math.round(n.position.y) })),
  edges: edges.map((e) => ({ from: e.source, port: Number((e.sourceHandle ?? "o0").slice(1)) || 0, to: e.target })),
});

// ------------------------------------------------------------------ lecture de la trace : jetons par bloc
class FlowCursor {
  i = 0; at = new Map<number, number>(); counts: number[]; st: number[];
  constructor(public ev: number[][], public nb: number, public ns: number) { this.counts = new Array(nb).fill(0); this.st = new Array(ns).fill(1); }
  seek(t: number) {
    if (this.i > 0 && this.ev[this.i - 1][0] > t) { this.i = 0; this.at.clear(); this.counts.fill(0); this.st.fill(1); }
    while (this.i < this.ev.length && this.ev[this.i][0] <= t) {
      const e = this.ev[this.i++];
      if (e[1] === 6) { const prev = this.at.get(e[2]); if (prev != null) this.counts[prev]--; this.at.set(e[2], e[3]); this.counts[e[3]]++; }
      else if (e[1] === 7) { const prev = this.at.get(e[2]); if (prev != null) { this.counts[prev]--; this.at.delete(e[2]); } }
      else if (e[1] === 0) this.st[e[2]] = e[3];
    }
  }
}

function Editor() {
  const { runId } = useParams();
  const [sp, setSp] = useSearchParams();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const base = `/v1/orgs/${org.id}`;
  const writable = canWrite(org);
  const [data, setData] = useState<AutoResp | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [flowId, setFlowId] = useState<string>(sp.get("flux") ?? "");
  const [sel, setSel] = useState<string | null>(null);
  const [val, setVal] = useState<Validation | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [sim, setSim] = useState<FlowSim | null>(null);
  const [reps, setReps] = useState(3);
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(60);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api<AutoResp>(`${base}/runs/${runId}/flow/auto`);
      setData(d);
      const fid = sp.get("flux");
      let g = d.graph;
      if (fid) { try { const f = await api<{ id: string; name: string; graph: Graph }>(`${base}/flows/${fid}`); g = { ...f.graph, name: f.name }; } catch { setFlowId(""); } }
      setGraph(g); const f = toFlow(g); setNodes(f.nodes); setEdges(f.edges); setVal(fid ? null : d.validation);
      const last = sp.get("sim") ?? d.simulations.find((s) => s.status === "done")?.id;
      if (last) openSim(last);
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, runId]);
  useEffect(() => { load(); }, [load]);

  const current = (): Graph | null => (graph ? fromFlow(graph, nodes, edges) : null);
  const onConnect = useCallback((c: Connection) => {
    setEdges((es) => addEdge({ ...c, targetHandle: "in" }, es.filter((e) => !(e.source === c.source && e.sourceHandle === c.sourceHandle))));
    setDirty(true);
  }, [setEdges]);
  const selected = nodes.find((n) => n.id === sel)?.data.block ?? null;
  const updBlock = (id: string, patch: Partial<Block> & { params?: Record<string, any> }) => {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, block: { ...n.data.block, ...patch, params: { ...n.data.block.params, ...(patch.params ?? {}) } } } } : n)));
    setDirty(true);
  };
  const addBlock = (type: BType) => {
    const id = `${type}_${Math.random().toString(36).slice(2, 7)}`;
    const params: Record<string, any> = type === "operation" || type === "inspect" ? { minutes: 1, servers: 1, ...(type === "inspect" ? { defect_pct: 3 } : {}) }
      : type === "source" ? { bundle_size: 10, wip_cap: 20, lots: [{ style: data?.problem_name || "Modèle", size: "", color: "", qty: 0 }] }
      : type === "decision" ? { mode: "prob", probs: [0.9, 0.1], outs: 2 } : type === "split" ? { components: ["devant", "dos"], outs: 2 }
      : type === "join" ? { match: "product" } : type === "batch" ? { size: 4 } : type === "delay" ? { minutes: 5 }
      : type === "acquire" || type === "release" ? { resource: graph?.resources[0]?.name ?? "Opératrices", qty: 1 } : type === "attribute" ? { set: { couleur: "bleu" } } : {};
    const y = 40 + (nodes.length % 6) * 120, x = 80 + Math.floor(nodes.length / 6) * 240;
    setNodes((ns) => [...ns, { id, type: "block", position: { x, y }, data: { block: { id, type, label: META[type].label, params } } }]);
    setSel(id); setDirty(true);
  };
  const delSel = () => { if (!sel) return; setNodes((ns) => ns.filter((n) => n.id !== sel)); setEdges((es) => es.filter((e) => e.source !== sel && e.target !== sel)); setSel(null); setDirty(true); };

  const validate = async () => {
    const g = current(); if (!g) return null;
    try { const v = await post<Validation>(`${base}/flows/validate`, { graph: g }); setVal(v); return v; }
    catch (e) { setMsg({ kind: "err", text: (e as Error).message }); return null; }
  };
  const save = async () => {
    const g = current(); if (!g) return;
    try {
      if (flowId) await api(`${base}/flows/${flowId}`, { method: "PATCH", body: JSON.stringify({ name: g.name, graph: g }) });
      else {
        const f = await post<{ id: string }>(`${base}/flows`, { name: g.name, graph: g, run_id: runId });
        setFlowId(f.id); setSp((p) => { p.set("flux", f.id); return p; }, { replace: true });
      }
      setDirty(false); setMsg({ kind: "ok", text: "Graphe enregistré ✓" });
      const d = await api<AutoResp>(`${base}/runs/${runId}/flow/auto`); setData(d);
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const regenerate = () => {
    if (!data) return;
    const g = data.graph; setGraph(g); const f = toFlow(g); setNodes(f.nodes); setEdges(f.edges); setVal(data.validation);
    setFlowId(""); setSp((p) => { p.delete("flux"); return p; }, { replace: true }); setDirty(true);
    setMsg({ kind: "ok", text: `Graphe généré depuis la gamme : ${g.blocks.filter((b) => b.type === "operation").length} opérations, ${g.blocks.filter((b) => b.type === "split").length} séparation(s), ${g.blocks.filter((b) => b.type === "join").length} assemblage(s).` });
  };
  const openFlow = async (id: string) => {
    if (!id) { regenerate(); return; }
    try {
      const f = await api<{ id: string; name: string; graph: Graph }>(`${base}/flows/${id}`);
      const g = { ...f.graph, name: f.name }; setGraph(g); const fl = toFlow(g); setNodes(fl.nodes); setEdges(fl.edges);
      setFlowId(id); setSp((p) => { p.set("flux", id); return p; }, { replace: true }); setDirty(false); setVal(null);
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const pollRef = useRef<number>();
  const openSim = async (id: string) => {
    try {
      const s = await api<FlowSim>(`${base}/simulations/${id}`);
      setSim(s); setT(0);
      if (s.status === "queued" || s.status === "running") { window.clearTimeout(pollRef.current); pollRef.current = window.setTimeout(() => openSim(id), 1800); }
      else { setBusy(false); if (s.status === "done") { setSp((p) => { p.set("sim", id); return p; }, { replace: true }); } }
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); setBusy(false); }
  };
  useEffect(() => () => window.clearTimeout(pollRef.current), []);
  const run = async () => {
    const v = await validate(); if (!v || !v.ok) { setMsg({ kind: "err", text: "Corrigez les erreurs du graphe avant de l'exécuter." }); return; }
    setBusy(true); setMsg(null);
    try { const s = await post<FlowSim>(`${base}/runs/${runId}/flow/simulate`, { graph: current(), replications: reps, flow_id: flowId || null }); setSim(s); openSim(s.id); }
    catch (e) { setMsg({ kind: "err", text: (e as Error).message }); setBusy(false); }
  };

  // ---------------------------------------------------------------- résultats + animation
  const res = sim?.status === "done" ? sim.results?.result ?? null : null;
  const until = res?.trace?.until ?? res?.shift_minutes ?? 480;
  const cursor = useMemo(() => (res?.trace ? new FlowCursor(res.trace.events, res.trace.blocks.length, res.trace.stations.length) : null), [res]);
  const [live, setLive] = useState<{ counts: number[]; st: number[] } | null>(null);
  useEffect(() => { if (!cursor) { setLive(null); return; } cursor.seek(t); setLive({ counts: [...cursor.counts], st: [...cursor.st] }); }, [cursor, t]);
  useEffect(() => {
    if (!playing || !cursor) return;
    let raf = 0, last = performance.now();
    const tick = (now: number) => { const dt = Math.min(0.25, (now - last) / 1000); last = now;
      setT((x) => { const nx = x + (dt * speed) / 60; if (nx >= until) { setPlaying(false); return until; } return nx; }); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf);
  }, [playing, speed, cursor, until]);
  // badges des nœuds : statistiques, jetons présents, erreurs
  useEffect(() => {
    const bad = new Set([...(val?.errors ?? []).flatMap((e) => e.blocks)]);
    const stats = new Map((res?.blocks ?? []).map((b) => [b.id, b]));
    const idx = new Map((res?.trace?.blocks ?? []).map((b, i) => [b, i]));
    setNodes((ns) => ns.map((n) => {
      const i = idx.get(n.id);
      const d: NodeData = { ...n.data, stat: stats.get(n.id), live: i != null && live ? Math.max(0, live.counts[i]) : undefined, bad: bad.has(n.id), bottleneck: res?.kpis.bottleneck === n.id };
      return d.stat === n.data.stat && d.live === n.data.live && d.bad === n.data.bad && d.bottleneck === n.data.bottleneck ? n : { ...n, data: d };
    }));
  }, [val, res, live, setNodes]);
  const model = sim?.layout?.model ?? data?.model ?? null;
  const frame: Frame | null = useMemo(() => (model && res?.trace && live ? {
    t, stations: model.stations.map((s) => { const k = res.trace!.stations.indexOf(s.id); return k >= 0 ? live.st[k] : 1; }),
    bundles: [], actors: [], done: 0, wip: 0, carriers: [],
  } : null), [model, res, live, t]);

  if (!data || !graph) return <div className="page">{msg ? <p className="notice err">{msg.text}</p> : <p className="muted">Génération du graphe depuis la gamme…</p>}</div>;
  const g = graph;
  const setG = (patch: Partial<Graph>) => { setGraph({ ...g, ...patch }); setDirty(true); };
  const rk = sim?.results && res?.replications?.kpis;
  const stationIds = (model?.stations ?? []).map((s) => s.id);
  const selStation = selected && (selected.type === "operation" || selected.type === "inspect") ? String(selected.params.station ?? "") || null : null;

  return (
    <div className="page pf-page">
      <div className="page-head">
        <div><h1>Logique par blocs (Process Flow)</h1>
          <p className="muted">{data.problem_name || "Gamme"} · <Link to={`/calculs/${runId}`}>calcul</Link> · <Link to={`/simulation/${runId}`}>simulation 3D</Link> · les jetons (paquets, composants) circulent de bloc en bloc ; les opérations liées à un poste animent le plan.</p></div>
        <div className="actions">
          <label className="small">Graphe <select value={flowId} onChange={(e) => openFlow(e.target.value)}>
            <option value="">Généré depuis la gamme</option>{data.flows.map((f) => <option key={f.id} value={f.id}>{f.name} ({fmt.date(f.updated_at)})</option>)}</select></label>
        </div>
      </div>
      {msg && <p className={`notice ${msg.kind === "ok" ? "ok" : "err"}`}>{msg.text}</p>}
      <div className="pf-toolbar row">
        <input aria-label="Nom du graphe" value={g.name} onChange={(e) => setG({ name: e.target.value })} />
        <button className="btn small" onClick={regenerate}>↻ Générer depuis la gamme</button>
        <button className="btn small" onClick={validate}>Valider</button>
        {writable && <button className="btn small" onClick={save}>{dirty ? "Enregistrer" : "Enregistré"}</button>}
        <label className="small">Réplications <input type="number" min={1} max={20} value={reps} onChange={(e) => setReps(Math.max(1, Math.min(20, +e.target.value)))} style={{ width: "4rem" }} /></label>
        {writable && <button className="btn small primary" disabled={busy} onClick={run}>{busy ? "Exécution…" : "▶ Exécuter"}</button>}
      </div>
      {val && (val.errors.length || val.warnings.length) ? <ul className="pf-issues small">
        {val.errors.map((e, i) => <li key={`e${i}`} className="error" onClick={() => e.blocks[0] && setSel(e.blocks[0])}>✕ {e.msg}{e.blocks.length ? ` (${e.blocks.length} bloc${e.blocks.length > 1 ? "s" : ""})` : ""}</li>)}
        {val.warnings.map((e, i) => <li key={`w${i}`} className="warning" onClick={() => e.blocks[0] && setSel(e.blocks[0])}>⚠ {e.msg}</li>)}
      </ul> : val?.ok ? <p className="small ok-t">✓ Graphe valide : pas de cycle non contrôlé ni de branche orpheline.</p> : null}

      <div className="pf-grid">
        <aside className="card pf-palette">
          <h3>Blocs</h3>
          {TYPES.map((k) => <button key={k} className="pf-pal" title={META[k].hint} disabled={!writable} onClick={() => addBlock(k)}>
            <i style={{ background: META[k].color }}>{META[k].icon}</i>{META[k].label}</button>)}
          <h3>Ressources</h3>
          {g.resources.map((r, i) => <div key={i} className="row small pf-res">
            <input aria-label="Nom" value={r.name} onChange={(e) => setG({ resources: g.resources.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
            <select aria-label="Type" value={r.kind} onChange={(e) => setG({ resources: g.resources.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)) })}>
              <option value="operator">opérateur</option><option value="machine">machine</option><option value="chariot">chariot</option></select>
            <input aria-label="Nombre" type="number" min={1} value={r.capacity} onChange={(e) => setG({ resources: g.resources.map((x, j) => (j === i ? { ...x, capacity: +e.target.value } : x)) })} />
            <button className="link" onClick={() => setG({ resources: g.resources.filter((_, j) => j !== i) })} aria-label="Supprimer">✕</button></div>)}
          <button className="link small" onClick={() => setG({ resources: [...g.resources, { name: `Chariots`, kind: "chariot", capacity: 2 }] })}>+ Ressource</button>
          <h3>Journée</h3>
          <label className="small">Durée (min)<input type="number" min={30} max={960} value={g.shift?.minutes ?? 480} onChange={(e) => setG({ shift: { minutes: +e.target.value, breaks: g.shift?.breaks ?? [] } })} /></label>
          <label className="small">Variabilité des temps (%)<input type="number" min={0} max={100} value={Math.round((g.settings?.dist?.cv ?? 0.1) * 100)} onChange={(e) => setG({ settings: { ...g.settings, dist: { kind: "normal", cv: +e.target.value / 100 } } })} /></label>
          <label className="small">Efficience (%)<input type="number" min={10} max={250} value={Math.round((g.settings?.efficiency ?? 1) * 100)} onChange={(e) => setG({ settings: { ...g.settings, efficiency: +e.target.value / 100 } })} /></label>
        </aside>
        <section className="card pf-canvas">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type === "position" && x.dragging === false)) setDirty(true); }}
            onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === "remove")) setDirty(true); }} onConnect={onConnect}
            onNodeClick={(_, n) => setSel(n.id)} onPaneClick={() => setSel(null)} fitView minZoom={0.1} deleteKeyCode={writable ? ["Delete", "Backspace"] : null}
            nodesDraggable={writable} nodesConnectable={writable}>
            <Background gap={20} /><Controls /><MiniMap pannable zoomable nodeColor={(n) => META[(n.data as NodeData).block.type].color} />
          </ReactFlow>
        </section>
        <aside className="card pf-props">
          {selected ? <BlockProps b={selected} stations={stationIds} resources={g.resources.map((r) => r.name)} writable={writable}
            upd={(p) => updBlock(selected.id, p)} del={delSel} stat={res?.blocks.find((x) => x.id === selected.id)} />
            : <p className="muted small">Touchez un bloc pour régler ses paramètres. Reliez une sortie (à droite) à l'entrée d'un autre bloc (à gauche). Suppr efface le bloc ou le lien choisi.</p>}
        </aside>
      </div>

      {sim && (sim.status === "queued" || sim.status === "running") && <p className="notice warn">Exécution en cours… le serveur gratuit peut mettre une minute à se réveiller.</p>}
      {sim?.status === "failed" && <p className="notice err">Échec : {sim.error}</p>}
      {res && <section className="card">
        <div className="kpis">
          <div className="kpi"><span>Produits finis</span><b>{rk ? ciTxt(rk.pieces, 0) : fmt.n(res.kpis.pieces, 0)}</b><small>{fmt.n(res.kpis.per_hour, 1)} pcs/h · {res.replications?.n ?? 1} réplication(s)</small></div>
          <div className="kpi"><span>Temps de traversée</span><b>{rk ? ciTxt(rk.lead_time_avg, 0) : fmt.n(res.kpis.lead_time_avg, 0)} min</b><small>de la coupe à la sortie</small></div>
          <div className="kpi"><span>Encours moyen</span><b>{rk ? ciTxt(rk.wip_avg, 0) : fmt.n(res.kpis.wip_avg, 0)} pcs</b><small>max {fmt.n(res.kpis.wip_max, 0)}</small></div>
          <div className="kpi warn"><span>Goulot</span><b>{res.blocks.find((b) => b.id === res.kpis.bottleneck)?.label ?? "—"}</b><small>bloc d'opération le plus occupé</small></div>
          <div className="kpi"><span>Conservation</span><b>{res.conservation.ok ? "✓" : "✕"}</b><small>{fmt.n(res.conservation.launched, 0)} lancées = {fmt.n(res.conservation.done, 0)} finies + {fmt.n(res.conservation.in_system, 0)} en cours</small></div>
        </div>
        <div className="sim-timeline">
          <button className="btn small" onClick={() => setT(0)}>⏮</button>
          <button className="btn small primary" onClick={() => { if (t >= until) setT(0); setPlaying(!playing); }}>{playing ? "⏸ Pause" : "▶ Lecture"}</button>
          <select aria-label="Vitesse" value={speed} onChange={(e) => setSpeed(+e.target.value)}>{[10, 30, 60, 120, 300, 600].map((s) => <option key={s} value={s}>x{s}</option>)}</select>
          <input className="sim-range" type="range" min={0} max={until} step={0.1} value={Math.min(t, until)} onChange={(e) => setT(+e.target.value)} aria-label="Temps simulé" />
          <b className="sim-clock">{fmtClock(t)}</b><span className="small muted">● = jetons présents dans le bloc</span>
          {res.trace?.truncated && <span className="badge warn">animation jusqu'à {fmtClock(until)}</span>}
        </div>
        {model && <div className="pf-plan"><h4>Plan : postes liés aux blocs d'opération</h4>
          <Legend keys={STATION_STATES.slice(0, 3)} labels={STATE_LABEL} colors={STATE_COLOR} />
          <ErrorBoundary label="Plan indisponible"><SimCanvas2D model={model} plan={data.workshop_plan} frame={frame} selected={selStation}
            onSelect={(sid) => { const n = nodes.find((x) => String(x.data.block.params.station ?? "") === sid); if (n) setSel(n.id); }} /></ErrorBoundary></div>}
        <div className="table-wrap"><table className="small">
          <thead><tr><th>Bloc</th><th>Type</th><th>Entrés</th><th>Sortis</th><th>Encours moy. / max</th><th>Occupation</th><th>Retouches</th></tr></thead>
          <tbody>{res.blocks.map((b) => <tr key={b.id} className={b.id === res.kpis.bottleneck ? "warn" : ""} onClick={() => setSel(b.id)}>
            <td>{b.label}</td><td>{META[b.type as BType]?.label ?? b.type}</td><td>{b.entered}</td><td>{b.exited}</td><td>{fmt.n(b.wip_avg, 1)} / {b.wip_max}</td>
            <td>{b.utilization_pct != null ? `${fmt.n(b.utilization_pct, 1)} %` : "—"}</td><td>{b.defects ?? ""}</td></tr>)}</tbody></table></div>
        {res.resources.length > 0 && <p className="small muted">Ressources : {res.resources.map((r) => `${r.name} ${fmt.n(r.utilization_pct, 0)} % (×${r.capacity})`).join(" · ")}</p>}
      </section>}
      {data.simulations.length > 0 && <p className="small muted">Exécutions : {data.simulations.map((s) => <button key={s.id} className={`link ${sim?.id === s.id ? "on" : ""}`} onClick={() => openSim(s.id)}>{s.name} ({fmt.date(s.created_at)})</button>)}</p>}
    </div>
  );
}

const ciTxt = (v: CI | undefined, d = 1) => (!v || v.mean == null ? "—" : (v.n ?? 1) > 1 && v.lo != null ? `${fmt.n(Number(v.mean), d)} ± ${fmt.n((Number(v.hi) - Number(v.lo)) / 2, d)}` : fmt.n(Number(v.mean), d));

function BlockProps({ b, stations, resources, writable, upd, del, stat }: {
  b: Block; stations: string[]; resources: string[]; writable: boolean; upd: (p: Partial<Block> & { params?: Record<string, any> }) => void; del: () => void; stat?: BlockRes;
}) {
  const p = b.params;
  const num = (k: string, label: string, step = 1, min = 0) => <label>{label}<input type="number" step={step} min={min} value={p[k] ?? ""} onChange={(e) => upd({ params: { [k]: e.target.value === "" ? undefined : +e.target.value } })} /></label>;
  const list = (k: string, label: string) => <label>{label}<input value={(p[k] ?? []).join(", ")} onChange={(e) => upd({ params: { [k]: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} /></label>;
  return (
    <fieldset disabled={!writable} className="plain pf-form">
      <div className="card-head"><h3 style={{ color: META[b.type].color }}>{META[b.type].icon} {META[b.type].label}</h3>{writable && <button className="btn small danger" onClick={del}>Supprimer</button>}</div>
      <p className="muted small">{META[b.type].hint}</p>
      <label>Nom<input value={b.label} maxLength={80} onChange={(e) => upd({ label: e.target.value })} /></label>
      {b.type === "source" && <>
        {num("bundle_size", "Pièces par paquet", 1, 1)}{num("interval_min", "Intervalle (min, 0 = tiré)", 0.5)}{num("wip_cap", "Produits en cours max (0 = illimité)")}
        <p className="small muted">Lots (modèle ; taille ; couleur ; quantité, 0 = illimité) :</p>
        {(p.lots ?? []).map((l: any, i: number) => <div key={i} className="row small pf-lot">
          {(["style", "size", "color"] as const).map((k) => <input key={k} aria-label={k} value={l[k] ?? ""} onChange={(e) => upd({ params: { lots: p.lots.map((x: any, j: number) => (j === i ? { ...x, [k]: e.target.value } : x)) } })} />)}
          <input aria-label="qty" type="number" value={l.qty ?? 0} onChange={(e) => upd({ params: { lots: p.lots.map((x: any, j: number) => (j === i ? { ...x, qty: +e.target.value } : x)) } })} />
          <button className="link" onClick={() => upd({ params: { lots: p.lots.filter((_: any, j: number) => j !== i) } })}>✕</button></div>)}
        <button className="link small" onClick={() => upd({ params: { lots: [...(p.lots ?? []), { style: "Modèle", size: "M", color: "", qty: 100 }] } })}>+ Lot</button>
      </>}
      {(b.type === "operation" || b.type === "inspect") && <>
        {num("minutes", "Temps par pièce (min)", 0.01)}{num("servers", "Serveurs (opératrices en parallèle)", 1, 1)}{num("queue_capacity", "File devant (0 = illimitée)")}{num("setup_min", "Mise en route au changement de lot (min)", 0.5)}
        {b.type === "inspect" && num("defect_pct", "Défauts (%) → sortie retouche", 0.5)}
        <label>Ressource prise pendant l'opération<select value={p.resource ?? ""} onChange={(e) => upd({ params: { resource: e.target.value || undefined } })}><option value="">—</option>{resources.map((r) => <option key={r}>{r}</option>)}</select></label>
        <label>Poste du plan (animation)<select value={p.station ?? ""} onChange={(e) => upd({ params: { station: e.target.value || undefined } })}><option value="">—</option>{stations.map((s) => <option key={s} value={s}>Poste {s}</option>)}</select></label>
        {p.operations?.length ? <p className="small muted">Opérations : {p.operations.join(", ")}{p.operators?.length ? ` · ${p.operators.join(", ")}` : ""}</p> : null}
      </>}
      {b.type === "queue" && num("capacity", "Capacité (0 = illimitée)")}
      {b.type === "delay" && num("minutes", "Durée (min)", 0.5)}
      {(b.type === "decision" || b.type === "split") && num("outs", "Nombre de sorties", 1, 2)}
      {b.type === "decision" && <>
        <label>Règle<select value={p.mode ?? "prob"} onChange={(e) => upd({ params: { mode: e.target.value } })}><option value="prob">Probabilités</option><option value="attr">Selon un attribut</option><option value="cond">Condition</option></select></label>
        {(p.mode ?? "prob") === "prob" && <label>Probabilités par sortie<input value={(p.probs ?? []).join(", ")} onChange={(e) => upd({ params: { probs: e.target.value.split(",").map((x) => Number(x.trim().replace("%", "")) || 0) } })} /></label>}
        {p.mode === "attr" && <><label>Attribut<input value={p.attr ?? ""} placeholder="taille, couleur, modele…" onChange={(e) => upd({ params: { attr: e.target.value } })} /></label>
          {Array.from({ length: Math.max(2, p.outs ?? 2) }, (_, i) => <label key={i}>Valeurs → sortie {i + 1}<input value={(p.routes?.[i] ?? []).join(", ")} onChange={(e) => { const r = [...(p.routes ?? [])]; r[i] = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); upd({ params: { routes: r } }); }} /></label>)}</>}
        {p.mode === "cond" && <div className="row small"><input aria-label="Attribut" placeholder="attribut" value={p.attr ?? ""} onChange={(e) => upd({ params: { attr: e.target.value } })} />
          <select aria-label="Opérateur" value={p.op ?? "=="} onChange={(e) => upd({ params: { op: e.target.value } })}>{["==", "!=", ">", "<", ">=", "<="].map((o) => <option key={o}>{o}</option>)}</select>
          <input aria-label="Valeur" placeholder="valeur" value={p.value ?? ""} onChange={(e) => upd({ params: { value: e.target.value } })} /></div>}
      </>}
      {b.type === "split" && list("components", "Composants (un par sortie)")}
      {b.type === "join" && <label>Appariement<select value={p.match ?? "product"} onChange={(e) => upd({ params: { match: e.target.value } })}><option value="product">même produit (paquet d'origine)</option><option value="lot">même lot</option><option value="size">même taille</option></select></label>}
      {b.type === "batch" && <>{num("size", "Jetons par groupe", 1, 1)}<label>Même attribut<input value={p.key ?? ""} placeholder="(aucun)" onChange={(e) => upd({ params: { key: e.target.value || undefined } })} /></label></>}
      {(b.type === "acquire" || b.type === "release") && <><label>Ressource<select value={p.resource ?? ""} onChange={(e) => upd({ params: { resource: e.target.value } })}>{resources.map((r) => <option key={r}>{r}</option>)}</select></label>{num("qty", "Quantité", 1, 1)}</>}
      {b.type === "attribute" && <>
        <label>Fixer (clé = valeur, …)<input value={Object.entries(p.set ?? {}).map(([k, v]) => `${k}=${v}`).join(", ")} onChange={(e) => upd({ params: { set: Object.fromEntries(e.target.value.split(",").map((x) => x.split("=").map((y) => y.trim())).filter((x) => x[0])) } })} /></label>
        <label>Ou tirer au hasard l'attribut<input value={p.attr ?? ""} placeholder="ex. taille" onChange={(e) => upd({ params: { attr: e.target.value || undefined } })} /></label>
        <label>Valeurs et poids (S:30, M:50…)<input value={(p.values ?? []).map((v: any) => `${v[0]}:${v[1]}`).join(", ")} onChange={(e) => upd({ params: { values: e.target.value.split(",").map((x) => x.split(":").map((y) => y.trim())).filter((x) => x[0]).map((x) => [x[0], Number(x[1] ?? 1)]) } })} /></label>
      </>}
      {stat && <p className="small">Résultat : {stat.entered} entrés, {stat.exited} sortis, encours moy. {fmt.n(stat.wip_avg, 1)} (max {stat.wip_max}){stat.utilization_pct != null ? `, occupation ${fmt.n(stat.utilization_pct, 1)} %` : ""}{stat.lead_avg != null ? `, traversée ${fmt.n(stat.lead_avg, 0)} min` : ""}{stat.waiting ? `, ${stat.waiting} en attente d'assemblage` : ""}.</p>}
    </fieldset>
  );
}

export default function FlowEditor() {
  return <ReactFlowProvider><Editor /></ReactFlowProvider>;
}
