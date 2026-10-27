"""
Simulation à événements discrets (DES) avec SimPy.
Modélise le flux de pièces entre postes de travail dans un atelier de confection.
"""
from __future__ import annotations

import simpy
import random
import statistics
import math
from dataclasses import dataclass, field
from typing import Optional

from engine.models import BalancingResult, Operation


@dataclass
class SimulationConfig:
    """Configuration de la simulation."""
    num_parts: int = 100              # Nombre de pièces à simuler
    arrival_interval_min: float = 0.0  # 0 = au plus vite (flux tiré par le goulot)
    warmup_parts: int = 10            # Pièces en warm-up (ignorées dans les stats)
    transport_time_min: float = 0.3   # Temps de transport inter-poste (minutes)
    random_seed: int = 42
    variability: float = 0.1          # Coefficient de variation des temps (0 = déterministe)


@dataclass
class StationStats:
    """Statistiques par poste de travail."""
    station_id: int
    name: str
    total_processed: int = 0
    total_time_worked: float = 0.0
    utilization_pct: float = 0.0
    avg_queue_length: float = 0.0
    max_queue_length: int = 0
    avg_waiting_time: float = 0.0
    operations: list[str] = field(default_factory=list)


@dataclass
class SimulationResult:
    """Résultat complet de la simulation."""
    success: bool = True
    error_message: str = ""
    config: SimulationConfig = field(default_factory=SimulationConfig)

    # KPIs globaux
    total_parts_completed: int = 0
    simulation_time_min: float = 0.0
    throughput_per_hour: float = 0.0
    avg_cycle_time_min: float = 0.0
    std_cycle_time_min: float = 0.0
    min_cycle_time_min: float = 0.0
    max_cycle_time_min: float = 0.0
    avg_wip: float = 0.0

    # Par poste
    station_stats: list[StationStats] = field(default_factory=list)

    # Détail des pièces (temps de complétion individuels)
    part_completion_times: list[float] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"✅ Simulation terminee ({self.total_parts_completed} pieces)",
            f"⏱️  Temps simule: {self.simulation_time_min:.1f} min",
            f"📈 Debit: {self.throughput_per_hour:.1f} pieces/h",
            f"🔄 Temps cycle moyen: {self.avg_cycle_time_min:.2f} min (±{self.std_cycle_time_min:.2f})",
            f"📊 WIP moyen: {self.avg_wip:.1f} pieces",
        ]
        if self.station_stats:
            lines.append("")
            lines.append("📋 Taux d'occupation par poste:")
            for s in sorted(self.station_stats, key=lambda x: x.station_id):
                bar = "█" * int(s.utilization_pct / 5) + "░" * (20 - int(s.utilization_pct / 5))
                bottleneck = " ← GOULOT" if s.utilization_pct >= 95 else ""
                lines.append(
                    f"  Poste {s.station_id} ({s.name:20s}): {bar} {s.utilization_pct:.0f}%"
                    f"  file={s.avg_queue_length:.1f}/{s.max_queue_length}"
                    f"{bottleneck}"
                )
        return "\n".join(lines)


def _rnd(duration: float, variability: float) -> float:
    """Applique une variabilité aléatoire à une durée."""
    if variability <= 0 or duration <= 0:
        return duration
    return random.gauss(duration, duration * variability)


class SimulationEngine:
    """Moteur de simulation SimPy pour atelier de confection."""

    def __init__(self, result: BalancingResult, config: Optional[SimulationConfig] = None):
        self.result = result
        self.config = config or SimulationConfig()
        self.env = simpy.Environment()
        random.seed(self.config.random_seed)

        self.part_count = 0
        self.completed_parts: list[float] = []
        self.station_data: dict[int, dict] = {}
        self.wip_history: list[tuple[float, int]] = []

        self._build_stations()

    def _build_stations(self):
        """Construit les ressources SimPy pour chaque poste."""
        for sd in self.result.station_details:
            sid = sd["station"]
            # Capacité = nombre d'ouvriers, min 1
            capacity = max(1, len(sd.get("workers", [])))
            self.station_data[sid] = {
                "resource": simpy.Resource(self.env, capacity=capacity),
                "processed": 0,
                "time_worked": 0.0,
                "queue_lengths": [],
                "max_queue": 0,
                "waiting_times": [],
                "name": sd.get("name", f"Poste {sid}"),
                "operations": sd.get("operations", []),
            }

    def _process_at_station(self, part_id: int, op: Operation, sid: int) -> float:
        """Simule le processing d'une opération sur un poste."""
        sd = self.station_data[sid]
        resource = sd["resource"]

        # Enregistre la file avant la requête
        sd["queue_lengths"].append(len(resource.queue))
        if len(resource.queue) > sd["max_queue"]:
            sd["max_queue"] = len(resource.queue)

        arrive = self.env.now
        with resource.request() as req:
            yield req
            wait = self.env.now - arrive
            sd["waiting_times"].append(wait)

            duration = _rnd(op.duration, self.config.variability)
            yield self.env.timeout(duration)
            sd["time_worked"] += duration

        sd["processed"] += 1
        return self.env.now

    def _part_process(self, part_id: int):
        """Processus complet d'une pièce à travers toutes ses opérations."""
        problem = self.result.problem
        # Ordonnancement topologique: opérations dans l'ordre de précédence
        ops = list(problem.operations)
        # Trier par assigned_station, puis par ordre du problème (indice préservé)
        op_order = {id(o): i for i, o in enumerate(ops)}
        ops.sort(key=lambda o: (
            self.result.operation_assignments.get(o.id, 999),
            op_order.get(id(o), 0),
        ))

        for op in ops:
            sid = self.result.operation_assignments.get(op.id)
            if sid is None or sid < 0:
                continue
            # Transport inter-poste
            yield self.env.timeout(self.config.transport_time_min)
            yield from self._process_at_station(part_id, op, sid)

        self.completed_parts.append(self.env.now)

    def _part_generator(self):
        """Génère les pièces selon l'intervalle d'arrivée."""
        # Phase de warm-up: génère rapidement les premières pièces
        for i in range(self.config.warmup_parts):
            self.part_count += 1
            self.env.process(self._part_process(self.part_count))
            yield self.env.timeout(0.1)

        # Phase de production
        for i in range(self.config.num_parts):
            self.part_count += 1
            self.env.process(self._part_process(self.part_count))
            if self.config.arrival_interval_min > 0:
                yield self.env.timeout(self.config.arrival_interval_min)
            else:
                # Au plus vite: délai minimal pour laisser le process démarrer
                yield self.env.timeout(0.05)

    def _wip_monitor(self, interval: float = 1.0):
        """Surveille le WIP à intervalle régulier."""
        while True:
            wip = sum(
                len(sd["resource"].users) + len(sd["resource"].queue)
                for sd in self.station_data.values()
            )
            self.wip_history.append((self.env.now, wip))
            yield self.env.timeout(interval)

    def run(self) -> SimulationResult:
        """Exécute la simulation et retourne les résultats."""
        try:
            # Calculer un temps max réaliste
            total_work = sum(op.duration for op in self.result.problem.operations)
            min_stations = max(1, self.result.stations_used)
            min_cycle = total_work / min_stations if min_stations else total_work
            total_parts = self.config.warmup_parts + self.config.num_parts
            max_time = total_parts * (min_cycle + self.config.transport_time_min * 2) * 2
            max_time = max(max_time, 60.0)  # au moins 1h

            self.env.process(self._part_generator())
            self.env.process(self._wip_monitor())
            self.env.run(until=max_time)
        except Exception as e:
            return SimulationResult(success=False, error_message=str(e))

        if not self.completed_parts:
            return SimulationResult(
                success=False,
                error_message="Aucune pièce terminée",
                config=self.config,
            )

        # Calcul des stats globales
        completed = self.completed_parts[self.config.warmup_parts:]
        if not completed:
            completed = self.completed_parts

        sim_time = completed[-1] if completed else self.env.now

        station_stats = []
        for sid, sd in sorted(self.station_data.items()):
            utilization = (sd["time_worked"] / (sim_time * sd["resource"].capacity)) * 100 if sim_time > 0 else 0
            avg_q = statistics.mean(sd["queue_lengths"]) if sd["queue_lengths"] else 0
            avg_w = statistics.mean(sd["waiting_times"]) if sd["waiting_times"] else 0
            station_stats.append(StationStats(
                station_id=sid,
                name=sd["name"],
                total_processed=sd["processed"],
                utilization_pct=min(100.0, utilization),
                avg_queue_length=avg_q,
                max_queue_length=sd["max_queue"],
                avg_waiting_time=avg_w,
                operations=sd["operations"],
            ))

        # Cycle time des pièces complétées
        ct_list = []
        for i in range(1, len(completed)):
            ct_list.append(completed[i] - completed[i - 1])

        avg_wip = statistics.mean([w for _, w in self.wip_history]) if self.wip_history else 0

        throughput = (len(completed) / sim_time * 60) if sim_time > 0 else 0

        return SimulationResult(
            config=self.config,
            total_parts_completed=len(completed),
            simulation_time_min=sim_time,
            throughput_per_hour=throughput,
            avg_cycle_time_min=statistics.mean(ct_list) if ct_list else 0,
            std_cycle_time_min=statistics.stdev(ct_list) if len(ct_list) > 1 else 0,
            min_cycle_time_min=min(ct_list) if ct_list else 0,
            max_cycle_time_min=max(ct_list) if ct_list else 0,
            avg_wip=avg_wip,
            station_stats=station_stats,
            part_completion_times=completed,
        )


# =============================================================================
# Jumeau numérique : journée de ligne simulée par paquets (v2.3, 2026-10-27)
# -----------------------------------------------------------------------------
# Extension additive : n'utilise ni ne modifie les solveurs. Travaille sur un
# « plan » de ligne en dictionnaires (stations ordonnées, ouvrières, opérations)
# tel que produit par un calcul d'équilibrage, pour :
#   - simuler une journée (paquets d'encours, ouvrières = ressources SimPy,
#     pannes, absences, variabilité, efficience, distances d'implantation) ;
#   - appliquer des scénarios « et si » (absence + réaffectation par compétences,
#     changement d'effectif, taille de paquet…) ;
#   - contrôler l'implantation selon des règles Lean (retours en arrière,
#     croisements, ouvrière trop loin de son 2e poste).
# Le flux suit l'ordre des stations (ligne série) : les branches parallèles de
# la gamme sont aplaties dans l'ordre des stations.
# =============================================================================

LAYOUT_SPACING_M = 1.6      # entraxe de deux postes voisins
LAYOUT_AISLE_M = 1.4        # largeur de l'allée d'une cellule en U
LONG_TRANSFER_M = 3.0       # transfert de paquet jugé long
FAR_SECOND_STATION_M = 2.5  # ouvrière trop loin de son 2e poste
UNQUALIFIED_EFFICIENCY = 0.5


@dataclass
class LineDayConfig:
    """Paramètres d'une journée simulée."""
    shift_minutes: float = 480.0          # durée simulée (plafonnée par l'appelant)
    bundle_size: int = 10                 # pièces par paquet
    efficiency: float = 1.0               # efficience globale (1 = temps standard)
    variability: float = 0.10             # coefficient de variation du temps par pièce
    handling_min: float = 0.10            # prise + dépose d'un paquet
    walk_speed_m_per_min: float = 50.0    # déplacement à pied avec un paquet (~0,8 m/s)
    start_wip_bundles: int = 1            # paquets en attente devant chaque station au départ
    initial_wip: Optional[dict] = None    # {station: pièces} : remplace start_wip_bundles
    feed_limit: Optional[int] = None      # pièces à lancer au maximum (reste de commande)
    wip_cap_bundles: Optional[int] = None # plafond d'encours de la ligne (CONWIP) ; défaut = Σ(opératrices+1)
    seed: int = 42
    trace: bool = True
    max_trace_events: int = 40000
    snapshot_every_min: float = 5.0


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def default_layout(stations: list, kind: str = "line", spacing: float = LAYOUT_SPACING_M,
                   aisle: float = LAYOUT_AISLE_M) -> dict:
    """Positions par défaut (mètres) : en ligne, ou en U (aller puis retour face à face)."""
    ids = [int(s["station"] if isinstance(s, dict) else s) for s in stations]
    pos: dict[str, dict] = {}
    if kind == "u" and len(ids) > 2:
        half = math.ceil(len(ids) / 2)
        for i, sid in enumerate(ids):
            if i < half:
                pos[str(sid)] = {"x": round(i * spacing, 2), "y": 0.0}
            else:
                j = len(ids) - 1 - i          # retour : face au poste aller
                pos[str(sid)] = {"x": round(j * spacing + (spacing / 2 if len(ids) % 2 else 0), 2),
                                 "y": aisle}
    else:
        kind = "line"
        for i, sid in enumerate(ids):
            pos[str(sid)] = {"x": round(i * spacing, 2), "y": 0.0}
    return {"kind": kind, "positions": pos}


def _positions(plan: dict, layout: Optional[dict]) -> dict[int, tuple[float, float]]:
    order = [int(s["station"]) for s in plan.get("stations", [])]
    base = default_layout(order, (layout or {}).get("kind", "line"))["positions"]
    given = (layout or {}).get("positions") or {}
    out = {}
    for sid in order:
        p = given.get(str(sid)) or given.get(sid) or base[str(sid)]
        out[sid] = (_num(p.get("x")), _num(p.get("y")))
    return out


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _station_skills(st: dict) -> set:
    req: set = set()
    for op in st.get("operations", []):
        for s in op.get("skills") or op.get("required_skills") or []:
            if s:
                req.add(str(s))
    return req


def station_workers(plan: dict) -> dict[int, list[str]]:
    """Ouvrières de chaque station ; postes sans nom = ouvrières anonymes « S<n>-<k> »."""
    out: dict[int, list[str]] = {}
    for st in plan.get("stations", []):
        sid = int(st["station"])
        ids = [str(w) for w in (st.get("worker_ids") or []) if w]
        n = max(1, int(st.get("operators") or len(ids) or 1))
        while len(ids) < n:
            ids.append(f"S{sid}-{len(ids) + 1}")
        out[sid] = ids
    return out


def _worker_label(plan: dict, wid: str) -> str:
    info = (plan.get("workers") or {}).get(wid) or {}
    if info.get("name"):
        return str(info["name"])
    for st in plan.get("stations", []):
        ids = list(st.get("worker_ids") or [])
        names = list(st.get("workers") or [])
        if wid in ids and ids.index(wid) < len(names):
            return str(names[ids.index(wid)])
    if wid.startswith("S") and "-" in wid:
        return f"Opératrice {wid[1:]}"
    return wid


def apply_scenario(plan: dict, scenario: Optional[dict] = None) -> tuple[dict, list[str]]:
    """Applique un scénario au plan (copie) et renvoie (plan, notes).

    scenario : {"absent": [worker_id], "reassign": bool, "operators": {station: n}}
    - absence : l'ouvrière est retirée ; si une station n'a plus personne et que
      la réaffectation est demandée, on prend l'ouvrière qualifiée (compétences
      requises ⊆ compétences) dont le départ pénalise le moins la ligne : déplacée
      si sa station garde quelqu'un, sinon partagée entre ses deux postes.
      Sans ouvrière qualifiée : la moins chargée tient le poste à 50 % de rendement.
    - operators : effectif imposé par station (renforts anonymes ou retraits).
    """
    import copy
    scenario = scenario or {}
    p = copy.deepcopy(plan)
    p.setdefault("workers", {})
    notes: list[str] = []
    sw = station_workers(p)
    minutes = {int(s["station"]): _num(s.get("minutes")) for s in p.get("stations", [])}
    unqualified: dict[str, set] = {}

    # Changement d'effectif
    for k, n in (scenario.get("operators") or {}).items():
        sid, n = int(k), max(0, int(n))
        if sid not in sw:
            continue
        cur = sw[sid]
        if n > len(cur):
            for i in range(n - len(cur)):
                wid = f"R{sid}-{i + 1}"
                p["workers"][wid] = {"name": f"Renfort {sid}.{i + 1}", "skills": sorted(_station_skills(
                    next(s for s in p["stations"] if int(s["station"]) == sid))), "efficiency": 1.0}
                cur.append(wid)
            notes.append(f"Station {sid} : effectif porté à {n}.")
        elif n < len(cur):
            sw[sid] = cur[:n]
            notes.append(f"Station {sid} : effectif réduit à {n}.")

    # Absences
    absent = {str(w) for w in scenario.get("absent") or []}
    for sid in sw:
        sw[sid] = [w for w in sw[sid] if w not in absent]
    if absent:
        notes.append("Absente(s) : " + ", ".join(_worker_label(p, w) for w in sorted(absent)) + ".")

    reassign = scenario.get("reassign", True)
    st_by_id = {int(s["station"]): s for s in p.get("stations", [])}
    for sid in sorted(sw):
        if sw[sid]:
            continue
        if not reassign:
            notes.append(f"Station {sid} sans ouvrière : la ligne est bloquée à ce poste.")
            continue
        req = _station_skills(st_by_id[sid])
        best = None
        for donor, ws in sw.items():
            if donor == sid:
                continue
            for w in ws:
                if w in absent:
                    continue
                skills = set((p["workers"].get(w) or {}).get("skills") or [])
                qualified = req.issubset(skills) if req else True
                n = len(ws)
                if n >= 2:
                    cost = max(minutes[donor] / (n - 1), minutes[sid])
                    mode = "move"
                else:
                    cost = minutes[donor] / n + minutes[sid]
                    mode = "share"
                key = (not qualified, cost)
                if best is None or key < best[0]:
                    best = (key, w, donor, mode, qualified)
        if best is None:
            notes.append(f"Station {sid} sans ouvrière disponible : la ligne est bloquée à ce poste.")
            continue
        _, w, donor, mode, qualified = best
        label = _worker_label(p, w)
        if mode == "move":
            sw[donor] = [x for x in sw[donor] if x != w]
            notes.append(f"Station {sid} : {label} quitte la station {donor} (réaffectation selon compétences).")
        else:
            notes.append(f"Station {sid} : {label} tient aussi la station {donor} (poste partagé).")
        sw[sid] = [w]
        if not qualified:
            unqualified.setdefault(w, set()).add(sid)
            notes.append(f"Aucune ouvrière qualifiée pour la station {sid} : {label} la tient à "
                         f"{int(UNQUALIFIED_EFFICIENCY * 100)} % de rendement.")

    for st in p.get("stations", []):
        sid = int(st["station"])
        st["worker_ids"] = list(sw[sid])
        st["workers"] = [_worker_label(p, w) for w in sw[sid]]
        st["operators"] = len(sw[sid])
    p["unqualified"] = {w: sorted(s) for w, s in unqualified.items()}
    return p, notes


def lean_check(plan: dict, layout: Optional[dict] = None) -> dict:
    """Règles Lean sur l'implantation : distances, retours en arrière, croisements, 2e poste éloigné."""
    order = [int(s["station"]) for s in plan.get("stations", [])]
    pos = _positions(plan, layout)
    kind = (layout or {}).get("kind", "line")
    transfers, warnings = [], []
    for a, b in zip(order, order[1:]):
        d = _dist(pos[a], pos[b])
        transfers.append({"from": a, "to": b, "meters": round(d, 2)})
        if d > LONG_TRANSFER_M:
            warnings.append({"kind": "long_transfer", "stations": [a, b],
                             "message": f"Transfert {a} → {b} de {d:.1f} m : rapprocher les postes."})
    # Retour en arrière : projection sur l'axe entrée → sortie (sauf cellule en U, qui revient par construction)
    if kind != "u" and len(order) >= 2:
        ax = (pos[order[-1]][0] - pos[order[0]][0], pos[order[-1]][1] - pos[order[0]][1])
        norm = math.hypot(*ax) or 1.0
        for a, b in zip(order, order[1:]):
            proj = ((pos[b][0] - pos[a][0]) * ax[0] + (pos[b][1] - pos[a][1]) * ax[1]) / norm
            if proj < -0.3:
                warnings.append({"kind": "backtrack", "stations": [a, b],
                                 "message": f"Retour en arrière de la station {a} vers {b} ({-proj:.1f} m) : "
                                            f"le flux doit avancer sans revenir."})
    # Croisements de flux (diagramme spaghetti)
    segs = list(zip(order, order[1:]))

    def ccw(p1, p2, p3):
        return (p3[1] - p1[1]) * (p2[0] - p1[0]) - (p2[1] - p1[1]) * (p3[0] - p1[0])

    for i in range(len(segs)):
        for j in range(i + 2, len(segs)):
            a1, a2 = pos[segs[i][0]], pos[segs[i][1]]
            b1, b2 = pos[segs[j][0]], pos[segs[j][1]]
            d1, d2 = ccw(b1, b2, a1), ccw(b1, b2, a2)
            d3, d4 = ccw(a1, a2, b1), ccw(a1, a2, b2)
            if d1 * d2 < 0 and d3 * d4 < 0:
                warnings.append({"kind": "crossing", "stations": [segs[i][0], segs[i][1], segs[j][0], segs[j][1]],
                                 "message": f"Le flux {segs[i][0]} → {segs[i][1]} croise le flux "
                                            f"{segs[j][0]} → {segs[j][1]}."})
    # Ouvrière sur plusieurs postes trop éloignés
    seen: dict[str, list[int]] = {}
    for sid, ws in station_workers(plan).items():
        for w in ws:
            seen.setdefault(w, []).append(sid)
    far = []
    for w, sts in seen.items():
        if len(sts) < 2:
            continue
        d = max(_dist(pos[a], pos[b]) for a in sts for b in sts)
        if d > FAR_SECOND_STATION_M:
            far.append(w)
            warnings.append({"kind": "far_second_station", "worker": w, "stations": sts,
                             "message": f"{_worker_label(plan, w)} travaille sur les stations "
                                        f"{', '.join(map(str, sts))} distantes de {d:.1f} m : "
                                        f"les mettre côte à côte ou face à face (cellule en U)."})
    per_piece = sum(t["meters"] for t in transfers)
    length = max((_dist(pos[a], pos[b]) for a in order for b in order), default=0.0)
    if kind != "u" and len(order) >= 8 and (far or length > 12):
        warnings.append({"kind": "suggest_u", "message": f"Ligne de {length:.0f} m : une cellule en U "
                                                          f"rapprocherait entrée et sortie et les postes partagés."})
    return {"kind": kind, "transfers": transfers, "meters_per_bundle": round(per_piece, 2),
            "line_length_m": round(length, 2), "warnings": warnings}


class LineDaySimulator:
    """Journée de ligne : paquets d'encours, ouvrières (ressources SimPy), pannes."""

    def __init__(self, plan: dict, layout: Optional[dict] = None, config: Optional[LineDayConfig] = None,
                 breakdowns: Optional[list] = None):
        self.plan = plan
        self.cfg = config or LineDayConfig()
        self.rng = random.Random(self.cfg.seed)
        self.env = simpy.Environment()
        self.order = [int(s["station"]) for s in plan.get("stations", [])]
        self.pos = _positions(plan, layout)
        self.sw = station_workers(plan)
        # station_workers complète les postes vides : on respecte un effectif nul explicite
        for st in plan.get("stations", []):
            if "operators" in st and int(st.get("operators") or 0) == 0 and not st.get("worker_ids"):
                self.sw[int(st["station"])] = []
        self.minutes = {int(s["station"]): _num(s.get("minutes")) for s in plan.get("stations", [])}
        winfo = plan.get("workers") or {}
        unq = plan.get("unqualified") or {}
        self.weff: dict[tuple[str, int], float] = {}
        for sid, ws in self.sw.items():
            for w in ws:
                e = _num((winfo.get(w) or {}).get("efficiency"), 1.0) or 1.0
                if sid in (unq.get(w) or []):
                    e *= UNQUALIFIED_EFFICIENCY
                self.weff[(w, sid)] = e
        self.res = {w: simpy.Resource(self.env, capacity=1) for ws in self.sw.values() for w in ws}
        self.down: dict[int, list[tuple[float, float]]] = {sid: [] for sid in self.order}
        for b in breakdowns or []:
            sid = int(b.get("station", 0))
            if sid in self.down:
                s0 = max(0.0, _num(b.get("start_min")))
                self.down[sid].append((s0, s0 + max(0.0, _num(b.get("duration_min")))))
        self.st = {sid: {"wip": 0, "max_wip": 0, "waiting": 0, "done": 0, "busy": 0.0, "waits": [],
                         "down_min": 0.0} for sid in self.order}
        self.wbusy = {w: 0.0 for w in self.res}
        self.wwalk = {w: 0.0 for w in self.res}
        self.wlast: dict[str, int] = {}
        self.events: list[list] = []
        self.bundles: dict[int, int] = {}
        self.trace_truncated = False
        self.finished: list[tuple[float, int]] = []
        self.lead_times: list[float] = []
        self.transport_m = 0.0
        self.launched = 0
        self.next_id = 0
        self.snapshots: list[list] = []
        self.in_transit = 0
        self.reserved = 0
        size = max(1, int(self.cfg.bundle_size))
        cap_b = self.cfg.wip_cap_bundles or sum(len(self.sw.get(s) or []) + 1 for s in self.order)
        self.cap_pieces = max(1, int(cap_b)) * size

    # -- utilitaires
    def _ev(self, *row):
        if not self.cfg.trace:
            return
        if len(self.events) >= self.cfg.max_trace_events:
            self.trace_truncated = True
            return
        self.events.append([round(self.env.now, 2), *row])

    def _down_until(self, sid: int, t: float) -> Optional[float]:
        for a, b in self.down[sid]:
            if a <= t < b:
                return b
        return None

    def _extend_for_downtime(self, sid: int, start: float, dur: float) -> float:
        end, counted = start + dur, set()
        changed = True
        while changed:
            changed = False
            for i, (a, b) in enumerate(self.down[sid]):
                if i in counted:
                    continue
                if a < end and b > start:
                    counted.add(i)
                    end += min(b, end) - max(a, start) if a >= start else b - start
                    changed = True
        return end - start

    def _duration(self, sid: int, size: int, w: str) -> float:
        m = self.minutes[sid] / max(1e-6, self.cfg.efficiency * self.weff.get((w, sid), 1.0))
        mean = size * m
        cv = max(0.0, self.cfg.variability)
        if cv <= 0 or mean <= 0:
            return mean
        sd = m * cv * math.sqrt(size)
        return max(0.3 * mean, self.rng.gauss(mean, sd))

    def _can_launch(self, size: int) -> bool:
        lim = self.cfg.feed_limit
        return lim is None or self.launched + size <= lim

    def _launch(self, at_index: int = 0, size: Optional[int] = None, fresh: bool = True):
        size = size or max(1, int(self.cfg.bundle_size))
        self.next_id += 1
        bid = self.next_id
        self.bundles[bid] = size
        if fresh:
            self.launched += size
        self.env.process(self._bundle(bid, size, at_index, fresh))

    # -- processus
    def _bundle(self, bid: int, size: int, start_index: int, fresh: bool):
        t0 = self.env.now
        prev = None
        for idx in range(start_index, len(self.order)):
            sid = self.order[idx]
            if prev is not None:
                d = _dist(self.pos[prev], self.pos[sid])
                self.transport_m += d
                self.in_transit += size
                yield self.env.timeout(self.cfg.handling_min + d / max(1e-6, self.cfg.walk_speed_m_per_min))
                self.in_transit -= size
            st = self.st[sid]
            st["wip"] += size
            if idx == 0 and fresh and self.reserved > 0:
                self.reserved -= 1                  # place déjà comptée par le lanceur
            else:
                st["waiting"] += 1
            st["max_wip"] = max(st["max_wip"], st["wip"])
            arrive = self.env.now
            self._ev(bid, sid, 0)
            workers = self.sw.get(sid) or []
            if not workers:
                return  # poste sans ouvrière : le paquet reste bloqué
            while True:
                up = self._down_until(sid, self.env.now)
                if up is None:
                    break
                yield self.env.timeout(up - self.env.now)
            reqs = [(w, self.res[w].request()) for w in workers]
            yield self.env.any_of([r for _, r in reqs])
            chosen = None
            for w, r in reqs:
                if r.triggered and chosen is None:
                    chosen = (w, r)
                elif r.triggered:
                    self.res[w].release(r)
                else:
                    r.cancel()
            w, req = chosen
            st["waiting"] -= 1
            st["waits"].append(self.env.now - arrive)
            if self.wlast.get(w) not in (None, sid):
                self.wwalk[w] += _dist(self.pos[self.wlast[w]], self.pos[sid])
            self.wlast[w] = sid
            work = self._duration(sid, size, w)
            total = self._extend_for_downtime(sid, self.env.now, work)
            st["down_min"] += total - work
            self._ev(bid, sid, 1, w)
            yield self.env.timeout(total)
            self.res[w].release(req)
            st["busy"] += work
            self.wbusy[w] += work
            st["done"] += size
            st["wip"] -= size
            self._ev(bid, sid, 2, w)
            prev = sid
        self.finished.append((self.env.now, size))
        if start_index == 0 and fresh:
            self.lead_times.append(self.env.now - t0)

    def _feeder(self):
        """Lancement en tête de ligne : un paquet attend toujours devant le 1er poste,
        tant que l'encours total reste sous le plafond (flux tiré, CONWIP)."""
        size = max(1, int(self.cfg.bundle_size))
        first = self.order[0]
        while True:
            line_wip = sum(st["wip"] for st in self.st.values()) + self.in_transit
            if (self.st[first]["waiting"] < 1 and line_wip + size <= self.cap_pieces
                    and self._can_launch(size)):
                self._launch(0)
                self.st[first]["waiting"] += 1      # réservé jusqu'à l'arrivée effective
                self.reserved += 1
            yield self.env.timeout(0.25)

    def _snapshots(self):
        every = max(0.5, self.cfg.snapshot_every_min)
        while True:
            self.snapshots.append([round(self.env.now, 1), [self.st[s]["wip"] for s in self.order],
                                   sum(n for _, n in self.finished)])
            yield self.env.timeout(every)

    def run(self) -> dict:
        cfg = self.cfg
        size = max(1, int(cfg.bundle_size))
        if not self.order:
            return {"success": False, "error": "Aucune station dans ce calcul."}
        # Encours de départ devant chaque station (aval) ; amont : flux tiré
        init = cfg.initial_wip
        for idx, sid in enumerate(self.order):
            if init is not None:
                pieces = int(_num(init.get(sid, init.get(str(sid), 0))))
            else:
                pieces = cfg.start_wip_bundles * size if idx > 0 else 0
            while pieces > 0:
                n = min(size, pieces)
                self._launch(idx, n, fresh=False)
                pieces -= n
        first_ops = max(1, len(self.sw.get(self.order[0]) or [1]))
        for _ in range(first_ops):
            if self._can_launch(size):
                self._launch(0)
        self.env.process(self._feeder())
        self.env.process(self._snapshots())
        self.env.run(until=cfg.shift_minutes)
        return self._result()

    def _result(self) -> dict:
        T = max(1e-6, self.cfg.shift_minutes)
        done = sum(n for _, n in self.finished)
        stations = []
        for sid in self.order:
            st = self.st[sid]
            nw = len(self.sw.get(sid) or [])
            util = st["busy"] / (nw * T) * 100 if nw else 0.0
            series = [snap[1][self.order.index(sid)] for snap in self.snapshots]
            stations.append({
                "station": sid, "operators": nw, "workers": list(self.sw.get(sid) or []),
                "pieces": st["done"], "utilization_pct": round(min(100.0, util), 1),
                "avg_wait_min": round(statistics.mean(st["waits"]), 2) if st["waits"] else 0.0,
                "max_wip": st["max_wip"], "avg_wip": round(statistics.mean(series), 1) if series else 0.0,
                "down_min": round(st["down_min"], 1),
                "minutes_per_piece": round(self.minutes[sid], 4),
                "load_per_operator": round(self.minutes[sid] / nw, 4) if nw else None,
            })
        blocked = [s["station"] for s in stations if s["operators"] == 0]
        wutil = {w: self.wbusy[w] / T for w in self.res}
        for s in stations:
            s["worker_util_max"] = round(max((wutil[w] for w in s["workers"]), default=0) * 100, 1)
        if blocked:
            bottleneck = blocked[0]
        else:
            # goulot = poste dont l'ouvrière la plus occupée l'est le plus ; égalité : plus grosse file devant
            bottleneck = max(stations, key=lambda s: (round(s["worker_util_max"]), s["avg_wip"]))["station"] \
                if stations else None
        hours = max(1, math.ceil(T / 60))
        hourly = [0] * hours
        for t, n in self.finished:
            hourly[min(hours - 1, int(t // 60))] += n
        workers = [{"id": w, "name": _worker_label(self.plan, w),
                    "stations": [s for s, ws in self.sw.items() if w in ws],
                    "utilization_pct": round(min(100.0, self.wbusy[w] / T * 100), 1),
                    "walk_m": round(self.wwalk[w], 1)} for w in self.res]
        wip_max = max((sum(s[1]) for s in self.snapshots), default=0)
        return {
            "success": True,
            "pieces": done,
            "per_hour": round(done / T * 60, 1),
            "shift_minutes": round(T, 1),
            "bottleneck": bottleneck,
            "blocked_stations": blocked,
            "wip_max": wip_max,
            "wip_avg": round(statistics.mean([sum(s[1]) for s in self.snapshots]), 1) if self.snapshots else 0,
            "lead_time_min": round(statistics.mean(self.lead_times), 1) if self.lead_times else None,
            "avg_wait_min": round(statistics.mean([w for s in self.order for w in self.st[s]["waits"]]), 2)
            if any(self.st[s]["waits"] for s in self.order) else 0.0,
            "transport_m": round(self.transport_m, 1),
            "walk_m": round(sum(self.wwalk.values()), 1),
            "hourly": hourly,
            "stations": stations,
            "workers": workers,
            "snapshots": self.snapshots,
            "trace": {"events": self.events, "bundles": self.bundles, "truncated": self.trace_truncated,
                      "codes": {"0": "arrivée", "1": "début", "2": "fin"}},
            "config": {"bundle_size": max(1, int(self.cfg.bundle_size)), "efficiency": self.cfg.efficiency,
                       "variability": self.cfg.variability, "handling_min": self.cfg.handling_min,
                       "seed": self.cfg.seed},
        }


def simulate_line_day(plan: dict, layout: Optional[dict] = None, config: Optional[LineDayConfig] = None,
                      scenario: Optional[dict] = None) -> dict:
    """Point d'entrée : applique le scénario, simule la journée, ajoute le contrôle Lean.

    scenario : clés de `apply_scenario` + "breakdowns": [{station, start_min, duration_min}].
    """
    scen = scenario or {}
    p, notes = apply_scenario(plan, scen)
    sim = LineDaySimulator(p, layout, config, scen.get("breakdowns"))
    res = sim.run()
    res["notes"] = notes
    res["lean"] = lean_check(p, layout)
    res["plan"] = {"stations": [{"station": int(s["station"]), "worker_ids": s.get("worker_ids", []),
                                 "workers": s.get("workers", []), "operators": s.get("operators", 0),
                                 "minutes": _num(s.get("minutes"))} for s in p.get("stations", [])],
                   "unqualified": p.get("unqualified", {})}
    for b in scen.get("breakdowns") or []:
        res["notes"].append(f"Panne station {int(b.get('station', 0))} : {_num(b.get('duration_min')):.0f} min "
                            f"à partir de la minute {_num(b.get('start_min')):.0f}.")
    return res
