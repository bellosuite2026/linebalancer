"""
LayoutView2D - Vue Implantation 2D (Layout Sketch)
Éditeur de plan d'usine avec grille magnétique, murs, zones, assets.
Supporte les couches (layers), snap, cotes, alignement.
"""

from __future__ import annotations

import math
from typing import Optional, List, Dict, Any, Set
from enum import Enum
from dataclasses import dataclass, field

from gui.debug_logger import debug as log_debug
from gui.svg_icons import get_machine_pixmap

from PySide6.QtCore import (
    QObject, QPointF, QRectF, Qt, QTimer, Signal, Slot, QLineF, QSizeF
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPainterPathStroker,
    QPen, QPixmap, QPolygonF, QTransform, QMouseEvent, QKeyEvent, QWheelEvent, QFontMetrics
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsPolygonItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QGraphicsPathItem, QGraphicsItemGroup, QMenu, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QGroupBox, QFormLayout, QPushButton, QScrollArea, QTreeWidget,
    QTreeWidgetItem, QSplitter, QDialog, QDialogButtonBox, QColorDialog,
    QInputDialog, QMessageBox, QToolBar, QSizePolicy, QLineEdit
)

from engine.models_v2 import (
    BuildingLayout, WallSegment, Door, Zone, PhysicalAsset, WorkstationLayout,
    Vector2D, AssetCategory, WallType, ZoneType, TransportLink, TransportMode,
    ViewMode, DimensionLayout
)


# ============================================================
# COULEURS & STYLES LAYOUT
# ============================================================

LAYOUT_BG = "#0a1018"
LAYOUT_GRID_LIGHT = "#1e2a3a"
LAYOUT_GRID_DARK = "#141e2e"
LAYOUT_GRID_MAJOR = "#2a3a4a"

# Couleurs des murs (visibles sur fond sombre)
WALL_TYPE_COLOR = {
    WallType.EXTERIOR: "#ffffff",    # Blanc pur pour murs extérieurs
    WallType.INTERIOR: "#e5e7eb",    # Gris très clair pour murs intérieurs
    WallType.COLUMN: "#fbbf24",      # Ambre pour poteaux
}


LAYER_COLORS = {
    "structure": "#e5e7eb",       # Murs, poteaux -> Blanc / Gris clair
    "circulation": "#2e90fa",     # Allées, AGV, convoyeurs -> Bleu
    "equipment": "#f79009",       # Machines -> Orange
    "storage": "#a78bfa",         # Racks, stockage -> Violet
    "workstations": "#12b76a",    # Postes de travail -> Vert
    "annotation": "#94a3b8",      # Cotes, texte
    "safety": "#f97066",          # Sécurité -> Rouge
}

# Mapping catégorie d'asset -> couche (couleur de codage)
CATEGORY_LAYER = {
    AssetCategory.MACHINE: "equipment",
    AssetCategory.CONVEYOR: "circulation",
    AssetCategory.RACK: "storage",
    AssetCategory.AGV: "circulation",
    AssetCategory.WORKSTATION: "workstations",
    AssetCategory.SAFETY: "safety",
    AssetCategory.STRUCTURAL: "structure",
}

# Couleurs par catégorie (dérivées des couches)
CATEGORY_COLORS = {
    AssetCategory.MACHINE: "#f79009",       # Equipment: Orange
    AssetCategory.CONVEYOR: "#2e90fa",       # Circulation: Bleu
    AssetCategory.RACK: "#a78bfa",          # Storage: Violet
    AssetCategory.AGV: "#2e90fa",           # Circulation: Bleu
    AssetCategory.WORKSTATION: "#12b76a",   # Workstations: Vert
    AssetCategory.SAFETY: "#f97066",        # Safety: Rouge
    AssetCategory.STRUCTURAL: "#e5e7eb",    # Structure: Blanc/Gris clair
}


# Couleurs 3D pour les zones (RGBA 0-1)
ZONE_3D_COLORS = {
    ZoneType.CIRCULATION_PEDESTRIAN: (0.55, 0.64, 0.98, 0.3),
    ZoneType.CIRCULATION_FORKLIFT: (0.55, 0.64, 0.98, 0.4),
    ZoneType.CIRCULATION_AGV: (0.18, 0.56, 0.98, 0.3),
    ZoneType.STORAGE: (0.65, 0.54, 0.98, 0.2),
    ZoneType.WORK_AREA: (0.07, 0.72, 0.41, 0.2),
    ZoneType.OFFICE: (0.98, 0.75, 0.18, 0.2),
}

# Couleur 2D des zones selon le type (codage par couche)
ZONE_TYPE_COLOR = {
    ZoneType.CIRCULATION_PEDESTRIAN: LAYER_COLORS["circulation"],
    ZoneType.CIRCULATION_FORKLIFT: LAYER_COLORS["circulation"],
    ZoneType.CIRCULATION_AGV: LAYER_COLORS["circulation"],
    ZoneType.STORAGE: LAYER_COLORS["storage"],
    ZoneType.WORK_AREA: LAYER_COLORS["workstations"],
    ZoneType.OFFICE: "#f79009",
}


# ============================================================
# OUTILS DE DESSIN (MODES)
# ============================================================

class LayoutTool(str, Enum):
    SELECT = "select"
    PAN = "pan"
    WALL = "wall"
    DOOR = "door"
    ZONE = "zone"
    RECT_ZONE = "rect_zone"
    ASSET = "asset"
    WORKSTATION = "workstation"
    TRANSPORT = "transport"
    MEASURE = "measure"
    DIMENSION = "dimension"  # Cotation linéaire (style LibreCAD)


class SnapMode(str, Enum):
    GRID = "grid"
    ENDPOINT = "endpoint"
    MIDPOINT = "midpoint"
    INTERSECTION = "intersection"
    PERPENDICULAR = "perpendicular"
    TANGENT = "tangent"
    NONE = "none"


# ============================================================
# ITEMS GRAPHIQUES PERSONNALISÉS
# ============================================================

class GridItem(QGraphicsItem):
    """Grille magnétique configurable."""
    
    def __init__(self, grid_size: float = 1.0, major_every: int = 5, units: str = "meters"):
        super().__init__()
        self.grid_size = grid_size
        self.major_every = major_every
        self.units = units
        self.setZValue(-100)
    
    def boundingRect(self) -> QRectF:
        return QRectF(-10000, -10000, 20000, 20000)
    
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        
        rect = self.boundingRect()
        left = int(rect.left() / self.grid_size) * self.grid_size
        top = int(rect.top() / self.grid_size) * self.grid_size
        right = int(rect.right() / self.grid_size) * self.grid_size
        bottom = int(rect.bottom() / self.grid_size) * self.grid_size
        
        # Grille fine
        pen_minor = QPen(QColor(LAYOUT_GRID_LIGHT), 0.5)
        pen_minor.setCosmetic(True)
        painter.setPen(pen_minor)
        
        x = left
        minor_count = 0
        while x <= right:
            if minor_count % self.major_every != 0:
                painter.drawLine(QLineF(x, top, x, bottom))
            minor_count += 1
            x += self.grid_size
        
        y = top
        minor_count = 0
        while y <= bottom:
            if minor_count % self.major_every != 0:
                painter.drawLine(QLineF(left, y, right, y))
            minor_count += 1
            y += self.grid_size
        
        # Grille majeure
        pen_major = QPen(QColor(LAYOUT_GRID_MAJOR), 1.0)
        pen_major.setCosmetic(True)
        painter.setPen(pen_major)
        
        x = left
        major_count = 0
        while x <= right:
            if major_count % self.major_every == 0:
                painter.drawLine(QLineF(x, top, x, bottom))
            major_count += 1
            x += self.grid_size
        
        y = top
        major_count = 0
        while y <= bottom:
            if major_count % self.major_every == 0:
                painter.drawLine(QLineF(left, y, right, y))
            major_count += 1
            y += self.grid_size


class WallItem(QGraphicsPathItem):
    """Segment de mur avec épaisseur."""
    
    def __init__(self, wall: WallSegment, scale: float = 1000.0, view=None):
        super().__init__()
        self.wall = wall
        self.scale = scale  # pixels par mètre
        self.view = view
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setZValue(10)
        self._length_text_item = None
        self._length_bg = None
        self._update_path()

    def _update_path(self):
        path = QPainterPath()
        s = self.wall.start
        e = self.wall.end
        thickness = self.wall.thickness_m
        
        dx = e.x - s.x
        dy = e.y - s.y
        length = math.hypot(dx, dy)
        if length == 0:
            self.setPath(path)
            self._update_length_text()
            return
        
        nx = -dy / length * thickness / 2
        ny = dx / length * thickness / 2
        
        if getattr(self.wall, 'has_door', False) and getattr(self.wall, 'door_id', None):
            t = getattr(self.wall, 'door_position', 0.5)
            gap = getattr(self.wall, 'door_width', 1.0) / 2
            
            mid_x = s.x + t * dx
            mid_y = s.y + t * dy
            
            door_along_x = dx / length * gap
            door_along_y = dy / length * gap
            
            left_end_x = mid_x - door_along_x
            left_end_y = mid_y - door_along_y
            right_start_x = mid_x + door_along_x
            right_start_y = mid_y + door_along_y
            
            path.moveTo((s.x + nx) * self.scale, (s.y + ny) * self.scale)
            path.lineTo((left_end_x + nx) * self.scale, (left_end_y + ny) * self.scale)
            path.lineTo((left_end_x - nx) * self.scale, (left_end_y - ny) * self.scale)
            path.lineTo((s.x - nx) * self.scale, (s.y - ny) * self.scale)
            path.closeSubpath()
            
            path.moveTo((right_start_x + nx) * self.scale, (right_start_y + ny) * self.scale)
            path.lineTo((e.x + nx) * self.scale, (e.y + ny) * self.scale)
            path.lineTo((e.x - nx) * self.scale, (e.y - ny) * self.scale)
            path.lineTo((right_start_x - nx) * self.scale, (right_start_y - ny) * self.scale)
            path.closeSubpath()
        else:
            path.moveTo((s.x + nx) * self.scale, (s.y + ny) * self.scale)
            path.lineTo((e.x + nx) * self.scale, (e.y + ny) * self.scale)
            path.lineTo((e.x - nx) * self.scale, (e.y - ny) * self.scale)
            path.lineTo((s.x - nx) * self.scale, (s.y - ny) * self.scale)
            path.closeSubpath()
        
        self.setPath(path)
        
        color = WALL_TYPE_COLOR.get(self.wall.wall_type, "#e5e7eb")
        pen = QPen(QColor(color), 2.0)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(color + "60")))
        
        self._update_length_text()
    
    def _update_length_text(self):
        """Affiche la longueur du mur au centre."""
        length_m = self.wall.length()
        if length_m < 0.1:  # Ne pas afficher si trop court
            if self._length_text_item:
                self._length_text_item.setPlainText("")
            return
        
        if self._length_text_item is None:
            self._length_text_item = QGraphicsTextItem(f"{length_m:.2f} m", self)
            self._length_text_item.setDefaultTextColor(QColor("#ffffff"))
            font = QFont("Arial", 8)
            font.setBold(True)
            self._length_text_item.setFont(font)
            self._length_text_item.setZValue(11)
            # Fond semi-transparent
            self._length_bg = QGraphicsRectItem(self)
            self._length_bg.setZValue(10)
            self._length_bg.setPen(Qt.PenStyle.NoPen)
            self._length_bg.setBrush(QBrush(QColor(0, 0, 0, 150)))
        else:
            self._length_text_item.setPlainText(f"{length_m:.2f} m")
        
        # Centrer sur le mur
        s = self.wall.start
        e = self.wall.end
        mid_x = (s.x + e.x) / 2 * self.scale
        mid_y = (s.y + e.y) / 2 * self.scale
        
        text_rect = self._length_text_item.boundingRect()
        self._length_text_item.setPos(mid_x - text_rect.width() / 2, mid_y - text_rect.height() / 2)
        
        # Mettre à jour le fond
        if self._length_bg:
            padding = 2
            self._length_bg.setRect(
                mid_x - text_rect.width() / 2 - padding,
                mid_y - text_rect.height() / 2 - padding,
                text_rect.width() + 2 * padding,
                text_rect.height() + 2 * padding
            )
    
    def mouseMoveEvent(self, event):
            super().mouseMoveEvent(event)
            # Mettre à jour le modèle
            pos = self.pos()
            self.wall.start = Vector2D(pos.x() / self.scale, pos.y() / self.scale)
            # Note: pour un vrai déplacement, il faut gérer start/end
            self._update_length_text()
    
    def contextMenuEvent(self, event):
        if self.view:
            self.view.show_item_context_menu(self, event.screenPos())
    
    def mouseDoubleClickEvent(self, event):
        if self.view:
            self.view.rename_item(self)
        super().mouseDoubleClickEvent(event)


class ZoneItem(QGraphicsPolygonItem):
    """Zone délimitée (polygone)."""
    
    def __init__(self, zone: Zone, scale: float = 1000.0, view=None):
        super().__init__()
        self.zone = zone
        self.scale = scale
        self.view = view
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setZValue(5)
        self._name_text_item = None
        self._update_polygon()
    
    def _update_polygon(self):
        poly = QPolygonF()
        for v in self.zone.vertices:
            poly.append(QPointF(v.x * self.scale, v.y * self.scale))
        self.setPolygon(poly)

        base_color = self._safe_color(self.zone.color, ZONE_TYPE_COLOR.get(self.zone.zone_type, "#2c7a7b"))
        color = QColor(base_color)
        color.setAlpha(int(self.zone.opacity * 255))
        self.setBrush(QBrush(color))
        pen = QPen(QColor(base_color), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)

        # Mettre à jour ou créer le texte du nom
        self._update_name_text()

    @staticmethod
    def _safe_color(value, fallback: str) -> str:
        """Retourne une chaîne couleur hex valide depuis value (str, tuple RGBA, etc.)."""
        if isinstance(value, str):
            c = QColor(value)
            if c.isValid():
                return value
            return fallback
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            r, g, bl = value[0], value[1], value[2]
            if all(0.0 <= c <= 1.0 for c in (r, g, bl)):
                return f"#{int(r*255):02x}{int(g*255):02x}{int(bl*255):02x}"
            return f"#{int(r):02x}{int(g):02x}{int(bl):02x}"
        return fallback
    
    def _update_name_text(self):
        """Met à jour l'affichage du nom de la zone au centre."""
        if not self.zone.name:
            if self._name_text_item:
                self._name_text_item.setPlainText("")
            if self._name_bg_rect:
                self._name_bg_rect.setVisible(False)
            return

        if not self.zone.vertices:
            return

        # Taille de police : soit stockée dans metadata, soit ~8 % de la petite dimension
        xs = [v.x for v in self.zone.vertices]
        ys = [v.y for v in self.zone.vertices]
        zone_w = (max(xs) - min(xs)) * self.scale
        zone_h = (max(ys) - min(ys)) * self.scale
        font_size_meta = self.zone.metadata.get("font_size")
        if font_size_meta:
            font_px = max(16, min(max(zone_w, zone_h) * 0.5, font_size_meta))
        else:
            font_px = max(20, min(zone_w, zone_h) * 0.08)
            font_px = min(font_px, 160)

        if self._name_text_item is None:
            self._name_text_item = QGraphicsTextItem(self.zone.name, self)
            self._name_text_item.setZValue(7)
            self._name_text_item.setDefaultTextColor(QColor("#ffffff"))
            self._name_bg_rect = QGraphicsRectItem(self)
            self._name_bg_rect.setZValue(6)
            self._name_bg_rect.setPen(Qt.PenStyle.NoPen)
            self._name_bg_rect.setBrush(QBrush(QColor(10, 16, 24, 220)))
        else:
            self._name_text_item.setPlainText(self.zone.name)

        font = QFont("Arial")
        font.setPixelSize(int(font_px))
        font.setBold(True)
        self._name_text_item.setFont(font)

        centroid = self.zone.centroid()
        tw = self._name_text_item.boundingRect().width()
        th = self._name_text_item.boundingRect().height()
        cx = centroid.x * self.scale - tw / 2
        cy = centroid.y * self.scale - th / 2
        self._name_text_item.setPos(cx, cy)
        if self._name_bg_rect:
            self._name_bg_rect.setVisible(True)
            pad = font_px * 0.3
            self._name_bg_rect.setRect(
                cx - pad, cy - pad, tw + pad * 2, th + pad * 2
            )
    
    def contextMenuEvent(self, event):
        if self.view:
            self.view.show_item_context_menu(self, event.screenPos())
    
    def mouseDoubleClickEvent(self, event):
        if self.view:
            self.view.rename_item(self)
        super().mouseDoubleClickEvent(event)


class AssetItem(QGraphicsRectItem):
    """Asset physique (machine, rack, convoyeur)."""
    
    def __init__(self, asset: PhysicalAsset, scale: float = 1000.0, view=None):
        super().__init__()
        self.asset = asset
        self.scale = scale
        self.view = view
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(20)
        self._name_text_item = None
        self._update_geometry()
    
    def _update_geometry(self):
        w = self.asset.width_m * self.scale
        h = self.asset.depth_m * self.scale
        self.setRect(-w/2, -h/2, w, h)
        self.setPos(self.asset.position.x * self.scale, self.asset.position.y * self.scale)
        self.setRotation(self.asset.rotation_deg)
        
        # Couleur selon catégorie (codage par couche)
        color = CATEGORY_COLORS.get(self.asset.category, "#8da2fb")
        pen = QPen(QColor(color), 2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(color + "60")))
        
        # Mettre à jour le label de nom
        self._update_name_text()
    
    def _update_name_text(self):
        """Affiche le nom de l'asset au centre."""
        if not self.asset.name:
            # Nettoyer si pas de nom
            if self._name_text_item:
                self._name_text_item.setPlainText("")
            if self._name_bg_rect:
                self._name_bg_rect.setRect(0, 0, 0, 0)
            return
            
        if self._name_text_item is None:
            self._name_text_item = QGraphicsTextItem(self.asset.name, self)
            self._name_text_item.setDefaultTextColor(QColor("#ffffff"))
            font = QFont("Arial", 9)
            font.setBold(True)
            self._name_text_item.setFont(font)
            self._name_text_item.setZValue(21)
            # Fond semi-transparent derrière le texte
            self._name_bg_rect = QGraphicsRectItem(self)
            self._name_bg_rect.setZValue(20)
            self._name_bg_rect.setPen(Qt.PenStyle.NoPen)
            self._name_bg_rect.setBrush(QBrush(QColor(0, 0, 0, 120)))
        else:
            self._name_text_item.setPlainText(self.asset.name)
        
        # Centrer le texte dans l'asset
        text_rect = self._name_text_item.boundingRect()
        x_pos = -text_rect.width() / 2
        y_pos = -text_rect.height() / 2
        self._name_text_item.setPos(x_pos, y_pos)
        # Mettre à jour le fond
        if self._name_bg_rect:
            padding = 3
            self._name_bg_rect.setRect(
                x_pos - padding, y_pos - padding,
                text_rect.width() + 2*padding, text_rect.height() + 2*padding
            )
    
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.asset.position = Vector2D(
                value.x() / self.scale, value.y() / self.scale
            )
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        rect = self.rect()
        if rect.width() < 10 or rect.height() < 10:
            return
        machine_type = self.asset.machine_type or self.asset.asset_type
        if not machine_type:
            return
        icon_size = int(min(rect.width(), rect.height()) * 0.6)
        if icon_size < 8:
            return
        pixmap = get_machine_pixmap(machine_type, icon_size)
        if pixmap.isNull():
            return
        x = rect.x() + (rect.width() - pixmap.width()) / 2
        y = rect.y() + (rect.height() - pixmap.height()) / 2
        painter.setOpacity(0.85)
        painter.drawPixmap(x, y, pixmap)
        painter.setOpacity(1.0)
    
    def contextMenuEvent(self, event):
        if self.view:
            self.view.show_item_context_menu(self, event.screenPos())
    
    def mouseDoubleClickEvent(self, event):
        if self.view:
            self.view.rename_item(self)
        super().mouseDoubleClickEvent(event)


class WorkstationItem(QGraphicsRectItem):
    """Poste de travail layout."""
    
    def __init__(self, ws: WorkstationLayout, scale: float = 1000.0, view=None):
        super().__init__()
        self.workstation = ws
        self.scale = scale
        self.view = view
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setZValue(15)
        self._name_text_item = None
        self._name_bg_rect = None
        self._update_geometry()
    
    def _update_geometry(self):
        w = self.workstation.width_m * self.scale
        h = self.workstation.depth_m * self.scale
        self.setRect(-w/2, -h/2, w, h)
        self.setPos(self.workstation.position.x * self.scale, self.workstation.position.y * self.scale)
        self.setRotation(self.workstation.rotation_deg)
        pen = QPen(QColor(LAYER_COLORS["workstations"]), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(LAYER_COLORS["workstations"] + "40")))
        
        # Mettre à jour le label de nom
        self._update_name_text()
    
    def _update_name_text(self):
        """Affiche le nom du poste au centre."""
        if not self.workstation.name:
            if self._name_text_item:
                self._name_text_item.setPlainText("")
            if self._name_bg_rect:
                self._name_bg_rect.setRect(0, 0, 0, 0)
            return
            
        if self._name_text_item is None:
            self._name_text_item = QGraphicsTextItem(self.workstation.name, self)
            self._name_text_item.setDefaultTextColor(QColor("#ffffff"))
            font = QFont("Arial", 9)
            font.setBold(True)
            self._name_text_item.setFont(font)
            self._name_text_item.setZValue(16)
            # Fond semi-transparent derrière le texte
            self._name_bg_rect = QGraphicsRectItem(self)
            self._name_bg_rect.setZValue(15)
            self._name_bg_rect.setPen(Qt.PenStyle.NoPen)
            self._name_bg_rect.setBrush(QBrush(QColor(0, 0, 0, 120)))
        else:
            self._name_text_item.setPlainText(self.workstation.name)
        
        # Centrer le texte
        text_rect = self._name_text_item.boundingRect()
        x_pos = -text_rect.width() / 2
        y_pos = -text_rect.height() / 2
        self._name_text_item.setPos(x_pos, y_pos)
        # Mettre à jour le fond
        if self._name_bg_rect:
            padding = 3
            self._name_bg_rect.setRect(
                x_pos - padding, y_pos - padding,
                text_rect.width() + 2*padding, text_rect.height() + 2*padding
            )
    
    def contextMenuEvent(self, event):
        if self.view:
            self.view.show_item_context_menu(self, event.screenPos())
    
    def mouseDoubleClickEvent(self, event):
        if self.view:
            self.view.rename_item(self)
        super().mouseDoubleClickEvent(event)


class FlowDot(QGraphicsEllipseItem):
    """Point animé se déplaçant le long d'un lien de transport."""

    def __init__(self, link_item: TransportLinkItem, color: QColor, radius: float = 4.0):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.link_item = link_item
        self.radius = radius
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.GlobalColor.white, 0.5))
        self.setZValue(15)
        self._progress = 0.0  # 0..1 along the full path
        self._speed = 0.008   # progress per tick
        self.setVisible(False)

    def advance_progress(self):
        self._progress += self._speed
        if self._progress > 1.0:
            self._progress = 1.0
        pts = self.link_item.link.path_points
        if len(pts) < 2:
            self.setVisible(False)
            return False

        # Map 0..1 progress to position along polyline
        total_len = 0.0
        seg_lens = []
        for i in range(len(pts) - 1):
            d = pts[i].distance_to(pts[i + 1])
            seg_lens.append(d)
            total_len += d

        if total_len < 0.001:
            self.setVisible(False)
            return False

        target = self._progress * total_len
        accum = 0.0
        s = self.link_item.scale
        for i, seg in enumerate(seg_lens):
            if accum + seg >= target or i == len(seg_lens) - 1:
                t = (target - accum) / seg if seg > 0 else 0
                x = (pts[i].x + t * (pts[i + 1].x - pts[i].x)) * s
                y = (pts[i].y + t * (pts[i + 1].y - pts[i].y)) * s
                self.setPos(x, y)
                self.setVisible(True)
                break
            accum += seg

        if self._progress >= 1.0:
            self._progress = 0.0

        return True


class TransportLinkItem(QGraphicsPathItem):
    """Lien de transport (chemin) avec fleche directionnelle."""

    _arrow_size = 10.0

    def __init__(self, link: TransportLink, scale: float = 1000.0, view=None):
        super().__init__()
        self.link = link
        self.scale = scale
        self.view = view
        self.setZValue(8)
        self._name_text_item = None

        colors = {
            TransportMode.MANUAL: "#f43f5e",
            TransportMode.CONVEYOR: "#2563eb",
            TransportMode.AGV: "#7c3aed",
            TransportMode.FORKLIFT: "#ea580c",
        }
        self._color_str = colors.get(self.link.transport_mode, "#f43f5e")
        color = QColor(self._color_str)
        pen = QPen(color, 4.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if self.link.transport_mode == TransportMode.MANUAL:
            pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self._update_path()
        self._update_name_text()

    def _update_path(self):
        path = QPainterPath()
        if not self.link.path_points:
            return
        p0 = self.link.path_points[0]
        path.moveTo(p0.x * self.scale, p0.y * self.scale)
        for p in self.link.path_points[1:]:
            path.lineTo(p.x * self.scale, p.y * self.scale)
        self.setPath(path)

    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        pts = self.link.path_points
        if len(pts) < 2:
            return

        painter.save()
        painter.setPen(QPen(QColor(self._color_str), 3.0))
        brush = QBrush(QColor(self._color_str))
        painter.setBrush(brush)

        s = self.scale
        asz = self._arrow_size

        # Draw arrowheads at the end of each segment
        for i in range(len(pts) - 1):
            a = pts[i]
            b = pts[i + 1]
            dx = b.x - a.x
            dy = b.y - a.y
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len < 0.001:
                continue

            # Arrow position: 70% along the segment
            t = 0.7
            mx = (a.x + t * dx) * s
            my = (a.y + t * dy) * s

            angle = math.atan2(dy, dx)
            self._draw_arrow(painter, mx, my, angle, asz)

        # Arrow at the end point
        last = pts[-1]
        prev = pts[-2]
        dx = last.x - prev.x
        dy = last.y - prev.y
        angle = math.atan2(dy, dx)
        self._draw_arrow(painter, last.x * s, last.y * s, angle, asz * 1.3)

        painter.restore()

    def _draw_arrow(self, painter, x, y, angle, size):
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        p1 = QPointF(x - size * cos_a + size * 0.4 * -sin_a,
                     y - size * sin_a + size * 0.4 * cos_a)
        p2 = QPointF(x - size * cos_a + size * 0.4 * sin_a,
                     y - size * sin_a - size * 0.4 * cos_a)
        poly = QPolygonF([QPointF(x, y), p1, p2])
        painter.drawPolygon(poly)
    
    def _update_name_text(self):
        name = getattr(self.link, 'name', None) or self.link.id
        if not self.link.path_points:
            if self._name_text_item:
                self._name_text_item.setPlainText("")
            return

        if self._name_text_item is None:
            self._name_text_item = QGraphicsTextItem(name)
            self._name_text_item.setDefaultTextColor(QColor("#ffffff"))
            font = QFont("Arial", 8)
            font.setBold(True)
            self._name_text_item.setFont(font)
            self._name_text_item.setZValue(9)
            self._name_text_item.setParentItem(self)
        else:
            self._name_text_item.setPlainText(name)
        
        # Position au milieu du chemin
        mid_idx = len(self.link.path_points) // 2
        mid_pt = self.link.path_points[mid_idx]
        text_rect = self._name_text_item.boundingRect()
        self._name_text_item.setPos(
            mid_pt.x * self.scale - text_rect.width() / 2,
            mid_pt.y * self.scale - text_rect.height() / 2
        )
    
    def contextMenuEvent(self, event):
        if self.view:
            self.view.show_item_context_menu(self, event.screenPos())
    
    def mouseDoubleClickEvent(self, event):
        if self.view:
            self.view.rename_item(self)
        super().mouseDoubleClickEvent(event)


SNAP_MARKER_STYLE = {
    SnapMode.GRID: ("#2e90fa", "G"),
    SnapMode.ENDPOINT: ("#ff6d5a", "E"),
    SnapMode.MIDPOINT: ("#12b76a", "M"),
    SnapMode.INTERSECTION: ("#f79009", "X"),
    SnapMode.PERPENDICULAR: ("#a78bfa", "P"),
    SnapMode.TANGENT: ("#8da2fb", "T"),
    SnapMode.NONE: ("#94a3b8", ""),
}


class SnapMarkerItem(QGraphicsEllipseItem):
    """Marqueur de snap (point d'accroche) avec code couleur selon le type."""

    def __init__(self, pos: QPointF, snap_type: SnapMode):
        super().__init__(-6, -6, 12, 12)
        self.setPos(pos)
        self.setZValue(100)
        self.snap_type = snap_type
        color, _ = SNAP_MARKER_STYLE.get(snap_type, ("#ff6d5a", ""))
        pen = QPen(QColor(color), 2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(color + "80")))


class DimensionItem(QGraphicsItemGroup):
    """Cote professionnelle (style LibreCAD) :
    - ligne de cote parallèle avec offset
    - lignes de rappel (extension) en pointillés
    - têtes de flèche aux deux extrémités
    - texte de distance en mètres
    """

    def __init__(self, p1: QPointF, p2: QPointF, dim_pos: QPointF, scale: float, view=None):
        super().__init__()
        self.p1 = p1
        self.p2 = p2
        self.dim_pos = dim_pos
        self.scale = scale
        self.view = view
        self.setZValue(25)
        self._build()

    def _build(self):
        dx = self.p2.x() - self.p1.x()
        dy = self.p2.y() - self.p1.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return

        dir_x = dx / length
        dir_y = dy / length
        # Normale (perpendiculaire)
        norm_x = -dir_y
        norm_y = dir_x

        # Offset signé du point de placement sur la normale
        offset = ((self.dim_pos.x() - self.p1.x()) * norm_x +
                  (self.dim_pos.y() - self.p1.y()) * norm_y)

        d1 = QPointF(self.p1.x() + norm_x * offset, self.p1.y() + norm_y * offset)
        d2 = QPointF(self.p2.x() + norm_x * offset, self.p2.y() + norm_y * offset)

        # --- Ligne de cote (parallèle) ---
        dim_line = QGraphicsLineItem(QLineF(d1, d2))
        pen = QPen(QColor(LAYER_COLORS["annotation"]), 1.5)
        pen.setCosmetic(True)
        dim_line.setPen(pen)
        self.addToGroup(dim_line)

        # --- Lignes de rappel (extension) en pointillés ---
        ext_pen = QPen(QColor("#94a3b8"), 1.0, Qt.PenStyle.DashLine)
        ext_pen.setCosmetic(True)
        ext1 = QGraphicsLineItem(QLineF(self.p1, d1))
        ext1.setPen(ext_pen)
        self.addToGroup(ext1)
        ext2 = QGraphicsLineItem(QLineF(self.p2, d2))
        ext2.setPen(ext_pen)
        self.addToGroup(ext2)

        # --- Têtes de flèche aux deux extrémités ---
        arrow_size = 9
        self._add_arrowhead(d1, dir_x, dir_y, arrow_size)
        self._add_arrowhead(d2, -dir_x, -dir_y, arrow_size)

        # --- Texte de distance (mètres) ---
        dist_m = length / self.scale
        text = QGraphicsTextItem(f"{dist_m:.2f} m")
        text.setDefaultTextColor(QColor("#e5e7eb"))
        font = QFont("Arial", 9)
        font.setBold(True)
        text.setFont(font)
        mid_x = (d1.x() + d2.x()) / 2
        mid_y = (d1.y() + d2.y()) / 2
        tr = text.boundingRect()
        text.setPos(mid_x - tr.width() / 2, mid_y - tr.height() / 2)
        self.addToGroup(text)

        self.distance_m = dist_m

    def _add_arrowhead(self, tip: QPointF, dir_x: float, dir_y: float, size: float):
        """Triangle plein pointant selon (dir_x, dir_y)."""
        base_x = tip.x() - dir_x * size
        base_y = tip.y() - dir_y * size
        perp_x = -dir_y * size * 0.5
        perp_y = dir_x * size * 0.5
        path = QPainterPath()
        path.moveTo(tip.x(), tip.y())
        path.lineTo(base_x + perp_x, base_y + perp_y)
        path.lineTo(base_x - perp_x, base_y - perp_y)
        path.closeSubpath()
        arrow = QGraphicsPathItem(path)
        arrow.setBrush(QBrush(QColor(LAYER_COLORS["annotation"])))
        arrow.setPen(Qt.PenStyle.NoPen)
        self.addToGroup(arrow)


class MeasureItem(QGraphicsItemGroup):
    """Mesure persistante : segment + étiquette de distance (mètres)."""

    def __init__(self, p1: QPointF, p2: QPointF, scale: float, view=None):
        super().__init__()
        self.scale = scale
        self.setZValue(24)
        self._build(p1, p2)

    def _build(self, p1: QPointF, p2: QPointF):
        line = QGraphicsLineItem(QLineF(p1, p2))
        pen = QPen(QColor("#f79009"), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        line.setPen(pen)
        self.addToGroup(line)

        dist_m = QLineF(p1, p2).length() / self.scale
        text = QGraphicsTextItem(f"{dist_m:.2f} m")
        text.setDefaultTextColor(QColor("#f79009"))
        font = QFont("Arial", 10)
        font.setBold(True)
        text.setFont(font)
        tr = text.boundingRect()
        mid_x = (p1.x() + p2.x()) / 2 - tr.width() / 2
        mid_y = (p1.y() + p2.y()) / 2 - tr.height() / 2
        text.setPos(mid_x, mid_y)
        self.addToGroup(text)
        self.distance_m = dist_m


# ============================================================
# VUE PRINCIPALE LAYOUT 2D
# ============================================================

class LayoutView2D(QGraphicsView):
    """Vue Implantation 2D - Éditeur de plan d'usine."""
    
    # Signaux
    tool_changed = Signal(str)
    selection_changed = Signal(list)
    status_message = Signal(str)
    building_changed = Signal()

    def __init__(self, building: BuildingLayout, parent=None):
        super().__init__(parent)
        self.building = building
        self._history: list[dict] = [building.to_dict()]
        self._redo_stack: list[dict] = []
        self._suppress_undo: bool = False

        self.scale = 1000.0  # 1m = 1000px (1mm = 1px)

        # Configuration vue
        self.setScene(QGraphicsScene(self))
        self.scene().selectionChanged.connect(self._on_selection_changed)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        # État
        self.current_tool = LayoutTool.SELECT
        self.snap_modes: Set[SnapMode] = {
            SnapMode.GRID, SnapMode.ENDPOINT, SnapMode.MIDPOINT, SnapMode.INTERSECTION
        }
        self.grid_size_m = building.grid_size_m
        self.snap_enabled = building.snap_enabled

        # Dessin en cours
        self._drawing = False
        self._draw_start = QPointF()
        self._current_item = None
        self._temp_items: List[QGraphicsItem] = []
        self._wall_start = None
        self._wall_target_length: Optional[float] = None
        self._zone_points: List[Vector2D] = []

        # Overlay de saisie de longueur pour les murs
        self._wall_length_overlay = QLineEdit(self.viewport())
        self._wall_length_overlay.setPlaceholderText("Longueur (m)")
        self._wall_length_overlay.setFixedWidth(120)
        self._wall_length_overlay.hide()
        self._wall_length_overlay.returnPressed.connect(self._on_wall_length_confirmed)
        self._wall_length_overlay.editingFinished.connect(self._on_wall_length_confirmed)

        # Asset en cours de placement
        self._pending_asset: Optional[PhysicalAsset] = None
        self._asset_preview_item = None

        # Porte en cours de placement
        self._pending_door: Optional[Door] = None
        self._door_preview_item = None
        self._door_flip_side = False  # F pour inverser le côté d'ouverture

        # Animation de flux
        self._flow_dots: List[FlowDot] = []
        self._flow_timer = QTimer(self)
        self._flow_timer.timeout.connect(self._tick_flow)
        self._flow_running = False

        # Sélection
        self._multi_select = False

        # Grille
        self._grid_item = GridItem(grid_size=self.grid_size_m * self.scale, major_every=5)
        self.scene().addItem(self._grid_item)

        # Remplir la scène
        self.rebuild_scene()

    def _notify_changed(self):
        """Émet building_changed en enregistrant l'état précédent pour annulation."""
        if not self._suppress_undo:
            self.push_undo()
        self.building_changed.emit()

    def export_gltf(self, path: str) -> str:
        """Exporte le bâtiment courant au format glTF 2.0 (.gltf)."""
        from engine.gltf_export import export_layout_to_gltf
        return export_layout_to_gltf(self.building, path)

    def _on_selection_changed(self):
        items = self.scene().selectedItems()
        log_debug(f"Scene selection changed: {len(items)} item(s)")
        for it in items:
            desc = type(it).__name__
            if hasattr(it, 'id'):
                desc += f" id={it.id}"
            if hasattr(it, 'wall') and it.wall:
                desc += f" wall_id={it.wall.id}"
            if hasattr(it, 'door') and it.door:
                desc += f" door_id={it.door.id}"
            desc += f" has_door={hasattr(it,'door')} has_wall={hasattr(it,'wall')}"
            log_debug(f"  └─ {desc}")
        self.selection_changed.emit(items)
    
    def rebuild_scene(self):
        """Reconstruit la scène à partir du modèle."""
        # Sauvegarder les items non-modèle (grille)
        grid = self._grid_item
        
        self.scene().clear()
        
        # Re-add grille
        self._grid_item = GridItem(grid_size=self.grid_size_m * self.scale, major_every=5)
        self.scene().addItem(self._grid_item)
        
        # Murs
        for wall in self.building.walls:
            item = WallItem(wall, self.scale, self)
            self.scene().addItem(item)
        
        # Portes
        for door in self.building.doors:
            # Trouver le mur parent
            wall = next((w for w in self.building.walls if w.id == door.wall_id), None)
            if wall:
                item = DoorItem(door, wall, self.scale, self)
                self.scene().addItem(item)
        
        # Zones
        for zone in self.building.zones:
            item = ZoneItem(zone, self.scale, self)
            self.scene().addItem(item)
        
        # Assets
        for asset in self.building.assets:
            item = AssetItem(asset, self.scale, self)
            self.scene().addItem(item)
        
        # Postes de travail
        for ws in self.building.workstations:
            item = WorkstationItem(ws, self.scale, self)
            self.scene().addItem(item)
        
        # Liens de transport
        for link in self.building.transport_links:
            item = TransportLinkItem(link, self.scale, self)
            self.scene().addItem(item)

        # Cotes (dimensions)
        for dim in self.building.dimensions:
            self._rebuild_dimension(dim)

        # Recréer les dots d'animation si le flux était actif
        was_running = self._flow_running
        self._flow_dots.clear()
        if was_running:
            self._rebuild_flow_dots()
            self._flow_timer.start(30)

    def _rebuild_flow_dots(self):
        """Crée les points animés pour chaque lien de transport."""
        for item in self.scene().items():
            if isinstance(item, TransportLinkItem):
                pts = item.link.path_points
                if len(pts) >= 2:
                    color = QColor(item._color_str)
                    dot = FlowDot(item, color)
                    self.scene().addItem(dot)
                    dot._speed = max(0.002, 0.012 - 0.002 * len(self._flow_dots))
                    self._flow_dots.append(dot)

    def _tick_flow(self):
        for dot in self._flow_dots:
            dot.advance_progress()

    def start_flow_animation(self):
        if self._flow_running:
            return
        self._flow_running = True
        self._rebuild_flow_dots()
        self._flow_timer.start(30)

    def stop_flow_animation(self):
        self._flow_running = False
        self._flow_timer.stop()
        for dot in self._flow_dots:
            self.scene().removeItem(dot)
        self._flow_dots.clear()

    def toggle_flow_animation(self) -> bool:
        if self._flow_running:
            self.stop_flow_animation()
        else:
            self.start_flow_animation()
        return self._flow_running

    def _rebuild_dimension(self, dim: DimensionLayout):
        """Reconstruit un item de cote à partir du modèle (offset stocké en metadata)."""
        p1 = QPointF(dim.start.x * self.scale, dim.start.y * self.scale)
        p2 = QPointF(dim.end.x * self.scale, dim.end.y * self.scale)
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        norm_x = -dy / length
        norm_y = dx / length
        offset_px = dim.metadata.get("offset_px", 20.0)
        mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
        dim_pos = QPointF(mid.x() + norm_x * offset_px, mid.y() + norm_y * offset_px)
        item = DimensionItem(p1, p2, dim_pos, self.scale, self)
        self.scene().addItem(item)

    @property
    def layout_data(self) -> BuildingLayout:
        """Propriété de compatibilité pour accéder au layout."""
        return self.building

    # ============================================================
    # LAYOUT DATA ACCESS
    # ============================================================

    @property
    def layout_data(self) -> BuildingLayout:
        """Compatibilité: retourne le bâtiment actuel."""
        return self.building

    def push_undo(self):
        """Sauvegarde l'état courant (après mutation) dans l'historique."""
        if self._suppress_undo:
            return
        self._history.append(self.building.to_dict())
        if len(self._history) > 51:
            self._history.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if len(self._history) <= 1:
            return
        current = self._history.pop()
        self._redo_stack.append(current)
        prev = self._history[-1]
        self._suppress_undo = True
        self.building = BuildingLayout.from_dict(prev)
        self.grid_size_m = self.building.grid_size_m
        self.snap_enabled = self.building.snap_enabled
        self.rebuild_scene()
        self.building_changed.emit()
        self._suppress_undo = False

    def redo(self):
        if not self._redo_stack:
            return
        nxt = self._redo_stack.pop()
        self._history.append(nxt)
        self._suppress_undo = True
        self.building = BuildingLayout.from_dict(nxt)
        self.grid_size_m = self.building.grid_size_m
        self.snap_enabled = self.building.snap_enabled
        self.rebuild_scene()
        self.building_changed.emit()
        self._suppress_undo = False

    def set_layout(self, layout: BuildingLayout):
        """Remplace le layout complet et reconstruit la scène."""
        self._suppress_undo = True
        self.building = layout
        self.grid_size_m = layout.grid_size_m
        self.snap_enabled = layout.snap_enabled
        self.rebuild_scene()
        self.building_changed.emit()
        self._suppress_undo = False
        # Enregistre l'état résultant pour annulation
        self._history.append(self.building.to_dict())
        if len(self._history) > 51:
            self._history.pop(0)
        self._redo_stack.clear()
    
    # ============================================================
    # OUTILS
    # ============================================================
    
    def set_tool(self, tool: LayoutTool):
        # Nettoyer l'état des outils intermédiaires avant de changer
        if hasattr(self, '_measure_start'):
            self._measure_start = None
        if hasattr(self, '_dimension_state'):
            self._reset_dimension_state()
        self.current_tool = tool
        self.tool_changed.emit(tool.value)
        self._update_cursor()
        self.status_message.emit(f"Outil: {tool.value}")
        self._clear_door_preview()
        if tool != LayoutTool.DOOR:
            self._pending_door = None
        # Assurer que la vue a le focus pour les raccourcis clavier
        self.setFocus()
    
    def set_door_type(self, door_type: str):
        if self._pending_door is None:
            self._pending_door = Door(id="", wall_id="", door_type=door_type)
        else:
            self._pending_door.door_type = door_type
        self.status_message.emit(f"Type porte: {door_type}")
    
    def _clear_door_preview(self):
        if self._door_preview_item:
            self.scene().removeItem(self._door_preview_item)
            self._door_preview_item = None
    
    def _update_cursor(self):
        cursors = {
            LayoutTool.SELECT: Qt.CursorShape.ArrowCursor,
            LayoutTool.PAN: Qt.CursorShape.OpenHandCursor,
            LayoutTool.WALL: Qt.CursorShape.CrossCursor,
            LayoutTool.DOOR: Qt.CursorShape.PointingHandCursor,
            LayoutTool.ZONE: Qt.CursorShape.CrossCursor,
            LayoutTool.RECT_ZONE: Qt.CursorShape.CrossCursor,
            LayoutTool.ASSET: Qt.CursorShape.DragMoveCursor,
            LayoutTool.WORKSTATION: Qt.CursorShape.DragMoveCursor,
            LayoutTool.TRANSPORT: Qt.CursorShape.CrossCursor,
            LayoutTool.MEASURE: Qt.CursorShape.CrossCursor,
            LayoutTool.DIMENSION: Qt.CursorShape.CrossCursor,
        }
        self.setCursor(cursors.get(self.current_tool, Qt.CursorShape.ArrowCursor))
    
    def set_snap_mode(self, mode: SnapMode, enabled: bool):
        if enabled:
            self.snap_modes.add(mode)
        else:
            self.snap_modes.discard(mode)
    
    def set_grid_size(self, size_m: float):
        self.grid_size_m = size_m
        self._grid_item.grid_size = size_m * self.scale
        self._grid_item.update()
    
    def set_pending_asset(self, asset: PhysicalAsset):
        """Prépare un asset à placer par clic."""
        self._pending_asset = asset
        self.set_tool(LayoutTool.ASSET)
    
    # ============================================================
    # SNAPPING
    # ============================================================
    
    def snap_point(self, pos: QPointF) -> QPointF:
        """Applique le snap au point donné."""
        if not self.snap_enabled:
            return pos
        
        best_pos = pos
        best_dist = float('inf')
        snap_threshold = 15  # pixels
        
        # Snap grille
        if SnapMode.GRID in self.snap_modes:
            grid_pix = self.grid_size_m * self.scale
            x = round(pos.x() / grid_pix) * grid_pix
            y = round(pos.y() / grid_pix) * grid_pix
            grid_pos = QPointF(x, y)
            dist = (grid_pos - pos).manhattanLength()
            if dist < best_dist:
                best_dist = dist
                best_pos = grid_pos
        
        # Snap aux points existants (endpoints, midpoints)
        if SnapMode.ENDPOINT in self.snap_modes or SnapMode.MIDPOINT in self.snap_modes:
            for item in self.scene().items():
                if isinstance(item, (WallItem, AssetItem, WorkstationItem, ZoneItem)):
                    points = self._get_snap_points(item)
                    for snap_pos, snap_type in points:
                        dist = (snap_pos - pos).manhattanLength()
                        if dist < best_dist and dist < snap_threshold:
                            best_dist = dist
                            best_pos = snap_pos
        
        # Snap aux intersections (croisement de murs / segments)
        if SnapMode.INTERSECTION in self.snap_modes:
            for inter in self._get_intersection_points():
                dist = (inter - pos).manhattanLength()
                if dist < best_dist and dist < snap_threshold:
                    best_dist = dist
                    best_pos = inter
        
        return best_pos
    
    def _collect_segments(self) -> List[QLineF]:
        """Retourne tous les segments (murs, bords d'assets/zones) en pixels."""
        segments = []
        for item in self.scene().items():
            if isinstance(item, WallItem):
                wall = item.wall
                segments.append(QLineF(
                    wall.start.x * self.scale, wall.start.y * self.scale,
                    wall.end.x * self.scale, wall.end.y * self.scale,
                ))
            elif isinstance(item, (AssetItem, WorkstationItem)):
                rect = item.rect()
                p = item.pos()
                corners = [p + rect.topLeft(), p + rect.topRight(),
                           p + rect.bottomRight(), p + rect.bottomLeft(), p + rect.topLeft()]
                for i in range(len(corners) - 1):
                    segments.append(QLineF(corners[i], corners[i + 1]))
            elif isinstance(item, ZoneItem):
                poly = item.polygon()
                n = poly.size()
                for i in range(n):
                    segments.append(QLineF(poly.at(i), poly.at((i + 1) % n)))
        return segments
    
    def _get_intersection_points(self) -> List[QPointF]:
        """Points d'intersection entre segments (dans un rayon de seuillage)."""
        segments = self._collect_segments()
        points = []
        threshold = 12  # pixels (tolérance d'intersection)
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                inter = self._line_intersection(segments[i], segments[j])
                if inter is not None:
                    points.append(inter)
        return points
    
    @staticmethod
    def _line_intersection(l1: QLineF, l2: QLineF) -> Optional[QPointF]:
        """Retourne le point d'intersection des deux segments, ou None."""
        p1, p2 = l1.p1(), l1.p2()
        p3, p4 = l2.p1(), l2.p2()
        x1, y1, x2, y2 = p1.x(), p1.y(), p2.x(), p2.y()
        x3, y3, x4, y4 = p3.x(), p3.y(), p4.x(), p4.y()
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-9:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / denom
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return QPointF(x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        return None
    
    def _get_snap_points(self, item: QGraphicsItem) -> List[tuple]:
        """Retourne les points de snap d'un item."""
        points = []
        
        if isinstance(item, WallItem):
            wall = item.wall
            pts = [
                (QPointF(wall.start.x * self.scale, wall.start.y * self.scale), SnapMode.ENDPOINT),
                (QPointF(wall.end.x * self.scale, wall.end.y * self.scale), SnapMode.ENDPOINT),
            ]
            # Milieu
            if SnapMode.MIDPOINT in self.snap_modes:
                mx = (wall.start.x + wall.end.x) / 2 * self.scale
                my = (wall.start.y + wall.end.y) / 2 * self.scale
                pts.append((QPointF(mx, my), SnapMode.MIDPOINT))
            points.extend(pts)
        
        elif isinstance(item, (AssetItem, WorkstationItem)):
            rect = item.rect()
            pos = item.pos()
            # Coins
            corners = [
                pos + rect.topLeft(), pos + rect.topRight(),
                pos + rect.bottomLeft(), pos + rect.bottomRight(),
            ]
            for c in corners:
                points.append((c, SnapMode.ENDPOINT))
            # Milieux
            if SnapMode.MIDPOINT in self.snap_modes:
                midpoints = [
                    pos + QPointF(rect.center().x(), rect.top()),
                    pos + QPointF(rect.center().x(), rect.bottom()),
                    pos + QPointF(rect.left(), rect.center().y()),
                    pos + QPointF(rect.right(), rect.center().y()),
                ]
                for m in midpoints:
                    points.append((m, SnapMode.MIDPOINT))
        
        elif isinstance(item, ZoneItem):
            poly = item.polygon()
            for i in range(poly.size()):
                pt = poly.at(i)
                points.append((pt, SnapMode.ENDPOINT))
                if SnapMode.MIDPOINT in self.snap_modes and i < poly.size() - 1:
                    next_pt = poly.at(i + 1)
                    mid = QPointF((pt.x() + next_pt.x()) / 2, (pt.y() + next_pt.y()) / 2)
                    points.append((mid, SnapMode.MIDPOINT))
        
        return points
    
    def show_snap_markers(self, pos: QPointF):
        """Affiche les marqueurs de snap possibles (points + intersections)."""
        # Nettoyer anciens
        for item in self._temp_items:
            self.scene().removeItem(item)
        self._temp_items.clear()
        
        if not self.snap_enabled:
            return
        
        # Marqueurs de snap (endpoints / midpoints)
        for item in self.scene().items():
            if isinstance(item, (WallItem, AssetItem, WorkstationItem, ZoneItem)):
                for snap_pos, snap_type in self._get_snap_points(item):
                    dist = (snap_pos - pos).manhattanLength()
                    if dist < 15:
                        marker = SnapMarkerItem(snap_pos, snap_type)
                        self.scene().addItem(marker)
                        self._temp_items.append(marker)
        
        # Marqueurs d'intersection
        if SnapMode.INTERSECTION in self.snap_modes:
            for inter in self._get_intersection_points():
                if (inter - pos).manhattanLength() < 15:
                    marker = SnapMarkerItem(inter, SnapMode.INTERSECTION)
                    self.scene().addItem(marker)
                    self._temp_items.append(marker)
    
    def clear_snap_markers(self):
        for item in self._temp_items:
            self.scene().removeItem(item)
        self._temp_items.clear()
    
    # ============================================================
    # ÉVÉNEMENTS SOURIS
    # ============================================================
    
    def mousePressEvent(self, event: QMouseEvent):
        pos = self.mapToScene(event.pos())
        snapped = self.snap_point(pos)
        
        if event.button() == Qt.MouseButton.LeftButton:
            # Désactiver le rubber band pour les outils de dessin
            drawing_tools = {
                LayoutTool.WALL, LayoutTool.DOOR, LayoutTool.ZONE,
                LayoutTool.RECT_ZONE, LayoutTool.ASSET, LayoutTool.WORKSTATION,
                LayoutTool.TRANSPORT, LayoutTool.MEASURE
            }
            if self.current_tool in drawing_tools:
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
            
            if self.current_tool == LayoutTool.SELECT:
                item = self.itemAt(event.pos())
                log_debug(
                    f"SELECT click viewport({event.pos().x()},{event.pos().y()}) "
                    f"→ item={type(item).__name__ if item else 'None'}"
                )
                # Si l'item cliqué n'est pas sélectionnable, remonter la chaîne parent
                if item and not (item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable):
                    parent = item.parentItem()
                    while parent:
                        if parent.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                            item = parent
                            break
                        parent = parent.parentItem()
                if item and (item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable):
                    if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                        self.scene().clearSelection()
                    item.setSelected(True)
                    log_debug(
                        f"  → manual setSelected({type(item).__name__}) "
                        f"id={getattr(item, 'id', getattr(getattr(item, 'wall', None), 'id', None))}"
                    )
                else:
                    log_debug("  → empty space, RubberBandDrag")
                    self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                    super().mousePressEvent(event)
            elif self.current_tool == LayoutTool.PAN:
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                super().mousePressEvent(event)
            elif self.current_tool == LayoutTool.WALL:
                self._start_wall(snapped)
            elif self.current_tool == LayoutTool.DOOR:
                self._place_door(snapped)
            elif self.current_tool == LayoutTool.ZONE:
                self._add_zone_point(snapped)
            elif self.current_tool == LayoutTool.RECT_ZONE:
                self._draw_start = snapped
                self._drawing = True
            elif self.current_tool == LayoutTool.ASSET:
                self._place_asset(snapped)
            elif self.current_tool == LayoutTool.WORKSTATION:
                self._place_workstation(snapped)
            elif self.current_tool == LayoutTool.TRANSPORT:
                self._start_transport(snapped)
            elif self.current_tool == LayoutTool.MEASURE:
                self._start_measure(snapped)
            elif self.current_tool == LayoutTool.DIMENSION:
                self._handle_dimension_click(snapped)
        
        elif event.button() == Qt.MouseButton.RightButton:
            if self.current_tool == LayoutTool.ZONE:
                self._finish_zone()
            elif self.current_tool == LayoutTool.WALL:
                self._cancel_wall()
            elif self.current_tool == LayoutTool.TRANSPORT:
                self._cancel_transport()
            elif self.current_tool == LayoutTool.MEASURE:
                self._cancel_measure()
            elif self.current_tool == LayoutTool.DIMENSION:
                self._cancel_dimension()
            else:
                super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        pos = self.mapToScene(event.pos())
        snapped = self.snap_point(pos)
        
        # Marqueurs de snap
        self.show_snap_markers(snapped)
        
        if self.current_tool == LayoutTool.WALL and self._wall_start:
            self._update_wall_preview(snapped)
        elif self.current_tool == LayoutTool.RECT_ZONE and self._drawing:
            self._update_rect_zone_preview(snapped)
        elif self.current_tool == LayoutTool.TRANSPORT and self._current_item:
            self._update_transport_preview(snapped)
        elif self.current_tool == LayoutTool.MEASURE and self._current_item:
            self._update_measure_preview(snapped)
        elif self.current_tool == LayoutTool.DIMENSION and self._current_item:
            self._update_dimension_preview(snapped)
        elif self.current_tool == LayoutTool.ASSET and self._pending_asset:
            self._update_asset_preview(snapped)
        elif self.current_tool == LayoutTool.DOOR:
            self._update_door_preview(snapped)
        
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        pos = self.mapToScene(event.pos())
        snapped = self.snap_point(pos)
        
        if event.button() == Qt.MouseButton.LeftButton:
            if self.current_tool == LayoutTool.RECT_ZONE and self._drawing:
                self._finish_rect_zone(snapped)
            elif self.current_tool == LayoutTool.PAN:
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            elif self.current_tool in {LayoutTool.WALL, LayoutTool.ZONE, LayoutTool.RECT_ZONE, LayoutTool.ASSET, LayoutTool.WORKSTATION, LayoutTool.TRANSPORT, LayoutTool.MEASURE, LayoutTool.DIMENSION}:
                # Restaurer le mode par défaut après dessin
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        
        super().mouseReleaseEvent(event)
        self.clear_snap_markers()
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if self.current_tool == LayoutTool.ZONE:
            self._finish_zone()
        elif self.current_tool == LayoutTool.TRANSPORT:
            self._finish_transport()
        else:
            super().mouseDoubleClickEvent(event)
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_current_action()
        elif event.key() == Qt.Key.Key_Space:
            self.set_tool(LayoutTool.PAN)
        elif event.key() == Qt.Key.Key_V:
            self.set_tool(LayoutTool.SELECT)
        elif event.key() == Qt.Key.Key_W:
            self.set_tool(LayoutTool.WALL)
        elif event.key() == Qt.Key.Key_D:
            self.set_tool(LayoutTool.DOOR)
        elif event.key() == Qt.Key.Key_Z:
            self.set_tool(LayoutTool.ZONE)
        elif event.key() == Qt.Key.Key_R:
            self.set_tool(LayoutTool.RECT_ZONE)
        elif event.key() == Qt.Key.Key_G:
            self.snap_enabled = not self.snap_enabled
            self.status_message.emit(f"Snap: {'ON' if self.snap_enabled else 'OFF'}")
        elif event.key() == Qt.Key.Key_F and self.current_tool == LayoutTool.DOOR:
            self._door_flip_side = not self._door_flip_side
            side = "gauche" if self._door_flip_side else "droite"
            self.status_message.emit(f"Côté d'ouverture: {side}")
        elif event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
        else:
            super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space:
            self.set_tool(LayoutTool.SELECT)
        super().keyReleaseEvent(event)
    
    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
            self.scale(factor, factor)
            self.scale *= factor
        else:
            super().wheelEvent(event)
    
    # ============================================================
    # ACTIONS OUTILS
    # ============================================================
    
    def _start_wall(self, pos: QPointF):
        if self._wall_start is None:
            self._wall_start = pos
            self._wall_target_length = None
            self._wall_length_overlay.clear()
            self._wall_length_overlay.show()
            self._wall_length_overlay.setFocus()
            self._wall_length_overlay.move(10, 10)
            self._wall_length_overlay.raise_()
            # Créer item temporaire
            self._current_item = QGraphicsLineItem()
            self._current_item.setPen(QPen(QColor("#ff6d5a"), 2, Qt.PenStyle.DashLine))
            self.scene().addItem(self._current_item)
            self.status_message.emit("Mur: cliquez pour définir la fin (ou entrez une longueur)")
        else:
            # Finir le mur
            start_vec = Vector2D(self._wall_start.x() / self.scale, self._wall_start.y() / self.scale)
            end_vec = Vector2D(pos.x() / self.scale, pos.y() / self.scale)
            
            if self._wall_target_length is not None and self._wall_target_length > 0.001:
                d = (end_vec - start_vec)
                current_len = d.length()
                if current_len > 1e-9:
                    d = d.normalized()
                else:
                    d = Vector2D(1.0, 0.0)
                end_vec = start_vec + d * self._wall_target_length
            
            wall = WallSegment(
                id=f"wall_{len(self.building.walls)}",
                start=start_vec,
                end=end_vec,
                wall_type=WallType.INTERIOR,
            )
            self.building.walls.append(wall)
            item = WallItem(wall, self.scale, self)
            self.scene().addItem(item)
            self._wall_start = None
            self._wall_target_length = None
            self._wall_length_overlay.hide()
            self._cleanup_temp()
            self._notify_changed()
            self._validate_and_report_geometry()
    
    def _on_wall_length_confirmed(self):
        text = self._wall_length_overlay.text().strip()
        if text:
            try:
                length = float(text)
                if length > 0:
                    self._wall_target_length = length
                    self.status_message.emit(f"Longueur cible: {length:.2f} m")
                else:
                    self._wall_target_length = None
                    self.status_message.emit("Longueur annulée (valeur <= 0)")
            except ValueError:
                self._wall_target_length = None
                self.status_message.emit("Longueur invalide")
        else:
            self._wall_target_length = None
        self._wall_length_overlay.clear()
    
    def _update_wall_preview(self, pos: QPointF):
        if self._current_item and self._wall_start:
            if self._wall_target_length is not None and self._wall_target_length > 0.001:
                start_vec = Vector2D(self._wall_start.x() / self.scale, self._wall_start.y() / self.scale)
                cursor_vec = Vector2D(pos.x() / self.scale, pos.y() / self.scale)
                d = cursor_vec - start_vec
                current_len = d.length()
                if current_len > 1e-9:
                    d = d.normalized() * self._wall_target_length
                else:
                    d = Vector2D(self._wall_target_length, 0.0)
                constrained = start_vec + d
                line = QLineF(self._wall_start, constrained.to_qpointf())
                self._current_item.setLine(line)
            else:
                line = QLineF(self._wall_start, pos)
                self._current_item.setLine(line)
    
    def _cancel_wall(self):
        self._wall_start = None
        self._wall_target_length = None
        self._wall_length_overlay.hide()
        self._wall_length_overlay.clear()
        self._cleanup_temp()
    
    def _validate_and_report_geometry(self):
        errors = self.building.validate_geometry()
        if errors:
            msg = "\n".join(errors[:5])
            if len(errors) > 5:
                msg += f"\n... et {len(errors) - 5} autre(s)"
            self.status_message.emit(f"Géométrie: {len(errors)} alerte(s)")
            QMessageBox.warning(self, "Cohérence géométrique", msg)
        else:
            self.status_message.emit("Géométrie: cohérente")
    
    def _update_door_preview(self, pos: QPointF):
        self._clear_door_preview()
        
        nearest_wall = None
        min_dist = float('inf')
        best_t = 0.5
        
        for wall in self.building.walls:
            dist, t = self._point_line_distance(
                Vector2D(pos.x() / self.scale, pos.y() / self.scale),
                wall.start, wall.end
            )
            if dist < min_dist and dist < 0.3:
                min_dist = dist
                nearest_wall = wall
                best_t = t
        
        if not nearest_wall:
            return
        
        door_type = self._pending_door.door_type if self._pending_door else "swing"
        swing_side = "left" if self._door_flip_side else "right"
        
        preview_door = Door(
            id="preview",
            wall_id=nearest_wall.id,
            position_ratio=best_t,
            door_type=door_type,
            swing_side=swing_side,
        )
        
        self._door_preview_item = DoorItem(preview_door, nearest_wall, self.scale, self)
        self._door_preview_item.setOpacity(0.6)
        self.scene().addItem(self._door_preview_item)
    
    def _place_door(self, pos: QPointF):
        nearest_wall = None
        min_dist = float('inf')
        best_t = 0.5
        
        for wall in self.building.walls:
            dist, t = self._point_line_distance(
                Vector2D(pos.x() / self.scale, pos.y() / self.scale),
                wall.start, wall.end
            )
            if dist < min_dist and dist < 0.3:
                min_dist = dist
                nearest_wall = wall
                best_t = t
        
        if not nearest_wall:
            self.status_message.emit("Aucun mur proche pour placer la porte")
            return
        
        door_type = self._pending_door.door_type if self._pending_door else "swing"
        swing_side = "left" if self._door_flip_side else "right"
        
        t_clamped = max(0.15, min(0.85, best_t))
        
        # Empêcher les doublons : vérifier AVANT d'ajouter la nouvelle porte
        for existing_door in self.building.doors:
            if (existing_door.wall_id == nearest_wall.id
                    and abs(existing_door.position_ratio - t_clamped) < 0.05):
                self.status_message.emit("Porte déjà présente à cet emplacement")
                self._clear_door_preview()
                return

        door = Door(
            id=f"door_{len(self.building.doors)}",
            wall_id=nearest_wall.id,
            position_ratio=t_clamped,
            door_type=door_type,
            swing_side=swing_side,
        )
        self.building.doors.append(door)

        self._create_door_opening(nearest_wall, door)

        # Mettre à jour le visuel du mur (gap de porte)
        for scene_item in self.scene().items():
            if isinstance(scene_item, WallItem) and scene_item.wall.id == nearest_wall.id:
                scene_item._update_path()
                break

        item = DoorItem(door, nearest_wall, self.scale, self)
        self.scene().addItem(item)
        self._notify_changed()
        self.status_message.emit(f"Porte {door_type} ajoutée sur {nearest_wall.id} (côté {swing_side})")

        self._clear_door_preview()

        # Rebasculer en SELECT pour permettre la sélection immédiate
        self.set_tool(LayoutTool.SELECT)
    
    def _create_door_opening(self, wall: WallSegment, door: Door):
        """Marque le mur comme ayant une porte."""
        wall.has_door = True
        wall.door_id = door.id
        wall.door_position = door.position_ratio
        wall.door_width = door.width_m
    
    def _add_zone_point(self, pos: QPointF):
        self._zone_points.append(Vector2D(pos.x() / self.scale, pos.y() / self.scale))
        
        # Mettre à jour preview
        if self._current_item:
            self.scene().removeItem(self._current_item)
        
        if len(self._zone_points) >= 2:
            poly = QPolygonF()
            for p in self._zone_points:
                poly.append(QPointF(p.x * self.scale, p.y * self.scale))
            # Fermer pour preview
            poly.append(QPointF(pos.x(), pos.y()))
            
            self._current_item = QGraphicsPolygonItem(poly)
            self._current_item.setPen(QPen(QColor("#8da2fb"), 2, Qt.PenStyle.DashLine))
            self._current_item.setBrush(QBrush(QColor("#8da2fb40")))
            self.scene().addItem(self._current_item)
        
        if len(self._zone_points) == 1:
            # Premier point - marquer
            marker = QGraphicsEllipseItem(-5, -5, 10, 10)
            marker.setPos(pos)
            marker.setPen(QPen(QColor("#ff6d5a"), 2))
            marker.setBrush(QBrush(QColor("#ff6d5a")))
            self.scene().addItem(marker)
            self._temp_items.append(marker)
    
    def _finish_zone(self):
        if len(self._zone_points) >= 3:
            # Demander nom et type de zone
            name, zone_type = self._ask_zone_properties()
            if name is None:
                self._zone_points.clear()
                self._cleanup_temp()
                return
            
            zone = Zone(
                id=f"zone_{len(self.building.zones)}",
                name=name,
                zone_type=zone_type,
                vertices=self._zone_points.copy(),
            )
            self.building.zones.append(zone)
            item = ZoneItem(zone, self.scale, self)
            self.scene().addItem(item)
            self._notify_changed()
            self.status_message.emit(f"Zone créée: {zone.name}")
        else:
            self.status_message.emit("Zone annulée: minimum 3 points requis")
        self._zone_points.clear()
        self._cleanup_temp()
    
    def _ask_zone_properties(self) -> tuple:
        """Demande le nom et le type de zone via un dialogue."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Nouvelle zone")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        
        form = QFormLayout()
        
        name_edit = QLineEdit(f"Zone {len(self.building.zones) + 1}")
        form.addRow("Nom:", name_edit)
        
        type_combo = QComboBox()
        for zt in ZoneType:
            type_combo.addItem(zt.value, zt)
        type_combo.setCurrentText(ZoneType.WORK_AREA.value)
        form.addRow("Type:", type_combo)
        
        layout.addLayout(form)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return name_edit.text(), type_combo.currentData()
        return None, None
    
    def _start_rect_zone(self, pos: QPointF):
        self._draw_start = pos
        self._drawing = True
    
    def _update_rect_zone_preview(self, pos: QPointF):
        if self._current_item:
            self.scene().removeItem(self._current_item)
        
        rect = QRectF(self._draw_start, pos).normalized()
        self._current_item = QGraphicsRectItem(rect)
        self._current_item.setPen(QPen(QColor("#8da2fb"), 2, Qt.PenStyle.DashLine))
        self._current_item.setBrush(QBrush(QColor("#8da2fb40")))
        self.scene().addItem(self._current_item)
    
    def _finish_rect_zone(self, pos: QPointF):
        rect = QRectF(self._draw_start, pos).normalized()
        if rect.width() > 10 and rect.height() > 10:
            # Demander nom et type de zone
            name, zone_type = self._ask_zone_properties()
            if name is None:
                self._drawing = False
                self._cleanup_temp()
                return
            
            # Créer zone rectangulaire
            vertices = [
                Vector2D(rect.left() / self.scale, rect.top() / self.scale),
                Vector2D(rect.right() / self.scale, rect.top() / self.scale),
                Vector2D(rect.right() / self.scale, rect.bottom() / self.scale),
                Vector2D(rect.left() / self.scale, rect.bottom() / self.scale),
            ]
            zone = Zone(
                id=f"zone_{len(self.building.zones)}",
                name=name,
                zone_type=zone_type,
                vertices=vertices,
            )
            self.building.zones.append(zone)
            item = ZoneItem(zone, self.scale, self)
            self.scene().addItem(item)
            self._notify_changed()
            self.status_message.emit(f"Zone rectangulaire créée: {zone.name}")
        self._drawing = False
        self._cleanup_temp()
    
    def _place_asset(self, pos: QPointF):
        if self._pending_asset:
            asset = PhysicalAsset(
                id=f"asset_{len(self.building.assets)}",
                name=self._pending_asset.name,
                category=self._pending_asset.category,
                asset_type=self._pending_asset.asset_type,
                width_m=self._pending_asset.width_m,
                depth_m=self._pending_asset.depth_m,
                height_m=self._pending_asset.height_m,
                position=Vector2D(pos.x() / self.scale, pos.y() / self.scale),
                machine_type=self._pending_asset.machine_type,
                color_3d=self._pending_asset.color_3d,
            )
            self.building.assets.append(asset)
            item = AssetItem(asset, self.scale, self)
            self.scene().addItem(item)
            self._notify_changed()
            self.status_message.emit(f"Asset placé: {asset.name}")
            self._pending_asset = None
            self.set_tool(LayoutTool.SELECT)
            # Nettoyer l'aperçu
            if hasattr(self, '_asset_preview_item') and self._asset_preview_item:
                self.scene().removeItem(self._asset_preview_item)
                self._asset_preview_item = None

    def _update_asset_preview(self, pos: QPointF):
        """Affiche un aperçu fantôme de l'asset pendant le déplacement."""
        if hasattr(self, '_asset_preview_item') and self._asset_preview_item:
            self.scene().removeItem(self._asset_preview_item)
        
        asset = self._pending_asset
        w = asset.width_m * self.scale
        h = asset.depth_m * self.scale
        
        # Rectangle fantôme centré sur la souris
        self._asset_preview_item = QGraphicsRectItem(-w/2, -h/2, w, h)
        self._asset_preview_item.setPos(pos.x(), pos.y())
        self._asset_preview_item.setPen(QPen(QColor("#8da2fb"), 2, Qt.PenStyle.DashLine))
        self._asset_preview_item.setBrush(QBrush(QColor("#8da2fb40")))
        self._asset_preview_item.setZValue(100)
        self.scene().addItem(self._asset_preview_item)

    def _place_workstation(self, pos: QPointF):
        ws = WorkstationLayout(
            id=f"ws_{len(self.building.workstations)}",
            name=f"Poste {len(self.building.workstations) + 1}",
            position=Vector2D(pos.x() / self.scale, pos.y() / self.scale),
        )
        self.building.workstations.append(ws)
        item = WorkstationItem(ws, self.scale, self)
        self.scene().addItem(item)
        self._notify_changed()
        self.status_message.emit(f"Poste créé: {ws.name}")
    
    def _start_transport(self, pos: QPointF):
        self._transport_points = [Vector2D(pos.x() / self.scale, pos.y() / self.scale)]
        self._current_item = QGraphicsPathItem()
        path = QPainterPath()
        path.moveTo(pos)
        self._current_item.setPath(path)
        self._current_item.setPen(QPen(QColor("#8da2fb"), 2, Qt.PenStyle.DashLine))
        self.scene().addItem(self._current_item)
    
    def _update_transport_preview(self, pos: QPointF):
        if self._current_item and self._transport_points:
            path = QPainterPath()
            path.moveTo(self._transport_points[0].x * self.scale, self._transport_points[0].y * self.scale)
            for p in self._transport_points[1:]:
                path.lineTo(p.x * self.scale, p.y * self.scale)
            path.lineTo(pos.x(), pos.y())
            self._current_item.setPath(path)
    
    def _finish_transport(self):
        if len(self._transport_points) >= 2:
            link = TransportLink(
                id=f"transport_{len(self.building.transport_links)}",
                source_id="",  # À déterminer par proximité
                target_id="",
                transport_mode=TransportMode.MANUAL,
                path_points=self._transport_points.copy(),
            )
            link.calculate_distance()
            self.building.transport_links.append(link)
            item = TransportLinkItem(link, self.scale, self)
            self.scene().addItem(item)
            self._notify_changed()
            self.status_message.emit(f"Lien de transport créé")
        self._transport_points.clear()
        self._cleanup_temp()
    
    def _cancel_transport(self):
        self._transport_points.clear()
        self._cleanup_temp()
    
    def _start_measure(self, pos: QPointF):
        # Mesure en 2 clics : 1er point, puis 2e point
        if not hasattr(self, '_measure_start') or self._measure_start is None:
            self._measure_start = pos
            self._current_item = QGraphicsLineItem()
            pen = QPen(QColor("#f79009"), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._current_item.setPen(pen)
            self.scene().addItem(self._current_item)
            self.status_message.emit("Mesure: cliquez le 2ème point")
        else:
            p1 = self._measure_start
            p2 = pos
            item = MeasureItem(p1, p2, self.scale, self)
            self.scene().addItem(item)
            self.status_message.emit(f"Distance: {item.distance_m:.2f} m")
            self._measure_start = None
            self._cleanup_temp()
            self.set_tool(LayoutTool.SELECT)

    def _update_measure_preview(self, pos: QPointF):
        if self._current_item and hasattr(self, '_measure_start') and self._measure_start is not None:
            line = QLineF(self._measure_start, pos)
            self._current_item.setLine(line)
            dist_m = line.length() / self.scale
            self.status_message.emit(f"Distance: {dist_m:.2f} m")

    def _cancel_measure(self):
        if hasattr(self, '_measure_start'):
            delattr(self, '_measure_start')
        self._cleanup_temp()

    # ---- Cotation (dimension) pro : 3 clics ----
    # État 0 : choisir le 1er point
    # État 1 : choisir le 2e point (mesuré)
    # État 2 : choisir la position de la ligne de cote (offset)

    def _handle_dimension_click(self, pos: QPointF):
        if not hasattr(self, '_dimension_state') or self._dimension_state is None:
            self._dimension_state = 0

        if self._dimension_state == 0:
            self._dimension_start = pos
            self._dimension_state = 1
            self._current_item = QGraphicsLineItem()
            self._current_item.setPen(QPen(QColor(LAYER_COLORS["annotation"]), 1, Qt.PenStyle.DashLine))
            self.scene().addItem(self._current_item)
            self.status_message.emit("Cote: cliquez le 2ème point")
        elif self._dimension_state == 1:
            self._dimension_end = pos
            self._dimension_state = 2
            self.status_message.emit("Cote: cliquez pour placer la ligne de cote")
        elif self._dimension_state == 2:
            self._finish_dimension(pos)

    def _update_dimension_preview(self, pos: QPointF):
        if not hasattr(self, '_dimension_state'):
            return
        if self._dimension_state == 1:
            line = QLineF(self._dimension_start, pos)
            self._current_item.setLine(line)
        elif self._dimension_state == 2:
            # Aperçu complet de la cote à l'offset courant
            if self._current_item:
                self.scene().removeItem(self._current_item)
                self._current_item = None
            self._current_item = DimensionItem(
                self._dimension_start, self._dimension_end, pos, self.scale, self
            )
            self.scene().addItem(self._current_item)

    def _finish_dimension(self, pos: QPointF):
        if not (hasattr(self, '_dimension_start') and hasattr(self, '_dimension_end')):
            self._reset_dimension_state()
            return

        p1 = self._dimension_start
        p2 = self._dimension_end

        # Conserver dans le modèle (offset en pixels stocké dans metadata)
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        norm_x = -dy / length if length > 0 else 0
        norm_y = dx / length if length > 0 else 0
        offset_px = (pos.x() - p1.x()) * norm_x + (pos.y() - p1.y()) * norm_y

        dim = DimensionLayout(
            id=f"dim_{len(self.building.dimensions)}",
            start=Vector2D(p1.x() / self.scale, p1.y() / self.scale),
            end=Vector2D(p2.x() / self.scale, p2.y() / self.scale),
            text_pos=Vector2D(pos.x() / self.scale, pos.y() / self.scale),
            distance_m=length / self.scale,
            metadata={"offset_px": offset_px},
        )
        self.building.dimensions.append(dim)

        item = DimensionItem(p1, p2, pos, self.scale, self)
        self.scene().addItem(item)

        self._reset_dimension_state()
        self._cleanup_temp()
        self.set_tool(LayoutTool.SELECT)
        self._notify_changed()
        self.status_message.emit(f"Cote créée: {dim.distance_m:.2f} m")

    def _reset_dimension_state(self):
        for attr in ('_dimension_start', '_dimension_end', '_dimension_state'):
            if hasattr(self, attr):
                delattr(self, attr)

    def _cancel_dimension(self):
        self._reset_dimension_state()
        self._cleanup_temp()
        self.set_tool(LayoutTool.SELECT)
        self.status_message.emit("Cote annulée")

    def _cleanup_temp(self):
        if self._current_item:
            self.scene().removeItem(self._current_item)
            self._current_item = None
        for item in self._temp_items:
            self.scene().removeItem(item)
        self._temp_items.clear()
        # Nettoyer l'aperçu d'asset
        if hasattr(self, '_asset_preview_item') and self._asset_preview_item:
            self.scene().removeItem(self._asset_preview_item)
            self._asset_preview_item = None
    
    def _cancel_current_action(self):
        self._cancel_wall()
        self._zone_points.clear()
        self._cleanup_temp()
        self.set_tool(LayoutTool.SELECT)
    
    def _delete_selected(self):
        for item in self.scene().selectedItems():
            if isinstance(item, WallItem):
                self.building.walls = [w for w in self.building.walls if w.id != item.wall.id]
            elif isinstance(item, ZoneItem):
                self.building.zones = [z for z in self.building.zones if z.id != item.zone.id]
            elif isinstance(item, AssetItem):
                self.building.assets = [a for a in self.building.assets if a.id != item.asset.id]
            elif isinstance(item, WorkstationItem):
                self.building.workstations = [w for w in self.building.workstations if w.id != item.workstation.id]
            elif isinstance(item, TransportLinkItem):
                self.building.transport_links = [t for t in self.building.transport_links if t.id != item.link.id]
            elif isinstance(item, DoorItem):
                self.building.doors = [d for d in self.building.doors if d.id != item.door.id]
                # Restaurer le gabarit du mur (fermer la gap de porte)
                for wall in self.building.walls:
                    if wall.id == item.wall.id:
                        wall.has_door = False
                        wall.door_id = None
                        # Mettre à jour le visuel du mur
                        for si in self.scene().items():
                            if isinstance(si, WallItem) and si.wall.id == wall.id:
                                si._update_path()
                                break
                        break
            self.scene().removeItem(item)
        self._notify_changed()
    
    def show_item_context_menu(self, item, screen_pos: QPoint):
        """Affiche le menu contextuel pour un item."""
        menu = QMenu()
        
        # Action Renommer
        rename_action = menu.addAction("✏️ Renommer")
        rename_action.triggered.connect(lambda: self.rename_item(item))
        
        menu.addSeparator()
        
        # Action Supprimer
        delete_action = menu.addAction("🗑️ Supprimer")
        delete_action.triggered.connect(lambda: self.delete_item(item))
        
        # Propriétés spécifiques selon le type
        if isinstance(item, ZoneItem):
            menu.addSeparator()
            type_action = menu.addAction("🔧 Changer type")
            type_action.triggered.connect(lambda: self.change_zone_type(item))
        
        elif isinstance(item, WallItem):
            menu.addSeparator()
            type_action = menu.addAction("🔧 Changer type mur")
            type_action.triggered.connect(lambda: self.change_wall_type(item))
        
        elif isinstance(item, DoorItem):
            menu.addSeparator()
            props_action = menu.addAction("📐 Propriétés...")
            props_action.triggered.connect(lambda: self._show_door_properties(item))
        
        elif isinstance(item, WallItem):
            menu.addSeparator()
            type_action = menu.addAction("🔧 Changer type mur")
            type_action.triggered.connect(lambda: self.change_wall_type(item))
            props_action = menu.addAction("📐 Propriétés...")
            props_action.triggered.connect(lambda: self._show_wall_properties_dialog(item))
        
        elif isinstance(item, AssetItem):
            menu.addSeparator()
            rotate_action = menu.addAction("🔄 Rotation +90°")
            rotate_action.triggered.connect(lambda: self.rotate_asset(item, 90))
            
            rotate_neg_action = menu.addAction("🔄 Rotation -90°")
            rotate_neg_action.triggered.connect(lambda: self.rotate_asset(item, -90))
        
        menu.exec(screen_pos)
    
    def rename_item(self, item):
        """Renomme un item via une boîte de dialogue."""
        if isinstance(item, ZoneItem):
            self._rename_zone(item)
        elif isinstance(item, AssetItem):
            self._rename_asset(item)
        elif isinstance(item, WorkstationItem):
            self._rename_workstation(item)
        elif isinstance(item, WallItem):
            self._rename_wall(item)
        elif isinstance(item, TransportLinkItem):
            self._rename_transport(item)
    
    def delete_item(self, item):
        """Supprime un item spécifique."""
        if isinstance(item, WallItem):
            self.building.walls = [w for w in self.building.walls if w.id != item.wall.id]
        elif isinstance(item, ZoneItem):
            self.building.zones = [z for z in self.building.zones if z.id != item.zone.id]
        elif isinstance(item, AssetItem):
            self.building.assets = [a for a in self.building.assets if a.id != item.asset.id]
        elif isinstance(item, WorkstationItem):
            self.building.workstations = [w for w in self.building.workstations if w.id != item.workstation.id]
        elif isinstance(item, TransportLinkItem):
            self.building.transport_links = [t for t in self.building.transport_links if t.id != item.link.id]
        elif isinstance(item, DoorItem):
            self.building.doors = [d for d in self.building.doors if d.id != item.door.id]
        self.scene().removeItem(item)
        self._notify_changed()

    # ------------------------------------------------------------------
    # Door properties dialog & helpers
    # ------------------------------------------------------------------

    def _show_door_properties(self, item: DoorItem):
        """Ouvre la boîte de dialogue des propriétés de la porte."""
        dlg = DoorPropertiesDialog(item.door, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.update_door_item(item)

    def update_door_item(self, item: DoorItem):
        """Met à jour le visuel d'une porte et de son mur après modification."""
        wall = next(
            (w for w in self.building.walls if w.id == item.wall.id), None
        )
        if wall:
            wall.has_door = True
            wall.door_id = item.door.id
            wall.door_position = item.door.position_ratio
            wall.door_width = item.door.width_m
            # Mettre à jour le tracé du mur (gap)
            for si in self.scene().items():
                if isinstance(si, WallItem) and si.wall.id == wall.id:
                    si._update_path()
                    break
        item.on_door_changed()
        self._notify_changed()

    def _show_wall_properties_dialog(self, item: WallItem):
        w = item.wall
        # Raccourci vers les propriétés via QInputDialog pour l'instant
        from PySide6.QtWidgets import QInputDialog
        length, ok = QInputDialog.getDouble(
            self, f"Mur {w.id}", "Longueur (m):",
            w.length(), 0.1, 100.0, 2
        )
        if ok:
            w.set_length(length)
            item._update_path()
            self._notify_changed()

    def _rename_zone(self, item: ZoneItem):
        name, ok = QInputDialog.getText(self, "Renommer zone", "Nom:", text=item.zone.name)
        if ok and name:
            item.zone.name = name
            item._update_name_text()
            self._notify_changed()
            self.status_message.emit(f"Zone renommée: {name}")
    
    def _rename_asset(self, item: AssetItem):
        name, ok = QInputDialog.getText(self, "Renommer machine", "Nom:", text=item.asset.name)
        if ok and name:
            item.asset.name = name
            self._notify_changed()
            self.status_message.emit(f"Machine renommée: {name}")
    
    def _rename_workstation(self, item: WorkstationItem):
        name, ok = QInputDialog.getText(self, "Renommer poste", "Nom:", text=item.workstation.name)
        if ok and name:
            item.workstation.name = name
            self._notify_changed()
            self.status_message.emit(f"Poste renommé: {name}")
    
    def _rename_wall(self, item: WallItem):
        name, ok = QInputDialog.getText(self, "Renommer mur", "Nom:", text=getattr(item.wall, 'name', ''))
        if ok and name:
            item.wall.name = name
            self._notify_changed()
            self.status_message.emit(f"Mur renommé: {name}")
    
    def _rename_transport(self, item: TransportLinkItem):
        name, ok = QInputDialog.getText(self, "Renommer lien", "Nom:", text=getattr(item.link, 'name', ''))
        if ok and name:
            item.link.name = name
            self._notify_changed()
            self.status_message.emit(f"Lien renommé: {name}")
    
    def change_zone_type(self, item: ZoneItem):
        """Change le type de zone."""
        from PySide6.QtWidgets import QComboBox
        
        combo = QComboBox()
        for zt in ZoneType:
            combo.addItem(zt.value, zt)
        combo.setCurrentText(item.zone.zone_type.value if hasattr(item.zone.zone_type, 'value') else item.zone.zone_type)
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Type de zone")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Type de zone:"))
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item.zone.zone_type = combo.currentData()
            # Changer la couleur (hex) selon le type
            item.zone.color = ZONE_TYPE_COLOR.get(item.zone.zone_type, "#2c7a7b")
            item._update_polygon()
            self._notify_changed()
            self.status_message.emit(f"Type zone changé: {item.zone.zone_type.value if hasattr(item.zone.zone_type, 'value') else item.zone.zone_type}")
    
    def change_wall_type(self, item: WallItem):
        """Change le type de mur."""
        from PySide6.QtWidgets import QComboBox
        
        combo = QComboBox()
        for wt in WallType:
            combo.addItem(wt.value, wt)
        combo.setCurrentText(item.wall.wall_type.value)
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Type de mur")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Type de mur:"))
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item.wall.wall_type = combo.currentData()
            item._update_path()
            self._notify_changed()
            self.status_message.emit(f"Type mur changé: {item.wall.wall_type.value}")
    
    def rotate_asset(self, item: AssetItem, angle: int):
        """Tourne un asset de l'angle donné."""
        item.asset.rotation_deg = (item.asset.rotation_deg + angle) % 360
        item.setRotation(item.asset.rotation_deg)
        self._notify_changed()
        self.status_message.emit(f"Asset tourné: {item.asset.rotation_deg}°")
    
    def _point_line_distance(self, point: Vector2D, line_start: Vector2D, line_end: Vector2D) -> tuple:
        """Retourne (distance, paramètre t sur le segment 0-1)."""
        dx = line_end.x - line_start.x
        dy = line_end.y - line_start.y
        length_sq = dx*dx + dy*dy
        
        if length_sq == 0:
            return point.distance_to(line_start), 0.0
        
        t = ((point.x - line_start.x) * dx + (point.y - line_start.y) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        
        proj_x = line_start.x + t * dx
        proj_y = line_start.y + t * dy
        dist = math.hypot(point.x - proj_x, point.y - proj_y)
        
        return dist, t


# ============================================================
# BOÎTE DE DIALOGUE PROPRIÉTÉS PORTE
# ============================================================

class DoorPropertiesDialog(QDialog):
    """Boîte de dialogue des propriétés d'une porte.
    Toute modification est appliquée uniquement au clic sur OK."""

    def __init__(self, door: Door, view: LayoutView2D, parent=None):
        super().__init__(parent)
        self.door_ref = door
        self.view = view
        # Travailler sur une copie ; appliquer seulement si OK
        self.door = Door(
            id=door.id,
            wall_id=door.wall_id,
            position_ratio=door.position_ratio,
            width_m=door.width_m,
            height_m=door.height_m,
            door_type=door.door_type,
            swing_side=door.swing_side,
            opening_direction=door.opening_direction,
            swing_angle_deg=door.swing_angle_deg,
            frame_width_m=door.frame_width_m,
            name=door.name,
        )

        self.setWindowTitle(f"Propriétés — {door.id}")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Type
        self._type = QComboBox()
        self._type.addItems(["swing", "sliding", "rollup"])
        self._type.setCurrentText(self.door.door_type)
        form.addRow("Type:", self._type)

        # Position
        self._pos = QDoubleSpinBox()
        self._pos.setRange(0.0, 1.0)
        self._pos.setSingleStep(0.01)
        self._pos.setDecimals(2)
        self._pos.setValue(self.door.position_ratio)
        form.addRow("Position:", self._pos)

        # Largeur
        self._width = QDoubleSpinBox()
        self._width.setRange(0.5, 5.0)
        self._width.setSingleStep(0.1)
        self._width.setDecimals(2)
        self._width.setSuffix(" m")
        self._width.setValue(self.door.width_m)
        form.addRow("Largeur:", self._width)

        # Hauteur
        self._height = QDoubleSpinBox()
        self._height.setRange(1.5, 5.0)
        self._height.setSingleStep(0.1)
        self._height.setDecimals(2)
        self._height.setSuffix(" m")
        self._height.setValue(self.door.height_m)
        form.addRow("Hauteur:", self._height)

        # Swing options
        self._side = QComboBox()
        self._side.addItems(["left", "right"])
        self._side.setCurrentText(self.door.swing_side)

        self._direction = QComboBox()
        self._direction.addItems(["inward", "outward"])
        self._direction.setCurrentText(self.door.opening_direction)

        self._angle = QDoubleSpinBox()
        self._angle.setRange(30.0, 180.0)
        self._angle.setSingleStep(5.0)
        self._angle.setDecimals(0)
        self._angle.setSuffix(" °")
        self._angle.setValue(self.door.swing_angle_deg)

        self._swing_group = QGroupBox("Battant (swing)")
        sg_layout = QVBoxLayout(self._swing_group)
        sg_form = QFormLayout()
        sg_form.addRow("Côté:", self._side)
        sg_form.addRow("Direction:", self._direction)
        sg_form.addRow("Angle:", self._angle)
        sg_layout.addLayout(sg_form)

        form.addRow(self._swing_group)
        layout.addLayout(form)

        # Afficher/masquer options swing selon le type
        self._type.currentTextChanged.connect(self._toggle_swing)
        self._toggle_swing(self._type.currentText())

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_swing(self, door_type: str):
        self._swing_group.setVisible(door_type == "swing")

    def accept(self):
        """Applique les modifications sur l'objet Door original."""
        d = self.door_ref
        d.door_type = self._type.currentText()
        d.position_ratio = self._pos.value()
        d.width_m = self._width.value()
        d.height_m = self._height.value()
        d.swing_side = self._side.currentText()
        d.opening_direction = self._direction.currentText()
        d.swing_angle_deg = self._angle.value()
        super().accept()


# ============================================================
# ITEMS SUPPLÉMENTAIRES
# ============================================================

class DoorItem(QGraphicsItem):
    """Porte sur un mur - représentation CAD 2D."""
    
    def __init__(self, door: Door, wall: WallSegment, scale: float, view=None):
        super().__init__()
        self.door = door
        self.wall = wall
        self.scale = scale
        self.view = view
        self.setZValue(12)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsToShape, False)

        t = door.position_ratio
        cx = (wall.start.x + t * (wall.end.x - wall.start.x)) * scale
        cy = (wall.start.y + t * (wall.end.y - wall.start.y)) * scale

        wall_dx = wall.end.x - wall.start.x
        wall_dy = wall.end.y - wall.start.y
        wall_angle = math.degrees(math.atan2(wall_dy, wall_dx))

        self.setPos(cx, cy)
        self.setRotation(wall_angle)

    # --- computed helpers (live from model) ---

    @property
    def _door_width_px(self):
        return self.door.width_m * self.scale

    @property
    def _wall_thickness_px(self):
        return self.wall.thickness_m * self.scale

    def on_door_changed(self):
        """Appeler après modification du modèle pour rafraîchir l'affichage."""
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self):
        arc_radius = self._door_width_px
        margin = 15
        size = max(self._wall_thickness_px, arc_radius * 2) + margin * 2
        return QRectF(-size/2, -size/2, size, size)

    def shape(self):
        """Forme de sélection précise conforme AutoCAD/LibreCAD.
        Cadre + secteur de débattement (swing) ou rails (sliding).
        Utilise united() pour fusionner les sous-formes proprement."""
        d = self.door
        w = self._door_width_px
        h = self._wall_thickness_px
        half_w = w / 2
        half_h = h / 2

        rect = QPainterPath()
        rect.addRect(QRectF(-half_w, -half_h, w, h))

        if d.door_type == "swing":
            swing_dir = 1 if d.swing_side == "right" else -1
            open_dir = 1 if d.opening_direction == "outward" else -1
            arc_r = w
            sa = 90 if swing_dir * open_dir > 0 else -90
            span = -swing_dir * open_dir * d.swing_angle_deg
            sector = QPainterPath()
            sector.moveTo(0, 0)
            sector.arcTo(-arc_r, -arc_r, arc_r * 2, arc_r * 2, sa * 16, span * 16)
            sector.closeSubpath()
            return rect.united(sector)

        elif d.door_type == "sliding":
            offset = half_w + d.frame_width_m * self.scale
            rr = 8
            for side in [-1, 1]:
                x1 = side * offset
                x2 = side * (offset + w * 0.6)
                rail = QPainterPath()
                rail.addRect(min(x1, x2), -half_h - rr, abs(x2 - x1), rr * 2 + h)
                rect = rect.united(rail)
            return rect

        return rect

    def paint(self, painter, option, widget):
        d = self.door
        w = self._door_width_px
        h = self._wall_thickness_px
        half_w = w / 2
        half_h = h / 2

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Cadre de la porte
        if self.isSelected():
            frame_pen = QPen(QColor("#ff6d5a"), 3)
            painter.setBrush(QBrush(QColor("#ff6d5a50")))
        else:
            frame_pen = QPen(QColor("#ff6d5a"), 2)
            painter.setBrush(QBrush(QColor("#ff6d5a30")))
        painter.setPen(frame_pen)
        painter.drawRect(QRectF(-half_w, -half_h, w, h))

        # Arc de débattement pour swing
        if d.door_type == "swing":
            arc_pen = QPen(QColor("#ff6d5a"), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(arc_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            swing_dir = 1 if d.swing_side == "right" else -1
            open_dir = 1 if d.opening_direction == "outward" else -1

            arc_radius = w
            start_angle = 90 if swing_dir * open_dir > 0 else -90
            arc_path = QPainterPath()
            arc_path.arcTo(-arc_radius, -arc_radius, arc_radius * 2, arc_radius * 2,
                           start_angle * 16, -swing_dir * open_dir * d.swing_angle_deg * 16)
            painter.drawPath(arc_path)

            # Petite flèche sur l'arc
            arrow_angle = math.radians(start_angle - swing_dir * open_dir * d.swing_angle_deg * 0.7)
            arrow_x = arc_radius * math.cos(arrow_angle)
            arrow_y = arc_radius * math.sin(arrow_angle)
            painter.setPen(QPen(QColor("#ff6d5a"), 2))
            painter.drawLine(QLineF(arrow_x * 0.7, arrow_y * 0.7, arrow_x, arrow_y))

        # Rails pour sliding
        elif d.door_type == "sliding":
            track_pen = QPen(QColor("#94a3b8"), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(track_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            offset = half_w + d.frame_width_m * self.scale
            for side in [-1, 1]:
                x1 = side * offset
                x2 = side * (offset + w * 0.6)
                painter.drawLine(QLineF(x1, -half_h, x2, -half_h))
                painter.drawLine(QLineF(x1, half_h, x2, half_h))

        # Lignes pour rollup
        elif d.door_type == "rollup":
            painter.setPen(QPen(QColor("#ff6d5a"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            segments = 6
            frame_w = d.frame_width_m * self.scale
            for i in range(segments + 1):
                y = -half_h + (i / segments) * h
                painter.drawLine(QLineF(-half_w + frame_w, y, half_w - frame_w, y))

        # Nom
        if d.name:
            painter.setPen(QColor("#ffffff"))
            font = QFont("Arial", 8)
            font.setBold(True)
            painter.setFont(font)
            fm = painter.fontMetrics()
            text_rect = fm.boundingRect(d.name)
            painter.drawText(int(-text_rect.width()/2), int(half_h + text_rect.height() + 2), d.name)
    
    def contextMenuEvent(self, event):
        if self.view:
            self.view.show_item_context_menu(self, event.screenPos())
    
    def mouseDoubleClickEvent(self, event):
        if self.view:
            self.view.rename_item(self)
        super().mouseDoubleClickEvent(event)


# ============================================================
# PANNEAU DE PROPRIÉTÉS LAYOUT
# ============================================================

class LayoutPropertiesPanel(QWidget):
    """Panneau d'inspection pour les éléments du layout."""
    
    def __init__(self, view: LayoutView2D):
        super().__init__()
        self.view = view
        self.current_item = None
        self.setup_ui()
        view.selection_changed.connect(self.on_selection_changed)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        self.header = QLabel("Aucun élément sélectionné")
        self.header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 8px;")
        layout.addWidget(self.header)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.content = QWidget()
        self.form = QFormLayout(self.content)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)
        
        layout.addStretch()
    
    def on_selection_changed(self, items: List[QGraphicsItem]):
        if len(items) == 1:
            self.set_item(items[0])
        else:
            self.clear()
            self.header.setText(f"{len(items)} éléments sélectionnés")
    
    def set_item(self, item: QGraphicsItem):
        self.current_item = item
        self.clear()
        
        if isinstance(item, WallItem):
            self._show_wall(item.wall)
        elif isinstance(item, ZoneItem):
            self._show_zone(item.zone)
        elif isinstance(item, AssetItem):
            self._show_asset(item.asset)
        elif isinstance(item, WorkstationItem):
            self._show_workstation(item.workstation)
        elif isinstance(item, TransportLinkItem):
            self._show_transport(item.link)
        elif isinstance(item, DoorItem):
            self._show_door(item.door)
    
    def clear(self):
        while self.form.count():
            child = self.form.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
    
    def _add_field(self, label: str, widget: QWidget):
        self.form.addRow(label, widget)
    
    def _show_wall(self, wall: WallSegment):
        self.header.setText(f"🧱 Mur: {wall.id}")
        
        # Type
        combo = QComboBox()
        combo.addItems([t.value for t in WallType])
        combo.setCurrentText(wall.wall_type.value)
        combo.currentTextChanged.connect(lambda v: self._update_wall(wall, "wall_type", WallType(v)))
        self._add_field("Type:", combo)
        
        # Longueur
        spin_len = QDoubleSpinBox()
        spin_len.setRange(0.05, 100.0)
        spin_len.setSingleStep(0.1)
        spin_len.setSuffix(" m")
        spin_len.setValue(wall.length())
        spin_len.valueChanged.connect(lambda v: self._update_wall_length(wall, v))
        self._add_field("Longueur:", spin_len)
        
        # Angle
        spin_ang = QDoubleSpinBox()
        spin_ang.setRange(-180.0, 180.0)
        spin_ang.setSingleStep(1.0)
        spin_ang.setSuffix(" °")
        spin_ang.setValue(wall.angle_deg())
        spin_ang.valueChanged.connect(lambda v: self._update_wall_angle(wall, v))
        self._add_field("Angle:", spin_ang)
        
        # Épaisseur
        spin = QDoubleSpinBox()
        spin.setRange(0.05, 1.0)
        spin.setSingleStep(0.05)
        spin.setSuffix(" m")
        spin.setValue(wall.thickness_m)
        spin.valueChanged.connect(lambda v: self._update_wall(wall, "thickness_m", v))
        self._add_field("Épaisseur:", spin)
        
        # Hauteur
        spin2 = QDoubleSpinBox()
        spin2.setRange(2.0, 10.0)
        spin2.setSingleStep(0.1)
        spin2.setSuffix(" m")
        spin2.setValue(wall.height_m)
        spin2.valueChanged.connect(lambda v: self._update_wall(wall, "height_m", v))
        self._add_field("Hauteur:", spin2)
    
    def _update_wall(self, wall: WallSegment, key: str, value):
        setattr(wall, key, value)
        self.view._notify_changed()
    
    def _update_wall_length(self, wall: WallSegment, value: float):
        wall.set_length(value)
        QTimer.singleShot(0, lambda: self._safe_rebuild())
        self._validate_and_report_geometry()
    
    def _update_wall_angle(self, wall: WallSegment, value: float):
        center = wall.center()
        d = (wall.end - wall.start).normalized()
        rotated = d.rotated(value - wall.angle_deg())
        half_len = wall.length() / 2
        wall.start = center - rotated * half_len
        wall.end = center + rotated * half_len
        QTimer.singleShot(0, lambda: self._safe_rebuild())
        self._validate_and_report_geometry()
    
    def _safe_rebuild(self):
        try:
            self.rebuild_scene()
            self._notify_changed()
        except Exception:
            pass
    
    def _show_zone(self, zone: Zone):
        self.header.setText(f"📦 Zone: {zone.name}")
        
        edit = QLineEdit(zone.name)
        edit.textChanged.connect(lambda t: self._update_zone(zone, "name", t))
        self._add_field("Nom:", edit)
        
        combo = QComboBox()
        combo.addItems([t.value for t in ZoneType])
        combo.setCurrentText(zone.zone_type.value if hasattr(zone.zone_type, 'value') else zone.zone_type)
        combo.currentTextChanged.connect(lambda v: self._update_zone(zone, "zone_type", ZoneType(v)))
        self._add_field("Type:", combo)
        
        # Couleur
        btn = QPushButton(zone.color)
        btn.setStyleSheet(f"background: {zone.color};")
        btn.clicked.connect(lambda: self._pick_color(zone, btn))
        self._add_field("Couleur:", btn)
        
        # Opacité
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.1)
        spin.setValue(zone.opacity)
        spin.valueChanged.connect(lambda v: self._update_zone(zone, "opacity", v))
        self._add_field("Opacité:", spin)
        
        # Surface
        self._add_field("Surface:", QLabel(f"{zone.area():.1f} m²"))
    
    def _update_zone(self, zone: Zone, key: str, value):
        setattr(zone, key, value)
        # Mise à jour visuelle immédiate du label et du polygone
        for item in self.view.scene().items():
            if isinstance(item, ZoneItem) and item.zone.id == zone.id:
                if key == "name":
                    item._update_name_text()
                else:
                    item._update_polygon()
                break
        self.view._notify_changed()
    
    def _pick_color(self, zone: Zone, btn: QPushButton):
        color = QColorDialog.getColor(QColor(zone.color), self)
        if color.isValid():
            zone.color = color.name()
            btn.setText(color.name())
            btn.setStyleSheet(f"background: {color.name()};")
            self.view._notify_changed()
    
    def _show_asset(self, asset: PhysicalAsset):
        self.header.setText(f"🏭 Asset: {asset.name}")
        
        fields = [
            ("ID", asset.id, False),
            ("Type", asset.asset_type, True),
            ("Catégorie", asset.category.value, True),
            ("Largeur (m)", asset.width_m, True, "double", 0.1, 20.0),
            ("Profondeur (m)", asset.depth_m, True, "double", 0.1, 20.0),
            ("Hauteur (m)", asset.height_m, True, "double", 0.1, 10.0),
            ("Rotation (°)", asset.rotation_deg, True, "int", 0, 360),
            ("Couleur 3D", asset.color_3d, True, "color"),
        ]
        
        for field_info in fields:
            label = field_info[0]
            value = field_info[1]
            editable = field_info[2] if len(field_info) > 2 else False
            
            if not editable:
                self._add_field(label, QLabel(str(value)))
            elif field_info[3] == "double":
                spin = QDoubleSpinBox()
                spin.setRange(field_info[4], field_info[5])
                spin.setSingleStep(0.1)
                spin.setSuffix(" m")
                spin.setValue(value)
                spin.valueChanged.connect(lambda v, a=asset, k=label.lower(): self._update_asset(a, k, v))
                self._add_field(label, spin)
            elif field_info[3] == "int":
                spin = QSpinBox()
                spin.setRange(field_info[4], field_info[5])
                spin.setSuffix(" °")
                spin.setValue(value)
                spin.valueChanged.connect(lambda v, a=asset, k=label.lower(): self._update_asset(a, k, v))
                self._add_field(label, spin)
            elif field_info[3] == "color":
                btn = QPushButton(value)
                btn.setStyleSheet(f"background: {value};")
                btn.clicked.connect(lambda: self._pick_asset_color(asset, btn))
                self._add_field(label, btn)
            else:
                edit = QLineEdit(str(value))
                edit.textChanged.connect(lambda t, a=asset, k=label.lower(): self._update_asset(a, k, t))
                self._add_field(label, edit)
    
    def _update_asset(self, asset: PhysicalAsset, key: str, value):
        key_map = {
            "id": "id", "type": "asset_type", "catégorie": "category",
            "largeur (m)": "width_m", "profondeur (m)": "depth_m",
            "hauteur (m)": "height_m", "rotation (°)": "rotation_deg",
        }
        attr = key_map.get(key, key.replace(" ", "_").lower())
        if hasattr(asset, attr):
            setattr(asset, attr, value)
            self.view._notify_changed()
    
    def _pick_asset_color(self, asset: PhysicalAsset, btn: QPushButton):
        color = QColorDialog.getColor(QColor(asset.color_3d), self)
        if color.isValid():
            asset.color_3d = color.name()
            btn.setText(color.name())
            btn.setStyleSheet(f"background: {color.name()};")
            self.view._notify_changed()
    
    def _show_workstation(self, ws: WorkstationLayout):
        self.header.setText(f"🏭 Poste: {ws.name}")
        
        edit = QLineEdit(ws.name)
        edit.textChanged.connect(lambda t: self._update_ws(ws, "name", t))
        self._add_field("Nom:", edit)
        
        spin = QDoubleSpinBox()
        spin.setRange(0.5, 20.0)
        spin.setSingleStep(0.1)
        spin.setSuffix(" m")
        spin.setValue(ws.width_m)
        spin.valueChanged.connect(lambda v: self._update_ws(ws, "width_m", v))
        self._add_field("Largeur:", spin)
        
        spin2 = QDoubleSpinBox()
        spin2.setRange(0.5, 20.0)
        spin2.setSingleStep(0.1)
        spin2.setSuffix(" m")
        spin2.setValue(ws.depth_m)
        spin2.valueChanged.connect(lambda v: self._update_ws(ws, "depth_m", v))
        self._add_field("Profondeur:", spin2)
    
    def _update_ws(self, ws: WorkstationLayout, key: str, value):
        setattr(ws, key, value)
        self.view._notify_changed()
    
    def _show_transport(self, link: TransportLink):
        self.header.setText(f"🔗 Transport: {link.id}")
        
        combo = QComboBox()
        combo.addItems([t.value for t in TransportMode])
        combo.setCurrentText(link.transport_mode.value)
        combo.currentTextChanged.connect(lambda v: self._update_transport(link, "transport_mode", TransportMode(v)))
        self._add_field("Mode:", combo)
        
        spin = QDoubleSpinBox()
        spin.setRange(0.1, 10.0)
        spin.setSingleStep(0.1)
        spin.setSuffix(" m/s")
        spin.setValue(link.speed_m_s)
        spin.valueChanged.connect(lambda v: self._update_transport(link, "speed_m_s", v))
        self._add_field("Vitesse:", spin)
        
        self._add_field("Distance:", QLabel(f"{link.distance_m:.1f} m"))
        self._add_field("Temps transit:", QLabel(f"{link.transit_time_s:.0f} s"))
    
    def _update_transport(self, link: TransportLink, key: str, value):
        setattr(link, key, value)
        self.view._notify_changed()
    
    def _show_door(self, door: Door):
        self.header.setText(f"🚪 Porte: {door.id}")
        
        w_type, spin_type = self._create_stepper_field(
            0, 1, ["swing", "sliding", "rollup"].index(door.door_type), 1, "",
            lambda v: self._update_door(door, "door_type", ["swing", "sliding", "rollup"][int(v)])
        )
        spin_type.setDecimals(0)
        type_combo = QComboBox()
        type_combo.addItems(["swing", "sliding", "rollup"])
        type_combo.setCurrentText(door.door_type)
        type_combo.currentTextChanged.connect(lambda v: self._update_door(door, "door_type", v))
        self._add_field("Type:", type_combo)
        
        w_pos, spin_pos = self._create_stepper_field(
            0.0, 1.0, door.position_ratio, 0.01, "",
            lambda v: self._update_door(door, "position_ratio", v)
        )
        spin_pos.setDecimals(2)
        self.widgets["position_ratio"] = spin_pos
        self._add_field("Position:", w_pos)
        
        w_w, spin_w = self._create_stepper_field(
            0.5, 5.0, door.width_m, 0.1, " m",
            lambda v: self._update_door(door, "width_m", v)
        )
        spin_w.setDecimals(2)
        self.widgets["width_m"] = spin_w
        self._add_field("Largeur:", w_w)
        
        w_h, spin_h = self._create_stepper_field(
            1.5, 5.0, door.height_m, 0.1, " m",
            lambda v: self._update_door(door, "height_m", v)
        )
        spin_h.setDecimals(2)
        self.widgets["height_m"] = spin_h
        self._add_field("Hauteur:", w_h)
        
        if door.door_type == "swing":
            side_combo = QComboBox()
            side_combo.addItems(["left", "right"])
            side_combo.setCurrentText(door.swing_side)
            side_combo.currentTextChanged.connect(lambda v: self._update_door(door, "swing_side", v))
            self._add_field("Côté d'ouverture:", side_combo)
            
            dir_combo = QComboBox()
            dir_combo.addItems(["inward", "outward"])
            dir_combo.setCurrentText(door.opening_direction)
            dir_combo.currentTextChanged.connect(lambda v: self._update_door(door, "opening_direction", v))
            self._add_field("Direction:", dir_combo)
            
            w_ang, spin_ang = self._create_stepper_field(
                30.0, 180.0, door.swing_angle_deg, 5.0, " °",
                lambda v: self._update_door(door, "swing_angle_deg", v)
            )
            spin_ang.setDecimals(0)
            self._add_field("Angle d'ouverture:", w_ang)
    
    def _update_door(self, door: Door, key: str, value):
        setattr(door, key, value)
        self.view.rebuild_scene()
        self.view._notify_changed()


# ============================================================
# BARRE D'OUTILS LAYOUT
# ============================================================

class LayoutToolbar(QToolBar):
    """Barre d'outils pour la Vue Implantation 2D."""
    
    tool_selected = Signal(LayoutTool)
    
    def __init__(self, view: LayoutView2D):
        super().__init__("Outils Implantation")
        self.view = view
        self.setMovable(False)
        self.setIconSize(QSize(24, 24))
        self.setup_tools()
    
    def setup_tools(self):
        tools = [
            (LayoutTool.SELECT, "🖱️", "Sélection (V)", "Sélectionner et déplacer"),
            (LayoutTool.PAN, "✋", "Pan (Espace)", "Déplacer la vue"),
            (None, None, None, None),  # Séparateur
            (LayoutTool.WALL, "🧱", "Mur (W)", "Dessiner un mur"),
            (LayoutTool.DOOR, "🚪", "Porte", "Placer une porte sur un mur"),
            (LayoutTool.RECT_ZONE, "📐", "Zone Rect.", "Zone rectangulaire"),
            (LayoutTool.ZONE, "📦", "Zone Polygone", "Zone par points"),
            (None, None, None, None),
            (LayoutTool.ASSET, "🏭", "Asset", "Placer machine/rack/convoyeur"),
            (LayoutTool.WORKSTATION, "🏭", "Poste", "Placer un poste de travail"),
            (None, None, None, None),
            (LayoutTool.TRANSPORT, "🔗", "Transport", "Créer liaison logistique"),
            (LayoutTool.MEASURE, "📏", "Mesurer", "Mesurer distance"),
        ]
        
        self._actions = {}
        
        for tool, icon, text, tooltip in tools:
            if tool is None:
                self.addSeparator()
                continue
            
            action = QAction(text, self)
            action.setToolTip(tooltip)
            action.setCheckable(True)
            action.setData(tool)
            action.triggered.connect(lambda checked, t=tool: self.on_tool_triggered(t))
            self.addAction(action)
            self._actions[tool] = action
        
        # Par défaut sélection
        self._actions[LayoutTool.SELECT].setChecked(True)
    
    def on_tool_triggered(self, tool: LayoutTool):
        for t, action in self._actions.items():
            action.setChecked(t == tool)
        self.view.set_tool(tool)


# ============================================================
# WIDGET PRINCIPAL LAYOUT 2D
# ============================================================

class LayoutView2DWidget(QWidget):
    """Widget complet Vue Implantation 2D avec toolbar, vue, propriétés."""
    
    def __init__(self, building: BuildingLayout = None):
        super().__init__()
        self.building = building or BuildingLayout()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Splitter principal
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ===== PANNEAU GAUCHE: OUTILS + PROPRIÉTÉS =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        
        # Toolbar
        self.toolbar = LayoutToolbar(None)  # Será connecté après
        left_layout.addWidget(self.toolbar)
        
        # Propriétés
        self.properties = LayoutPropertiesPanel(None)
        left_layout.addWidget(self.properties)
        
        # ===== VUE CENTRALE =====
        self.view = LayoutView2D(self.building)
        
        # Connecter toolbar et propriétés
        self.toolbar.view = self.view
        self.properties.view = self.view
        
        # ===== PANNEAU DROIT: COUCHES / ARBORESCENCE =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        
        # Arborescence des couches
        self.layer_tree = QTreeWidget()
        self.layer_tree.setHeaderLabels(["Couches / Éléments"])
        self.layer_tree.setMaximumWidth(300)
        self.populate_layer_tree()
        right_layout.addWidget(QLabel("📋 Couches"))
        right_layout.addWidget(self.layer_tree)
        
        # Infos projet
        info_group = QGroupBox("Infos Projet")
        info_layout = QFormLayout(info_group)
        self.lbl_name = QLabel(self.building.name)
        self.lbl_grid = QLabel(f"{self.building.grid_size_m} m")
        self.lbl_units = QLabel(self.building.units)
        self.lbl_stats = QLabel("0 murs, 0 zones, 0 assets")
        info_layout.addRow("Nom:", self.lbl_name)
        info_layout.addRow("Grille:", self.lbl_grid)
        info_layout.addRow("Unités:", self.lbl_units)
        info_layout.addRow("Stats:", self.lbl_stats)
        right_layout.addWidget(info_group)
        
        right_layout.addStretch()
        
        # Assembler
        splitter.addWidget(left_panel)
        splitter.addWidget(self.view)
        splitter.addWidget(right_panel)
        splitter.setSizes([280, 1000, 300])
        
        layout.addWidget(splitter)
        
        # Connecter signaux
        self.view.building_changed.connect(self.on_building_changed)
        self.view.status_message.connect(self.on_status)
    
    def populate_layer_tree(self):
        self.layer_tree.clear()
        
        layers = [
            ("structure", "🏗️ Structure", self.building.walls),
            ("circulation", "🛣️ Circulation", self.building.zones),
            ("equipment", "🏭 Équipements", self.building.assets),
            ("workstations", "🏭 Postes", self.building.workstations),
            ("transport", "🔗 Transport", self.building.transport_links),
        ]
        
        for layer_id, label, items in layers:
            parent = QTreeWidgetItem([f"{label} ({len(items)})"])
            parent.setData(0, Qt.ItemDataRole.UserRole, layer_id)
            self.layer_tree.addTopLevelItem(parent)
            
            for item in items:
                child = QTreeWidgetItem([getattr(item, 'name', getattr(item, 'id', 'Inconnu'))])
                child.setData(0, Qt.ItemDataRole.UserRole, item.id)
                parent.addChild(child)
        
        self.layer_tree.expandAll()
    
    def on_building_changed(self):
        self.populate_layer_tree()
        self.update_stats()
    
    def update_stats(self):
        stats = (f"{len(self.building.walls)} murs, "
                f"{len(self.building.zones)} zones, "
                f"{len(self.building.assets)} assets, "
                f"{len(self.building.workstations)} postes")
        self.lbl_stats.setText(stats)
    
    def on_status(self, msg: str):
        # Pourrait afficher dans une status bar
        pass
    
    def set_building(self, building: BuildingLayout):
        self.building = building
        self.view.building = building
        self.view.rebuild_scene()
        self.populate_layer_tree()
        self.update_stats()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Données de test
    building = BuildingLayout(name="Usine Test", grid_size_m=1.0)
    
    # Quelques murs
    building.walls.append(WallSegment(
        id="wall_1", start=Vector2D(0, 0), end=Vector2D(20, 0),
        wall_type=WallType.EXTERIOR, thickness_m=0.3
    ))
    building.walls.append(WallSegment(
        id="wall_2", start=Vector2D(20, 0), end=Vector2D(20, 15),
        wall_type=WallType.EXTERIOR, thickness_m=0.3
    ))
    building.walls.append(WallSegment(
        id="wall_3", start=Vector2D(20, 15), end=Vector2D(0, 15),
        wall_type=WallType.EXTERIOR, thickness_m=0.3
    ))
    building.walls.append(WallSegment(
        id="wall_4", start=Vector2D(0, 15), end=Vector2D(0, 0),
        wall_type=WallType.EXTERIOR, thickness_m=0.3
    ))
    
    # Cloison intérieure
    building.walls.append(WallSegment(
        id="wall_5", start=Vector2D(10, 0), end=Vector2D(10, 15),
        wall_type=WallType.INTERIOR, thickness_m=0.15
    ))
    
    # Zone
    building.zones.append(Zone(
        id="zone_1", name="Atelier Montage", zone_type=ZoneType.WORK_AREA,
        vertices=[Vector2D(1, 1), Vector2D(9, 1), Vector2D(9, 14), Vector2D(1, 14)],
        color="#2c7a7b"
    ))
    
    # Asset
    building.assets.append(PhysicalAsset(
        id="asset_1", name="Piqueuse plate", category=AssetCategory.MACHINE,
        asset_type="piqueuse_plate", width_m=2.0, depth_m=1.5, height_m=1.5,
        position=Vector2D(3, 3), machine_type="piqueuse_plate"
    ))
    
    widget = LayoutView2DWidget(building)
    widget.resize(1400, 800)
    widget.setWindowTitle("Textile Line Balancer - Vue Implantation 2D")
    widget.show()
    
    sys.exit(app.exec())