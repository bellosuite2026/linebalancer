"""
Vue Logique (Flow/VSM) : éditeur de graphe de nœuds (type VisoNode).

Extrait de gui/main.py (Phase 2 - découpage GUI). Contient le modèle de
données des nœuds (NODE_BLUEPRINTS), les items graphiques (EdgeItem,
NodeItem) et l'éditeur canvas (NodeEditor) avec undo/redo, drag-drop,
alignement et presse-papiers.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import (
    QMimeData, QObject, QPointF, Qt, QTimer, Signal, QSize, QLineF, QRectF,
)
from PySide6.QtGui import (
    QBrush, QColor, QDrag, QFont, QImage, QPainter, QPainterPath, QPen,
    QPixmap, QPolygon, QTransform, QPolygonF, QKeySequence, QAction, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsObject, QGraphicsPathItem,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsPolygonItem, QGraphicsEllipseItem, QGraphicsTextItem,
    QPushButton, QToolButton,
)

from gui.svg_icons import get_machine_pixmap, get_node_type_pixmap
from engine.models_v2 import ViewMode
from gui.theme import (
    C_BG, C_CANVAS, C_PANEL, C_CARD, C_CARD_HOVER, C_BORDER, C_BORDER_STRONG,
    C_TEXT, C_MUTED, C_ACCENT, C_ACCENT2, C_DANGER,
    NODE_TYPE_COLORS, NODE_ICONS, NODE_W, NODE_H, PORT_R, PORT_Y,
    station_color,
)

ROOT = Path(__file__).resolve().parent
PROJECT_FILE = ROOT / "project.json"

# ============================================================
# GUI DATA MODEL (Nodes & Edges)
# ============================================================

NODE_BLUEPRINTS = {
    "operation": {"title": "Operation", "subtitle": "Tache de la gamme", "x": 100, "y": 100,
        "config": {"op_id": "", "name": "", "duration": 0.0, "predecessors": "",
                   "machine_type": "", "skills": "", "section": "", "task_type": "VA"}},
    "workstation": {"title": "Poste de travail", "subtitle": "Station physique", "x": 400, "y": 100,
        "config": {"ws_id": "", "name": "", "machine_type": "", "available": True,
                   "max_workers": 1, "section": ""}},
    "worker": {"title": "Ouvrier", "subtitle": "Ressource humaine", "x": 700, "y": 100,
        "config": {"worker_id": "", "name": "", "skills": "", "efficiency": 1.0, "available": True}},
    "machine": {"title": "Type Machine", "subtitle": "Equipement requis", "x": 100, "y": 300,
        "config": {"machine_type": "", "name": "", "section": ""}},
    "section": {"title": "Section/Atelier", "subtitle": "Zone de production", "x": 400, "y": 300,
        "config": {"section_id": "", "name": ""}},
    "layout_machine": {"title": "Machine Layout", "subtitle": "Position machine sur plan", "x": 100, "y": 100,
        "config": {"machine_type": "piqueuse_plate", "name": "", "width_mm": 2000,
                   "height_mm": 1500, "rotation_deg": 0, "section": ""}},
    "layout_section": {"title": "Zone/Section", "subtitle": "Zone atelier delinee", "x": 400, "y": 100,
        "config": {"section_id": "", "name": "", "width_mm": 10000, "height_mm": 8000, "color": "#2c7a7b"}},
    "layout_flow": {"title": "Flux Pieces", "subtitle": "Liaison flux entre machines", "x": 400, "y": 300,
        "config": {"flow_type": "pieces", "name": "", "cadence_pieces_h": 60, "couleur": "#ff6d5a"}},
    "wall": {"title": "Mur", "subtitle": "Mur exterieur/interieur", "x": 100, "y": 500,
        "config": {"wall_type": "interior", "thickness_mm": 200, "height_mm": 3000}},
    "door": {"title": "Porte", "subtitle": "Acces", "x": 400, "y": 500,
        "config": {"door_type": "swing", "width_mm": 1000, "height_mm": 2100}},
    "zone_circulation": {"title": "Zone Circulation", "subtitle": "Allee pietons/chariots", "x": 700, "y": 500,
        "config": {"zone_type": "circulation_pedestrian", "width_mm": 3000, "color": "#8da2fb"}},
    "rack": {"title": "Rack Stockage", "subtitle": "Rayonnage", "x": 100, "y": 700,
        "config": {"rack_type": "palettes_3n", "width_mm": 2700, "depth_mm": 1100, "height_mm": 6000, "levels": 3}},
    "conveyor": {"title": "Convoyeur", "subtitle": "Transport automatise", "x": 400, "y": 700,
        "config": {"conveyor_type": "belt", "length_mm": 5000, "width_mm": 500, "speed_m_min": 10}},
    "agv_path": {"title": "Trajectoire AGV", "subtitle": "Chemin vehicule autonome", "x": 700, "y": 700,
        "config": {"path_type": "bidirectional", "width_mm": 1500, "speed_m_s": 1.5}},
}

def _split_cfg(value: str, sep: str = ";") -> list[str]:
    """Découpe une chaîne de valeurs séparées par sep."""
    return [v.strip() for v in (value or "").split(sep) if v.strip()]


def make_node(node_type: str, **overrides) -> dict:
    bp = NODE_BLUEPRINTS[node_type]
    return {
        "id": overrides.get("id", f"{node_type}_{int(time.time()*1000)%10000}"),
        "type": node_type,
        "title": bp["title"],
        "subtitle": bp["subtitle"],
        "x": overrides.get("x", bp["x"]),
        "y": overrides.get("y", bp["y"]),
        "enabled": overrides.get("enabled", True),
        "config": {**bp["config"], **overrides.get("config", {})},
    }

def default_workflow() -> dict:
    return {
        "nodes": [
            make_node("section", id="section_1", config={"section_id": "MONTAGE", "name": "Montage"}),
            make_node("machine", id="machine_1", config={"machine_type": "piqueuse_plate", "name": "Piqueuse plate"}),
            make_node("workstation", id="ws_1", config={"ws_id": "WS01", "name": "Poste 1", "machine_type": "piqueuse_plate"}),
            make_node("worker", id="worker_1", config={"worker_id": "W001", "name": "Marie D.", "skills": "couture_droite,couture_courbe"}),
            make_node("operation", id="op_1", config={"op_id": "OP010", "name": "Montage epaule", "duration": 0.55, "machine_type": "piqueuse_plate", "skills": "couture_droite", "task_type": "VA"}),
        ],
        "edges": [],
    }

def load_project() -> dict:
    try:
        if PROJECT_FILE.exists():
            data = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
            if isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list):
                return data
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return default_workflow()

def save_project(project: dict) -> None:
    try:
        PROJECT_FILE.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ============================================================
# GRAPHICS: EDGES & NODES (Base pour Vue Logique)
# ============================================================

class EdgeItem(QGraphicsPathItem):
    def __init__(self, from_id: str, to_id: str, edge_type: str = "default"):
        super().__init__()
        self.from_id = from_id
        self.to_id = to_id
        self.edge_type = edge_type
        # Style par type de liaison d'équilibrage (couleur + épaisseur + marque)
        self._style = {
            "flow":       {"color": "#ff6d5a", "width": 3.4, "dash": None,            "arrow": True},
            "precedence": {"color": "#2e90fa", "width": 2.6, "dash": (7, 5),          "arrow": True},
            "machine":    {"color": "#f79009", "width": 2.4, "dash": (10, 4),         "arrow": True},
            "worker":     {"color": "#12b76a", "width": 2.4, "dash": (2, 4),          "arrow": True},
            "section":    {"color": "#06aed4", "width": 2.0, "dash": (4, 4),          "arrow": False},
            "transport":  {"color": "#8da2fb", "width": 2.4, "dash": (2, 4),          "arrow": True},
            "default":    {"color": "#5d6b82", "width": 2.0, "dash": None,            "arrow": False},
        }.get(edge_type, {"color": "#5d6b82", "width": 2.0, "dash": None, "arrow": False})
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.update_style()

    def update_style(self):
        s = self._style
        pen = QPen(QColor(s["color"]), s["width"])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if s["dash"]:
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern(s["dash"])
        self.setPen(pen)

    def update_path(self, p1: QPointF, p2: QPointF):
        path = QPainterPath(p1)
        dx = max(80.0, abs(p2.x() - p1.x()) / 2)
        direction = 1 if p2.x() >= p1.x() else -1
        path.cubicTo(p1.x() + dx * direction, p1.y(),
                     p2.x() - dx * direction, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def paint(self, painter, option, widget=None):
        selected = self.isSelected()
        s = self._style
        pen = QPen(QColor(C_ACCENT if selected else s["color"]),
                   s["width"] + (1.0 if selected else 0.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if s["dash"]:
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern(s["dash"])
        self.setPen(pen)

        # Flèche directionnelle à l'arrivée (marque de sens)
        if s["arrow"]:
            path = self.path()
            if not path.isEmpty():
                end = path.pointAtPercent(1.0)
                # tangente à la fin pour orienter la flèche
                p_prev = path.pointAtPercent(0.97)
                import math as _m
                angle = _m.atan2(end.y() - p_prev.y(), end.x() - p_prev.x())
                self._draw_arrow(painter, end, angle, s["color"])

        super().paint(painter, option, widget)

    def _draw_arrow(self, painter, tip: QPointF, angle: float, color: str):
        import math as _m
        size = 11.0
        a1 = angle + _m.radians(150)
        a2 = angle - _m.radians(150)
        p1 = tip - QPointF(_m.cos(a1) * size, _m.sin(a1) * size)
        p2 = tip - QPointF(_m.cos(a2) * size, _m.sin(a2) * size)
        poly = QPolygonF([tip, p1, p2])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(color)))
        painter.drawPolygon(poly)


class NodeItem(QGraphicsObject):
    def __init__(self, node: dict, editor: "NodeEditor"):
        super().__init__()
        self.node = node
        self.editor = editor
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setPos(node["x"], node["y"])
        self.setZValue(1)
        self._delete_rect = QRectF(NODE_W - 30, 8, 24, 24)

    def boundingRect(self) -> QRectF:
        return QRectF(-9, -9, NODE_W + 18, NODE_H + 18)

    def input_pos(self) -> QPointF:
        return self.mapToScene(0, PORT_Y)

    def output_pos(self) -> QPointF:
        return self.mapToScene(NODE_W, PORT_Y)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.node["x"] = round(self.pos().x())
            self.node["y"] = round(self.pos().y())
            self.editor.update_edges()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged and value:
            self.editor.select_node(self.node["id"])
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        pos = event.pos()
        node_id = self.node["id"]
        if self._delete_rect.contains(pos):
            QTimer.singleShot(0, lambda: self.editor.remove_node(node_id))
            event.accept()
            return
        self.editor.select_node(node_id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.editor.persist()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        node = self.node
        enabled = node.get("enabled", True)
        selected = node["id"] == self.editor.selected_id

        node_color = QColor(NODE_TYPE_COLORS.get(node["type"], C_ACCENT2))
        # Coloration par poste pour les vues équilibrées (lisibilité)
        station = node.get("config", {}).get("station")
        station_tint = None
        if node["type"] == "operation" and station is not None:
            station_tint = QColor(station_color(station))
            node_color = station_tint
        icon_bg = QColor(node_color)
        icon_bg.setAlpha(42 if enabled else 20)

        body = QRectF(0, 0, NODE_W, NODE_H)
        path = QPainterPath()
        path.addRoundedRect(body, 13, 13)

        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(body.translated(0, 4), 13, 13)
        shadow = QColor(0, 0, 0, 80 if enabled else 45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(shadow_path, QBrush(shadow))

        border_color = station_tint if station_tint is not None else QColor(C_ACCENT if selected else C_BORDER)
        painter.setPen(QPen(border_color, 2.2 if selected else 1.6))
        painter.setBrush(QBrush(QColor(C_CARD if enabled else "#141c2b")))
        painter.drawPath(path)

        icon_box = QRectF(15, 17, 40, 40)
        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_box, 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(icon_bg))
        painter.drawPath(icon_path)

        node_type = node["type"]
        config = node.get("config", {})
        pixmap = None
        if node_type in ["workstation", "machine", "layout_machine"]:
            machine_type = config.get("machine_type", "")
            if machine_type:
                pixmap = get_machine_pixmap(machine_type, 40)
        if pixmap is None:
            pixmap = get_node_type_pixmap(node_type, 40)

        if not pixmap.isNull():
            painter.drawPixmap(icon_box.toRect(), pixmap)
        else:
            icon_text = NODE_ICONS.get(node["type"], "?")
            painter.setPen(QPen(QColor(node_color), 2))
            painter.setFont(QFont("Segoe UI Emoji", 18))
            painter.drawText(icon_box, Qt.AlignmentFlag.AlignCenter, icon_text)

        painter.setPen(QPen(QColor(C_TEXT)))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title_rect = QRectF(65, 12, NODE_W - 80, 28)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, node["title"])

        painter.setPen(QPen(QColor(C_MUTED)))
        painter.setFont(QFont("Segoe UI", 9))
        sub_rect = QRectF(65, 36, NODE_W - 80, 20)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"ID: {node['id']}")

        config = node.get("config", {})
        y = 60
        painter.setFont(QFont("Segoe UI", 8))
        for k, v in list(config.items())[:3]:
            if v:
                painter.setPen(QPen(QColor(C_MUTED)))
                painter.drawText(QRectF(15, y, NODE_W - 30, 18),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 f"{k}: {str(v)[:30]}")
                y += 18

        # Badge d'ordre d'opération + sens des étapes
        op_seq = config.get("op_seq")
        op_dir = config.get("op_dir", "")
        if node["type"] == "operation" and op_seq is not None:
            try:
                seq_val = int(op_seq)
            except (TypeError, ValueError):
                seq_val = None
            if seq_val is not None:
                badge_r = 13
                badge_cx, badge_cy = 16, 16
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(C_ACCENT)))
                painter.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)
                painter.setPen(QPen(QColor("#ffffff")))
                painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                painter.drawText(QRectF(badge_cx - badge_r, badge_cy - badge_r,
                                        badge_r * 2, badge_r * 2),
                                 Qt.AlignmentFlag.AlignCenter, str(seq_val))
                if op_dir:
                    painter.setPen(QPen(QColor(C_ACCENT2), 2))
                    painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
                    painter.drawText(QRectF(NODE_W - 40, 8, 32, 20),
                                     Qt.AlignmentFlag.AlignCenter, str(op_dir))

        port_y = PORT_Y
        painter.setPen(QPen(QColor(C_BORDER_STRONG), 2))
        painter.setBrush(QBrush(QColor(C_CARD)))
        painter.drawEllipse(QPointF(0, port_y), PORT_R, PORT_R)
        painter.setPen(QPen(QColor(C_ACCENT), 2))
        painter.setBrush(QBrush(QColor(C_ACCENT)))
        painter.drawEllipse(QPointF(NODE_W, port_y), PORT_R, PORT_R)

        del_rect = QRectF(NODE_W - 30, 8, 24, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#3a2a2a")))
        painter.drawRoundedRect(del_rect, 6, 6)
        painter.setPen(QPen(QColor(C_TEXT)))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(del_rect, Qt.AlignmentFlag.AlignCenter, "✕")


# ============================================================
# NODE EDITOR BASE (Canvas pour Vue Logique)
# ============================================================

class NodeEditor(QGraphicsView):
    node_selected = Signal(str)
    project_changed = Signal()
    view_mode_changed = Signal(str)

    NODE_MIME_TYPE = "application/x-textile-node-type"

    def __init__(self, parent=None, workflow: dict = None, derived: bool = False):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self.workflow = workflow if workflow is not None else load_project()
        self._derived = derived
        self.selected_id = None
        self.node_items = {}
        self.edge_items = {}
        self._drag_edge = None
        self._drag_start_node = None
        self._drag_start_port = None
        self.current_view_mode = ViewMode.LOGICAL
        self._undo_stack = []
        self._redo_stack = []
        self._clipboard = None
        self._clipboard_offset = QPointF(30, 30)
        # Filtre d'affichage : ne montrer QUE les liaisons issues de
        # l'équilibrage (flow / precedence) et masquer les liaisons
        # héritées de la vue de départ. Activé sur les vues dérivées.
        self.balance_only_edges = False

        self.rebuild()

    def rebuild(self):
        self.scene().clear()
        self.node_items = {}
        self.edge_items = {}

        for node in self.workflow.get("nodes", []):
            if not self.should_show_node(node):
                continue
            item = NodeItem(node, self)
            self.scene().addItem(item)
            self.node_items[node["id"]] = item

        for edge in self.workflow.get("edges", []):
            from_id, to_id = edge[0], edge[1]
            etype = edge[2] if len(edge) > 2 else "default"
            if self.balance_only_edges and etype not in (
                "flow", "precedence", "machine", "worker", "section"
            ):
                continue
            if from_id in self.node_items and to_id in self.node_items:
                self.add_edge_item(from_id, to_id, etype)

        self.update_edges()

    def should_show_node(self, node: dict) -> bool:
        ntype = node["type"]
        if self.current_view_mode == ViewMode.LOGICAL:
            return ntype not in ["wall", "door", "zone_circulation", "rack", "conveyor", "agv_path"]
        elif self.current_view_mode == ViewMode.LAYOUT_2D:
            return ntype in ["layout_machine", "layout_section", "layout_flow",
                           "wall", "door", "zone_circulation", "rack", "conveyor", "agv_path",
                           "machine", "workstation", "section"]
        return True

    def set_view_mode(self, mode: ViewMode):
        self.current_view_mode = mode
        self.rebuild()
        self.view_mode_changed.emit(mode.value)

    def add_edge_item(self, from_id: str, to_id: str, edge_type: str = "default"):
        if from_id not in self.node_items or to_id not in self.node_items:
            return
        edge = EdgeItem(from_id, to_id, edge_type)
        self.scene().addItem(edge)
        self.edge_items[(from_id, to_id)] = edge

    def update_edges(self):
        for (from_id, to_id), edge in self.edge_items.items():
            if from_id in self.node_items and to_id in self.node_items:
                edge.update_path(
                    self.node_items[from_id].output_pos(),
                    self.node_items[to_id].input_pos()
                )

    # ============================================================
    # ORDRE D'OPÉRATION & SYNCHRO DEPUIS ÉQUILIBRAGE
    # ============================================================

    def apply_operation_order(self):
        """Calcule l'ordre topologique des opérations et renseigne
        config['op_seq'] (indice d'ordre) et config['op_dir'] (sens des étapes)."""
        nodes = self.workflow.get("nodes", [])
        op_nodes = [n for n in nodes if n["type"] == "operation"]
        if not op_nodes:
            return

        op_by_id = {}
        for n in op_nodes:
            cfg = n.get("config", {})
            op_by_id[cfg.get("op_id", n["id"])] = n

        # Tri topologique (Kahn) selon les prédecesseurs
        indeg = {n["id"]: 0 for n in op_nodes}
        succ = {n["id"]: [] for n in op_nodes}
        for n in op_nodes:
            cfg = n.get("config", {})
            preds = _split_cfg(cfg.get("predecessors", ""), ";")
            for p in preds:
                pn = op_by_id.get(p)
                if pn and pn["id"] != n["id"]:
                    succ[pn["id"]].append(n["id"])
                    indeg[n["id"]] += 1

        from collections import deque
        queue = deque(sorted([nid for nid, d in indeg.items() if d == 0]))
        order = []
        while queue:
            cur = queue.popleft()
            order.append(cur)
            for s in succ[cur]:
                indeg[s] -= 1
                if indeg[s] == 0:
                    queue.append(s)
        # En cas de cycle, ajouter le reste
        for n in op_nodes:
            if n["id"] not in order:
                order.append(n["id"])

        pos = {n["id"]: (n.get("x", 0), n.get("y", 0)) for n in op_nodes}
        for i, nid in enumerate(order, start=1):
            n = next(x for x in op_nodes if x["id"] == nid)
            n["config"]["op_seq"] = i
            # Sens : direction vers le prochain de la chaîne (successeur direct)
            nxt = None
            for s in succ[nid]:
                if s in pos:
                    nxt = s
                    break
            if nxt is None:
                n["config"].pop("op_dir", None)
                continue
            x1, y1 = pos[nid]
            x2, y2 = pos[nxt]
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) >= abs(dy):
                n["config"]["op_dir"] = "→" if dx >= 0 else "←"
            else:
                n["config"]["op_dir"] = "↓" if dy >= 0 else "↑"

    def sync_from_balance_result(self, result):
        """Met à jour la vue logique pour refléter un équilibrage de façon
        lisible et FIDÈLE :
        - ordre d'opération + sens (badges),
        - chaque opération colorée et regroupée en COLONNE par station,
        - les opérations sont reliées (rouge) aux POSTES PHYSIQUES DÉJÀ
          PRÉSENTS dans le projet (jamais de postes dupliqués/créés),
        - arêtes de précédence (bleu) entre opérations.
        - seules les liaisons issues de l'équilibrage sont affichées
          (les liaisons héritées de la vue de départ sont masquées).

        IMPORTANT : le nombre de postes affiché correspond EXACTEMENT au
        résultat (stations utilisées). On ne crée aucun nœud Poste.
        """
        self.balance_only_edges = True
        self.apply_operation_order()

        problem = result.problem if hasattr(result, "problem") else result.get("problem", {})
        op_assign = result.operation_assignments if hasattr(result, "operation_assignments") \
            else result.get("operation_assignments", {})
        station_details = result.station_details if hasattr(result, "station_details") \
            else result.get("station_details", [])

        existing_nodes = {n["id"]: n for n in self.workflow.get("nodes", [])}
        op_to_node = {}
        for n in self.workflow.get("nodes", []):
            if n["type"] == "operation":
                op_to_node[n.get("config", {}).get("op_id", n["id"])] = n["id"]

        # Mapping station -> nœud Poste PHYSIQUE existant dans le projet.
        # On n'en créé JAMAIS de nouveau : si le poste n'existe pas comme nœud,
        # on se contente du regroupement visuel en colonne.
        ws_node_by_id = {n["id"]: n for n in self.workflow.get("nodes", []) if n["type"] == "workstation"}
        ws_node_by_wsid = {
            str(n.get("config", {}).get("ws_id", "")): n
            for n in self.workflow.get("nodes", []) if n["type"] == "workstation"
        }

        ws_by_station = {}
        for sd in station_details:
            station = sd.get("station", 0)
            phys_id = sd.get("workstation", "")
            ws_node = None
            if phys_id:
                ws_node = ws_node_by_id.get(phys_id) or ws_node_by_wsid.get(str(phys_id))
            ws_by_station[station] = ws_node["id"] if ws_node else None

        # Stations utilisées (triées pour un agencement stable)
        used_stations = sorted({int(s) for s in op_assign.values() if s is not None})

        # ── Réorganisation en colonnes par station (lisibilité) ──
        col_gap = 300          # espacement horizontal entre stations
        row_gap = 130          # espacement vertical entre opérations
        col_x0 = 80
        col_y0 = 110
        ops_by_station: dict[int, list] = {s: [] for s in used_stations}
        for op_id, station in op_assign.items():
            node_id = op_to_node.get(op_id)
            if node_id and station in ops_by_station:
                ops_by_station[station].append(node_id)

        for col_idx, station in enumerate(used_stations):
            cx = col_x0 + col_idx * col_gap
            # Poste physique existant en tête de colonne (si présent)
            ws_id = ws_by_station.get(station)
            if ws_id and ws_id in existing_nodes:
                ws_node = existing_nodes[ws_id]
                ws_node["x"] = cx
                ws_node["y"] = col_y0 - 70
                ws_node.setdefault("config", {})["station"] = station
            # Opérations empilées sous le poste (regroupement de la station)
            for row_idx, node_id in enumerate(ops_by_station[station]):
                node = existing_nodes[node_id]
                node["x"] = cx
                node["y"] = col_y0 + row_idx * row_gap
                node.setdefault("config", {})["station"] = station

        # Arêtes opération -> poste physique (affectation, rouge)
        new_edges = []
        for op_id, station in op_assign.items():
            from_node = op_to_node.get(op_id)
            to_node = ws_by_station.get(station)
            if from_node and to_node and (from_node, to_node) not in self.edge_items:
                new_edges.append((from_node, to_node, "flow"))

        # Arêtes de précédence manquantes (bleu)
        for op in (problem.operations if hasattr(problem, "operations") else []):
            from_node = op_to_node.get(op.id)
            if not from_node:
                continue
            for pred in op.predecessors:
                to_node = op_to_node.get(pred)
                if to_node and (to_node, from_node) not in self.edge_items:
                    new_edges.append((to_node, from_node, "precedence"))

        # ── Liaisons ressources (machine / ouvrier / section) ──
        # Pour chaque opération on relie :
        #   op -> machine (type machine requis)
        #   op -> worker  (ouvrier affecté à la station)
        #   op -> section (section de l'opération)
        # Les nœuds ressources sont créés à la volée (vue dérivée) s'ils
        # n'existent pas déjà dans le projet d'origine.
        res_nodes = {}  # clé "type:valeur" -> node_id

        def ensure_resource(rtype, value, label):
            if not value:
                return None
            key = f"{rtype}:{value}"
            if key in res_nodes:
                return res_nodes[key]
            # Chercher un nœud existant du bon type avec la bonne valeur
            for n in self.workflow.get("nodes", []):
                c = n.get("config", {})
                match = False
                if rtype == "machine":
                    match = str(c.get("machine_type", "")) == str(value) or n["id"] == f"machine_{value}"
                elif rtype == "worker":
                    match = str(c.get("worker_id", "")) == str(value) or n["id"] == f"worker_{value}"
                elif rtype == "section":
                    match = str(c.get("section_id", "")) == str(value) or n["id"] == f"section_{value}"
                if n["type"] == rtype and match:
                    res_nodes[key] = n["id"]
                    return n["id"]
            node = make_node(rtype, x=0, y=0)
            node["id"] = f"{rtype}_{value}" if rtype != "worker" else f"worker_{value}"
            cfg = node.setdefault("config", {})
            if rtype == "machine":
                cfg["machine_type"] = value
                node["title"] = f"Machine : {value}"
            elif rtype == "worker":
                cfg["worker_id"] = value
                node["title"] = f"Ouvrier : {value}"
            elif rtype == "section":
                cfg["section_id"] = value
                node["title"] = f"Section : {value}"
            self.workflow["nodes"].append(node)
            existing_nodes[node["id"]] = node
            res_nodes[key] = node["id"]
            return node["id"]

        # Positionnement des ressources à droite des colonnes d'opérations
        res_x = col_x0 + (len(used_stations) + 1) * col_gap
        res_y0 = col_y0

        # Machine par opération
        for op in (problem.operations if hasattr(problem, "operations") else []):
            from_node = op_to_node.get(op.id)
            if not from_node:
                continue
            to_node = ensure_resource("machine", op.machine_type, op.machine_type)
            if to_node and (from_node, to_node) not in self.edge_items:
                new_edges.append((from_node, to_node, "machine"))
            sec_node = ensure_resource("section", op.section, op.section)
            if sec_node and (from_node, sec_node) not in self.edge_items:
                new_edges.append((from_node, sec_node, "section"))

        # Ouvrier par station (worker_ids renseignés par le solveur)
        for sd in station_details:
            for wid in sd.get("worker_ids", []):
                for op_id in sd.get("operations", []):
                    from_node = op_to_node.get(op_id)
                    if not from_node:
                        continue
                    to_node = ensure_resource("worker", wid, wid)
                    if to_node and (from_node, to_node) not in self.edge_items:
                        new_edges.append((from_node, to_node, "worker"))

        # Disposer les nœuds ressources créés verticalement à droite
        seen = sorted(set(res_nodes.values()))
        for i, rid in enumerate(seen):
            node = existing_nodes[rid]
            node["x"] = res_x
            node["y"] = res_y0 + i * row_gap

        self._push_undo()
        for f, t, et in new_edges:
            self.workflow["edges"].append([f, t, et])
            self.add_edge_item(f, t, et)

        self.rebuild()
        self.persist()

    def persist(self):
        self.workflow["nodes"] = [
            {"id": n["id"], "type": n["type"], "title": n["title"],
             "subtitle": n["subtitle"], "x": n["x"], "y": n["y"],
             "enabled": n.get("enabled", True), "config": n.get("config", {})}
            for n in self.workflow["nodes"]
        ]
        self.workflow["edges"] = [
            [k[0], k[1], self.edge_items[k].edge_type]
            for k in self.edge_items.keys()
        ]
        self.workflow["view_mode"] = self.current_view_mode.value
        if not self._derived:
            save_project(self.workflow)
        self.project_changed.emit()

    def select_node(self, node_id: str):
        if self.selected_id == node_id:
            return
        self.selected_id = node_id
        for nid, item in self.node_items.items():
            item.update()
        self.node_selected.emit(node_id)

    def add_node(self, node_type: str, pos: QPointF = None):
        if pos is None:
            pos = self.mapToScene(self.viewport().rect().center())
        self._push_undo()
        node = make_node(node_type, x=round(pos.x()), y=round(pos.y()))
        self.workflow["nodes"].append(node)
        self.rebuild()
        self.project_changed.emit()

    def remove_node(self, node_id: str):
        self._push_undo()
        self.workflow["nodes"] = [n for n in self.workflow["nodes"] if n["id"] != node_id]
        self.workflow["edges"] = [e for e in self.workflow["edges"] if e[0] != node_id and e[1] != node_id]
        self.rebuild()
        self.project_changed.emit()

    def toggle_node(self, node_id: str):
        for node in self.workflow["nodes"]:
            if node["id"] == node_id:
                node["enabled"] = not node.get("enabled", True)
                break
        self.rebuild()
        self.project_changed.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.NODE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(self.NODE_MIME_TYPE):
            node_type = event.mimeData().data(self.NODE_MIME_TYPE).data().decode()
            pos = self.mapToScene(event.position().toPoint())
            self.add_node(node_type, pos)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, NodeItem):
                local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
                if local.x() > NODE_W - 20 and abs(local.y() - PORT_Y) < 15:
                    self._drag_start_node = item.node["id"]
                    self._drag_start_port = "output"
                    self._drag_edge = QGraphicsPathItem()
                    self._drag_edge.setZValue(-2)
                    pen = QPen(QColor(C_ACCENT), 2.4, Qt.PenStyle.DashLine)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    self._drag_edge.setPen(pen)
                    self.scene().addItem(self._drag_edge)
                    start = item.output_pos()
                    self._drag_edge.setPath(QPainterPath(start))
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_edge:
            start_node = self.node_items.get(self._drag_start_node)
            if start_node:
                start = start_node.output_pos()
                end = self.mapToScene(event.position().toPoint())
                path = QPainterPath(start)
                dx = max(80.0, abs(end.x() - start.x()) / 2)
                direction = 1 if end.x() >= start.x() else -1
                path.cubicTo(start.x() + dx * direction, start.y(),
                           end.x() - dx * direction, end.y(), end.x(), end.y())
                self._drag_edge.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_edge:
            self.scene().removeItem(self._drag_edge)
            self._drag_edge = None
            target_item = self.itemAt(event.position().toPoint())
            if isinstance(target_item, NodeItem) and target_item.node["id"] != self._drag_start_node:
                local = target_item.mapFromScene(self.mapToScene(event.position().toPoint()))
                if local.x() < 20 and abs(local.y() - PORT_Y) < 15:
                    from_id = self._drag_start_node
                    to_id = target_item.node["id"]
                    if (from_id, to_id) not in self.edge_items:
                        self._push_undo()
                        self.workflow["edges"].append([from_id, to_id])
                        self.add_edge_item(from_id, to_id)
                        self.update_edges()
                        self.persist()
            self._drag_start_node = None
            self._drag_start_port = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def _push_undo(self):
        import copy
        state = {
            "nodes": copy.deepcopy(self.workflow.get("nodes", [])),
            "edges": copy.deepcopy(self.workflow.get("edges", [])),
        }
        self._undo_stack.append(state)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            return
        import copy
        current_state = {
            "nodes": copy.deepcopy(self.workflow.get("nodes", [])),
            "edges": copy.deepcopy(self.workflow.get("edges", [])),
        }
        self._redo_stack.append(current_state)
        prev_state = self._undo_stack.pop()
        self.workflow["nodes"] = prev_state["nodes"]
        self.workflow["edges"] = prev_state["edges"]
        self.rebuild()
        self.project_changed.emit()

    def redo(self):
        if not self._redo_stack:
            return
        import copy
        current_state = {
            "nodes": copy.deepcopy(self.workflow.get("nodes", [])),
            "edges": copy.deepcopy(self.workflow.get("edges", [])),
        }
        self._undo_stack.append(current_state)
        next_state = self._redo_stack.pop()
        self.workflow["nodes"] = next_state["nodes"]
        self.workflow["edges"] = next_state["edges"]
        self.rebuild()
        self.project_changed.emit()

    def copy_selection(self):
        selected = self._get_selected_nodes()
        if not selected:
            return
        import copy
        self._clipboard = {
            "nodes": [copy.deepcopy(next(n for n in self.workflow["nodes"] if n["id"] == nid)) for nid in selected],
            "edges": [e for e in self.workflow["edges"] if e[0] in selected and e[1] in selected],
        }
        self._clipboard_offset = QPointF(30, 30)

    def cut_selection(self):
        self.copy_selection()
        self.delete_selection()

    def paste_selection(self):
        if not hasattr(self, "_clipboard") or not self._clipboard:
            return
        import copy
        import time
        id_map = {}
        new_nodes = []
        for node in self._clipboard["nodes"]:
            new_id = f"{node['id']}_copy_{int(time.time()*1000)%10000}"
            id_map[node["id"]] = new_id
            new_node = copy.deepcopy(node)
            new_node["id"] = new_id
            new_node["x"] += self._clipboard_offset.x()
            new_node["y"] += self._clipboard_offset.y()
            new_nodes.append(new_node)
        self._push_undo()
        self.workflow["nodes"].extend(new_nodes)
        for edge in self._clipboard["edges"]:
            if edge[0] in id_map and edge[1] in id_map:
                self.workflow["edges"].append([id_map[edge[0]], id_map[edge[1]]])
        self._clipboard_offset += QPointF(30, 30)
        self.rebuild()
        self.project_changed.emit()

    def duplicate_selection(self):
        self.copy_selection()
        self.paste_selection()

    def delete_selection(self):
        selected = self._get_selected_nodes()
        if not selected:
            return
        self._push_undo()
        for nid in selected:
            self.remove_node(nid)

    def select_all_nodes(self):
        for item in self.node_items.values():
            item.setSelected(True)

    def clear_selection(self):
        for item in self.node_items.values():
            item.setSelected(False)

    def _get_selected_nodes(self):
        return [nid for nid, item in self.node_items.items() if item.isSelected()]

    def _get_selected_positions(self):
        selected = self._get_selected_nodes()
        if len(selected) < 2:
            return []
        return [(nid, self.node_items[nid].pos()) for nid in selected]

    def align_horizontal(self):
        positions = self._get_selected_positions()
        if not positions:
            return
        self._push_undo()
        avg_y = sum(p.y() for _, p in positions) / len(positions)
        for nid, _ in positions:
            item = self.node_items[nid]
            item.setPos(item.pos().x(), avg_y)
            item.node["y"] = round(avg_y)
        self.persist()

    def align_vertical(self):
        positions = self._get_selected_positions()
        if not positions:
            return
        self._push_undo()
        avg_x = sum(p.x() for _, p in positions) / len(positions)
        for nid, _ in positions:
            item = self.node_items[nid]
            item.setPos(avg_x, item.pos().y())
            item.node["x"] = round(avg_x)
        self.persist()

    def distribute_horizontal(self):
        positions = self._get_selected_positions()
        if len(positions) < 3:
            return
        self._push_undo()
        positions.sort(key=lambda x: x[1].x())
        min_x = positions[0][1].x()
        max_x = positions[-1][1].x()
        step = (max_x - min_x) / (len(positions) - 1)
        for i, (nid, _) in enumerate(positions):
            x = min_x + i * step
            item = self.node_items[nid]
            item.setPos(x, item.pos().y())
            item.node["x"] = round(x)
        self.persist()

    def distribute_vertical(self):
        positions = self._get_selected_positions()
        if len(positions) < 3:
            return
        self._push_undo()
        positions.sort(key=lambda x: x[1].y())
        min_y = positions[0][1].y()
        max_y = positions[-1][1].y()
        step = (max_y - min_y) / (len(positions) - 1)
        for i, (nid, _) in enumerate(positions):
            y = min_y + i * step
            item = self.node_items[nid]
            item.setPos(item.pos().x(), y)
            item.node["y"] = round(y)
        self.persist()

    def center_view(self):
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def fit_selection(self):
        selected = self._get_selected_nodes()
        if not selected:
            return
        rect = QRectF()
        for nid in selected:
            item = self.node_items[nid]
            rect = rect.united(item.sceneBoundingRect())
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def fit_all(self):
        if self.node_items:
            rect = QRectF()
            for item in self.node_items.values():
                rect = rect.united(item.sceneBoundingRect())
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)


# ============================================================
# PALETTE DRAG SOURCE
# ============================================================

class PaletteNodeButton(QPushButton):
    def __init__(self, node_type: str, label: str):
        super().__init__(label)
        self.node_type = node_type
        self._drag_start = None
        self.setObjectName("palette")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(f"Cliquer pour creer un noeud {label} ou glisser pour le placer")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(NodeEditor.NODE_MIME_TYPE, self.node_type.encode())
        drag.setMimeData(mime)
        pixmap = get_node_type_pixmap(self.node_type, 64)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(32, 32))
        drag.exec(Qt.DropAction.CopyAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


# ============================================================
