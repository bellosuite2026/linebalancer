import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { Line, Precheck, Problem, ProblemRow } from "../lib/types";
import {
  MACHINES, check, emptyDraft, emptyOp, emptyWk, emptyWs, fromProblem, nextId, parsePasted, pasteOps, pasteWk, pasteWs, toProblem,
  type Draft, type OpRow, type WkRow, type WsRow,
} from "../lib/gamme";
import SuggestInput from "../components/SuggestInput";
import { GARMENTS, aggregateHistory, loadCatalog, loadHistory, suggest, type Catalog, type HistoryEntry, type Suggestion } from "../lib/suggest";

type Tab = "ops" | "ws" | "wk";
const SEVERITY: Record<string, string> = { error: "Bloquant", warning: "Attention", info: "Info" };
const draftKey = (org: string) => `tlb.gamme.brouillon.${org}`;

interface Col<R> { key: keyof R & string; label: string; width?: string; type?: "text" | "number" | "check"; list?: string; placeholder?: string; title?: string }

const OP_COLS: Col<OpRow>[] = [
  { key: "id", label: "Op_ID", width: "6.5rem" },
  { key: "name", label: "Désignation", width: "minmax(14rem,2fr)", placeholder: "ex. Assembler côtés" },
  { key: "duration", label: "SAM (min)", width: "6rem", type: "number" },
  { key: "predecessors", label: "Prédécesseurs", width: "9rem", placeholder: "OP010, OP020", title: "Opérations à terminer avant celle-ci, séparées par des virgules" },
  { key: "machine_type", label: "Machine", width: "10rem", list: "dl-machines" },
  { key: "skills", label: "Compétences", width: "minmax(9rem,1fr)", list: "dl-skills", placeholder: "couture_droite, ourlet" },
  { key: "section", label: "Section", width: "7rem", list: "dl-sections" },
  { key: "optional", label: "Opt.", width: "3rem", type: "check", title: "Opération optionnelle" },
];
const WS_COLS: Col<WsRow>[] = [
  { key: "id", label: "Poste_ID", width: "6.5rem" },
  { key: "name", label: "Nom", width: "minmax(12rem,2fr)", placeholder: "ex. Piqueuse plate 1" },
  { key: "machine_type", label: "Machine", width: "11rem", list: "dl-machines" },
  { key: "max_workers", label: "Ouvriers max", width: "6.5rem", type: "number" },
  { key: "section", label: "Section", width: "8rem", list: "dl-sections" },
  { key: "available", label: "Dispo.", width: "3.5rem", type: "check" },
];
const WK_COLS: Col<WkRow>[] = [
  { key: "id", label: "Ouvrier_ID", width: "6.5rem" },
  { key: "name", label: "Nom", width: "minmax(10rem,1fr)" },
  { key: "skills", label: "Compétences", width: "minmax(14rem,2fr)", list: "dl-skills", placeholder: "couture_droite, surjet_5_fils" },
  { key: "efficiency", label: "Efficacité", width: "6rem", type: "number", title: "1 = 100 % ; 0,9 = 90 %" },
  { key: "assigned_station", label: "Poste imposé", width: "7rem", list: "dl-ws" },
  { key: "available", label: "Dispo.", width: "3.5rem", type: "check" },
];

export default function GammeEditor() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [d, setD] = useState<Draft>(() => {
    try { const s = localStorage.getItem(draftKey(org.id)); if (s) return JSON.parse(s) as Draft; } catch { /* brouillon illisible */ }
    return emptyDraft();
  });
  const [tab, setTab] = useState<Tab>("ops");
  const [lines, setLines] = useState<Line[]>([]);
  const [saved, setSaved] = useState<ProblemRow[]>([]);
  const [precheck, setPrecheck] = useState<Precheck | null>(null);
  const [paste, setPaste] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  useEffect(() => { loadCatalog().then(setCatalog); }, []);
  useEffect(() => { loadHistory(org.id).then(setHistory); }, [org.id]);

  useEffect(() => {
    api<Line[]>(`/v1/orgs/${org.id}/lines`).then(setLines).catch(() => {});
    api<ProblemRow[]>(`/v1/orgs/${org.id}/problems?limit=100`).then(setSaved).catch(() => {});
  }, [org.id]);

  const loadSaved = (id: string) => {
    setBusy("Chargement…"); setMsg(null);
    api<ProblemRow>(`/v1/orgs/${org.id}/problems/${id}`)
      .then((r) => { setD(fromProblem(r.payload!, r.line_id || "")); setPrecheck(null); setSavedId(null); })
      .catch((e) => setMsg({ kind: "err", text: e.message })).finally(() => setBusy(""));
  };

  // Ouverture d'une gamme enregistrée (?depuis=id) ou d'un import (sessionStorage)
  useEffect(() => {
    const from = params.get("depuis");
    const imported = sessionStorage.getItem("tlb.gamme.import");
    if (imported) {
      sessionStorage.removeItem("tlb.gamme.import");
      try { const { problem, lineId } = JSON.parse(imported); setD(fromProblem(problem, lineId || "")); setMsg({ kind: "ok", text: "Gamme importée : vous pouvez la corriger avant le calcul." }); } catch { /* ignore */ }
    } else if (from) {
      loadSaved(from);
      setParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { localStorage.setItem(draftKey(org.id), JSON.stringify(d)); }, [d, org.id]);

  const update = (f: (x: Draft) => Draft) => { setD(f); setPrecheck(null); setSavedId(null); };
  const chk = useMemo(() => check(d), [d]);

  const sam = d.ops.reduce((s, o) => s + (Number(o.duration.replace(",", ".")) || 0), 0);
  const cyc = Number(d.cycle.replace(",", ".")) || 0;
  const machines = useMemo(() => [...new Set([...MACHINES, ...d.ops.map((o) => o.machine_type), ...d.ws.map((w) => w.machine_type)].filter(Boolean))], [d]);
  const skills = useMemo(() => [...new Set([...d.ops, ...d.wk].flatMap((r) => r.skills.split(/[;,]/).map((s) => s.trim())).filter(Boolean))].sort(), [d]);
  const sections = useMemo(() => [...new Set([...d.ops, ...d.ws].map((r) => r.section.trim()).filter(Boolean))], [d]);

  const getSuggestions = useCallback((q: string, rowIndex: number) => suggest(q, {
    history, catalog, garment: d.garment,
    local: aggregateHistory(toProblem({ ...d, ops: d.ops.filter((_, j) => j !== rowIndex) }).operations),
  }), [history, catalog, d]);

  const applySuggestion = (i: number, s: Suggestion) => update((x) => ({
    ...x, ops: x.ops.map((o, j) => {
      if (j !== i) return o;
      const fillTime = !o.duration.trim() || o.est;
      return {
        ...o, name: s.name,
        duration: fillTime && s.duration ? String(s.duration) : o.duration,
        est: fillTime && s.duration ? s.kind === "catalogue" : o.est,
        machine_type: o.machine_type.trim() || s.machine_type,
        section: o.section.trim() || s.section,
        skills: o.skills.trim() || s.skills,
      };
    }),
  }));

  const verify = async () => {
    setMsg(null);
    if (chk.errors.length) { setMsg({ kind: "err", text: "Corrigez d'abord les erreurs signalées." }); return; }
    setBusy("Vérification…");
    try { setPrecheck(await post<Precheck>("/v1/precheck", toProblem(d))); }
    catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };

  const save = async (thenRun: boolean) => {
    setMsg(null);
    if (chk.errors.length) { setMsg({ kind: "err", text: "Corrigez d'abord les erreurs signalées." }); return; }
    setBusy("Enregistrement…");
    try {
      const row = savedId ? { id: savedId } : await post<ProblemRow>(`/v1/orgs/${org.id}/problems`, { problem: toProblem(d), line_id: d.lineId || null });
      setSavedId(row.id);
      loadHistory(org.id, true).then(setHistory);
      if (thenRun) { nav(`/calcul?gamme=${row.id}`); return; }
      setMsg({ kind: "ok", text: "Gamme enregistrée. Elle est disponible dans « Nouveau calcul »." });
      api<ProblemRow[]>(`/v1/orgs/${org.id}/problems?limit=100`).then(setSaved).catch(() => {});
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };

  const importFiles = async (fs: FileList | null) => {
    if (!fs?.length) return;
    const fd = new FormData();
    const pick = (re: RegExp) => [...fs].find((f) => re.test(f.name.toLowerCase()));
    const samF = pick(/sam|gamme|op/) ?? fs[0];
    fd.append("sam", samF);
    const wsF = pick(/poste|machine|workstation/); if (wsF && wsF !== samF) fd.append("workstations", wsF);
    const wkF = pick(/ouvrier|worker|operat|personnel/); if (wkF && wkF !== samF) fd.append("workers", wkF);
    fd.append("target_cycle_time", d.cycle && cyc > 0 ? String(cyc) : "1");
    fd.append("name", d.name || samF.name.replace(/\.\w+$/, ""));
    setBusy("Import…"); setMsg(null);
    try {
      const out = await api<{ problem: Problem }>("/v1/import/problem", { method: "POST", body: fd });
      const nd = fromProblem(out.problem, d.lineId);
      update(() => ({ ...nd, cycle: d.cycle, ws: wsF ? nd.ws : d.ws, wk: wkF ? nd.wk : d.wk }));
      setMsg({ kind: "ok", text: `${nd.ops.length} opérations importées${wsF ? `, ${nd.ws.length} postes` : ""}${wkF ? `, ${nd.wk.length} ouvriers` : ""}.` });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };

  const applyPaste = () => {
    const rows = parsePasted(paste ?? "");
    if (!rows.length) { setPaste(null); return; }
    update((x) => {
      const clean = <R extends { id: string }>(a: R[]) => a.filter((r) => r.id.trim() || Object.values(r).some((v) => typeof v === "string" && v.trim() && v !== "1"));
      if (tab === "ops") return { ...x, ops: [...clean(x.ops), ...pasteOps(rows)] };
      if (tab === "ws") return { ...x, ws: [...clean(x.ws), ...pasteWs(rows)] };
      return { ...x, wk: [...clean(x.wk), ...pasteWk(rows)] };
    });
    setPaste(null);
  };

  const reset = () => {
    if (!confirm("Effacer la gamme en cours d'édition ?")) return;
    update(() => emptyDraft()); setMsg(null);
  };

  if (!canWrite(org)) return <div className="page"><p className="notice warn">Votre rôle (lecteur) ne permet pas de modifier une gamme.</p></div>;

  const counts = { ops: d.ops.filter((o) => o.id.trim()).length, ws: d.ws.filter((o) => o.id.trim()).length, wk: d.wk.filter((o) => o.id.trim()).length };

  return (
    <div className="page wide">
      <div className="page-head">
        <div><h1>Gamme et ligne</h1><p className="muted">Saisissez ou corrigez les opérations, les postes et les ouvriers, puis lancez le calcul.</p></div>
        <div className="actions">
          <select value="" onChange={(e) => { if (e.target.value && confirm("Remplacer la gamme en cours d'édition ?")) loadSaved(e.target.value); }} disabled={!saved.length}>
            <option value="">Ouvrir une gamme enregistrée…</option>
            {saved.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.operations_count} op. · {fmt.date(s.created_at)}</option>)}
          </select>
          <label className="btn">Importer des fichiers
            <input type="file" multiple hidden accept=".xlsx,.xls,.csv,.json" onChange={(e) => { importFiles(e.target.files); e.target.value = ""; }} />
          </label>
          <button className="btn ghost" onClick={reset}>Nouvelle</button>
        </div>
      </div>

      {msg && <p className={`notice ${msg.kind}`}>{msg.text}</p>}

      <section className="card">
        <div className="form-grid">
          <label>Nom de la gamme<input value={d.name} placeholder="ex. Pantalon Théo – réf. 1203" onChange={(e) => update((x) => ({ ...x, name: e.target.value }))} /></label>
          <label>Ligne
            <select value={d.lineId} onChange={(e) => {
              const l = lines.find((x) => x.id === e.target.value);
              update((x) => ({ ...x, lineId: e.target.value, cycle: x.cycle || (l?.target_cycle_time ? String(l.target_cycle_time) : "") }));
            }}>
              <option value="">— Aucune —</option>
              {lines.map((l) => <option key={l.id} value={l.id}>{l.name}{l.product ? ` · ${l.product}` : ""}</option>)}
            </select>
          </label>
          <label>Type de vêtement
            <select value={d.garment ?? ""} onChange={(e) => update((x) => ({ ...x, garment: e.target.value }))}>
              {GARMENTS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
            <small className="muted">Oriente les propositions d'opérations.</small>
          </label>
          <label>Cadence cible (min / pièce)
            <input type="number" step="0.01" min="0" value={d.cycle} onChange={(e) => update((x) => ({ ...x, cycle: e.target.value }))} />
            <small className="muted">{cyc > 0 ? `Une pièce toutes les ${fmt.n(cyc)} min = ${fmt.n(60 / cyc, 0)} pièces/h, ${fmt.n(480 / cyc, 0)} par journée de 8 h.` : "Temps disponible ÷ quantité à produire."}</small>
          </label>
        </div>
        <div className="kpis">
          <div className="kpi"><span>Opérations</span><b>{counts.ops}</b></div>
          <div className="kpi"><span>Temps total SAM</span><b>{fmt.n(sam)} min</b></div>
          <div className="kpi"><span>Stations théoriques</span><b>{cyc > 0 && sam > 0 ? Math.ceil(sam / cyc) : "—"}</b><small>minimum</small></div>
          <div className="kpi"><span>Postes</span><b>{counts.ws || "—"}</b></div>
          <div className="kpi"><span>Ouvriers</span><b>{counts.wk || "—"}</b></div>
        </div>
      </section>

      <section className="card">
        <div className="tabs">
          <button className={tab === "ops" ? "on" : ""} onClick={() => setTab("ops")}>Opérations ({counts.ops})</button>
          <button className={tab === "ws" ? "on" : ""} onClick={() => setTab("ws")}>Postes / machines ({counts.ws})</button>
          <button className={tab === "wk" ? "on" : ""} onClick={() => setTab("wk")}>Ouvriers ({counts.wk})</button>
          <span className="spacer" />
          <button className="btn small ghost" onClick={() => setPaste("")}>Coller depuis Excel</button>
        </div>

        {paste !== null && (
          <div className="paste">
            <p className="small muted">Copiez des lignes dans Excel, dans l'ordre des colonnes ci-dessous ({(tab === "ops" ? OP_COLS : tab === "ws" ? WS_COLS : WK_COLS).map((c) => c.label).join(" · ")}), puis collez-les ici. Elles seront ajoutées à la fin du tableau.</p>
            <textarea rows={6} autoFocus value={paste} onChange={(e) => setPaste(e.target.value)} />
            <div className="actions"><button className="btn primary small" onClick={applyPaste}>Ajouter les lignes</button><button className="btn small ghost" onClick={() => setPaste(null)}>Annuler</button></div>
          </div>
        )}

        {tab === "ops" && <Grid prefix="op" cols={OP_COLS} rows={d.ops} cells={chk.cells}
          onChange={(rows) => update((x) => ({ ...x, ops: rows }))}
          make={(rows) => emptyOp(nextId(rows.map((r) => r.id), "OP", 3, 10))}
          custom={{
            name: (r, i, set, bad, addRow) => (
              <SuggestInput className={bad ? "bad" : ""} value={r.name} placeholder="Tapez : ourlet, poche, col…"
                onChange={(v) => set({ name: v })} onPick={(s) => applySuggestion(i, s)}
                getSuggestions={(q) => getSuggestions(q, i)} onEnterEmpty={addRow} />
            ),
            duration: (r, _i, set, bad) => (
              <input className={`${bad ? "bad" : ""} ${r.est ? "est" : ""}`} value={r.duration} inputMode="decimal"
                title={r.est ? "Temps estimé d'après le catalogue (valeur publiée) : à confirmer par chronométrage" : undefined}
                onChange={(e) => set({ duration: e.target.value, est: false })} />
            ),
          }}
          hint="Désignation : les propositions viennent de vos gammes puis du catalogue de temps publiés (temps en orange = estimé, à confirmer). Prédécesseurs : laissez vide si l'opération peut démarrer tout de suite. Plusieurs prédécesseurs : séparez-les par des virgules." />}
        {tab === "ws" && <Grid prefix="ws" cols={WS_COLS} rows={d.ws} cells={chk.cells}
          onChange={(rows) => update((x) => ({ ...x, ws: rows }))}
          make={(rows) => emptyWs(nextId(rows.map((r) => r.id), "WS", 2, 1))}
          hint="Facultatif : sans postes, le calcul répartit les opérations sans vérifier le parc machines. Un poste par machine physique." />}
        {tab === "wk" && <Grid prefix="wk" cols={WK_COLS} rows={d.wk} cells={chk.cells}
          onChange={(rows) => update((x) => ({ ...x, wk: rows }))}
          make={(rows) => emptyWk(nextId(rows.map((r) => r.id), "W", 3, 1))}
          hint="Facultatif : les compétences doivent reprendre les mots utilisés dans les opérations (ex. couture_droite)." />}

        <datalist id="dl-machines">{machines.map((m) => <option key={m} value={m} />)}</datalist>
        <datalist id="dl-skills">{skills.map((m) => <option key={m} value={m} />)}</datalist>
        <datalist id="dl-sections">{sections.map((m) => <option key={m} value={m} />)}</datalist>
        <datalist id="dl-ws">{d.ws.filter((w) => w.id).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</datalist>
      </section>

      {(chk.errors.length > 0 || chk.warnings.length > 0) && (
        <ul className="issues card">
          {chk.errors.slice(0, 12).map((e, i) => <li key={"e" + i} className="error"><b>À corriger</b> {e}</li>)}
          {chk.errors.length > 12 && <li className="error">… et {chk.errors.length - 12} autres.</li>}
          {chk.warnings.map((e, i) => <li key={"w" + i} className="warning"><b>Attention</b> {e}</li>)}
        </ul>
      )}

      {precheck && (
        <section className="card">
          <h3>Diagnostic</h3>
          {precheck.issues.length === 0 && precheck.validation_errors.length === 0 ? <p className="notice ok">Aucun problème détecté.</p> : (
            <ul className="issues">
              {precheck.validation_errors.map((v, i) => <li key={"v" + i} className="error"><b>Données</b> {v}</li>)}
              {precheck.issues.map((v, i) => <li key={i} className={v.severity}><b>{SEVERITY[v.severity] ?? v.severity}</b> {v.message}{v.suggestion && <em> → {v.suggestion}</em>}</li>)}
            </ul>
          )}
        </section>
      )}

      <div className="sticky-actions">
        <span className="muted small">{busy || (savedId ? "Enregistrée" : "Brouillon conservé sur cet ordinateur")}</span>
        <button className="btn" onClick={verify} disabled={!!busy}>Vérifier</button>
        <button className="btn" onClick={() => save(false)} disabled={!!busy || !!savedId}>Enregistrer</button>
        <button className="btn primary" onClick={() => save(true)} disabled={!!busy}>Enregistrer et calculer</button>
      </div>
      <p className="small muted">Vous préférez Excel ? <Link to="/aide/fichiers">Format des fichiers et modèles vides</Link>.</p>
    </div>
  );
}

type CellRenderer<R> = (row: R, i: number, set: (patch: Partial<R>) => void, bad: boolean, addRow: () => void) => ReactNode;

function Grid<R extends { id: string }>({ prefix, cols, rows, cells, onChange, make, hint, custom }: {
  prefix: string; cols: Col<R>[]; rows: R[]; cells: Set<string>; onChange: (rows: R[]) => void; make: (rows: R[]) => R; hint: string;
  custom?: Partial<Record<keyof R & string, CellRenderer<R>>>;
}) {
  const template = `2rem ${cols.map((c) => c.width ?? "1fr").join(" ")} 5.5rem`;
  const set = (i: number, key: keyof R, value: unknown) => onChange(rows.map((r, j) => (j === i ? { ...r, [key]: value } : r)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir; if (j < 0 || j >= rows.length) return;
    const a = [...rows]; [a[i], a[j]] = [a[j], a[i]]; onChange(a);
  };
  const add = (after?: number) => {
    const a = [...rows]; const row = make(rows);
    if (after === undefined) a.push(row); else a.splice(after + 1, 0, row);
    onChange(a);
  };
  return (
    <>
      <div className="grid-wrap">
        <div className="egrid" style={{ gridTemplateColumns: template }}>
          <div className="eh">#</div>
          {cols.map((c) => <div key={c.key} className="eh" title={c.title}>{c.label}</div>)}
          <div className="eh" />
          {rows.map((r, i) => (
            <div key={i} className="erow" style={{ display: "contents" }}>
              <div className="enum">{i + 1}</div>
              {cols.map((c) => {
                const v = r[c.key] as unknown;
                const bad = cells.has(`${prefix}:${i}:${c.key}`);
                const render = custom?.[c.key];
                if (render) return <div key={c.key} className="ecell">{render(r, i, (patch) => onChange(rows.map((x, j) => (j === i ? { ...x, ...patch } : x))), bad, () => { if (i === rows.length - 1) add(); })}</div>;
                return c.type === "check" ? (
                  <div key={c.key} className="ecell center-cell"><input type="checkbox" checked={!!v} onChange={(e) => set(i, c.key, e.target.checked)} /></div>
                ) : (
                  <div key={c.key} className="ecell">
                    <input className={bad ? "bad" : ""} value={String(v ?? "")} list={c.list} placeholder={c.placeholder}
                      inputMode={c.type === "number" ? "decimal" : undefined}
                      onChange={(e) => set(i, c.key, e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && i === rows.length - 1) { e.preventDefault(); add(); } }} />
                  </div>
                );
              })}
              <div className="ecell row-actions">
                <button title="Monter" onClick={() => move(i, -1)}>↑</button>
                <button title="Descendre" onClick={() => move(i, 1)}>↓</button>
                <button title="Insérer une ligne en dessous" onClick={() => add(i)}>+</button>
                <button title="Supprimer" onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="grid-foot">
        <button className="btn small" onClick={() => add()}>+ Ajouter une ligne</button>
        <span className="small muted">{hint}</span>
      </div>
    </>
  );
}
