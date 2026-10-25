"""
Outils d'implantation 2D : standards textile et barre d'outils Layout.

Extrait de gui/main.py (Phase 2 - découpage GUI). Contient
TextileLayoutStandards (jeux de dégagements par machine) et LayoutToolBar
(barre d'outils pour le mode Implantation 2D).
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QToolBar, QToolButton, QLabel, QCheckBox, QDoubleSpinBox, QComboBox,
    QButtonGroup,
)

from engine.models_v2 import (
    PhysicalAsset, AssetCategory, Vector2D,
)
from gui.layout_view_2d import LayoutTool, SnapMode
from gui.theme import C_MUTED, ASSET_3D_COLORS

# INDUSTRIAL ENGINEERING CONSTANTS - TEXTILE FACTORY STANDARDS
# ============================================================

class TextileLayoutStandards:
    """Standards d'implantation pour l'industrie textile/habillement (SLP, Lean)."""

    AISLE_MAIN = 3.5          # Allee principale (chariots elevateurs, 2 sens)
    AISLE_SECONDARY = 2.5     # Allee secondaire (transpalettes, 1 sens)
    AISLE_PEDESTRIAN = 1.2    # Allee pietonne
    AISLE_AGV = 2.0           # Allee AGV (unidirectionnelle)
    AISLE_EMERGENCY = 1.5     # Issue de secours minimum

    MACHINE_SIDE_CLEARANCE = 1.0      # Cote acces operateur/maintenance
    MACHINE_REAR_CLEARANCE = 0.8      # Arriere (evacuation, maintenance)
    MACHINE_FRONT_CLEARANCE = 1.2     # Avant (zone de travail operateur)
    MACHINE_BETWEEN_ROWS = 2.0        # Entre rangees dos-a-dos

    WORKSTATION_WIDTH = 1.2           # Largeur standard poste couture
    WORKSTATION_DEPTH = 1.0           # Profondeur standard
    WORKSTATION_SPACING = 0.3         # Espace entre postes adjacents
    CHAIR_SPACE = 0.6                 # Espace chaise/operateur

    RACK_AISLE_WIDTH = 3.0            # Allee entre racks (chariots)
    RACK_DEPTH_SINGLE = 1.1           # Rack simple face
    RACK_DEPTH_DOUBLE = 2.2           # Rack double face
    PALLET_WIDTH = 1.2                # Largeur palette standard
    PALLET_DEPTH = 1.0                # Profondeur palette standard

    CONVEYOR_WIDTH = 0.5              # Largeur bande standard
    CONVEYOR_CLEARANCE = 0.6          # Degagement lateral

    EMERGENCY_EXIT_MAX_DIST = 30.0    # Distance max issue secours (m)
    MAX_WALKING_DISTANCE = 50.0       # Distance marche max entre postes
    LIGHTING_MIN_LUX = 500            # Eclairage minimum zone couture (lux)
    NOISE_MAX_DB = 85                 # Bruit max (dB) sans protection

    MIN_FLOW_PATH_WIDTH = 1.0         # Largeur min chemin flux
    BUFFER_ZONE_SIZE = 2.0            # Zone tampon entre operations

    @classmethod
    def get_machine_clearance(cls, machine_type: str) -> Dict[str, float]:
        clearances = {
            "piqueuse_plate": {"front": 1.2, "rear": 0.8, "left": 1.0, "right": 0.6, "width": 1.2, "depth": 0.7, "height": 1.3},
            "piqueuse_2_aiguilles": {"front": 1.2, "rear": 0.8, "left": 1.0, "right": 0.8, "width": 1.3, "depth": 0.8, "height": 1.3},
            "surjeteuse": {"front": 1.1, "rear": 0.8, "left": 1.0, "right": 0.8, "width": 1.0, "depth": 0.7, "height": 1.2},
            "surjeteuse_3_fils": {"front": 1.0, "rear": 0.8, "left": 0.8, "right": 0.6, "width": 0.8, "depth": 0.6, "height": 1.2},
            "surjeteuse_4_fils": {"front": 1.0, "rear": 0.8, "left": 0.8, "right": 0.8, "width": 0.9, "depth": 0.6, "height": 1.2},
            "surjeteuse_5_fils": {"front": 1.1, "rear": 0.8, "left": 1.0, "right": 0.8, "width": 1.0, "depth": 0.7, "height": 1.2},
            "piqueuse_boutonniere": {"front": 1.5, "rear": 1.0, "left": 1.0, "right": 1.0, "width": 1.5, "depth": 1.2, "height": 1.5},
            "piqueuse_bouton": {"front": 1.2, "rear": 0.8, "left": 0.8, "right": 0.6, "width": 1.0, "depth": 0.8, "height": 1.3},
            "decoupe_laser": {"front": 2.0, "rear": 1.5, "left": 1.5, "right": 1.5, "width": 2.5, "depth": 3.0, "height": 2.0},
            "presse_vapeur": {"front": 1.2, "rear": 1.0, "left": 1.0, "right": 1.0, "width": 1.5, "depth": 1.2, "height": 1.8},
            "repasseuse": {"front": 1.0, "rear": 0.8, "left": 0.8, "right": 0.8, "width": 1.2, "depth": 0.8, "height": 1.5},
            "table_controle": {"front": 1.0, "rear": 0.6, "left": 0.6, "right": 0.6, "width": 1.5, "depth": 0.8, "height": 0.9},
            "table_travail": {"front": 1.0, "rear": 0.6, "left": 0.6, "right": 0.6, "width": 2.0, "depth": 1.0, "height": 0.9},
        }
        return clearances.get(machine_type, {"front": 1.0, "rear": 0.8, "left": 1.0, "right": 0.8, "width": 1.0, "depth": 0.8, "height": 1.5})


# ============================================================
# LAYOUT TOOLBAR (pour mode Implantation 2D)
# ============================================================

class LayoutToolBar(QToolBar):
    """Barre d'outils pour le mode Implantation 2D."""

    tool_changed = Signal(str)
    snap_changed = Signal(str, bool)
    grid_changed = Signal(float)

    def __init__(self, layout_view, parent=None):
        super().__init__("Outils Implantation", parent)
        self.layout_view = layout_view
        self.setIconSize(QSize(24, 24))
        self.setMovable(False)
        self.setup_ui()
        self.layout_view.tool_changed.connect(self.on_tool_changed)
        # Connecter les signaux snap de la toolbar vers la vue
        self.snap_changed.connect(lambda mode_str, enabled: self.layout_view.set_snap_mode(SnapMode(mode_str), enabled))
        self.grid_changed.connect(self.layout_view.set_grid_size)
        # Connecter le sélecteur de type de porte
        if hasattr(self, 'door_type_combo'):
            self.door_type_combo.currentTextChanged.connect(self.layout_view.set_door_type)

    def setup_ui(self):
        self.tool_buttons = {}
        tools = [
            (LayoutTool.SELECT, "🖱️", "Selection", "V"),
            (LayoutTool.PAN, "🤚", "Panoramique", "Esp"),
            (LayoutTool.WALL, "🧱", "Mur", "W"),
            (LayoutTool.DOOR, "🚪", "Porte", "D"),
            (LayoutTool.ZONE, "📐", "Zone (polygone)", "Z"),
            (LayoutTool.RECT_ZONE, "⬜", "Zone (rectangle)", "R"),
            (LayoutTool.ASSET, "🏭", "Asset/Machine", "A"),
            (LayoutTool.WORKSTATION, "👷", "Poste travail", "S"),
            (LayoutTool.TRANSPORT, "🔗", "Lien transport", "T"),
            (LayoutTool.MEASURE, "📏", "Mesure", "M"),
            (LayoutTool.DIMENSION, "📐", "Cotation", "C"),
        ]

        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)

        for tool, icon, name, shortcut in tools:
            btn = QToolButton()
            btn.setText(f"{icon} {name}")
            btn.setToolTip(f"{name} ({shortcut})")
            btn.setCheckable(True)
            btn.setObjectName("toolButton")
            btn.clicked.connect(lambda checked, t=tool: self.on_tool_button(t))
            self.addWidget(btn)
            self.tool_buttons[tool] = btn
            self.tool_group.addButton(btn)

        self.addSeparator()

        # Snap controls
        snap_label = QLabel("Aimantation:")
        snap_label.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; font-weight: 600;")
        self.addWidget(snap_label)

        self.snap_checks = {}
        snap_modes = [
            (SnapMode.GRID, "Grille"),
            (SnapMode.ENDPOINT, "Extremites"),
            (SnapMode.MIDPOINT, "Milieux"),
            (SnapMode.INTERSECTION, "Intersections"),
        ]
        for mode, label in snap_modes:
            chk = QCheckBox(label)
            chk.setChecked(mode in self.layout_view.snap_modes)
            chk.toggled.connect(lambda checked, m=mode: self.snap_changed.emit(m.value, checked))
            self.addWidget(chk)
            self.snap_checks[mode] = chk

        self.addSeparator()

        # Grid size
        grid_label = QLabel("Grille (m):")
        grid_label.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; font-weight: 600;")
        self.addWidget(grid_label)

        self.grid_spin = QDoubleSpinBox()
        self.grid_spin.setRange(0.1, 5.0)
        self.grid_spin.setSingleStep(0.1)
        self.grid_spin.setValue(self.layout_view.grid_size_m)
        self.grid_spin.setSuffix(" m")
        self.grid_spin.valueChanged.connect(self.on_grid_changed)
        self.addWidget(self.grid_spin)

        self.addSeparator()

        # Asset palette for quick placement
        asset_label = QLabel("Insertion rapide:")
        asset_label.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; font-weight: 600;")
        self.addWidget(asset_label)

        self.asset_combo = QComboBox()
        self.asset_combo.addItems([
            "— Choisir —", "Piqueuse plate", "Surjeteuse 3 fils", "Surjeteuse 4 fils",
            "Surjeteuse 5 fils", "Piqueuse boutonniere", "Piqueuse bouton",
            "Decoupe laser", "Presse vapeur", "Table travail",
            "Rack palettes 3N", "Rack palettes 4N", "Rack cantilever",
            "Convoyeur bande", "AGV station",
        ])
        self.asset_combo.currentTextChanged.connect(self.on_asset_selected)
        self.addWidget(self.asset_combo)

        self.addSeparator()

        # Door type selector for placement
        door_label = QLabel("Type porte:")
        door_label.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; font-weight: 600;")
        self.addWidget(door_label)

        self.door_type_combo = QComboBox()
        self.door_type_combo.addItems(["swing", "sliding", "rollup"])
        self.door_type_combo.setCurrentText("swing")
        self.door_type_combo.setToolTip("Type de porte pour l'insertion")
        self.addWidget(self.door_type_combo)

        self.addSeparator()

        # View controls
        self.zoom_in = QToolButton()
        self.zoom_in.setText("🔍+")
        self.zoom_in.setToolTip("Zoom + (Ctrl+molette)")
        self.zoom_in.clicked.connect(lambda: self.layout_view.scale(1.2, 1.2))
        self.addWidget(self.zoom_in)

        self.zoom_out = QToolButton()
        self.zoom_out.setText("🔍-")
        self.zoom_out.setToolTip("Zoom - (Ctrl+molette)")
        self.zoom_out.clicked.connect(lambda: self.layout_view.scale(0.8, 0.8))
        self.addWidget(self.zoom_out)

        self.zoom_fit = QToolButton()
        self.zoom_fit.setText("🎯")
        self.zoom_fit.setToolTip("Ajuster a la vue (F)")
        self.zoom_fit.clicked.connect(self.zoom_fit_view)
        self.addWidget(self.zoom_fit)

        self.tool_buttons[LayoutTool.SELECT].setChecked(True)

    def on_tool_button(self, tool: LayoutTool):
        self.layout_view.set_tool(tool)
        self.tool_changed.emit(tool.value)

    def on_tool_changed(self, tool_name: str):
        for tool, btn in self.tool_buttons.items():
            btn.setChecked(tool.value == tool_name)

    def on_grid_changed(self, value: float):
        self.layout_view.set_grid_size(value)
        self.grid_changed.emit(value)

    def on_asset_selected(self, text: str):
        if text == "— Choisir —":
            return

        asset_map = {
            "Piqueuse plate": ("piqueuse_plate", AssetCategory.MACHINE),
            "Surjeteuse 3 fils": ("surjeteuse_3_fils", AssetCategory.MACHINE),
            "Surjeteuse 4 fils": ("surjeteuse_4_fils", AssetCategory.MACHINE),
            "Surjeteuse 5 fils": ("surjeteuse_5_fils", AssetCategory.MACHINE),
            "Piqueuse boutonniere": ("piqueuse_boutonniere", AssetCategory.MACHINE),
            "Piqueuse bouton": ("piqueuse_bouton", AssetCategory.MACHINE),
            "Decoupe laser": ("decoupe_laser", AssetCategory.MACHINE),
            "Presse vapeur": ("presse_vapeur", AssetCategory.MACHINE),
            "Table travail": ("table_travail", AssetCategory.WORKSTATION),
            "Rack palettes 3N": ("rack_palettes_3n", AssetCategory.RACK),
            "Rack palettes 4N": ("rack_palettes_4n", AssetCategory.RACK),
            "Rack cantilever": ("rack_cantilever", AssetCategory.RACK),
            "Convoyeur bande": ("convoyeur_bande", AssetCategory.CONVEYOR),
            "AGV station": ("agv_station", AssetCategory.AGV),
        }

        if text in asset_map:
            asset_type, category = asset_map[text]
            clearances = TextileLayoutStandards.get_machine_clearance(asset_type)

            asset = PhysicalAsset(
                id=f"{asset_type}_{int(time.time()*1000)%10000}",
                name=text,
                category=category,
                asset_type=asset_type,
                width_m=clearances["width"],
                depth_m=clearances["depth"],
                height_m=clearances["height"],
                position=Vector2D(0, 0),
                rotation_deg=0,
                layer="equipment",
                color_3d=ASSET_3D_COLORS.get(category, "#8da2fb"),
                machine_type=asset_type if category == AssetCategory.MACHINE else "",
                metadata={"clearances": clearances}
            )

            self.layout_view.set_pending_asset(asset)
            self.asset_combo.setCurrentIndex(0)

    def zoom_fit_view(self):
        self.layout_view.fitInView(self.layout_view.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)


# ============================================================
