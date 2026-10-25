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
