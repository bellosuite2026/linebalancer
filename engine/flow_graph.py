"""
Graphe de flux de production avec NetworkX.
Modélise le mouvement des matières entre types de machines, sections et postes.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import networkx as nx

from engine.models import BalancingResult, Operation
from engine.models_v2 import TransportMode


@dataclass
class FlowEdgeAttr:
    """Attributs d’un arc de flux entre deux nœuds du graphe."""
    volume: float = 0.0           # Pièces/heure
    total_duration: float = 0.0   # Temps total cumulé (min)
    transport_mode: str = "manual"
    distance_m: float = 0.0
    operation_ids: list[str] = field(default_factory=list)

    def merge(self, other: FlowEdgeAttr) -> FlowEdgeAttr:
        self.volume += other.volume
        self.total_duration += other.total_duration
        self.operation_ids.extend(other.operation_ids)
        return self


@dataclass
class FlowNodeAttr:
    """Attributs d’un nœud du graphe de flux."""
    label: str = ""
    node_type: str = ""  # operation / machine_type / section / workstation
    duration: float = 0.0
    machine_type: str = ""
    section: str = ""
    total_in: float = 0.0
    total_out: float = 0.0


class ProductionFlowGraph:
    """Graphe orienté du flux de production.

    Deux niveaux d'agrégation :
      - Niveau opération (nœuds individuels)
      - Niveau type machine (agrégé par machine_type)
      - Niveau section atelier (agrégé par section)
    """

    def __init__(self):
        self.graph = nx.DiGraph()

    # ── Construction depuis un BalancingResult ──────────────────────

    @classmethod
    def from_balancing_result(cls, result: BalancingResult) -> ProductionFlowGraph:
        """Construit le graphe depuis un résultat d'équilibrage."""
        g = cls()
        ops = result.problem.operations
        assignments = result.operation_assignments

        for op in ops:
            sid = assignments.get(op.id, -1)
            g.graph.add_node(
                f"op_{op.id}",
                label=op.name,
                node_type="operation",
                duration=op.duration,
                machine_type=op.machine_type or "unknown",
                section=op.section or "general",
                station=sid,
            )
            # Agrégation type machine
            mt_key = f"mt_{op.machine_type}" if op.machine_type else None
            if mt_key and mt_key not in g.graph:
                g.graph.add_node(mt_key, label=op.machine_type, node_type="machine_type")
            # Agrégation section
            sec_key = f"sec_{op.section}" if op.section else None
            if sec_key and sec_key not in g.graph:
                g.graph.add_node(sec_key, label=op.section, node_type="section")

        # Arcs depuis les prédécesseurs
        op_map = {op.id: op for op in ops}
        for op in ops:
            for pred_id in op.predecessors:
                pred = op_map.get(pred_id)
                if pred is None:
                    continue
                # Arc opération → opération
                g._add_edge(f"op_{pred.id}", f"op_{op.id}", op, pred)

                # Arc type machine → type machine
                if pred.machine_type and op.machine_type and pred.machine_type != op.machine_type:
                    g._add_mt_edge(pred.machine_type, op.machine_type, op)

                # Arc section → section
                if pred.section and op.section and pred.section != op.section:
                    g._add_section_edge(pred.section, op.section, op)

        return g

    @classmethod
    def from_workflow(cls, workflow: dict) -> ProductionFlowGraph:
        """Construit le graphe depuis le workflow de la vue logique (dict brut)."""
        g = cls()
        nodes = {n["id"]: n for n in workflow.get("nodes", [])}

        for nid, node in nodes.items():
            cfg = node.get("config", {})
            g.graph.add_node(
                f"op_{nid}",
                label=cfg.get("name", node.get("title", nid)),
                node_type=node["type"],
                duration=cfg.get("duration", 0),
                machine_type=cfg.get("machine_type", ""),
                section=cfg.get("section", ""),
            )

            mt = cfg.get("machine_type", "")
            if mt:
                mt_key = f"mt_{mt}"
                if mt_key not in g.graph:
                    g.graph.add_node(mt_key, label=mt, node_type="machine_type")

            sec = cfg.get("section", "")
            if sec:
                sec_key = f"sec_{sec}"
                if sec_key not in g.graph:
                    g.graph.add_node(sec_key, label=sec, node_type="section")

        # Arcs depuis le champ predecessors
        for nid, node in nodes.items():
            cfg = node.get("config", {})
            preds_str = cfg.get("predecessors", "")
            if isinstance(preds_str, str):
                pred_ids = [p.strip() for p in preds_str.replace(";", ",").split(",") if p.strip()]
            elif isinstance(preds_str, list):
                pred_ids = preds_str
            else:
                continue

            for pred_id in pred_ids:
                if pred_id in nodes:
                    g._add_edge(f"op_{pred_id}", f"op_{nid}", node, nodes[pred_id])

                    pred_mt = nodes[pred_id].get("config", {}).get("machine_type", "")
                    mt = cfg.get("machine_type", "")
                    if pred_mt and mt and pred_mt != mt:
                        g._add_mt_edge(pred_mt, mt, node)

                    pred_sec = nodes[pred_id].get("config", {}).get("section", "")
                    sec = cfg.get("section", "")
                    if pred_sec and sec and pred_sec != sec:
                        g._add_section_edge(pred_sec, sec, node)

        return g

    # ── Ajout d'arcs ───────────────────────────────────────────────

    @staticmethod
    def _ensure_flow(edge_data: dict) -> FlowEdgeAttr:
        f = edge_data.get("flow", {})
        if isinstance(f, FlowEdgeAttr):
            return f
        return FlowEdgeAttr(**{k: v for k, v in f.items() if k in FlowEdgeAttr.__dataclass_fields__})

    def _add_edge(self, src: str, dst: str, op: Any, pred: Any = None):
        attr = FlowEdgeAttr(
            volume=1.0,
            total_duration=op.duration if hasattr(op, 'duration') else op.get('config', {}).get('duration', 0),
            operation_ids=[getattr(op, 'id', None) or op.get('id', '')],
        )
        if self.graph.has_edge(src, dst):
            existing = self.graph.edges[src, dst].get("flow", FlowEdgeAttr())
            existing.merge(attr)
        else:
            self.graph.add_edge(src, dst, flow=attr)

    def _add_mt_edge(self, src_mt: str, dst_mt: str, op: Any):
        src, dst = f"mt_{src_mt}", f"mt_{dst_mt}"
        attr = FlowEdgeAttr(volume=1.0)
        if self.graph.has_edge(src, dst):
            self.graph.edges[src, dst]["flow"].merge(attr)
        else:
            self.graph.add_edge(src, dst, flow=attr)

    def _add_section_edge(self, src_sec: str, dst_sec: str, op: Any):
        src, dst = f"sec_{src_sec}", f"sec_{dst_sec}"
        attr = FlowEdgeAttr(volume=1.0)
        if self.graph.has_edge(src, dst):
            self.graph.edges[src, dst]["flow"].merge(attr)
        else:
            self.graph.add_edge(src, dst, flow=attr)

    # ── Analyses ───────────────────────────────────────────────────

    def section_flow_matrix(self) -> dict[str, dict[str, float]]:
        """Matrice de flux entre sections."""
        sections = sorted({
            n for n, d in self.graph.nodes(data=True)
            if d.get("node_type") == "section"
        })
        matrix: dict[str, dict[str, float]] = {s: {t: 0.0 for t in sections} for s in sections}
        for s, t, data in self.graph.edges(data=True):
            ns = self.graph.nodes[s]
            nt = self.graph.nodes[t]
            if ns.get("node_type") == "section" and nt.get("node_type") == "section":
                flow = self._ensure_flow(data)
                matrix[s][t] += flow.volume
        return matrix

    def machine_type_flow(self) -> dict[str, dict[str, float]]:
        """Flux entre types de machines."""
        mts = sorted({
            n for n, d in self.graph.nodes(data=True)
            if d.get("node_type") == "machine_type"
        })
        matrix: dict[str, dict[str, float]] = {m: {n: 0.0 for n in mts} for m in mts}
        for s, t, data in self.graph.edges(data=True):
            ns = self.graph.nodes[s]
            nt = self.graph.nodes[t]
            if ns.get("node_type") == "machine_type" and nt.get("node_type") == "machine_type":
                flow = self._ensure_flow(data)
                matrix[s][t] += flow.volume
        return matrix

    def critical_path(self) -> list[str]:
        """Plus long chemin dans le graphe des opérations (critique)."""
        try:
            return list(nx.dag_longest_path(self.graph))
        except nx.NetworkXUnfeasible:
            return []

    def critical_path_length(self) -> float:
        """Durée totale du chemin critique (minutes)."""
        path = self.critical_path()
        total = 0.0
        for n in path:
            d = self.graph.nodes[n].get("duration", 0)
            total += d
        return total

    def bottleneck_machine_types(self, top_n: int = 3) -> list[tuple[str, float]]:
        """Types machine les plus sollicités (centralité d'intermédiarité)."""
        sub = self.graph.subgraph([
            n for n, d in self.graph.nodes(data=True)
            if d.get("node_type") == "machine_type"
        ])
        if sub.number_of_nodes() < 2:
            return []
        try:
            bc = nx.betweenness_centrality(sub)
            return sorted(bc.items(), key=lambda x: -x[1])[:top_n]
        except Exception:
            return []

    def throughput_estimate(self, cycle_time_min: float) -> dict[str, float]:
        """Estimation du débit max par section."""
        result = {}
        for n, d in self.graph.nodes(data=True):
            if d.get("node_type") == "section" and cycle_time_min > 0:
                result[n] = 60.0 / cycle_time_min
        return result

    def node_link_data(self) -> dict:
        """Export au format Node-Link JSON (D3.js compatible)."""
        # Nettoyer les attributs non sérialisables AVANT l'export
        for _, _, d in self.graph.edges(data=True):
            if "flow" in d and hasattr(d["flow"], "__dataclass_fields__"):
                d["flow"] = {k: getattr(d["flow"], k) for k in d["flow"].__dataclass_fields__}
        return nx.node_link_data(self.graph)

    # ── Affichage ───────────────────────────────────────────────────

    def summary(self) -> str:
        lines = [
            f"📊 Graphe de flux de production",
            f"   Nœuds: {self.graph.number_of_nodes()}",
            f"   Arcs:  {self.graph.number_of_edges()}",
        ]

        # Stats par type
        type_counts = defaultdict(int)
        for _, d in self.graph.nodes(data=True):
            type_counts[d.get("node_type", "unknown")] += 1
        for t, c in sorted(type_counts.items()):
            lines.append(f"     - {t}: {c}")

        # Flux entre sections
        sec_flow = self.section_flow_matrix()
        active = [(s, t, v) for s, row in sec_flow.items() for t, v in row.items() if v > 0]
        if active:
            lines.append(f"   Flux inter-sections: {len(active)}")
            for s, t, v in sorted(active, key=lambda x: -x[2])[:5]:
                sname = self.graph.nodes[s].get("label", s)
                tname = self.graph.nodes[t].get("label", t)
                lines.append(f"     {sname} → {tname}: {v:.0f} pièces")

        # Types machine critiques
        btl = self.bottleneck_machine_types(3)
        if btl:
            lines.append(f"   Types machine critiques:")
            for mt, score in btl:
                label = self.graph.nodes[mt].get("label", mt)
                lines.append(f"     {label}: centralité {score:.3f}")

        cp = self.critical_path()
        if cp:
            lines.append(f"   Chemin critique: {len(cp)} étapes, {self.critical_path_length():.1f} min")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(self.node_link_data(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> ProductionFlowGraph:
        g = cls()
        data = json.loads(json_str)
        g.graph = nx.node_link_graph(data)
        return g
