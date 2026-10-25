"""
SpaghettiDiagram - Diagramme des déplacements (Spaghetti Chart)
Analyse visuelle des trajets opérateurs, heatmap, optimisation ergonomie.
"""

from __future__ import annotations

import math
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

from PySide6.QtCore import (
    QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot, QLineF
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QLinearGradient, QTransform
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QFormLayout, QSplitter, QTreeWidget, QTreeWidgetItem, QScrollArea,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPathItem,
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsTextItem, QGraphicsPolygonItem
)

from engine.models_v2 import (
    BuildingLayout, PhysicalAsset, WorkstationLayout, TransportLink,
    OperatorProfile, Vector2D, Zone, ZoneType, AssetCategory, TransportMode
)


# ============================================================
# MODÈLES DE DONNÉES SPAGHETTI
# ============================================================

@dataclass
class MovementPath:
    """Un chemin de déplacement entre deux points."""
    id: str
    operator_id: str
    from_station: str
    to_station: str
    path_points: List[Vector2D] = field(default_factory=list)
    distance_m: float = 0.0
    duration_s: float = 0.0
    frequency_per_hour: float = 1.0
    transport_mode: str = "manual"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def color(self) -> QColor:
        colors = {
            "manual": QColor("#94a3b8"),
            "conveyor": QColor("#2e90fa"),
            "agv": QColor("#8da2fb"),
            "forklift": QColor("#f79009"),
        }
        return colors.get(self.transport_mode, QColor("#64748b"))


@dataclass
class SpaghettiData:
    """Données complètes pour le diagramme spaghetti."""
    movements: List[MovementPath] = field(default_factory=list)
    operator_positions: Dict[str, Vector2D] = field(default_factory=dict)  # Position home
    station_positions: Dict[str, Vector2D] = field(default_factory=dict)
    heatmap_grid: Dict[Tuple[int, int], float] = field(default_factory=dict)  # (x,y) -> intensité
    
    def total_distance(self) -> float:
        return sum(m.distance_m * m.frequency_per_hour for m in self.movements)
    
    def total_time_per_hour(self) -> float:
        return sum(m.duration_s * m.frequency_per_hour for m in self.movements)


class HeatmapMode(Enum):
    DISTANCE = "distance"
    FREQUENCY = "frequency"
    TIME = "time"
    CONGESTION = "congestion"


# ============================================================
# VUE GRAPHIQUE SPAGHETTI
# ============================================================

class SpaghettiView(QGraphicsView):
    """Vue graphique du diagramme spaghetti."""
    
    selection_changed = Signal(list)
    status_message = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
        # Données
        self.data: Optional[SpaghettiData] = None
        self.building: Optional[BuildingLayout] = None
        
        # Configuration affichage
        self.show_heatmap = True
        self.show_paths = True
        self.show_stations = True
        self.show_operators = True
        self.heatmap_mode = HeatmapMode.FREQUENCY
        self.heatmap_opacity = 0.6
        self.path_width_scale = 3.0
        self.min_path_width = 1.0
        self.max_path_width = 15.0
        
        # Items graphiques
        self._heatmap_items: List[QGraphicsRectItem] = []
        self._path_items: List[QGraphicsPathItem] = []
        self._station_items: Dict[str, QGraphicsEllipseItem] = {}
        self._operator_items: Dict[str, QGraphicsEllipseItem] = {}
        self._label_items: List[QGraphicsTextItem] = []
        
        # Interaction
        self._selected_paths: List[MovementPath] = []
    
    def set_data(self, data: SpaghettiData, building: BuildingLayout = None):
        self.data = data
        self.building = building
        self.rebuild()
    
    def rebuild(self):
        """Reconstruit la vue à partir des données."""
        self.scene().clear()
        self._heatmap_items.clear()
        self._path_items.clear()
        self._station_items.clear()
        self._operator_items.clear()
        self._label_items.clear()
        
        if not self.data:
            return
        
        # Déterminer les bounds
        bounds = self._calculate_bounds()
        margin = 5.0  # mètres
        self.scene().setSceneRect(
            bounds[0] - margin, bounds[1] - margin,
            bounds[2] - bounds[0] + 2*margin, bounds[3] - bounds[1] + 2*margin
        )
        
        # Ordre de dessin: heatmap -> paths -> stations -> operators -> labels
        if self.show_heatmap:
            self._draw_heatmap()
        
        if self.show_paths:
            self._draw_paths()
        
        if self.show_stations:
            self._draw_stations()
        
        if self.show_operators:
            self._draw_operators()
        
        self._draw_legend()
    
    def _calculate_bounds(self) -> Tuple[float, float, float, float]:
        """Calcule les bounds de tous les éléments."""
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        
        if self.data:
            for m in self.data.movements:
                for p in m.path_points:
                    min_x = min(min_x, p.x)
                    max_x = max(max_x, p.x)
                    min_y = min(min_y, p.y)
                    max_y = max(max_y, p.y)
            
            for pos in self.data.operator_positions.values():
                min_x = min(min_x, pos.x)
                max_x = max(max_x, pos.x)
                min_y = min(min_y, pos.y)
                max_y = max(max_y, pos.y)
            
            for pos in self.data.station_positions.values():
                min_x = min(min_x, pos.x)
                max_x = max(max_x, pos.x)
                min_y = min(min_y, pos.y)
                max_y = max(max_y, pos.y)
        
        if self.building:
            for ws in self.building.workstations:
                min_x = min(min_x, ws.position.x)
                max_x = max(max_x, ws.position.x)
                min_y = min(min_y, ws.position.y)
                max_y = max(max_y, ws.position.y)
        
        if min_x == float('inf'):
            return (0, 0, 100, 100)
        
        return (min_x, min_y, max_x, max_y)
    
    def _draw_heatmap(self):
        """Dessine la heatmap de congestion."""
        if not self.data or not self.data.heatmap_grid:
            return
        
        # Trouver la valeur max pour normaliser
        max_val = max(self.data.heatmap_grid.values()) if self.data.heatmap_grid else 1.0
        if max_val == 0:
            return
        
        cell_size = 1.0  # 1m x 1m
        
        for (gx, gy), value in self.data.heatmap_grid.items():
            if value <= 0:
                continue
            
            normalized = min(value / max_val, 1.0)
            
            # Couleur selon mode
            if self.heatmap_mode == HeatmapMode.DISTANCE:
                color = self._distance_color(normalized)
            elif self.heatmap_mode == HeatmapMode.TIME:
                color = self._time_color(normalized)
            elif self.heatmap_mode == HeatmapMode.CONGESTION:
                color = self._congestion_color(normalized)
            else:  # FREQUENCY
                color = self._frequency_color(normalized)
            
            color.setAlphaF(self.heatmap_opacity)
            
            rect = QGraphicsRectItem(
                gx * cell_size, gy * cell_size, cell_size, cell_size
            )
            rect.setPen(Qt.PenStyle.NoPen)
            rect.setBrush(QBrush(color))
            rect.setZValue(0)
            self.scene().addItem(rect)
            self._heatmap_items.append(rect)
    
    def _distance_color(self, v: float) -> QColor:
        """Bleu -> Vert -> Jaune -> Rouge"""
        if v < 0.33:
            return QColor(int(255*v/0.33), int(255*(1-v/0.33)), 255)
        elif v < 0.66:
            v = (v-0.33)/0.33
            return QColor(255, int(255*v), 0)
        else:
            v = (v-0.66)/0.34
            return QColor(255, int(255*(1-v)), 0)
    
    def _frequency_color(self, v: float) -> QColor:
        """Bleu clair -> Bleu foncé -> Violet"""
        r = int(30 + 100*v)
        g = int(100 - 80*v)
        b = int(200 + 55*v)
        return QColor(r, g, b)
    
    def _time_color(self, v: float) -> QColor:
        """Vert -> Jaune -> Orange -> Rouge"""
        if v < 0.5:
            return QColor(int(255*2*v), 255, 0)
        else:
            v = (v-0.5)*2
            return QColor(255, int(255*(1-v)), 0)
    
    def _congestion_color(self, v: float) -> QColor:
        """Heatmap classique"""
        if v < 0.25:
            return QColor(0, int(255*v/0.25), 255)
        elif v < 0.5:
            v = (v-0.25)/0.25
            return QColor(0, 255, int(255*(1-v)))
        elif v < 0.75:
            v = (v-0.5)/0.25
            return QColor(int(255*v), 255, 0)
        else:
            v = (v-0.75)/0.25
            return QColor(255, int(255*(1-v)), 0)
    
    def _draw_paths(self):
        """Dessine les chemins de déplacement."""
        if not self.data:
            return
        
        for movement in self.data.movements:
            if len(movement.path_points) < 2:
                continue
            
            path = QPainterPath()
            points = movement.path_points
            
            # Convertir en points scène
            start = points[0]
            path.moveTo(start.x, start.y)
            
            for p in points[1:]:
                path.lineTo(p.x, p.y)
            
            # Largeur selon fréquence
            freq = movement.frequency_per_hour
            width = self.min_path_width + (self.max_path_width - self.min_path_width) * \
                    min(freq / 20.0, 1.0)  # Max 20/h
            width *= self.path_width_scale
            
            pen = QPen(movement.color, max(1, width))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            
            # Style selon mode transport
            if movement.transport_mode == "conveyor":
                pen.setStyle(Qt.PenStyle.SolidLine)
            elif movement.transport_mode == "agv":
                pen.setStyle(Qt.PenStyle.DashLine)
            elif movement.transport_mode == "forklift":
                pen.setStyle(Qt.PenStyle.DotLine)
            else:
                pen.setStyle(Qt.PenStyle.SolidLine)
            
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(10)
            item.setData(0, movement.id)
            item.setToolTip(
                f"Déplacement: {movement.from_station} → {movement.to_station}\n"
                f"Distance: {movement.distance_m:.1f}m\n"
                f"Fréquence: {movement.frequency_per_hour:.1f}/h\n"
                f"Mode: {movement.transport_mode}"
            )
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            
            self.scene().addItem(item)
            self._path_items.append(item)
            
            # Flèches directionnelles
            self._add_arrows_to_path(points, movement.color, 2)
    
    def _add_arrows_to_path(self, points: List[Vector2D], color: QColor, count: int):
        """Ajoute des flèches directionnelles le long du chemin."""
        if len(points) < 2:
            return
        
        # Calculer la longueur totale
        total_len = 0
        segments = []
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i+1]
            dx = p2.x - p1.x
            dy = p2.y - p1.y
            seg_len = math.hypot(dx, dy)
            segments.append((p1, p2, dx, dy, seg_len))
            total_len += seg_len
        
        if total_len == 0:
            return
        
        # Placer les flèches
        spacing = total_len / (count + 1)
        for i in range(1, count + 1):
            target_dist = i * spacing
            # Trouver le segment
            accumulated = 0
            for p1, p2, dx, dy, seg_len in segments:
                if accumulated + seg_len >= target_dist:
                    # Point sur ce segment
                    t = (target_dist - accumulated) / seg_len
                    x = p1.x + t * dx
                    y = p1.y + t * dy
                    angle = math.atan2(dy, dx)
                    
                    # Dessiner flèche
                    self._draw_arrow(x, y, angle, segments[0][4])  # taille basée sur 1er segment
                    break
                accumulated += seg_len
    
    def _draw_arrow(self, x: float, y: float, angle: float, scale: float):
        """Dessine une flèche à la position donnée."""
        size = max(5, scale * 0.1)
        
        path = QPainterPath()
        path.moveTo(x, y)
        path.lineTo(x - size * math.cos(angle - math.pi/6), y - size * math.sin(angle - math.pi/6))
        path.moveTo(x, y)
        path.lineTo(x - size * math.cos(angle + math.pi/6), y - size * math.sin(angle + math.pi/6))
        
        pen = QPen(QColor("#ff6d5a"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        item.setZValue(11)
        self.scene().addItem(item)
    
    def _draw_stations(self):
        """Dessine les postes de travail."""
        if self.building:
            for ws in self.building.workstations:
                self._draw_station(ws.id, ws.name, ws.position, "#12b76a")
        
        for sid, pos in self.data.station_positions.items():
            if sid not in self._station_items:
                self._draw_station(sid, sid, pos, "#2e90fa")
    
    def _draw_station(self, sid: str, name: str, pos: Vector2D, color: str):
        radius = 12
        item = QGraphicsEllipseItem(pos.x - radius, pos.y - radius, radius*2, radius*2)
        item.setPen(QPen(QColor(color), 2))
        item.setBrush(QBrush(QColor(color + "80")))
        item.setZValue(20)
        item.setToolTip(f"Poste: {name}")
        item.setData(0, f"station:{sid}")
        self.scene().addItem(item)
        self._station_items[sid] = item
        
        # Label
        label = QGraphicsTextItem(name)
        label.setPos(pos.x - 20, pos.y - 30)
        label.setDefaultTextColor(QColor("#e5e7eb"))
        label.setFont(QFont("Segoe UI", 8))
        label.setZValue(21)
        self.scene().addItem(label)
        self._label_items.append(label)
    
    def _draw_operators(self):
        """Dessine les opérateurs (position home)."""
        for oid, pos in self.data.operator_positions.items():
            radius = 8
            item = QGraphicsEllipseItem(pos.x - radius, pos.y - radius, radius*2, radius*2)
            item.setPen(QPen(QColor("#ff6d5a"), 2))
            item.setBrush(QBrush(QColor("#ff6d5a")))
            item.setZValue(20)
            item.setToolTip(f"Opérateur: {oid}")
            item.setData(0, f"operator:{oid}")
            self.scene().addItem(item)
            self._operator_items[oid] = item
            
            # Avatar label
            label = QGraphicsTextItem("👤")
            label.setPos(pos.x - 6, pos.y - 6)
            label.setFont(QFont("Segoe UI Emoji", 10))
            label.setZValue(21)
            self.scene().addItem(label)
            self._label_items.append(label)
    
    def _draw_legend(self):
        """Dessine la légende."""
        # Légende heatmap
        pass
    
    # ============================================================
    # CONTRÔLES
    # ============================================================
    
    def set_heatmap_mode(self, mode: HeatmapMode):
        self.heatmap_mode = mode
        self.rebuild()
    
    def toggle_heatmap(self, show: bool):
        self.show_heatmap = show
        self.rebuild()
    
    def toggle_paths(self, show: bool):
        self.show_paths = show
        self.rebuild()
    
    def set_path_width_scale(self, scale: float):
        self.path_width_scale = scale
        self.rebuild()
    
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item and hasattr(item, 'data'):
                path_id = item.data(0)
                if isinstance(path_id, str) and path_id.startswith("movement:"):
                    self._toggle_path_selection(path_id)
        super().mousePressEvent(event)
    
    def _toggle_path_selection(self, path_id: str):
        if path_id in self._selected_paths:
            self._selected_paths.remove(path_id)
        else:
            self._selected_paths.append(path_id)
        self._update_selection_visual()
        self.selection_changed.emit(self._selected_paths)
    
    def _update_selection_visual(self):
        for item in self._path_items:
            path_id = item.data(0)
            if path_id in self._selected_paths:
                pen = item.pen()
                pen.setColor(QColor("#ff6d5a"))
                pen.setWidth(pen.width() + 2)
                item.setPen(pen)
            else:
                # Restaurer couleur originale
                movement = next((m for m in self.data.movements if m.id == path_id), None)
                if movement:
                    item.setPen(QPen(movement.color, item.pen().width()))


# ============================================================
# CALCULATEUR SPAGHETTI
# ============================================================

class SpaghettiCalculator(QObject):
    """Calculateur de diagramme spaghetti à partir du layout."""
    
    progress = Signal(int)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._stop = False
    
    def calculate(self, building: BuildingLayout, 
                  operators: List[OperatorProfile],
                  movements_config: List[Dict] = None):
        """Calcule les chemins et génère la heatmap."""
        self._stop = False
        try:
            self.progress.emit(10)
            
            data = SpaghettiData()
            
            # Positions stations
            for ws in building.workstations:
                data.station_positions[ws.id] = ws.position
            
            for asset in building.assets:
                data.station_positions[asset.id] = asset.position
            
            # Positions opérateurs (home position)
            for op in operators:
                if op.assigned_station_id and op.assigned_station_id in data.station_positions:
                    data.operator_positions[op.id] = data.station_positions[op.assigned_station_id]
                elif op.assigned_zone_id:
                    zone = next((z for z in building.zones if z.id == op.assigned_zone_id), None)
                    if zone:
                        data.operator_positions[op.id] = zone.centroid()
                else:
                    # Position par défaut
                    data.operator_positions[op.id] = Vector2D(0, 0)
            
            self.progress.emit(30)
            
            # Générer mouvements par défaut si pas de config
            if not movements_config:
                movements_config = self._generate_default_movements(building, operators)
            
            # Calculer chemins
            for i, mv_config in enumerate(movements_config):
                if self._stop:
                    return
                
                movement = self._create_movement(
                    mv_config, building, data.station_positions,
                    data.operator_positions
                )
                if movement:
                    data.movements.append(movement)
                
                self.progress.emit(30 + int(60 * (i + 1) / len(movements_config)))
            
            # Générer heatmap
            self._generate_heatmap(data)
            
            self.progress.emit(95)
            self.finished.emit(data)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _generate_default_movements(self, building: BuildingLayout, 
                                    operators: List[OperatorProfile]) -> List[Dict]:
        """Génère des mouvements par défaut basés sur le layout."""
        movements = []
        
        # Pour chaque opérateur mobile
        for op in operators:
            if op.is_mobile:
                # Logistique: va de zone en zone
                for zone in building.zones:
                    if zone.zone_type in [ZoneType.CIRCULATION_PEDESTRIAN, 
                                          ZoneType.STORAGE, ZoneType.WORK_AREA]:
                        # Mouvement vers cette zone
                        from_pos = op.assigned_zone_id or "home"
                        to_pos = zone.id
                        
                        # Trouver position réelle
                        from_station = self._find_nearest_station(from_pos, building)
                        to_station = self._find_nearest_station(to_pos, building)
                        
                        if from_station and to_station:
                            movements.append({
                                "id": f"mv_{op.id}_{zone.id}",
                                "operator_id": op.id,
                                "from": from_station,
                                "to": to_station,
                                "frequency_per_hour": 5.0,
                                "transport_mode": "manual",
                            })
        
        # Mouvements poste à poste (flux production)
        workstations = list(building.workstations)
        for i, ws in enumerate(workstations[:-1]):
            next_ws = workstations[i + 1]
            movements.append({
                "id": f"prod_{ws.id}_{next_ws.id}",
                "operator_id": "",
                "from": ws.id,
                "to": next_ws.id,
                "frequency_per_hour": 20.0,
                "transport_mode": "conveyor",
            })
        
        return movements
    
    def _find_nearest_station(self, zone_id: str, building: BuildingLayout) -> Optional[str]:
        zone = next((z for z in building.zones if z.id == zone_id), None)
        if not zone:
            return None
        
        centroid = zone.centroid()
        min_dist = float('inf')
        nearest = None
        
        for ws in building.workstations:
            d = centroid.distance_to(ws.position)
            if d < min_dist:
                min_dist = d
                nearest = ws.id
        
        for asset in building.assets:
            d = centroid.distance_to(asset.position)
            if d < min_dist:
                min_dist = d
                nearest = asset.id
        
        return nearest
    
    def _create_movement(self, config: Dict, building: BuildingLayout,
                        station_positions: Dict, operator_positions: Dict) -> Optional[MovementPath]:
        from_id = config.get("from")
        to_id = config.get("to")
        
        if not from_id or not to_id:
            return None
        
        from_pos = station_positions.get(from_id)
        to_pos = station_positions.get(to_id)
        
        if not from_pos or not to_pos:
            return None
        
        # Chemin simple (ligne droite) ou A* si murs
        path_points = self._calculate_path(from_pos, to_pos, building)
        
        # Distance
        distance = 0
        for i in range(len(path_points) - 1):
            distance += path_points[i].distance_to(path_points[i+1])
        
        # Vitesse selon mode
        mode = config.get("transport_mode", "manual")
        speeds = {"manual": 1.3, "conveyor": 0.5, "agv": 1.5, "forklift": 1.0}
        speed = speeds.get(mode, 1.3)
        
        duration = distance / speed * 60  # en secondes
        
        return MovementPath(
            id=config.get("id", f"mv_{from_id}_{to_id}"),
            operator_id=config.get("operator_id", ""),
            from_station=from_id,
            to_station=to_id,
            path_points=path_points,
            distance_m=distance,
            duration_s=duration,
            frequency_per_hour=config.get("frequency_per_hour", 1.0),
            transport_mode=mode,
        )
    
    def _calculate_path(self, start: Vector2D, end: Vector2D, 
                        building: BuildingLayout) -> List[Vector2D]:
        """Calcule le chemin (simplifié: ligne droite + contour murs)."""
        # Pour l'instant, ligne droite
        # TODO: Implémenter A* avec obstacles (murs)
        return [start, end]
    
    def _generate_heatmap(self, data: SpaghettiData):
        """Génère la heatmap de congestion."""
        cell_size = 1.0  # 1m
        grid = defaultdict(float)
        
        for movement in data.movements:
            weight = movement.frequency_per_hour
            
            for i in range(len(movement.path_points) - 1):
                p1 = movement.path_points[i]
                p2 = movement.path_points[i + 1]
                
                # Échantillonner le segment
                steps = max(int(p1.distance_to(p2) / 0.5), 1)
                for j in range(steps + 1):
                    t = j / steps
                    x = p1.x + (p2.x - p1.x) * t
                    y = p1.y + (p2.y - p1.y) * t
                    
                    gx = int(x)
                    gy = int(y)
                    grid[(gx, gy)] += weight
        
        data.heatmap_grid = dict(grid)


# ============================================================
# WIDGET PRINCIPAL SPAGHETTI
# ============================================================

class SpaghettiWidget(QWidget):
    """Widget complet Diagramme Spaghetti."""
    
    def __init__(self, building: BuildingLayout = None, 
                 operators: List[OperatorProfile] = None):
        super().__init__()
        self.building = building or BuildingLayout()
        self.operators = operators or []
        self.data: Optional[SpaghettiData] = None
        self.calculator = SpaghettiCalculator()
        self.setup_ui()
        self.calculate()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar gauche
        toolbar = QVBoxLayout()
        toolbar.setSpacing(8)
        
        self.btn_calc = QPushButton("🔄 Calculer")
        self.btn_calc.clicked.connect(self.calculate)
        toolbar.addWidget(self.btn_calc)
        
        self.btn_export = QPushButton("📸 Exporter")
        self.btn_export.clicked.connect(self.export_image)
        toolbar.addWidget(self.btn_export)
        
        toolbar.addStretch()
        
        # Heatmap controls
        hm_group = QGroupBox("Heatmap")
        hm_layout = QFormLayout(hm_group)
        
        self.chk_heatmap = QCheckBox("Activer")
        self.chk_heatmap.setChecked(True)
        self.chk_heatmap.toggled.connect(self.view.toggle_heatmap)
        hm_layout.addRow(self.chk_heatmap)
        
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Fréquence", "Distance", "Temps", "Congestion"])
        self.cmb_mode.currentTextChanged.connect(self.on_mode_changed)
        hm_layout.addRow("Mode:", self.cmb_mode)
        
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(10, 100)
        self.sld_opacity.setValue(60)
        self.sld_opacity.valueChanged.connect(self.on_opacity_changed)
        hm_layout.addRow("Opacité:", self.sld_opacity)
        
        toolbar.addWidget(hm_group)
        
        # Path controls
        path_group = QGroupBox("Chemins")
        path_layout = QFormLayout(path_group)
        
        self.chk_paths = QCheckBox("Afficher")
        self.chk_paths.setChecked(True)
        self.chk_paths.toggled.connect(self.view.toggle_paths)
        path_layout.addRow(self.chk_paths)
        
        self.sld_width = QSlider(Qt.Orientation.Horizontal)
        self.sld_width.setRange(10, 500)
        self.sld_width.setValue(300)
        self.sld_width.valueChanged.connect(lambda v: self.view.set_path_width_scale(v/100))
        path_layout.addRow("Épaisseur:", self.sld_width)
        
        toolbar.addWidget(path_group)
        
        # Filtres
        filter_group = QGroupBox("Filtres")
        filter_layout = QVBoxLayout(filter_group)
        
        self.chk_manual = QCheckBox("Manuel")
        self.chk_manual.setChecked(True)
        filter_layout.addWidget(self.chk_manual)
        
        self.chk_conveyor = QCheckBox("Convoyeur")
        self.chk_conveyor.setChecked(True)
        filter_layout.addWidget(self.chk_conveyor)
        
        self.chk_agv = QCheckBox("AGV")
        self.chk_agv.setChecked(True)
        filter_layout.addWidget(self.chk_agv)
        
        self.chk_forklift = QCheckBox("Chariot")
        self.chk_forklift.setChecked(True)
        filter_layout.addWidget(self.chk_forklift)
        
        toolbar.addWidget(filter_group)
        
        toolbar.addStretch()
        
        # Stats
        self.lbl_stats = QLabel("Stats: —")
        self.lbl_stats.setWordWrap(True)
        self.lbl_stats.setStyleSheet("font-size: 11px; color: #94a3b8;")
        toolbar.addWidget(self.lbl_stats)
        
        layout.addLayout(toolbar)
        
        # Vue centrale
        self.view = SpaghettiView()
        self.view.status_message.connect(self.on_status)
        self.view.selection_changed.connect(self.on_selection)
        
        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        
        # Panneau droit: liste mouvements
        right_panel = QWidget()
        right_panel.setMaximumWidth(350)
        right_layout = QVBoxLayout(right_panel)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Déplacements", "Dist.", "Frq/h"])
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        right_layout.addWidget(QLabel("📋 Mouvements"))
        right_layout.addWidget(self.tree)
        
        splitter.addWidget(self.tree)
        splitter.setSizes([1000, 300])
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(QWidget())  # spacer gauche pour toolbar
        
        # Wrapper pour toolbar + view
        center_widget = QWidget()
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        
        toolbar_widget = QWidget()
        toolbar_widget.setMaximumWidth(280)
        toolbar_widget.setLayout(toolbar)
        center_layout.addWidget(toolbar_widget)
        center_layout.addWidget(self.view, 1)
        
        splitter2 = QSplitter(Qt.Orientation.Horizontal)
        splitter2.addWidget(center_widget)
        splitter2.addWidget(right_panel)
        splitter2.setSizes([1100, 300])
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter2)
        
        # Connecter signaux calc
        self.calculator.progress.connect(self.on_progress)
        self.calculator.finished.connect(self.on_calculated)
        self.calculator.error.connect(self.on_error)
    
    def calculate(self):
        self.btn_calc.setEnabled(False)
        self.btn_calc.setText("⏳ Calcul...")
        self.calculator.calculate(self.building, self.operators)
    
    def on_progress(self, pct: int):
        self.btn_calc.setText(f"⏳ {pct}%")
    
    def on_calculated(self, data: SpaghettiData):
        self.data = data
        self.view.set_data(data, self.building)
        self.update_tree()
        self.update_stats()
        self.btn_calc.setEnabled(True)
        self.btn_calc.setText("🔄 Calculer")
    
    def on_error(self, err: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Erreur", err)
        self.btn_calc.setEnabled(True)
        self.btn_calc.setText("🔄 Calculer")
    
    def on_mode_changed(self, text: str):
        modes = {
            "Fréquence": HeatmapMode.FREQUENCY,
            "Distance": HeatmapMode.DISTANCE,
            "Temps": HeatmapMode.TIME,
            "Congestion": HeatmapMode.CONGESTION,
        }
        self.view.set_heatmap_mode(modes.get(text, HeatmapMode.FREQUENCY))
    
    def on_opacity_changed(self, value: int):
        self.view.heatmap_opacity = value / 100.0
        self.view.rebuild()
    
    def update_tree(self):
        self.tree.clear()
        if not self.data:
            return
        
        for mv in self.data.movements:
            item = QTreeWidgetItem([
                f"{mv.from_station} → {mv.to_station}",
                f"{mv.distance_m:.1f} m",
                f"{mv.frequency_per_hour:.1f}"
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, mv.id)
            self.tree.addTopLevelItem(item)
    
    def on_tree_selection(self):
        selected = self.tree.selectedItems()
        ids = [item.data(0, Qt.ItemDataRole.UserRole) for item in selected]
        self.view._selected_paths = ids
        self.view._update_selection_visual()
    
    def update_stats(self):
        if not self.data:
            self.lbl_stats.setText("Stats: —")
            return
        
        total_dist = self.data.total_distance()
        total_time = self.data.total_time_per_hour()
        nb_movements = len(self.data.movements)
        
        self.lbl_stats.setText(
            f"📊 Statistiques\n"
            f"Mouvements: {nb_movements}\n"
            f"Distance totale/h: {total_dist:.1f} m\n"
            f"Temps total/h: {total_time/60:.1f} min\n"
            f"Moyenne distance: {total_dist/nb_movements:.1f} m" if nb_movements else "—"
        )
    
    def on_status(self, msg: str):
        print(f"[Spaghetti] {msg}")
    
    def on_selection(self, ids: List[str]):
        pass
    
    def export_image(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", "spaghetti.png", "PNG (*.png)")
        if path:
            self.view.grab().save(path)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Succès", f"Exporté: {path}")


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Créer bâtiment test
    building = BuildingLayout(name="Usine Test")
    
    # Murs
    building.walls.append(WallSegment(
        id="w1", start=Vector2D(0, 0), end=Vector2D(30, 0), wall_type=WallType.EXTERIOR
    ))
    building.walls.append(WallSegment(
        id="w2", start=Vector2D(30, 0), end=Vector2D(30, 20), wall_type=WallType.EXTERIOR
    ))
    building.walls.append(WallSegment(
        id="w3", start=Vector2D(30, 20), end=Vector2D(0, 20), wall_type=WallType.EXTERIOR
    ))
    building.walls.append(WallSegment(
        id="w4", start=Vector2D(0, 20), end=Vector2D(0, 0), wall_type=WallType.EXTERIOR
    ))
    
    # Zones
    building.zones.append(Zone(
        id="z1", name="Montage", zone_type=ZoneType.WORK_AREA,
        vertices=[Vector2D(2, 2), Vector2D(28, 2), Vector2D(28, 10), Vector2D(2, 10)]
    ))
    building.zones.append(Zone(
        id="z2", name="Stockage", zone_type=ZoneType.STORAGE,
        vertices=[Vector2D(2, 12), Vector2D(28, 12), Vector2D(28, 18), Vector2D(2, 18)]
    ))
    building.zones.append(Zone(
        id="z3", name="Allée centrale", zone_type=ZoneType.CIRCULATION_PEDESTRIAN,
        vertices=[Vector2D(13, 2), Vector2D(17, 2), Vector2D(17, 18), Vector2D(13, 18)]
    ))
    
    # Postes
    building.workstations.append(WorkstationLayout(
        id="WS1", name="Poste 1", position=Vector2D(5, 5)
    ))
    building.workstations.append(WorkstationLayout(
        id="WS2", name="Poste 2", position=Vector2D(15, 5)
    ))
    building.workstations.append(WorkstationLayout(
        id="WS3", name="Poste 3", position=Vector2D(25, 5)
    ))
    building.workstations.append(WorkstationLayout(
        id="WS4", name="Poste 4", position=Vector2D(10, 15)
    ))
    building.workstations.append(WorkstationLayout(
        id="WS5", name="Poste 5", position=Vector2D(20, 15)
    ))
    
    # Opérateurs
    operators = [
        OperatorProfile(id="OP1", name="Marie D.", is_mobile=False, 
                        assigned_station_id="WS1"),
        OperatorProfile(id="OP2", name="Ahmed B.", is_mobile=False,
                        assigned_station_id="WS2"),
        OperatorProfile(id="OP3", name="Logisticien 1", is_mobile=True,
                        role="logistician"),
        OperatorProfile(id="OP4", name="Logisticien 2", is_mobile=True,
                        role="logistician"),
    ]
    
    widget = SpaghettiWidget(building, operators)
    widget.resize(1400, 900)
    widget.show()
    
    sys.exit(app.exec())