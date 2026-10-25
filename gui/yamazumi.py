"""
YamazumiChart - Diagramme d'équilibrage (Yamazumi)
Graphique à barres empilées VA/NVA/Attente avec glisser-déposer pour rééquilibrer.
"""

from __future__ import annotations

import sys
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import (
    QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot, QLineF
)
from PySide6.QtGui import (
    QBrush, QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap,
    QCursor, QFontMetrics
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QFormLayout, QScrollArea, QFrame, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsRectItem, QGraphicsTextItem, QGraphicsPathItem,
    QMenu, QMessageBox, QToolTip
)

from engine.models_v2 import (
    ProcessTask, WorkstationLayout, TaskType, OperatorProfile
)


# ============================================================
# COULEURS & STYLES
# ============================================================

YAMAZUMI_COLORS = {
    TaskType.VA: "#12b76a",       # Vert - Valeur Ajoutée
    TaskType.NVA: "#f97066",      # Rouge - Non Valeur Ajoutée
    TaskType.ATTENTE: "#f79009",  # Orange - Attente
}

YAMAZUMI_COLORS_Q = {
    TaskType.VA: QColor("#12b76a"),
    TaskType.NVA: QColor("#f97066"),
    TaskType.ATTENTE: QColor("#f79009"),
}

STATION_BG = "#182235"
STATION_BORDER = "#263244"
TAKT_LINE_COLOR = "#ff6d5a"
TAKT_LINE_WIDTH = 2


# ============================================================
# MODÈLE DE DONNÉES YAMAZUMI
# ============================================================

@dataclass
class YamazumiStation:
    """Une station dans le diagramme Yamazumi."""
    id: str
    name: str
    tasks: List[ProcessTask] = field(default_factory=list)
    takt_time: float = 0.0
    
    @property
    def total_time(self) -> float:
        return sum(t.duration_s for t in self.tasks)
    
    @property
    def va_time(self) -> float:
        return sum(t.duration_s for t in self.tasks if t.task_type == TaskType.VA)
    
    @property
    def nva_time(self) -> float:
        return sum(t.duration_s for t in self.tasks if t.task_type == TaskType.NVA)
    
    @property
    def wait_time(self) -> float:
        return sum(t.duration_s for t in self.tasks if t.task_type == TaskType.ATTENTE)
    
    @property
    def efficiency(self) -> float:
        if self.takt_time == 0:
            return 0.0
        return (self.total_time / self.takt_time) * 100
    
    @property
    def balance_ratio(self) -> float:
        if self.takt_time == 0:
            return 0.0
        return self.total_time / self.takt_time


@dataclass
class YamazumiConfig:
    """Configuration du diagramme Yamazumi."""
    bar_width: int = 80
    bar_spacing: int = 40
    max_bar_height: int = 400
    show_takt_line: bool = True
    show_efficiency: bool = True
    show_task_labels: bool = True
    animate_changes: bool = True


# ============================================================
# ITEMS GRAPHIQUES
# ============================================================

class TaskSegmentItem(QGraphicsRectItem):
    """Segment de tâche dans une barre Yamazumi."""
    
    def __init__(self, task: ProcessTask, station: YamazumiStation, 
                 x: float, y: float, height: float, width: float):
        super().__init__(x, y, width, height)
        self.task = task
        self.station = station
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setToolTip(f"{task.name}\n{task.duration_s:.1f}s\n{task.task_type.value}")
        
        # Couleur selon type
        color = YAMAZUMI_COLORS_Q.get(task.task_type, QColor("#888888"))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#0b1020"), 1))
        
        # Label
        self.label = QGraphicsTextItem(task.name, self)
        self.label.setDefaultTextColor(QColor("#ffffff"))
        self.label.setFont(QFont("Segoe UI", 7))
        self._update_label_pos()
    
    def _update_label_pos(self):
        if self.label:
            self.label.setPos(self.rect().x() + 2, self.rect().y() + 2)
    
    def mouseDoubleClickEvent(self, event):
        # Ouvrir éditeur de tâche
        print(f"Éditer tâche: {self.task.name}")


class StationBarItem(QGraphicsItem):
    """Barre complète d'une station."""
    
    def __init__(self, station: YamazumiStation, config: YamazumiConfig):
        super().__init__()
        self.station = station
        self.config = config
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        
        self.segments: List[TaskSegmentItem] = []
        self._build_bar()
    
    def _build_bar(self):
        """Construit la barre empilée."""
        x = 0
        y = 0
        
        # Calculer hauteurs proportionnelles
        total = self.station.total_time
        if total == 0:
            return
        
        scale = self.config.max_bar_height / max(total, self.station.takt_time)
        
        current_y = 0
        for task in self.station.tasks:
            h = task.duration_s * scale
            segment = TaskSegmentItem(
                task, self.station,
                x, current_y, h, self.config.bar_width
            )
            segment.setParentItem(self)
            self.segments.append(segment)
            current_y += h
        
        # Ligne Takt Time
        if self.config.show_takt_line and self.station.takt_time > 0:
            takt_h = self.station.takt_time * scale
            # Dessiné dans paint()
    
    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.config.bar_width, self.config.max_bar_height + 40)
    
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        # Fond station
        painter.setPen(QPen(QColor(STATION_BORDER), 1))
        painter.setBrush(QBrush(QColor(STATION_BG)))
        painter.drawRoundedRect(
            0, 0, self.config.bar_width, self.config.max_bar_height, 6, 6
        )
        
        # Ligne Takt Time
        if self.config.show_takt_line and self.station.takt_time > 0:
            total = self.station.total_time
            if total > 0:
                scale = self.config.max_bar_height / max(total, self.station.takt_time)
                takt_y = self.station.takt_time * scale
                
                painter.setPen(QPen(QColor(TAKT_LINE_COLOR), TAKT_LINE_WIDTH, 
                                    Qt.PenStyle.DashLine))
                painter.drawLine(0, takt_y, self.config.bar_width, takt_y)
                
                # Label Takt
                painter.setPen(QPen(QColor(TAKT_LINE_COLOR)))
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.drawText(
                    QRectF(0, takt_y - 15, self.config.bar_width, 20),
                    Qt.AlignmentFlag.AlignCenter, f"Takt: {self.station.takt_time:.1f}s"
                )
        
        # Label station
        painter.setPen(QPen(QColor("#e5e7eb")))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(
            QRectF(0, self.config.max_bar_height + 5, self.config.bar_width, 20),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.station.name}"
        )
        
        # Efficacité
        if self.config.show_efficiency:
            painter.setPen(QPen(QColor("#94a3b8")))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(
                QRectF(0, self.config.max_bar_height + 22, self.config.bar_width, 15),
                Qt.AlignmentFlag.AlignCenter,
                f"Eff: {self.station.efficiency:.0f}%  ({self.station.total_time:.1f}/{self.station.takt_time:.1f}s)"
            )
    
    def hoverEnterEvent(self, event):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        QToolTip.showText(event.screenPos(), 
            f"Station: {self.station.name}\n"
            f"Temps total: {self.station.total_time:.1f}s\n"
            f"Takt: {self.station.takt_time:.1f}s\n"
            f"Efficacité: {self.station.efficiency:.1f}%")
    
    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        QToolTip.hideText()


# ============================================================
# VUE YAMAZUMI PRINCIPALE
# ============================================================

class YamazumiView(QGraphicsView):
    """Vue principale du diagramme Yamazumi."""
    
    station_changed = Signal(object)  # YamazumiStation
    task_moved = Signal(ProcessTask, object, object)  # task, from_station, to_station
    
    def __init__(self, config: YamazumiConfig = None):
        super().__init__()
        self.config = config or YamazumiConfig()
        self.stations: List[YamazumiStation] = []
        self.station_items: List[StationBarItem] = []
        
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Fond
        self.setBackgroundBrush(QBrush(QColor("#0b1020")))
    
    def set_stations(self, stations: List[YamazumiStation]):
        """Définit les stations à afficher."""
        self.stations = stations
        self.rebuild()
    
    def rebuild(self):
        """Reconstruit le diagramme."""
        self.scene().clear()
        self.station_items.clear()
        
        if not self.stations:
            return
        
        x = 50
        y = 50
        
        for station in self.stations:
            item = StationBarItem(station, self.config)
            item.setPos(x, y)
            self.scene().addItem(item)
            self.station_items.append(item)
            
            x += self.config.bar_width + self.config.bar_spacing
        
        # Ajuster la scène
        self.scene().setSceneRect(
            0, 0,
            x + 100,
            self.config.max_bar_height + 150
        )
    
    def add_station(self, station: YamazumiStation):
        """Ajoute une station."""
        self.stations.append(station)
        self.rebuild()
    
    def remove_station(self, station_id: str):
        """Supprime une station."""
        self.stations = [s for s in self.stations if s.id != station_id]
        self.rebuild()
    
    def update_station(self, station_id: str):
        """Met à jour une station spécifique."""
        for item in self.station_items:
            if item.station.id == station_id:
                self.scene().removeItem(item)
                self.rebuild()
                break
    
    def mousePressEvent(self, event):
        # Clic droit pour menu contextuel
        if event.button() == Qt.MouseButton.RightButton:
            item = self.itemAt(event.pos())
            if isinstance(item, StationBarItem):
                self._show_station_menu(item, event.globalPos())
        super().mousePressEvent(event)
    
    def _show_station_menu(self, item: StationBarItem, pos):
        menu = QMenu(self)
        
        act_add_task = menu.addAction("➕ Ajouter tâche")
        act_add_task.triggered.connect(lambda: self._add_task_dialog(item))
        
        act_remove = menu.addAction("🗑️ Supprimer station")
        act_remove.triggered.connect(lambda: self.remove_station(item.station.id))
        
        menu.exec(pos)
    
    def _add_task_dialog(self, item: StationBarItem):
        # Dialogue pour ajouter une tâche
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QFormLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Ajouter tâche à {item.station.name}")
        layout = QFormLayout(dialog)
        
        name_edit = QLineEdit()
        dur_spin = QDoubleSpinBox()
        dur_spin.setRange(0.1, 1000)
        dur_spin.setSuffix(" s")
        dur_spin.setValue(30.0)
        
        type_combo = QComboBox()
        type_combo.addItems([t.value for t in TaskType])
        
        layout.addRow("Nom:", name_edit)
        layout.addRow("Durée:", dur_spin)
        layout.addRow("Type:", type_combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            task = ProcessTask(
                id=f"task_{len(item.station.tasks)}",
                name=name_edit.text() or "Nouvelle tâche",
                duration_s=dur_spin.value(),
                task_type=TaskType(type_combo.currentText())
            )
            item.station.tasks.append(task)
            self.rebuild()


# ============================================================
# PANNEAU DE CONFIGURATION
# ============================================================

class YamazumiConfigPanel(QWidget):
    """Panneau de configuration du diagramme Yamazumi."""
    
    config_changed = Signal()
    
    def __init__(self, view: YamazumiView):
        super().__init__()
        self.view = view
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Takt Time
        group = QGroupBox("⏱️ Takt Time Global")
        form = QFormLayout(group)
        
        self.takt_spin = QDoubleSpinBox()
        self.takt_spin.setRange(0.1, 1000)
        self.takt_spin.setSuffix(" s")
        self.takt_spin.setDecimals(1)
        self.takt_spin.valueChanged.connect(self.on_takt_changed)
        form.addRow("Takt Time:", self.takt_spin)
        
        layout.addWidget(group)
        
        # Options d'affichage
        group2 = QGroupBox("👁️ Affichage")
        form2 = QFormLayout(group2)
        
        self.chk_takt = QCheckBox("Ligne Takt Time")
        self.chk_takt.setChecked(True)
        self.chk_takt.toggled.connect(self.on_display_changed)
        form2.addRow(self.chk_takt)
        
        self.chk_eff = QCheckBox("Efficacité %")
        self.chk_eff.setChecked(True)
        self.chk_eff.toggled.connect(self.on_display_changed)
        form2.addRow(self.chk_eff)
        
        self.chk_labels = QCheckBox("Labels tâches")
        self.chk_labels.setChecked(True)
        self.chk_labels.toggled.connect(self.on_display_changed)
        form2.addRow(self.chk_labels)
        
        layout.addWidget(group2)
        
        # Barres
        group3 = QGroupBox("📊 Barres")
        form3 = QFormLayout(group3)
        
        self.spin_width = QSpinBox()
        self.spin_width.setRange(40, 200)
        self.spin_width.setValue(80)
        self.spin_width.valueChanged.connect(self.on_display_changed)
        form3.addRow("Largeur:", self.spin_width)
        
        self.spin_spacing = QSpinBox()
        self.spin_spacing.setRange(10, 100)
        self.spin_spacing.setValue(40)
        self.spin_spacing.valueChanged.connect(self.on_display_changed)
        form3.addRow("Espacement:", self.spin_spacing)
        
        self.spin_height = QSpinBox()
        self.spin_height.setRange(200, 800)
        self.spin_height.setValue(400)
        self.spin_height.setSuffix(" px")
        self.spin_height.valueChanged.connect(self.on_display_changed)
        form3.addRow("Hauteur max:", self.spin_height)
        
        layout.addWidget(group3)
        
        layout.addStretch()
    
    def on_takt_changed(self, value: float):
        for station in self.view.stations:
            station.takt_time = value
        self.view.rebuild()
        self.config_changed.emit()
    
    def on_display_changed(self):
        self.view.config.show_takt_line = self.chk_takt.isChecked()
        self.view.config.show_efficiency = self.chk_eff.isChecked()
        self.view.config.show_task_labels = self.chk_labels.isChecked()
        self.view.config.bar_width = self.spin_width.value()
        self.view.config.bar_spacing = self.spin_spacing.value()
        self.view.config.max_bar_height = self.spin_height.value()
        self.view.rebuild()
        self.config_changed.emit()


# ============================================================
# WIDGET COMPLET YAMAZUMI
# ============================================================

class YamazumiWidget(QWidget):
    """Widget complet Yamazumi avec vue, config et toolbar."""
    
    def __init__(self, stations: List[YamazumiStation] = None):
        super().__init__()
        self.stations = stations or []
        self.setup_ui()
        self.load_stations(self.stations)
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar gauche
        toolbar = QVBoxLayout()
        toolbar.setSpacing(8)
        
        self.btn_new = QPushButton("➕ Station")
        self.btn_new.clicked.connect(self.add_station)
        toolbar.addWidget(self.btn_new)
        
        self.btn_load = QPushButton("📂 Charger")
        self.btn_load.clicked.connect(self.load_from_file)
        toolbar.addWidget(self.btn_load)
        
        self.btn_save = QPushButton("💾 Sauver")
        self.btn_save.clicked.connect(self.save_to_file)
        toolbar.addWidget(self.btn_save)
        
        toolbar.addStretch()
        
        # Zoom
        self.btn_zoom_in = QPushButton("🔍+")
        self.btn_zoom_in.clicked.connect(lambda: self.zoom(1.2))
        toolbar.addWidget(self.btn_zoom_in)
        
        self.btn_zoom_out = QPushButton("🔍-")
        self.btn_zoom_out.clicked.connect(lambda: self.zoom(0.8))
        toolbar.addWidget(self.btn_zoom_out)
        
        self.btn_fit = QPushButton("🎯 Ajuster")
        self.btn_fit.clicked.connect(self.fit_view)
        toolbar.addWidget(self.btn_fit)
        
        layout.addLayout(toolbar)
        
        # Vue centrale
        self.view = YamazumiView()
        self.view.set_stations(self.stations)
        layout.addWidget(self.view, 1)
        
        # Panneau droit
        self.config_panel = YamazumiConfigPanel(self.view)
        self.config_panel.config_changed.connect(self.on_config_changed)
        layout.addWidget(self.config_panel)
    
    def load_stations(self, stations: List[YamazumiStation]):
        self.stations = stations
        self.view.set_stations(stations)
        
        # Mettre à jour le takt dans le panneau config
        if stations:
            self.config_panel.takt_spin.setValue(stations[0].takt_time)
    
    def add_station(self):
        new_station = YamazumiStation(
            id=f"station_{len(self.stations)+1}",
            name=f"Station {len(self.stations)+1}",
            takt_time=self.stations[0].takt_time if self.stations else 60.0
        )
        self.stations.append(new_station)
        self.view.add_station(new_station)
    
    def remove_station(self, station_id: str):
        self.view.remove_station(station_id)
        self.stations = [s for s in self.stations if s.id != station_id]
    
    def zoom(self, factor: float):
        self.view.scale(factor, factor)
    
    def fit_view(self):
        self.view.fitInView(self.view.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def load_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Charger Yamazumi", "", "JSON (*.json)")
        if path:
            import json
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._load_from_dict(data)
    
    def save_to_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Sauver Yamazumi", "yamazumi.json", "JSON (*.json)")
        if path:
            import json
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._to_dict(), f, indent=2, ensure_ascii=False)
    
    def _to_dict(self) -> dict:
        return {
            "stations": [
                {
                    "id": s.id, "name": s.name, "takt_time": s.takt_time,
                    "tasks": [
                        {"id": t.id, "name": t.name, "duration_s": t.duration_s,
                         "task_type": t.task_type.value}
                        for t in s.tasks
                    ]
                }
                for s in self.stations
            ]
        }
    
    def _load_from_dict(self, data: dict):
        stations = []
        for s_data in data.get("stations", []):
            tasks = [
                ProcessTask(
                    id=t["id"], name=t["name"], duration_s=t["duration_s"],
                    task_type=TaskType(t["task_type"])
                )
                for t in s_data.get("tasks", [])
            ]
            station = YamazumiStation(
                id=s_data["id"], name=s_data["name"],
                takt_time=s_data.get("takt_time", 60),
                tasks=tasks
            )
            stations.append(station)
        self.load_stations(stations)
    
    def on_config_changed(self):
        pass


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Créer stations de test
    stations = []
    
    # Station 1
    tasks1 = [
        ProcessTask(id="t1", name="Prise pièce", duration_s=5, task_type=TaskType.VA),
        ProcessTask(id="t2", name="Positionnement", duration_s=3, task_type=TaskType.VA),
        ProcessTask(id="t3", name="Vissage", duration_s=10, task_type=TaskType.VA),
        ProcessTask(id="t4", name="Contrôle visuel", duration_s=2, task_type=TaskType.NVA),
        ProcessTask(id="t5", name="Attente pièce", duration_s=5, task_type=TaskType.ATTENTE),
    ]
    stations.append(YamazumiStation(
        id="S1", name="Poste 1", takt_time=30, tasks=tasks1
    ))
    
    # Station 2
    tasks2 = [
        ProcessTask(id="t6", name="Prise pièce", duration_s=4, task_type=TaskType.VA),
        ProcessTask(id="t7", name="Montage", duration_s=12, task_type=TaskType.VA),
        ProcessTask(id="t8", name="Contrôle", duration_s=3, task_type=TaskType.NVA),
        ProcessTask(id="t9", name="Attente", duration_s=8, task_type=TaskType.ATTENTE),
    ]
    stations.append(YamazumiStation(
        id="S2", name="Poste 2", takt_time=30, tasks=tasks2
    ))
    
    # Station 3
    tasks3 = [
        ProcessTask(id="t10", name="Emballage", duration_s=6, task_type=TaskType.VA),
        ProcessTask(id="t11", name="Étiquetage", duration_s=2, task_type=TaskType.VA),
        ProcessTask(id="t12", name="Contrôle final", duration_s=4, task_type=TaskType.NVA),
    ]
    stations.append(YamazumiStation(
        id="S3", name="Poste 3", takt_time=30, tasks=tasks3
    ))
    
    widget = YamazumiWidget(stations)
    widget.resize(1400, 900)
    widget.show()
    
    sys.exit(app.exec())