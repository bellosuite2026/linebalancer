"""
TimelineGantt - Diagramme de Gantt multi-pistes
Support: Stations, Opérateurs, Machines, AGV, Convoyeurs.
Synchronisation temps réel avec simulation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
from datetime import datetime, timedelta

from PySide6.QtCore import (
    QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot, QLineF,
    QEvent, QAbstractTableModel, QModelIndex
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
    QLinearGradient, QStandardItemModel, QStandardItem
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QFormLayout, QSplitter, QTreeWidget, QTreeWidgetItem, QScrollArea,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
    QGraphicsTextItem, QGraphicsLineItem, QGraphicsPolygonItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu, QDialog, QDialogButtonBox, QLineEdit, QFormLayout,
    QToolBar, QAction
)

from engine.models_v2 import (
    BalancingResult, WorkstationLayout, PhysicalAsset, TransportLink,
    OperatorProfile, ProcessTask, TaskType, TransportMode
)


# ============================================================
# MODÈLES DE DONNÉES GANTT
# ============================================================

class TrackType(Enum):
    STATION = "station"
    OPERATOR = "operator"
    MACHINE = "machine"
    AGV = "agv"
    CONVEYOR = "conveyor"
    BUFFER = "buffer"


@dataclass
class GanttTrack:
    """Une piste dans le Gantt."""
    id: str
    name: str
    track_type: TrackType
    color: str = "#8da2fb"
    visible: bool = True
    order: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GanttTask:
    """Une tâche/barre dans le Gantt."""
    id: str
    track_id: str
    name: str
    start_time: float  # secondes depuis début
    end_time: float
    color: str = "#8da2fb"
    progress: float = 0.0  # 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    @property
    def is_milestone(self) -> bool:
        return self.duration <= 0.1


@dataclass
class TimeMarker:
    """Marqueur temporel (Takt, shift, pause)."""
    time: float
    label: str
    color: str = "#ff6d5a"
    line_style: str = "dash"  # solid, dash, dot


# ============================================================
# MODÈLE DE TABLEAU GANTT
# ============================================================

class GanttTableModel(QAbstractTableModel):
    """Modèle de tableau pour la liste des tâches Gantt."""
    
    HEADERS = ["Piste", "Tâche", "Début", "Fin", "Durée", "Type", "Progression"]
    
    def __init__(self, tasks: List["GanttTask"] = None):
        super().__init__()
        self.tasks = tasks or []
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.tasks)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)
    
    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None
    
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        
        task = self.tasks[index.row()]
        col = index.column()
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return task.track_id
            elif col == 1:
                return task.name
            elif col == 2:
                return self._format_time(task.start_time)
            elif col == 3:
                return self._format_time(task.end_time)
            elif col == 4:
                return self._format_duration(task.duration)
            elif col == 5:
                return "Jalon" if task.is_milestone else "Tâche"
            elif col == 6:
                return f"{task.progress*100:.0f}%"
        
        elif role == Qt.ItemDataRole.BackgroundRole and col == 6:
            # Barre de progression colorée
            return QBrush(QColor(task.color))
        
        return None
    
    def _format_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    
    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    
    def add_task(self, task: GanttTask):
        self.beginInsertRows(QModelIndex(), len(self.tasks), len(self.tasks))
        self.tasks.append(task)
        self.endInsertRows()
    
    def remove_task(self, row: int):
        self.beginRemoveRows(QModelIndex(), row, row)
        self.tasks.pop(row)
        self.endRemoveRows()
    
    def clear(self):
        self.beginResetModel()
        self.tasks.clear()
        self.endResetModel()


# ============================================================
# VUE GRAPHIQUE GANTT
# ============================================================

class GanttGraphicsView(QGraphicsView):
    """Vue graphique du diagramme de Gantt."""
    
    task_clicked = Signal(object)  # GanttTask
    time_changed = Signal(float)   # temps en secondes
    selection_changed = Signal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
        # Données
        self.tracks: List[GanttTrack] = []
        self.tasks: List[GanttTask] = []
        self.markers: List[TimeMarker] = []
        
        # Config
        self.pixels_per_second = 10.0  # zoom temporal
        self.track_height = 40
        self.track_spacing = 4
        self.margin_left = 200  # largeur labels pistes
        self.margin_top = 60    # hauteur header temps
        self.margin_bottom = 40
        
        # État
        self._current_time = 0.0
        self._playhead_item = None
        self._selected_tasks: List[GanttTask] = []
        
        # Items graphiques
        self._task_items: Dict[str, QGraphicsRectItem] = {}
        self._track_label_items: Dict[str, QGraphicsTextItem] = {}
        self._time_grid_items: List[QGraphicsLineItem] = []
        self._marker_items: List[QGraphicsLineItem] = {}
        
        self.setBackgroundBrush(QBrush(QColor("#0b1020")))
    
    def set_data(self, tracks: List[GanttTrack], tasks: List[GanttTask], 
                 markers: List[TimeMarker] = None):
        self.tracks = tracks
        self.tasks = tasks
        self.markers = markers or []
        self.rebuild()
    
    def rebuild(self):
        """Reconstruit la vue complète."""
        self.scene().clear()
        self._task_items.clear()
        self._track_label_items.clear()
        self._time_grid_items.clear()
        self._marker_items.clear()
        
        if not self.tracks:
            return
        
        # Calculer bounds temporels
        min_time = min((t.start_time for t in self.tasks), default=0)
        max_time = max((t.end_time for t in self.tasks), default=3600)
        
        # Ajouter marges
        time_range = max_time - min_time
        min_time -= time_range * 0.05
        max_time += time_range * 0.05
        
        # Hauteur totale
        total_height = len(self.tracks) * (self.track_height + self.track_spacing)
        
        # Scene rect
        scene_width = self.margin_left + (max_time - min_time) * self.pixels_per_second
        scene_height = self.margin_top + total_height + self.margin_bottom
        self.scene().setSceneRect(0, 0, scene_width, scene_height)
        
        # Dessiner grille temporelle
        self._draw_time_grid(min_time, max_time)
        
        # Dessiner marqueurs
        for marker in self.markers:
            self._draw_marker(marker, min_time)
        
        # Dessiner pistes et tâches
        y = self.margin_top
        for track in self.tracks:
            if not track.visible:
                y += self.track_height + self.track_spacing
                continue
            
            self._draw_track(track, y, min_time, max_time)
            y += self.track_height + self.track_spacing
        
        # Playhead (temps actuel)
        self._draw_playhead(self._current_time, min_time)
    
    def _draw_time_grid(self, min_time: float, max_time: float):
        """Dessine la grille temporelle (secondes, minutes, heures)."""
        # Déterminer pas de grille
        time_range = max_time - min_time
        if time_range <= 300:      # < 5min: 10s
            major_step = 60
            minor_step = 10
        elif time_range <= 1800:   # < 30min: 1min
            major_step = 300
            minor_step = 60
        elif time_range <= 7200:   # < 2h: 5min
            major_step = 600
            minor_step = 60
        else:                      # > 2h: 15min
            major_step = 900
            minor_step = 300
        
        start_major = int(min_time / major_step) * major_step
        
        # Lignes majeures
        time = start_major
        while time <= max_time:
            x = self.margin_left + (time - min_time) * self.pixels_per_second
            
            # Ligne verticale
            line = QGraphicsLineItem(x, self.margin_top, x, 
                                     self.margin_top + len(self.tracks) * (self.track_height + self.track_spacing))
            line.setPen(QPen(QColor("#263244"), 0.5))
            self.scene().addItem(line)
            self._time_grid_items.append(line)
            
            # Label temps
            label = QGraphicsTextItem(self._format_time_label(time))
            label.setPos(x + 2, 2)
            label.setDefaultTextColor(QColor("#94a3b8"))
            label.setFont(QFont("Segoe UI", 8))
            self.scene().addItem(label)
            
            time += major_step
        
        # Lignes mineures (optionnel, plus subtiles)
        time = start_major
        while time <= max_time:
            if int(time / 60) % 5 != 0:  # Pas sur les majeures
                x = self.margin_left + (time - min_time) * self.pixels_per_second
                line = QGraphicsLineItem(x, self.margin_top, x, 
                                         self.margin_top + len(self.tracks) * (self.track_height + self.track_spacing))
                line.setPen(QPen(QColor("#1e2a3a"), 0.3))
                self.scene().addItem(line)
                self._time_grid_items.append(line)
            time += minor_step
    
    def _draw_marker(self, marker: TimeMarker, min_time: float):
        """Dessine un marqueur temporel (Takt, pause, etc.)."""
        x = self.margin_left + (marker.time - min_time) * self.pixels_per_second
        
        pen = QPen(QColor(marker.color), 2)
        if marker.line_style == "dash":
            pen.setStyle(Qt.PenStyle.DashLine)
        elif marker.line_style == "dot":
            pen.setStyle(Qt.PenStyle.DotLine)
        
        line = QGraphicsLineItem(x, self.margin_top, x, 
                                 self.scene().sceneRect().height())
        line.setPen(pen)
        line.setZValue(5)
        self.scene().addItem(line)
        self._marker_items[marker.label] = line
        
        # Label
        label = QGraphicsTextItem(marker.label)
        label.setPos(x + 2, self.margin_top - 20)
        label.setDefaultTextColor(QColor(marker.color))
        label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.scene().addItem(label)
    
    def _draw_track(self, track: GanttTrack, y: float, min_time: float, max_time: float):
        """Dessine une piste avec ses tâches."""
        # Fond piste
        bg = QGraphicsRectItem(
            self.margin_left, y,
            (max_time - min_time) * self.pixels_per_second,
            self.track_height
        )
        bg.setPen(QPen(QColor("#1e2a3a"), 0.5))
        bg.setBrush(QBrush(QColor("#141c2b")))
        bg.setZValue(-1)
        self.scene().addItem(bg)
        
        # Label piste
        label = QGraphicsTextItem(track.name)
        label.setPos(4, y + 2)
        label.setDefaultTextColor(QColor(track.color))
        label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        label.setZValue(1)
        self.scene().addItem(label)
        self._track_label_items[track.id] = label
        
        # Tâches de cette piste
        track_tasks = [t for t in self.tasks if t.track_id == track.id]
        for task in track_tasks:
            self._draw_task(task, y, min_time)
    
    def _draw_task(self, task: GanttTask, track_y: float, min_time: float):
        """Dessine une tâche comme barre."""
        x = self.margin_left + (task.start_time - min_time) * self.pixels_per_second
        width = task.duration * self.pixels_per_second
        
        # Hauteur barre (légèrement plus petite que la piste)
        bar_height = self.track_height - 8
        bar_y = track_y + 4
        
        # Barre principale
        rect = QGraphicsRectItem(x, bar_y, max(2, width), bar_height)
        rect.setPen(Qt.PenStyle.NoPen)
        
        # Gradient pour effet 3D
        gradient = QLinearGradient(x, bar_y, x, bar_y + bar_height)
        base_color = QColor(task.color)
        gradient.setColorAt(0, base_color.lighter(130))
        gradient.setColorAt(1, base_color.darker(120))
        rect.setBrush(QBrush(gradient))
        
        rect.setPen(QPen(QColor(task.color).darker(150), 1))
        rect.setZValue(10)
        rect.setData(0, task.id)
        rect.setToolTip(
            f"{task.name}\n"
            f"Début: {self._format_time_label(task.start_time)}\n"
            f"Fin: {self._format_time_label(task.end_time)}\n"
            f"Durée: {self._format_duration(task.duration)}"
        )
        rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        
        self.scene().addItem(rect)
        self._task_items[task.id] = rect
        
        # Progression (si < 100%)
        if task.progress > 0 and task.progress < 1.0:
            prog_width = width * task.progress
            prog_rect = QGraphicsRectItem(x, bar_y, max(1, prog_width), bar_height)
            prog_color = QColor(task.color)
            prog_color.setAlpha(180)
            prog_rect.setBrush(QBrush(prog_color))
            prog_rect.setPen(Qt.PenStyle.NoPen)
            prog_rect.setZValue(11)
            self.scene().addItem(prog_rect)
        
        # Label tâche
        if width > 50:
            label = QGraphicsTextItem(task.name)
            label.setPos(x + 4, bar_y + 2)
            label.setDefaultTextColor(QColor("#ffffff"))
            label.setFont(QFont("Segoe UI", 7))
            label.setZValue(12)
            self.scene().addItem(label)
    
    def _draw_playhead(self, current_time: float, min_time: float):
        """Dessine la tête de lecture (temps actuel)."""
        x = self.margin_left + (current_time - min_time) * self.pixels_per_second
        
        # Ligne verticale
        if self._playhead_item:
            self.scene().removeItem(self._playhead_item)
        
        self._playhead_item = QGraphicsLineItem(x, self.margin_top, x, 
                                                self.scene().sceneRect().height())
        pen = QPen(QColor("#ff6d5a"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._playhead_item.setPen(pen)
        self._playhead_item.setZValue(100)
        self.scene().addItem(self._playhead_item)
        
        # Label temps
        label = QGraphicsTextItem(f"▼ {self._format_time_label(current_time)}")
        label.setPos(x + 4, self.margin_top - 22)
        label.setDefaultTextColor(QColor("#ff6d5a"))
        label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        label.setZValue(101)
        self.scene().addItem(label)
    
    def _format_time_label(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    
    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    
    # ============================================================
    # API PUBLIQUE
    # ============================================================
    
    def set_time(self, time: float):
        """Définit le temps courant (playhead)."""
        self._current_time = time
        self._draw_playhead(time, min((t.start_time for t in self.tasks), default=0))
    
    def set_zoom(self, pixels_per_second: float):
        self.pixels_per_second = max(1.0, min(100.0, pixels_per_second))
        self.rebuild()
    
    def zoom_in(self):
        self.set_zoom(self.pixels_per_second * 1.5)
    
    def zoom_out(self):
        self.set_zoom(self.pixels_per_second / 1.5)
    
    def fit_all(self):
        if not self.tasks:
            return
        min_t = min(t.start_time for t in self.tasks)
        max_t = max(t.end_time for t in self.tasks)
        range_t = max_t - min_t
        available_width = self.viewport().width() - self.margin_left - 50
        self.set_zoom(available_width / range_t)
    
    def set_current_time(self, time: float):
        self._current_time = time
        if self._playhead_item:
            self._playhead_item.setPos(
                self.margin_left + (time - min((t.start_time for t in self.tasks), default=0)) * self.pixels_per_second,
                0
            )
    
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
            self.set_zoom(self.pixels_per_second * factor)
        else:
            super().wheelEvent(event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item and item.data(0):
                task_id = item.data(0)
                self.task_clicked.emit(next((t for t in self.tasks if t.id == task_id), None))
                # Sélection
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if task_id in self._selected_tasks:
                        self._selected_tasks.remove(task_id)
                    else:
                        self._selected_tasks.append(task_id)
                else:
                    self._selected_tasks = [task_id]
                self._update_selection_visual()
                self.selection_changed.emit(self._selected_tasks)
        super().mousePressEvent(event)
    
    def _update_selection_visual(self):
        for tid, item in self._task_items.items():
            if tid in self._selected_tasks:
                item.setPen(QPen(QColor("#ff6d5a"), 2))
            else:
                item.setPen(QPen(QColor(item.brush().color()).darker(150), 1))


# ============================================================
# WIDGET PRINCIPAL TIMELINE GANTT
# ============================================================

class TimelineGanttWidget(QWidget):
    """Widget complet Timeline Gantt multi-pistes."""
    
    def __init__(self, result: BalancingResult = None):
        super().__init__()
        self.result = result
        self.tracks: List[GanttTrack] = []
        self.tasks: List[GanttTask] = []
        self.markers: List[TimeMarker] = []
        self._simulation_timer = QTimer()
        self._simulation_time = 0.0
        self._simulation_speed = 1.0
        self.setup_ui()
        
        if result:
            self.load_from_result(result)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        self.btn_play = QPushButton("▶️ Play")
        self.btn_play.clicked.connect(self.toggle_play)
        toolbar.addWidget(self.btn_play)
        
        self.btn_pause = QPushButton("⏸️ Pause")
        self.btn_pause.clicked.connect(self.pause)
        self.btn_pause.setEnabled(False)
        toolbar.addWidget(self.btn_pause)
        
        self.btn_stop = QPushButton("⏹️ Stop")
        self.btn_stop.clicked.connect(self.stop)
        toolbar.addWidget(self.btn_stop)
        
        toolbar.addSpacing(20)
        
        self.btn_zoom_in = QPushButton("🔍+")
        self.btn_zoom_in.clicked.connect(lambda: self.view.zoom_in())
        toolbar.addWidget(self.btn_zoom_in)
        
        self.btn_zoom_out = QPushButton("🔍-")
        self.btn_zoom_out.clicked.connect(lambda: self.view.zoom_out())
        toolbar.addWidget(self.btn_zoom_out)
        
        self.btn_fit = QPushButton("🎯 Ajuster")
        self.btn_fit.clicked.connect(self.view.fit_all)
        toolbar.addWidget(self.btn_fit)
        
        toolbar.addSpacing(20)
        
        self.lbl_speed = QLabel("Vitesse:")
        toolbar.addWidget(self.lbl_speed)
        
        self.sld_speed = QSlider(Qt.Orientation.Horizontal)
        self.sld_speed.setRange(10, 500)
        self.sld_speed.setValue(100)
        self.sld_speed.setMaximumWidth(150)
        self.sld_speed.valueChanged.connect(self.on_speed_changed)
        toolbar.addWidget(self.sld_speed)
        
        toolbar.addStretch()
        
        self.lbl_time = QLabel("00:00:00 / 00:00:00")
        self.lbl_time.setStyleSheet("font-family: monospace; font-size: 13px;")
        toolbar.addWidget(self.lbl_time)
        
        layout.addLayout(toolbar)
        
        # Splitter principal
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Vue Gantt
        self.view = GanttGraphicsView()
        self.view.task_clicked.connect(self.on_task_clicked)
        self.view.selection_changed.connect(self.on_selection)
        
        # Panneau latéral
        side_panel = QWidget()
        side_panel.setMaximumWidth(350)
        side_layout = QVBoxLayout(side_panel)
        
        # Onglets
        self.tabs = QComboBox()
        self.tabs.addItems(["📋 Pistes", "📊 Tâches", "⏱️ Marqueurs"])
        self.tabs.currentTextChanged.connect(self.on_tab_changed)
        side_layout.addWidget(self.tabs)
        
        # Contenu onglets
        self.stack = QWidget()
        stack_layout = QVBoxLayout(self.stack)
        
        # Onglet Pistes
        self.tracks_tree = QTreeWidget()
        self.tracks_tree.setHeaderLabels(["Piste", "Type", "Couleur"])
        stack_layout.addWidget(self.tracks_tree)
        
        # Onglet Tâches
        self.tasks_table = QTableWidget()
        self.tasks_table.setColumnCount(7)
        self.tasks_table.setHorizontalHeaderLabels(GanttTableModel.HEADERS)
        self.tasks_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        stack_layout.addWidget(self.tasks_table)
        
        # Onglet Marqueurs
        self.markers_tree = QTreeWidget()
        self.markers_tree.setHeaderLabels(["Temps", "Label", "Couleur"])
        stack_layout.addWidget(self.markers_tree)
        
        side_layout.addWidget(self.stack)
        
        splitter.addWidget(self.view)
        splitter.addWidget(side_panel)
        splitter.setSizes([1100, 350])
        
        layout.addWidget(splitter)
        
        # Connecter
        self._simulation_timer.timeout.connect(self.on_simulation_tick)
        self._simulation_timer.setInterval(100)  # 10Hz
        
        # Initialiser listes
        self.tracks_model = QStandardItemModel()
        self.tasks_model = GanttTableModel(self.tasks)
        self.tasks_table.setModel(self.tasks_model)
    
    def load_from_result(self, result: BalancingResult):
        """Charge un résultat d'équilibrage dans le Gantt."""
        self.result = result
        self.tracks.clear()
        self.tasks.clear()
        self.markers.clear()
        
        # Marqueur Takt Time
        if result.problem and result.problem.target_cycle_time:
            takt_s = result.problem.target_cycle_time * 60
            self.markers.append(TimeMarker(
                time=takt_s,
                label=f"Takt Time ({result.problem.target_cycle_time:.1f} min)",
                color="#ff6d5a",
                line_style="dash"
            ))
        
        # Pistes Stations
        for i, sd in enumerate(result.station_details):
            station_id = f"station_{sd['station']}"
            track = GanttTrack(
                id=station_id,
                name=f"Station {sd['station']}",
                track_type=TrackType.STATION,
                color="#12b76a",
                order=i
            )
            self.tracks.append(track)
            
            # Tâches de cette station
            t = 0.0
            for op_id in sd["operations"]:
                op = result.problem.get_operation(op_id)
                if op:
                    task = GanttTask(
                        id=f"{station_id}_{op_id}",
                        track_id=station_id,
                        name=f"{op_id}: {op.name}",
                        start_time=t,
                        end_time=t + op.duration * 60,
                        color="#12b76a",
                        metadata={"op_id": op_id, "station": sd['station']}
                    )
                    self.tasks.append(task)
                    t += op.duration * 60
        
        # Pistes Opérateurs
        for i, w in enumerate(result.problem.workers):
            if w.id in result.worker_assignments:
                station = result.worker_assignments[w.id]
                track = GanttTrack(
                    id=f"worker_{w.id}",
                    name=f"{w.name} ({station})",
                    track_type=TrackType.OPERATOR,
                    color="#8da2fb",
                    order=len(self.tracks)
                )
                self.tracks.append(track)
                
                # Tâches opérateur (simplifié: même que station)
                sd = next((s for s in result.station_details if str(s['station']) == station), None)
                if sd:
                    t = 0.0
                    for op_id in sd["operations"]:
                        op = result.problem.get_operation(op_id)
                        if op:
                            task = GanttTask(
                                id=f"worker_{w.id}_{op_id}",
                                track_id=f"worker_{w.id}",
                                name=f"{w.name}: {op.name}",
                                start_time=t,
                                end_time=t + op.duration * 60,
                                color="#8da2fb",
                                metadata={"worker_id": w.id, "op_id": op_id}
                            )
                            self.tasks.append(task)
                            t += op.duration * 60
        
        # Pistes Machines (depuis assets si dispo)
        # Pour l'instant, on utilise les workstations
        
        # Marqueur fin de cycle
        if self.tasks:
            max_time = max(t.end_time for t in self.tasks)
            self.markers.append(TimeMarker(
                time=max_time,
                label="Fin de cycle",
                color="#f79009",
                line_style="solid"
            ))
        
        # Mettre à jour la vue
        self.view.set_data(self.tracks, self.tasks, self.markers)
        self.update_tracks_list()
        self.tasks_model = GanttTableModel(self.tasks)
        self.tasks_table.setModel(self.tasks_model)
        self.update_markers_list()
    
    def update_tracks_list(self):
        self.tracks_tree.clear()
        for track in self.tracks:
            item = QTreeWidgetItem([
                track.name,
                track.track_type.value,
                "●"
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, track.id)
            # Colorer le point
            item.setForeground(2, QBrush(QColor(track.color)))
            self.tracks_tree.addTopLevelItem(item)
    
    def update_markers_list(self):
        self.markers_tree.clear()
        for marker in self.markers:
            item = QTreeWidgetItem([
                self.view._format_time_label(marker.time),
                marker.label,
                "●"
            ])
            item.setForeground(2, QBrush(QColor(marker.color)))
            self.markers_tree.addTopLevelItem(item)
    
    def on_task_clicked(self, task: GanttTask):
        if task:
            # Trouver et sélectionner dans le tableau
            for row in range(self.tasks_model.rowCount()):
                if self.tasks_model.tasks[row].id == task.id:
                    self.tasks_table.selectRow(row)
                    break
    
    def on_selection(self, task_ids: List[str]):
        pass
    
    def on_tab_changed(self, text: str):
        # Basculer les vues dans le stack
        pass
    
    def toggle_play(self):
        if self._simulation_timer.isActive():
            self.pause()
        else:
            self._simulation_timer.start()
            self.btn_play.setEnabled(False)
            self.btn_pause.setEnabled(True)
    
    def pause(self):
        self._simulation_timer.stop()
        self.btn_play.setEnabled(True)
        self.btn_pause.setEnabled(False)
    
    def stop(self):
        self._simulation_timer.stop()
        self._simulation_time = 0.0
        self.view.set_time(0)
        self.update_time_label()
        self.btn_play.setEnabled(True)
        self.btn_pause.setEnabled(False)
    
    def on_simulation_tick(self):
        self._simulation_time += 0.1 * self._simulation_speed
        self.view.set_time(self._simulation_time)
        self.update_time_label()
        
        # Arrêter à la fin
        if self.tasks:
            max_t = max(t.end_time for t in self.tasks)
            if self._simulation_time >= max_t:
                self.stop()
    
    def on_speed_changed(self, value: int):
        self._simulation_speed = value / 100.0
    
    def update_time_label(self):
        max_t = max((t.end_time for t in self.tasks), default=0)
        self.lbl_time.setText(
            f"{self.view._format_time_label(self._simulation_time)} / "
            f"{self.view._format_time_label(max_t)}"
        )
    
    def on_simulation_finished(self):
        pass


# ============================================================
# GÉNÉRATEUR GANTT DEPUIS SIMULATION
# ============================================================

class GanttGenerator:
    """Génère un Gantt complet à partir d'une simulation."""
    
    @staticmethod
    def from_balancing_result(result: BalancingResult) -> Tuple[List[GanttTrack], List[GanttTask], List[TimeMarker]]:
        """Génère pistes, tâches et marqueurs depuis un résultat d'équilibrage."""
        tracks = []
        tasks = []
        markers = []
        
        # Takt Time
        if result.problem:
            takt_s = result.problem.target_cycle_time * 60
            markers.append(TimeMarker(
                time=takt_s,
                label=f"Takt: {result.problem.target_cycle_time:.1f} min",
                color="#ff6d5a",
                line_style="dash"
            ))
        
        # Stations
        for sd in result.station_details:
            st_id = f"station_{sd['station']}"
            tracks.append(GanttTrack(
                id=st_id,
                name=f"Station {sd['station']}",
                track_type=TrackType.STATION,
                color="#12b76a",
                order=sd['station']
            ))
            
            t = 0.0
            for op_id in sd["operations"]:
                op = result.problem.get_operation(op_id)
                if op:
                    tasks.append(GanttTask(
                        id=f"{st_id}_{op_id}",
                        track_id=st_id,
                        name=f"{op_id}: {op.name}",
                        start_time=t,
                        end_time=t + op.duration * 60,
                        color="#12b76a",
                        metadata={"op_id": op_id, "station": sd['station']}
                    ))
                    t += op.duration * 60
        
        # Opérateurs
        for w in result.problem.workers:
            if w.id in result.worker_assignments:
                station = result.worker_assignments[w.id]
                track = GanttTrack(
                    id=f"worker_{w.id}",
                    name=f"{w.name} (Station {station})",
                    track_type=TrackType.OPERATOR,
                    color="#8da2fb",
                    order=len(tracks)
                )
                tracks.append(track)
                
                sd = next((s for s in result.station_details if str(s['station']) == station), None)
                if sd:
                    t = 0.0
                    for op_id in sd["operations"]:
                        op = result.problem.get_operation(op_id)
                        if op:
                            tasks.append(GanttTask(
                                id=f"worker_{w.id}_{op_id}",
                                track_id=f"worker_{w.id}",
                                name=f"{w.name}: {op.name}",
                                start_time=t,
                                end_time=t + op.duration * 60,
                                color="#8da2fb",
                                metadata={"worker_id": w.id, "op_id": op_id}
                            ))
                            t += op.duration * 60
        
        # Fin de cycle
        if tasks:
            max_t = max(t.end_time for t in tasks)
            markers.append(TimeMarker(
                time=max_t,
                label="Fin de cycle",
                color="#f79009",
                line_style="solid"
            ))
        
        return tracks, tasks, markers


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Données de test
    tracks = [
        GanttTrack(id="S1", name="Station 1", track_type=TrackType.STATION, color="#12b76a"),
        GanttTrack(id="S2", name="Station 2", track_type=TrackType.STATION, color="#12b76a"),
        GanttTrack(id="W1", name="Marie D.", track_type=TrackType.OPERATOR, color="#8da2fb"),
        GanttTrack(id="M1", name="Piqueuse 1", track_type=TrackType.MACHINE, color="#f79009"),
    ]
    
    tasks = [
        GanttTask(id="t1", track_id="S1", name="Prise pièce", start_time=0, end_time=30, color="#12b76a"),
        GanttTask(id="t2", track_id="S1", name="Vissage", start_time=30, end_time=120, color="#12b76a"),
        GanttTask(id="t3", track_id="S1", name="Contrôle", start_time=120, end_time=150, color="#f97066"),
        GanttTask(id="t4", track_id="S2", name="Montage", start_time=0, end_time=90, color="#12b76a"),
        GanttTask(id="t5", track_id="W1", name="Marie: Vissage", start_time=30, end_time=120, color="#8da2fb"),
        GanttTask(id="t6", track_id="M1", name="Piqueuse: Cycle", start_time=0, end_time=150, color="#f79009"),
    ]
    
    markers = [
        TimeMarker(time=150, label="Takt Time", color="#ff6d5a", line_style="dash"),
        TimeMarker(time=300, label="Fin de cycle", color="#f79009", line_style="solid"),
    ]
    
    widget = TimelineGanttWidget()
    widget.view.set_data(tracks, tasks, markers)
    widget.resize(1400, 900)
    widget.show()
    
    sys.exit(app.exec())