import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { api, fmt, post, ROLE_LABEL } from "../lib/api";
import { supabase } from "../lib/supabase";
import { useSession } from "../lib/session";
import type { Plan } from "../lib/types";

// ---------------------------------------------------------------- types
interface AdminUserOrg { id: string; name: string; role: string; plan_code: string | null; status: string | null }
interface AdminUser {
  id: string; email: string; created_at: string; last_sign_in_at: string | null; confirmed: boolean;
  suspended: boolean; is_super_admin: boolean; runs_count: number; last_run_at: string | null; orgs: AdminUserOrg[];
}
interface AdminOrg {
  id: string; name: string; country: string; created_at: string; owner_email: string | null;
  members_count: number; lines_count: number; runs_count: number; last_run_at: string | null;
  plan_code: string | null; status: string | null; trial_ends_at: string | null; current_period_end: string | null;
  plan_active: boolean; paid_total_tnd: number;
}
interface Payment {
  id: string; org_id: string | null; org_name: string; plan_code: string; amount_tnd: number; paid_at: string;
  period_start: string | null; period_end: string | null; method: string; reference: string; note: string; created_at: string;
}
interface Overview {
  currency: string; payments_count: number; total_tnd: number; this_month_tnd: number; last_month_tnd: number;
  by_month: { month: string; total_tnd: number; count: number }[];
  by_plan: { plan_code: string; plan_name: string; total_tnd: number; count: number }[];
  subscriptions: { active: number; trialing: number; trial_expired: number; past_due: number; canceled: number; mrr_tnd: number };
  active_by_plan: Record<string, number>; users_count: number; orgs_count: number;
}

const STATUS: Record<string, string> = { trialing: "Essai", active: "Actif", past_due: "Paiement en retard", canceled: "Résilié" };
const METHODS: Record<string, string> = { virement: "Virement", especes: "Espèces", cheque: "Chèque", carte: "Carte", konnect: "Konnect", flouci: "Flouci", autre: "Autre" };
const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const tnd = (v: number | null | undefined) => `${fmt.n(v ?? 0, 3)} TND`;
const isoDay = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

function statusBadge(code: string | null, status: string | null, active = true) {
  if (!status) return <span className="badge">Sans offre</span>;
  const cls = !active ? "err" : status === "active" ? "ok" : status === "trialing" ? "info" : "warn";
  return <span className={`badge ${cls}`}>{code ?? "?"} · {!active && status === "trialing" ? "essai expiré" : STATUS[status] ?? status}</span>;
}

type Tab = "gains" | "users" | "orgs" | "payments";

export default function Admin() {
  const { session } = useSession();
  const [tab, setTab] = useState<Tab>("gains");
  const [ov, setOv] = useState<Overview | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [orgs, setOrgs] = useState<AdminOrg[] | null>(null);
  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [payFor, setPayFor] = useState<string>("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const [o, u, g, p] = await Promise.all([
        api<Overview>("/v1/admin/overview"), api<AdminUser[]>("/v1/admin/users"),
        api<AdminOrg[]>("/v1/admin/orgs"), api<Payment[]>("/v1/admin/payments"),
      ]);
      setOv(o); setUsers(u); setOrgs(g); setPayments(p);
    } catch (e) { setErr((e as Error).message); }
  }, []);

  useEffect(() => {
    load();
    supabase.from("plans").select("*").order("sort").then(({ data }) => setPlans((data as Plan[]) ?? []));
  }, [load]);

  const done = async (text: string) => { setMsg(text); await load(); };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Super admin <span className="badge admin">{session?.user.email}</span></h1>
          <p className="muted">Utilisateurs, ateliers, abonnements et gains de la plateforme.</p>
        </div>
        <button className="btn ghost small" onClick={() => { setMsg(""); load(); }}>Actualiser</button>
      </div>
      {err && <p className="notice err">{err}</p>}
      {msg && <p className="notice ok">{msg}</p>}
      <div className="tabs">
        {([["gains", "Gains"], ["users", `Utilisateurs${users ? ` (${users.length})` : ""}`],
          ["orgs", `Ateliers${orgs ? ` (${orgs.length})` : ""}`], ["payments", `Paiements${payments ? ` (${payments.length})` : ""}`]] as [Tab, string][])
          .map(([k, label]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      {!ov && !err && <p className="muted">Chargement…</p>}
      {tab === "gains" && ov && <Gains ov={ov} plans={plans} onPay={() => setTab("payments")} />}
      {tab === "users" && users && <Users users={users} onDone={done} onErr={setErr} />}
      {tab === "orgs" && orgs && <Orgs orgs={orgs} plans={plans} onDone={done} onErr={setErr}
        onPay={(id) => { setPayFor(id); setTab("payments"); }} />}
      {tab === "payments" && payments && orgs && <Payments payments={payments} orgs={orgs} plans={plans}
        initialOrg={payFor} onDone={done} onErr={setErr} />}
    </div>
  );
}

// ---------------------------------------------------------------- Gains
function Gains({ ov, plans, onPay }: { ov: Overview; plans: Plan[]; onPay: () => void }) {
  const s = ov.subscriptions;
  const max = Math.max(1, ...ov.by_month.map((m) => Number(m.total_tnd)));
  const label = (m: string) => { const [y, mo] = m.split("-"); return `${MONTHS[Number(mo) - 1]} ${y.slice(2)}`; };
  return (
    <>
      {ov.payments_count === 0 && (
        <div className="notice warn">
          <b>Aucun paiement enregistré pour l'instant.</b> Les gains ci-dessous sont donc à zéro : ils se rempliront
          dès que vous saisirez un paiement reçu (virement, espèces, chèque…) dans l'onglet{" "}
          <button className="link" onClick={onPay}>Paiements</button>. Le paiement en ligne n'est pas encore branché.
        </div>
      )}
      <section className="card">
        <h3>Encaissements</h3>
        <div className="kpis">
          <div className="kpi ok"><span>Total encaissé</span><b>{tnd(ov.total_tnd)}</b><small>{ov.payments_count} paiement{ov.payments_count > 1 ? "s" : ""}</small></div>
          <div className="kpi"><span>Ce mois-ci</span><b>{tnd(ov.this_month_tnd)}</b></div>
          <div className="kpi"><span>Mois dernier</span><b>{tnd(ov.last_month_tnd)}</b></div>
          <div className="kpi"><span>Revenu mensuel récurrent</span><b>{tnd(s.mrr_tnd)}</b><small>abonnements actifs × tarif</small></div>
        </div>
        <h3>Revenus par mois (12 derniers mois)</h3>
        <div className="bars">
          {ov.by_month.map((m) => (
            <div className="bar" key={m.month} title={`${label(m.month)} : ${tnd(m.total_tnd)} (${m.count})`}>
              {Number(m.total_tnd) > 0 && <span>{fmt.n(m.total_tnd, 0)}</span>}
              <div className={Number(m.total_tnd) > 0 ? "" : "zero"} style={{ height: `${(Number(m.total_tnd) / max) * 85}%` }} />
            </div>
          ))}
        </div>
        <div className="bars-labels">{ov.by_month.map((m) => <span key={m.month}>{label(m.month)}</span>)}</div>
      </section>
      <div className="form-grid">
        <section className="card">
          <h3>Revenus par offre</h3>
          <table><thead><tr><th>Offre</th><th>Tarif</th><th>Paiements</th><th>Total</th><th>Actifs</th></tr></thead>
            <tbody>{ov.by_plan.map((p) => {
              const plan = plans.find((x) => x.code === p.plan_code);
              return (
                <tr key={p.plan_code}><td>{p.plan_name}</td>
                  <td>{p.plan_code === "essai" ? "30 jours gratuits" : plan?.price_tnd_month == null ? "sur devis" : `${fmt.n(plan.price_tnd_month, 0)} TND/mois`}</td>
                  <td>{p.count}</td><td><b>{tnd(p.total_tnd)}</b></td><td>{ov.active_by_plan[p.plan_code] ?? 0}</td></tr>
              );
            })}</tbody></table>
        </section>
        <section className="card">
          <h3>Abonnements</h3>
          <div className="kpis">
            <div className="kpi ok"><span>Actifs (payants)</span><b>{s.active}</b></div>
            <div className="kpi"><span>Essais en cours</span><b>{s.trialing}</b></div>
            <div className="kpi warn"><span>Essais expirés</span><b>{s.trial_expired}</b></div>
            <div className="kpi"><span>En retard / résiliés</span><b>{s.past_due} / {s.canceled}</b></div>
            <div className="kpi"><span>Utilisateurs</span><b>{ov.users_count}</b></div>
            <div className="kpi"><span>Ateliers</span><b>{ov.orgs_count}</b></div>
          </div>
        </section>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Confirmation
function Confirm({ title, children, expected, label, action, onCancel, onConfirm }: {
  title: string; children: ReactNode; expected: string; label: string; action: string;
  onCancel: () => void; onConfirm: (typed: string) => Promise<void>;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="modal-back" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <div className="small">{children}</div>
        <label style={{ marginTop: ".8rem" }}>{label}
          <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={expected} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onCancel}>Annuler</button>
          <button className="btn danger" disabled={busy || typed.trim().toLowerCase() !== expected.toLowerCase()}
            onClick={async () => { setBusy(true); try { await onConfirm(typed.trim()); } finally { setBusy(false); } }}>{action}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Utilisateurs
function Users({ users, onDone, onErr }: { users: AdminUser[]; onDone: (m: string) => Promise<void>; onErr: (m: string) => void }) {
  const [q, setQ] = useState("");
  const [del, setDel] = useState<AdminUser | null>(null);
  const [busy, setBusy] = useState("");
  const list = useMemo(() => users.filter((u) => !q || u.email.toLowerCase().includes(q.toLowerCase())
    || u.orgs.some((o) => o.name.toLowerCase().includes(q.toLowerCase()))), [users, q]);

  const suspend = async (u: AdminUser, s: boolean) => {
    if (s && !window.confirm(`Suspendre ${u.email} ? Il sera déconnecté et ne pourra plus accéder à l'application.`)) return;
    setBusy(u.id); onErr("");
    try { await post(`/v1/admin/users/${u.id}/suspend`, { suspended: s }); await onDone(`${u.email} ${s ? "suspendu" : "réactivé"}.`); }
    catch (e) { onErr((e as Error).message); } finally { setBusy(""); }
  };
  const ownedAlone = (u: AdminUser) => u.orgs.filter((o) => o.role === "owner");

  return (
    <section className="card">
      <div className="inline-form"><input placeholder="Rechercher un e-mail ou un atelier…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <div className="table-wrap">
        <table className="admin-table">
          <thead><tr><th>Utilisateur</th><th>Inscrit le</th><th>Dernière connexion</th><th>Calculs</th><th>Ateliers · offre</th><th></th></tr></thead>
          <tbody>{list.map((u) => (
            <tr key={u.id}>
              <td><b>{u.email}</b>
                <span className="cell-sub">
                  {u.is_super_admin && <span className="badge admin">super admin</span>}
                  {u.suspended && <span className="badge err">suspendu</span>}
                  {!u.confirmed && <span className="badge warn">e-mail non confirmé</span>}
                </span></td>
              <td>{fmt.day(u.created_at)}</td>
              <td>{u.last_sign_in_at ? fmt.date(u.last_sign_in_at) : <span className="muted">jamais</span>}</td>
              <td>{u.runs_count}{u.last_run_at && <span className="cell-sub">dernier : {fmt.day(u.last_run_at)}</span>}</td>
              <td className="wrap">{u.orgs.length === 0 ? <span className="muted">aucun</span> : u.orgs.map((o) => (
                <div key={o.id}>{o.name} <span className="muted small">({ROLE_LABEL[o.role] ?? o.role})</span> {statusBadge(o.plan_code, o.status)}</div>))}</td>
              <td>{!u.is_super_admin && (
                <div className="row">
                  <button className="btn small" disabled={busy === u.id} onClick={() => suspend(u, !u.suspended)}>{u.suspended ? "Réactiver" : "Suspendre"}</button>
                  <button className="btn small ghost" style={{ color: "var(--err)" }} onClick={() => setDel(u)}>Supprimer</button>
                </div>)}</td>
            </tr>))}</tbody>
        </table>
      </div>
      {list.length === 0 && <p className="muted empty">Aucun utilisateur ne correspond.</p>}
      {del && (
        <Confirm title={`Supprimer ${del.email} ?`} expected={del.email} label="Pour confirmer, saisissez son e-mail" action="Supprimer définitivement"
          onCancel={() => setDel(null)}
          onConfirm={async (typed) => {
            onErr("");
            try {
              const r = await api<{ deleted_orgs: number }>(`/v1/admin/users/${del.id}`, { method: "DELETE", body: JSON.stringify({ confirm_email: typed }) });
              setDel(null);
              await onDone(`${del.email} supprimé${r.deleted_orgs ? ` (et ${r.deleted_orgs} atelier${r.deleted_orgs > 1 ? "s" : ""})` : ""}.`);
            } catch (e) { onErr((e as Error).message); setDel(null); }
          }}>
          <p>Le compte est supprimé définitivement. {ownedAlone(del).length > 0
            ? <>Ses ateliers dont il est le seul propriétaire seront aussi supprimés avec leurs lignes, gammes et calculs : <b>{ownedAlone(del).map((o) => o.name).join(", ")}</b>.</>
            : "Il n'est propriétaire d'aucun atelier."} Les paiements déjà saisis sont conservés.</p>
        </Confirm>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- Ateliers
function Orgs({ orgs, plans, onDone, onErr, onPay }: {
  orgs: AdminOrg[]; plans: Plan[]; onDone: (m: string) => Promise<void>; onErr: (m: string) => void; onPay: (id: string) => void;
}) {
  const [edit, setEdit] = useState<AdminOrg | null>(null);
  const [del, setDel] = useState<AdminOrg | null>(null);
  return (
    <section className="card">
      <div className="table-wrap">
        <table className="admin-table">
          <thead><tr><th>Atelier</th><th>Propriétaire</th><th>Créé le</th><th>Membres</th><th>Lignes</th><th>Calculs</th><th>Offre</th><th>Échéance</th><th>Payé</th><th></th></tr></thead>
          <tbody>{orgs.map((o) => (
            <tr key={o.id}>
              <td><b>{o.name}</b><span className="cell-sub">{o.country}</span></td>
              <td>{o.owner_email ?? <span className="muted">—</span>}</td>
              <td>{fmt.day(o.created_at)}</td>
              <td>{o.members_count}</td><td>{o.lines_count}</td>
              <td>{o.runs_count}{o.last_run_at && <span className="cell-sub">dernier : {fmt.day(o.last_run_at)}</span>}</td>
              <td>{statusBadge(o.plan_code, o.status, o.plan_active)}</td>
              <td>{fmt.day(o.status === "trialing" ? o.trial_ends_at : o.current_period_end)}</td>
              <td>{tnd(o.paid_total_tnd)}</td>
              <td><div className="row">
                <button className="btn small" onClick={() => setEdit(o)}>Changer l'offre</button>
                <button className="btn small" onClick={() => onPay(o.id)}>Paiement</button>
                <button className="btn small ghost" style={{ color: "var(--err)" }} onClick={() => setDel(o)}>Supprimer</button>
              </div></td>
            </tr>))}</tbody>
        </table>
      </div>
      {orgs.length === 0 && <p className="muted empty">Aucun atelier pour l'instant.</p>}
      {edit && <PlanModal org={edit} plans={plans} onCancel={() => setEdit(null)} onErr={onErr}
        onSaved={async (m) => { setEdit(null); await onDone(m); }} />}
      {del && (
        <Confirm title={`Supprimer l'atelier « ${del.name} » ?`} expected={del.name} label="Pour confirmer, saisissez le nom de l'atelier" action="Supprimer l'atelier"
          onCancel={() => setDel(null)}
          onConfirm={async (typed) => {
            onErr("");
            try { await api(`/v1/admin/orgs/${del.id}`, { method: "DELETE", body: JSON.stringify({ confirm_name: typed }) }); setDel(null); await onDone(`Atelier « ${del.name} » supprimé.`); }
            catch (e) { onErr((e as Error).message); setDel(null); }
          }}>
          <p>L'atelier, ses membres, lignes, gammes et {del.runs_count} calcul{del.runs_count > 1 ? "s" : ""} sont supprimés définitivement. Les comptes utilisateurs et les paiements sont conservés.</p>
        </Confirm>
      )}
    </section>
  );
}

function PlanModal({ org, plans, onCancel, onSaved, onErr }: {
  org: AdminOrg; plans: Plan[]; onCancel: () => void; onSaved: (m: string) => Promise<void>; onErr: (m: string) => void;
}) {
  const [plan, setPlan] = useState(org.plan_code ?? "atelier");
  const [status, setStatus] = useState(org.status ?? "active");
  const [until, setUntil] = useState((status === "trialing" ? org.trial_ends_at : org.current_period_end)?.slice(0, 10) ?? "");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); onErr("");
    const end = until ? new Date(`${until}T23:59:59`).toISOString() : null;
    try {
      await api(`/v1/admin/orgs/${org.id}/plan`, { method: "PUT", body: JSON.stringify({
        plan_code: plan, status, trial_ends_at: status === "trialing" ? end : null, current_period_end: status === "trialing" ? null : end }) });
      await onSaved(`Offre de « ${org.name} » mise à jour.`);
    } catch (er) { onErr((er as Error).message); onCancel(); } finally { setBusy(false); }
  };
  return (
    <div className="modal-back" onClick={onCancel}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Offre de « {org.name} »</h3>
        <label>Offre<select value={plan} onChange={(e) => setPlan(e.target.value)}>
          {plans.map((p) => <option key={p.code} value={p.code}>{p.name}{p.price_tnd_month ? ` (${fmt.n(p.price_tnd_month, 0)} TND/mois)` : ""}</option>)}
        </select></label>
        <label>Statut<select value={status} onChange={(e) => setStatus(e.target.value)}>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select></label>
        <label>{status === "trialing" ? "Fin de l'essai" : "Fin de période payée"}
          <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
        <p className="muted small">Résilié = plus aucun calcul possible pour cet atelier. Paiement en retard = 7 jours de grâce après l'échéance.</p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn ghost" onClick={onCancel}>Annuler</button>
          <button className="btn primary" disabled={busy}>Enregistrer</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- Paiements
function Payments({ payments, orgs, plans, initialOrg, onDone, onErr }: {
  payments: Payment[]; orgs: AdminOrg[]; plans: Plan[]; initialOrg: string; onDone: (m: string) => Promise<void>; onErr: (m: string) => void;
}) {
  const today = new Date();
  const nextMonth = new Date(today); nextMonth.setMonth(nextMonth.getMonth() + 1); nextMonth.setDate(nextMonth.getDate() - 1);
  const [f, setF] = useState({ org_id: initialOrg || orgs[0]?.id || "", plan_code: "atelier", amount_tnd: "149",
    paid_at: isoDay(today), period_start: isoDay(today), period_end: isoDay(nextMonth), method: "virement", reference: "", note: "", activate: true });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string | boolean) => setF((x) => ({ ...x, [k]: v }));
  const choosePlan = (code: string) => {
    const p = plans.find((x) => x.code === code);
    setF((x) => ({ ...x, plan_code: code, amount_tnd: p?.price_tnd_month != null ? String(p.price_tnd_month) : x.amount_tnd }));
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); onErr("");
    try {
      await post("/v1/admin/payments", { ...f, amount_tnd: f.amount_tnd.replace(",", "."),
        period_start: f.period_start || null, period_end: f.period_end || null });
      const org = orgs.find((o) => o.id === f.org_id);
      await onDone(`Paiement de ${tnd(Number(f.amount_tnd.replace(",", ".")))} enregistré pour « ${org?.name} »${f.activate ? ", offre activée" : ""}.`);
      setF((x) => ({ ...x, reference: "", note: "" }));
    } catch (er) { onErr((er as Error).message); } finally { setBusy(false); }
  };
  const remove = async (p: Payment) => {
    if (!window.confirm(`Supprimer le paiement de ${tnd(p.amount_tnd)} (${p.org_name}, ${fmt.day(p.paid_at)}) ? L'offre de l'atelier n'est pas modifiée.`)) return;
    onErr("");
    try { await api(`/v1/admin/payments/${p.id}`, { method: "DELETE" }); await onDone("Paiement supprimé."); }
    catch (er) { onErr((er as Error).message); }
  };
  return (
    <>
      <section className="card">
        <h3>Enregistrer un paiement reçu</h3>
        {orgs.length === 0 ? <p className="muted">Aucun atelier inscrit : rien à encaisser pour l'instant.</p> : (
          <form onSubmit={submit}>
            <div className="form-grid">
              <label>Atelier<select value={f.org_id} onChange={(e) => set("org_id", e.target.value)} required>
                {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}{o.owner_email ? ` (${o.owner_email})` : ""}</option>)}</select></label>
              <label>Offre<select value={f.plan_code} onChange={(e) => choosePlan(e.target.value)}>
                {plans.map((p) => <option key={p.code} value={p.code}>{p.name}{p.price_tnd_month ? ` (${fmt.n(p.price_tnd_month, 0)} TND/mois)` : p.price_tnd_month === null ? " (sur devis)" : ""}</option>)}</select></label>
              <label>Montant (TND)<input inputMode="decimal" value={f.amount_tnd} onChange={(e) => set("amount_tnd", e.target.value)} required pattern="[0-9]+([.,][0-9]{1,3})?" /></label>
              <label>Reçu le<input type="date" value={f.paid_at} onChange={(e) => set("paid_at", e.target.value)} required /></label>
              <label>Période du<input type="date" value={f.period_start} onChange={(e) => set("period_start", e.target.value)} /></label>
              <label>au<input type="date" value={f.period_end} onChange={(e) => set("period_end", e.target.value)} /></label>
              <label>Mode<select value={f.method} onChange={(e) => set("method", e.target.value)}>
                {Object.entries(METHODS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
              <label>Référence<input value={f.reference} onChange={(e) => set("reference", e.target.value)} placeholder="n° de virement, de chèque…" maxLength={200} /></label>
            </div>
            <label>Note<input value={f.note} onChange={(e) => set("note", e.target.value)} maxLength={1000} /></label>
            <label className="check"><input type="checkbox" checked={f.activate} onChange={(e) => set("activate", e.target.checked)} />
              Activer cette offre pour l'atelier jusqu'à la fin de la période</label>
            <button className="btn primary" disabled={busy}>Enregistrer le paiement</button>
          </form>
        )}
      </section>
      <section className="card">
        <h3>Paiements enregistrés</h3>
        {payments.length === 0 ? <p className="muted empty">Aucun paiement enregistré pour l'instant.</p> : (
          <div className="table-wrap"><table className="admin-table">
            <thead><tr><th>Reçu le</th><th>Atelier</th><th>Offre</th><th>Montant</th><th>Période</th><th>Mode</th><th>Référence</th><th></th></tr></thead>
            <tbody>{payments.map((p) => (
              <tr key={p.id}><td>{fmt.day(p.paid_at)}</td><td>{p.org_name}{!p.org_id && <span className="cell-sub">atelier supprimé</span>}</td>
                <td>{plans.find((x) => x.code === p.plan_code)?.name ?? p.plan_code}</td><td><b>{tnd(p.amount_tnd)}</b></td>
                <td>{p.period_start ? `${fmt.day(p.period_start)} → ${fmt.day(p.period_end)}` : "—"}</td>
                <td>{METHODS[p.method] ?? p.method}</td><td className="wrap">{p.reference}{p.note && <span className="cell-sub">{p.note}</span>}</td>
                <td><button className="btn small ghost" onClick={() => remove(p)}>Supprimer</button></td></tr>))}</tbody>
          </table></div>
        )}
      </section>
    </>
  );
}
