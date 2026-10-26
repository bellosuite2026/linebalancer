"""
Ressources d'une ligne : postes multi-machines, fractionnement des opérations
longues et affectation des ouvriers (compétences + rendement).

Partagé par les solveurs RPW et CP-SAT (v2.2) :

- `expand_problem(problem)` : fractionne chaque opération plus longue que la
  cadence en parts (mode "share" : k parts pleines + un reliquat combinable
  avec d'autres opérations ; mode "parallel" : rien n'est fractionné, le
  solveur dédouble la station). Renvoie le problème développé et la table
  part -> opération d'origine.
- `collapse_details(...)` : ramène les stations sur les opérations d'origine
  (clé `shares` = minutes de chaque opération partagée tenues par la station).
- `station_time(ops, problem)` : temps d'une station, déplacement entre
  machines compris (`machine_change_time` par machine supplémentaire).
- `assign_workstations(...)` : un poste physique par type de machine de la
  station (x nombre de postes parallèles). Les stations manuelles ne prennent
  pas de machine utile aux autres (corrige l'ancien glouton CP-SAT).
- `assign_workers(...)` : affectation optimale (méthode hongroise) des
  ouvriers qualifiés ; à compétences égales, les meilleurs rendements vont aux
  stations les plus chargées. Ajoute `worker_time` (temps réel au rendement de
  l'ouvrier) et `worker_efficiency` à chaque station.
- `staffable(skill_sets, workers)` : test de couplage (Hall) utilisé pendant
  la construction pour ne pas créer de station impossible à pourvoir.
"""
from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Iterable, Optional

from engine.models import LineBalancingProblem, Operation, Worker

EPS = 1e-6
PART_SEP = "#"


# --------------------------------------------------------------------------
# Fractionnement des opérations longues
# --------------------------------------------------------------------------

def split_durations(duration: float, cycle: float) -> list[float]:
    """Parts d'une opération : k parts pleines (= cadence) + reliquat éventuel."""
    if cycle <= 0 or duration <= cycle + EPS:
        return [duration]
    k = int(math.floor(duration / cycle + EPS))
    rest = duration - k * cycle
    parts = [cycle] * k
    if rest > 1e-3:
        parts.append(rest)
    return parts


def expand_problem(problem: LineBalancingProblem) -> tuple[LineBalancingProblem, dict[str, str]]:
    """Développe les opérations > cadence en parts (mode share). Sans opération
    longue (ou en mode parallel), renvoie le problème tel quel."""
    C = problem.target_cycle_time
    mode = (problem.split_mode or "share").lower()
    origin = {o.id: o.id for o in problem.operations}
    if mode != "share" or not any(o.duration > C + EPS for o in problem.operations):
        return problem, origin
    parts_of: dict[str, list[str]] = {}
    new_ops: list[Operation] = []
    for o in problem.operations:
        durs = split_durations(o.duration, C)
        if len(durs) == 1:
            parts_of[o.id] = [o.id]
            continue
        ids = [f"{o.id}{PART_SEP}{i + 1}" for i in range(len(durs))]
        parts_of[o.id] = ids
        for pid in ids:
            origin[pid] = o.id
    for o in problem.operations:
        preds = [p for pr in o.predecessors for p in parts_of.get(pr, [pr])]
        for i, pid in enumerate(parts_of[o.id]):
            d = split_durations(o.duration, C)[i] if len(parts_of[o.id]) > 1 else o.duration
            new_ops.append(Operation(
                id=pid, name=o.name if pid == o.id else f"{o.name} (part {i + 1})",
                duration=d, predecessors=list(preds), machine_type=o.machine_type,
                required_skills=list(o.required_skills), section=o.section,
                optional=o.optional, task_type=o.task_type))
    p = copy.copy(problem)
    p.operations = new_ops
    p.forced_assignments = {parts_of.get(k, [k])[0]: v for k, v in problem.forced_assignments.items()}
    p.forbidden_assignments = {pid: list(v) for k, v in problem.forbidden_assignments.items()
                               for pid in parts_of.get(k, [k])}
    p.same_station_groups = [[parts_of.get(k, [k])[0] for k in g] for g in problem.same_station_groups]
    return p, origin


def collapse_details(station_details: list[dict], origin: dict[str, str],
                     durations: dict[str, float]) -> tuple[dict[str, int], list[str]]:
    """Remplace les ids de parts par l'opération d'origine dans `station_details`.
    Renvoie (affectation op -> 1re station, messages sur les opérations partagées)."""
    assign: dict[str, int] = {}
    where: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for sd in station_details:
        ops: list[str] = []
        shares: dict[str, float] = {}
        for pid in sd["operations"]:
            oid = origin.get(pid, pid)
            if pid != oid:
                shares[oid] = round(shares.get(oid, 0.0) + durations[pid], 3)
                where[oid].append((sd["station"], durations[pid]))
            if oid not in ops:
                ops.append(oid)
            assign.setdefault(oid, sd["station"])
        sd["operations"] = ops
        if shares:
            sd["shares"] = shares
    msgs = []
    for oid, lst in where.items():
        parts = " + ".join(f"{d:.2f}" for _, d in lst)
        sts = ", ".join(str(s) for s, _ in lst)
        msgs.append(f"ℹ️ {oid} est partagée entre les stations {sts} ({parts} min)")
    return assign, msgs


# --------------------------------------------------------------------------
# Temps de station
# --------------------------------------------------------------------------

def station_machine_types(op_ids: Iterable[str], ops: dict[str, Operation]) -> list[str]:
    seen: list[str] = []
    for o in op_ids:
        m = ops[o].machine_type
        if m and m not in seen:
            seen.append(m)
    return seen


def station_time(op_ids: Iterable[str], ops: dict[str, Operation], problem: LineBalancingProblem) -> float:
    op_ids = list(op_ids)
    t = sum(ops[o].duration for o in op_ids)
    n = len(station_machine_types(op_ids, ops))
    if n > 1 and problem.machine_change_time > 0:
        t += problem.machine_change_time * (n - 1)
    return t


# --------------------------------------------------------------------------
# Compétences et rendement
# --------------------------------------------------------------------------

def qualified(worker: Worker, skills: set[str]) -> bool:
    return skills <= set(worker.skills)


def op_efficiency(worker: Worker, op: Operation) -> float:
    """Rendement de l'ouvrier sur une opération (matrice de polyvalence)."""
    base = worker.efficiency if worker.efficiency and worker.efficiency > 0 else 1.0
    if not op.required_skills or not worker.skill_levels:
        return base
    lv = [worker.skill_levels.get(s, base) for s in op.required_skills]
    lv = [v for v in lv if v and v > 0]
    return min(lv) if lv else base


def worker_station_time(worker: Worker, op_ids: Iterable[str], ops: dict[str, Operation],
                        problem: LineBalancingProblem, minutes: Optional[dict[str, float]] = None) -> float:
    """Temps réel d'une station tenue par `worker` (SAM / rendement)."""
    op_ids = list(op_ids)
    t = 0.0
    for o in op_ids:
        d = minutes.get(o, ops[o].duration) if minutes else ops[o].duration
        t += d / op_efficiency(worker, ops[o])
    n = len(station_machine_types(op_ids, ops))
    if n > 1 and problem.machine_change_time > 0:
        t += problem.machine_change_time * (n - 1)
    return t


def staffable(skill_sets: list[set[str]], workers: list[Worker]) -> bool:
    """Existe-t-il un ouvrier qualifié DISTINCT pour chaque ensemble de compétences ?"""
    sets = [s for s in skill_sets if s]
    if not sets:
        return True
    if len(sets) > len(workers):
        return False
    wsk = [set(w.skills) for w in workers]
    cand = [[i for i, ws in enumerate(wsk) if s <= ws] for s in sets]
    match: dict[int, int] = {}

    def aug(si: int, seen: set[int]) -> bool:
        for wi in cand[si]:
            if wi in seen:
                continue
            seen.add(wi)
            if wi not in match or aug(match[wi], seen):
                match[wi] = si
                return True
        return False

    for si in sorted(range(len(sets)), key=lambda i: len(cand[i])):
        if not aug(si, set()):
            return False
    return True


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Affectation de coût minimal (n lignes <= m colonnes). Renvoie col par ligne."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


# --------------------------------------------------------------------------
# Affectation des postes physiques
# --------------------------------------------------------------------------

def assign_workstations(problem: LineBalancingProblem, station_details: list[dict],
                        ops: dict[str, Operation], warnings: Optional[list[str]] = None) -> None:
    """Un poste par type de machine de la station (x `parallel`).

    Les stations avec machines sont servies d'abord ; une station manuelle ne
    prend qu'un poste restant dont le type n'est demandé par aucune station
    (sinon elle reste sans poste, ce qui n'est pas une violation).
    À type égal, on préfère un poste de la même section que la station."""
    warnings = warnings if warnings is not None else []
    pool = [ws for ws in problem.workstations if ws.available]
    used: set[str] = set()
    demanded = Counter()
    for sd in station_details:
        mts = station_machine_types(sd["operations"], ops)
        sd["machine_types"] = mts
        secs = sorted({ops[o].section for o in sd["operations"] if ops[o].section})
        sd["sections"] = secs
        for m in mts:
            demanded[m] += int(sd.get("parallel", 1))
    for sd in station_details:
        sd["workstation"] = ""
        sd.pop("workstations", None)
        mts = sd["machine_types"]
        if not mts:
            continue
        par = int(sd.get("parallel", 1))
        picked: list[str] = []
        missing: list[str] = []
        for m in mts:
            cands = [ws for ws in pool if ws.id not in used and ws.machine_type == m]
            cands.sort(key=lambda w: (0 if w.section and w.section in sd["sections"] else 1))
            take = cands[:par]
            if len(take) < par:
                missing.append(m)
            for w in take:
                used.add(w.id)
                picked.append(w.id)
        if picked and not missing:
            sd["workstation"] = picked[0]
            sd["workstations"] = picked
        else:
            for w in picked:
                used.discard(w)
            warnings.append(f"⚠️ Station {sd['station']} : aucun poste disponible pour la/les machine(s) "
                            f"{', '.join(missing or mts)}")
    # Stations manuelles : poste libre non demandé (table, etc.)
    for sd in station_details:
        if sd["machine_types"]:
            continue
        free = [ws for ws in pool if ws.id not in used and demanded.get(ws.machine_type, 0) == 0]
        if free:
            used.add(free[0].id)
            sd["workstation"] = free[0].id
            sd["workstations"] = [free[0].id]


# --------------------------------------------------------------------------
# Affectation des ouvriers
# --------------------------------------------------------------------------

def assign_workers(problem: LineBalancingProblem, station_details: list[dict],
                   ops: dict[str, Operation], warnings: Optional[list[str]] = None) -> dict[str, int]:
    """Affecte `parallel` ouvriers qualifiés par station en minimisant le temps
    réel total (SAM / rendement) : cardinalité maximale d'abord, puis meilleurs
    rendements sur les stations les plus chargées. Renvoie worker_id -> station."""
    warnings = warnings if warnings is not None else []
    workers = [w for w in problem.workers if w.available]
    for sd in station_details:
        sd["workers"], sd["worker_ids"] = [], []
    if not workers:
        return {}
    slots: list[tuple[dict, set[str]]] = []
    for sd in station_details:
        need: set[str] = set()
        for o in sd["operations"]:
            need.update(ops[o].required_skills)
        sd["_need"] = need
        for _ in range(int(sd.get("parallel", 1))):
            slots.append((sd, need))
    # Les stations exigeant des compétences d'abord ; les autres prennent les restants
    order = sorted(range(len(slots)), key=lambda i: 0 if slots[i][1] else 1)
    skill_slots = [i for i in order if slots[i][1]]
    free_slots = [i for i in order if not slots[i][1]]
    BIG = 1e6
    taken: dict[int, int] = {}  # slot -> worker index

    def solve(slot_ids: list[int], wk_ids: list[int], require_skill: bool):
        if not slot_ids or not wk_ids:
            return
        rows, cols = slot_ids, wk_ids
        cost = []
        for si in rows:
            sd, need = slots[si]
            par = int(sd.get("parallel", 1))
            row = []
            for wi in cols:
                w = workers[wi]
                if require_skill and not qualified(w, need):
                    row.append(BIG)
                else:
                    t = worker_station_time(w, sd["operations"], ops, problem, sd.get("shares")) / par
                    # léger coût de polyvalence : garder les polyvalents pour les stations difficiles
                    row.append(t + 1e-4 * len(w.skills))
            cost.append(row)
        transposed = len(rows) > len(cols)
        if transposed:
            cost = [list(r) for r in zip(*cost)]
        res = _hungarian(cost)
        for a, b in enumerate(res):
            if b < 0:
                continue
            si, wi = (rows[b], cols[a]) if transposed else (rows[a], cols[b])
            sd, need = slots[si]
            if require_skill and not qualified(workers[wi], need):
                continue
            taken[si] = wi

    solve(skill_slots, list(range(len(workers))), True)
    rest = [wi for wi in range(len(workers)) if wi not in taken.values()]
    solve(free_slots, rest, False)

    out: dict[str, int] = {}
    for si in sorted(taken):
        sd = slots[si][0]
        w = workers[taken[si]]
        sd["workers"].append(w.name)
        sd["worker_ids"].append(w.id)
        out[w.id] = sd["station"]
    C = problem.target_cycle_time
    for sd in station_details:
        need = sd.pop("_need", set())
        par = int(sd.get("parallel", 1))
        if sd["worker_ids"]:
            ws = [problem.get_worker(i) for i in sd["worker_ids"]]
            times = [worker_station_time(w, sd["operations"], ops, problem, sd.get("shares")) / par for w in ws]
            wt = round(sum(times) / len(times), 3)
            base = sd["total_time"]
            sd["worker_time"] = wt
            sd["worker_efficiency"] = round(base / wt, 3) if wt > 0 else 1.0
            if wt > C + EPS and sd["total_time"] <= C + EPS:
                warnings.append(f"⚠️ Station {sd['station']} : {wt:.2f} min au rendement de "
                                f"{', '.join(w.name for w in ws)} (> cadence {C:.2f})")
        if need and len(sd["worker_ids"]) < par:
            warnings.append(
                f"⚠️ Station {sd['station']} : aucun ouvrier disponible ne maîtrise TOUTES les compétences "
                f"requises ({', '.join(sorted(need))})")
    return out
