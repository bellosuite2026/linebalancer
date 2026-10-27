import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import {
  clock, fetchEntries, localHour, localMinute, minutesSince, OfflineQueue, pushEntries, REASON_LABEL, REASONS,
  sessionsPath, uuid, type Entry, type PlanStation, type ProdSession, type Reason,
} from "../lib/production";

type Popup = { station: number; kind: "defect" | "stop" } | null;

/** Page tablette (paysage) : gros boutons de comptage par station, file locale si le réseau coupe. */
export default function ProductionEntry() {
  const { id = "" } = useParams();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const queue = useMemo(() => new OfflineQueue(id), [id]);
  const [session, setSession] = useState<ProdSession | null>(null);
  const [server, setServer] = useState<Record<string, Entry>>({});
  const [pending, setPending] = useState<Record<string, Entry>>(() => queue.all());
  const [online, setOnline] = useState(navigator.onLine);
  const [err, setErr] = useState("");
  const [toast, setToast] = useState("");
  const [popup, setPopup] = useState<Popup>(null);
  const [, setTick] = useState(0);
  const syncing = useRef(false);
  const toastTimer = useRef<number>();

  const tz = session?.timezone || "Africa/Tunis";

  const refresh = useCallback(async () => {
    try {
      const [s, es] = await Promise.all([api<ProdSession>(`${sessionsPath(org.id)}/${id}`), fetchEntries(org.id, id)]);
      setSession(s);
      setServer(Object.fromEntries(es.map((e) => [e.client_id, e])));
      setOnline(true);
    } catch (e) {
      if (!session) setErr((e as Error).message);
      setOnline(false);
    }
  }, [org.id, id, session]);

  const sync = useCallback(async () => {
    if (syncing.current) return;
    const batch = Object.values(queue.all()).slice(0, 200);
    if (!batch.length) return;
    syncing.current = true;
    const r = await pushEntries(org.id, id, batch);
    syncing.current = false;
    if (r.ok) {
      queue.ack(batch);
      setServer((m) => ({ ...m, ...Object.fromEntries(r.saved.map((e) => [e.client_id, e])) }));
      setOnline(true); setErr("");
    } else if (r.fatal) {
      queue.drop(batch.map((e) => e.client_id));
      setErr(r.message);
    } else {
      setOnline(false);
    }
    setPending(queue.all());
  }, [org.id, id, queue]);

  useEffect(() => { refresh(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const t1 = window.setInterval(sync, 4000);
    const t2 = window.setInterval(() => { if (!syncing.current) refresh(); }, 20000);
    const t3 = window.setInterval(() => setTick((x) => x + 1), 15000);
    const on = () => { setOnline(true); sync(); };
    const off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { clearInterval(t1); clearInterval(t2); clearInterval(t3); window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, [sync, refresh]);

  const entries = useMemo(() => Object.values({ ...server, ...pending }).filter((e) => !e.voided), [server, pending]);
  const hour = localHour(tz);

  const save = (e: Entry, msg: string) => {
    queue.put(e);
    setPending(queue.all());
    flash(msg);
    window.setTimeout(sync, 50);
  };
  const flash = (msg: string) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 2200);
  };
  const base = (st: PlanStation): Entry => ({
    client_id: uuid(), station: st.station, slot_hour: localHour(tz), worker_id: st.worker_ids?.length === 1 ? st.worker_ids[0] : null,
    pieces: 0, defects: 0, rework: 0, entered_at: new Date().toISOString(),
  });
  const addPieces = (st: PlanStation, n: number) => save({ ...base(st), pieces: n }, `Station ${st.station} : +${n}`);
  const addDefect = (st: PlanStation, kind: "defects" | "rework") => {
    save({ ...base(st), [kind]: 1 }, `Station ${st.station} : ${kind === "defects" ? "défaut" : "retouche"} +1`);
    setPopup(null);
  };
  const startStop = (st: PlanStation, reason: Reason) => {
    save({ ...base(st), downtime_reason: reason, downtime_start: new Date().toISOString(), downtime_minutes: null },
      `Station ${st.station} : arrêt (${REASON_LABEL[reason].toLowerCase()})`);
    setPopup(null);
  };
  const endStop = (e: Entry) => {
    const mins = Math.round(minutesSince(e.downtime_start) * 10) / 10;
    save({ ...e, downtime_minutes: mins }, `Station ${e.station} : reprise après ${Math.round(mins)} min`);
  };
  const undo = (st: PlanStation) => {
    const last = entries.filter((e) => e.station === st.station && !(e.downtime_reason && e.downtime_minutes == null))
      .sort((a, b) => b.entered_at.localeCompare(a.entered_at))[0];
    if (!last) return flash("Rien à annuler");
    save({ ...last, voided: true }, `Annulé : ${last.pieces ? `+${last.pieces} pièces` : last.defects ? "défaut" : last.rework ? "retouche" : "arrêt"} (station ${st.station})`);
  };

  if (err && !session) return <div className="page"><p className="notice err">{err}</p><Link to="/production">Retour</Link></div>;
  if (!session) return <div className="center muted">Chargement de la session…</div>;
  const stations = session.plan?.stations || [];
  const nPending = Object.keys(pending).length;
  const closed = session.status === "closed";
  const writable = canWrite(org) && !closed;
  const minuteInHour = localMinute(tz);
  const expectedHour = session.target_per_hour * Math.max(minuteInHour, 1) / 60;

  return (
    <div className="tablet">
      <header className="tablet-head">
        <div>
          <b>{session.model || "Session"}</b>{session.line_name && <span> · {session.line_name}</span>}
          <span className="muted"> · objectif {session.target_per_hour} pcs/h</span>
        </div>
        <div className="tablet-clock">{clock(tz)}{" "}<small>créneau {hour} h</small></div>
        <div className={`sync ${online ? (nPending ? "wait" : "ok") : "off"}`}>
          <i />{online ? (nPending ? `Envoi de ${nPending} saisie${nPending > 1 ? "s" : ""}…` : "En ligne · tout est envoyé")
            : `Hors ligne · ${nPending} saisie${nPending > 1 ? "s" : ""} en attente`}
        </div>
        <div className="row">
          <button className="btn small" onClick={() => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.())}>Plein écran</button>
          <Link className="btn small" to={`/production/${id}`}>Tableau de bord</Link>
          <Link className="btn small ghost" to="/production">Quitter</Link>
        </div>
      </header>
      {closed && <p className="notice warn">Session fermée : la saisie est verrouillée.</p>}
      {!canWrite(org) && <p className="notice warn">Votre rôle (lecteur) ne permet pas de saisir.</p>}
      {err && <p className="notice err">{err}</p>}

      <div className="tablet-grid">
        {stations.map((st) => {
          const mine = entries.filter((e) => e.station === st.station);
          const total = mine.reduce((a, e) => a + (e.pieces || 0), 0);
          const thisHour = mine.filter((e) => e.slot_hour === hour).reduce((a, e) => a + (e.pieces || 0), 0);
          const defects = mine.reduce((a, e) => a + (e.defects || 0) + (e.rework || 0), 0);
          const ongoing = mine.find((e) => e.downtime_reason && e.downtime_minutes == null);
          const ratio = expectedHour >= 1 ? thisHour / expectedHour : 1;
          return (
            <section key={st.station} className={`tcard ${ongoing ? "stopped" : ratio < 0.8 ? "late" : "on"}`}>
              <div className="tcard-head">
                <span className="tnum">S{st.station}</span>
                <div className="tinfo">
                  <b>{st.operations.map((o) => o.name || o.id).join(" + ")}</b>
                  <small>{st.workers.join(", ") || "—"} · {st.minutes.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} min/pce</small>
                </div>
              </div>
              <div className="tcount">
                <div><b>{thisHour}</b><small>cette heure / {Math.round(session.target_per_hour)}</small></div>
                <div><b>{total}</b><small>aujourd'hui</small></div>
                <div><b>{defects}</b><small>déf./ret.</small></div>
              </div>
              {ongoing ? (
                <button className="tbtn stopbtn" disabled={!writable} onClick={() => endStop(ongoing)}>
                  Arrêt : {REASON_LABEL[ongoing.downtime_reason!]} · {Math.round(minutesSince(ongoing.downtime_start))} min<br /><span>Toucher pour reprendre</span>
                </button>
              ) : (
                <div className="tplus">
                  {[1, 5, 10].map((n) => <button key={n} className="tbtn plus" disabled={!writable} onClick={() => addPieces(st, n)}>+{n}</button>)}
                </div>
              )}
              <div className="tsec">
                <button className="tbtn sec" disabled={!writable} onClick={() => setPopup({ station: st.station, kind: "defect" })}>Défaut</button>
                <button className="tbtn sec" disabled={!writable || !!ongoing} onClick={() => setPopup({ station: st.station, kind: "stop" })}>Arrêt</button>
                <button className="tbtn sec undo" disabled={!writable} onClick={() => undo(st)} title="Annuler la dernière saisie">↶</button>
              </div>
              {popup?.station === st.station && (
                <div className="tpop" onClick={() => setPopup(null)}>
                  <div onClick={(e) => e.stopPropagation()}>
                    {popup.kind === "defect" ? (<>
                      <button className="tbtn choice" onClick={() => addDefect(st, "defects")}>Défaut +1</button>
                      <button className="tbtn choice" onClick={() => addDefect(st, "rework")}>Retouche +1</button>
                    </>) : REASONS.map((r) => (
                      <button key={r.code} className="tbtn choice" onClick={() => startStop(st, r.code)}><span>{r.icon}</span> {r.label}</button>
                    ))}
                    <button className="tbtn choice cancel" onClick={() => setPopup(null)}>Fermer</button>
                  </div>
                </div>
              )}
            </section>
          );
        })}
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
