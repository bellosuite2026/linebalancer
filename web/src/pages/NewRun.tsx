import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { Line, Precheck, Problem, ProblemRow, Run } from "../lib/types";

type Source = "files" | "saved";
const SEVERITY: Record<string, string> = { error: "Bloquant", warning: "Attention", info: "Info" };

export default function NewRun() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [lines, setLines] = useState<Line[]>([]);
  const [saved, setSaved] = useState<ProblemRow[]>([]);
  const [lineId, setLineId] = useState(params.get("ligne") || "");
  const [source, setSource] = useState<Source>("files");
  const [name, setName] = useState("");
  const [cycle, setCycle] = useState("");
  const [files, setFiles] = useState<{ sam?: File; workstations?: File; workers?: File }>({});
  const [savedId, setSavedId] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [problemId, setProblemId] = useState<string | null>(null);
  const [precheck, setPrecheck] = useState<Precheck | null>(null);
  const [kind, setKind] = useState<"balance" | "min_cycle">("balance");
  const [solver, setSolver] = useState<"rpw" | "cp_sat">("rpw");
  const [timeLimit, setTimeLimit] = useState(20);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Line[]>(`/v1/orgs/${org.id}/lines`).then((ls) => {
      setLines(ls);
      const l = ls.find((x) => x.id === lineId);
      if (l) { setName(l.product || l.name); if (l.target_cycle_time) setCycle(String(l.target_cycle_time)); }
    }).catch(() => {});
    api<ProblemRow[]>(`/v1/orgs/${org.id}/problems?limit=100`).then(setSaved).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org.id]);

  useEffect(() => {
    if (params.get("exemple") !== "1") return;
    (async () => {
      const get = async (f: string) => new File([await (await fetch(`/modeles/${f}`)).blob()], f, { type: "text/csv" });
      setFiles({ sam: await get("exemple_chemise_SAM.csv"), workstations: await get("exemple_chemise_postes.csv"),
        workers: await get("exemple_chemise_ouvriers.csv") });
      setName("Chemise homme (exemple)"); setCycle("1.2");
    })();
  }, [params]);

  const reset = () => { setProblem(null); setPrecheck(null); setProblemId(null); };

  const analyse = async (e: FormEvent) => {
    e.preventDefault(); setErr(""); reset();
    setBusy("Analyse de la gamme…");
    try {
      if (source === "files") {
        if (!files.sam) throw new Error("Le fichier de gamme SAM est obligatoire.");
        const fd = new FormData();
        fd.append("sam", files.sam);
        if (files.workstations) fd.append("workstations", files.workstations);
        if (files.workers) fd.append("workers", files.workers);
        fd.append("target_cycle_time", cycle);
        fd.append("name", name || files.sam.name.replace(/\.\w+$/, ""));
        const out = await api<{ problem: Problem; precheck: Precheck }>("/v1/import/problem", { method: "POST", body: fd });
        setProblem(out.problem); setPrecheck(out.precheck);
      } else {
        const row = await api<ProblemRow>(`/v1/orgs/${org.id}/problems/${savedId}`);
        const p = { ...row.payload!, target_cycle_time: Number(cycle) || row.target_cycle_time };
        setProblem(p); setProblemId(Number(cycle) && Number(cycle) !== row.target_cycle_time ? null : row.id);
        setPrecheck(await post<Precheck>("/v1/precheck", p));
      }
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  const launch = async () => {
    if (!problem) return;
    setErr(""); setBusy("Envoi du calcul…");
    try {
      const body = problemId ? { problem_id: problemId } : { problem, line_id: lineId || null };
      const run = await post<Run>(`/v1/orgs/${org.id}/runs`, { ...body, kind, solver, time_limit_seconds: timeLimit });
      nav(`/calculs/${run.id}`);
    } catch (e) { setErr((e as Error).message); setBusy(""); }
  };

  if (!canWrite(org)) return <div className="page"><p className="notice warn">Votre rôle (lecteur) ne permet pas de lancer un calcul.</p></div>;

  const errors = precheck?.issues.filter((i) => i.severity === "error") ?? [];
  const totalSam = problem?.operations.reduce((s, o) => s + o.duration, 0) ?? 0;

  return (
    <div className="page">
      <div className="page-head"><div><h1>Nouveau calcul</h1><p className="muted">1. Gamme et cadence · 2. Diagnostic · 3. Calcul</p></div></div>
      {err && <p className="notice err">{err}</p>}

      <form className="card" onSubmit={analyse}>
        <h3>1. Gamme et cadence</h3>
        <div className="form-grid">
          <label>Ligne
            <select value={lineId} onChange={(e) => {
              setLineId(e.target.value);
              const l = lines.find((x) => x.id === e.target.value);
              if (l?.target_cycle_time) setCycle(String(l.target_cycle_time));
            }}>
              <option value="">— Aucune —</option>
              {lines.map((l) => <option key={l.id} value={l.id}>{l.name}{l.product ? ` · ${l.product}` : ""}</option>)}
            </select>
          </label>
          <label>Cadence cible (min / pièce)
            <input type="number" step="0.01" min="0.01" required value={cycle} onChange={(e) => { setCycle(e.target.value); reset(); }} />
          </label>
        </div>

        <div className="tabs">
          <button type="button" className={source === "files" ? "on" : ""} onClick={() => { setSource("files"); reset(); }}>Importer des fichiers</button>
          <button type="button" className={source === "saved" ? "on" : ""} disabled={!saved.length} onClick={() => { setSource("saved"); reset(); }}>
            Gamme enregistrée {saved.length ? `(${saved.length})` : ""}
          </button>
        </div>

        {source === "files" ? (
          <>
            <label>Nom de la gamme<input placeholder="ex. Chemise homme MC – réf. 2041" value={name} onChange={(e) => setName(e.target.value)} /></label>
            <div className="files">
              <FileField label="Gamme SAM *" file={files.sam} onPick={(f) => { setFiles({ ...files, sam: f }); reset(); }} />
              <FileField label="Postes / machines" file={files.workstations} onPick={(f) => { setFiles({ ...files, workstations: f }); reset(); }} />
              <FileField label="Ouvriers / compétences" file={files.workers} onPick={(f) => { setFiles({ ...files, workers: f }); reset(); }} />
            </div>
            <p className="muted small">Excel (.xlsx), CSV ou JSON. Modèles :{" "}
              <a href="/modeles/modele_gamme_SAM.xlsx" download>gamme SAM</a> ·{" "}
              <a href="/modeles/modele_postes.xlsx" download>postes</a> ·{" "}
              <a href="/modeles/modele_ouvriers.xlsx" download>ouvriers</a> ·{" "}
              <Link to="/calcul?exemple=1">charger l'exemple chemise</Link>
            </p>
          </>
        ) : (
          <label>Gamme
            <select required value={savedId} onChange={(e) => { setSavedId(e.target.value); reset(); const r = saved.find((s) => s.id === e.target.value); if (r && !cycle) setCycle(String(r.target_cycle_time)); }}>
              <option value="">— Choisir —</option>
              {saved.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.operations_count} op. · {fmt.date(s.created_at)}</option>)}
            </select>
          </label>
        )}
        <button className="btn primary" disabled={!!busy}>{busy && !problem ? busy : "Analyser"}</button>
      </form>

      {problem && precheck && (
        <section className="card">
          <h3>2. Diagnostic</h3>
          <div className="kpis">
            <div className="kpi"><span>Opérations</span><b>{problem.operations.length}</b></div>
            <div className="kpi"><span>Temps total SAM</span><b>{fmt.n(totalSam)} min</b></div>
            <div className="kpi"><span>Stations théoriques</span><b>{Math.ceil(totalSam / problem.target_cycle_time)}</b><small>minimum</small></div>
            <div className="kpi"><span>Postes</span><b>{problem.workstations.length || "—"}</b></div>
            <div className="kpi"><span>Ouvriers</span><b>{problem.workers.length || "—"}</b></div>
          </div>
          {precheck.issues.length === 0 && precheck.validation_errors.length === 0 ? (
            <p className="notice ok">Aucun problème détecté.</p>
          ) : (
            <ul className="issues">
              {precheck.validation_errors.map((v, i) => <li key={"e" + i} className="error"><b>Données</b> {v}</li>)}
              {precheck.issues.map((v, i) => (
                <li key={i} className={v.severity}><b>{SEVERITY[v.severity] ?? v.severity}</b> {v.message}{v.suggestion && <em> → {v.suggestion}</em>}</li>
              ))}
            </ul>
          )}
          {errors.length > 0 && <p className="notice warn">{errors.length} point{errors.length > 1 ? "s" : ""} bloquant{errors.length > 1 ? "s" : ""} : le calcul peut échouer ou donner une solution non conforme.</p>}

          <h3>3. Calcul</h3>
          <div className="form-grid">
            <label>Objectif
              <select value={kind} onChange={(e) => setKind(e.target.value as "balance" | "min_cycle")}>
                <option value="balance">Équilibrer à la cadence cible</option>
                <option value="min_cycle">Trouver la cadence minimale</option>
              </select>
            </label>
            <label>Méthode
              <select value={solver} onChange={(e) => setSolver(e.target.value as "rpw" | "cp_sat")}>
                <option value="rpw">RPW – rapide (quelques secondes)</option>
                <option value="cp_sat">CP-SAT – optimisation (plus long)</option>
              </select>
            </label>
            {solver === "cp_sat" && (
              <label>Temps max (s){kind === "min_cycle" ? " par essai" : ""}
                <input type="number" min={5} max={300} value={timeLimit} onChange={(e) => setTimeLimit(Number(e.target.value))} />
              </label>
            )}
          </div>
          <button className="btn primary" onClick={launch} disabled={!!busy}>{busy || "Lancer le calcul"}</button>
        </section>
      )}
    </div>
  );
}

function FileField({ label, file, onPick }: { label: string; file?: File; onPick: (f?: File) => void }) {
  return (
    <label className={`file ${file ? "has" : ""}`}>
      <span>{label}</span>
      <small>{file ? file.name : "Choisir un fichier"}</small>
      <input type="file" accept=".xlsx,.xls,.csv,.json" onChange={(e) => onPick(e.target.files?.[0])} />
    </label>
  );
}
