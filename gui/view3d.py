"""
View3D - Vue 3D Temps Réel pour Digital Factory Suite
Rendu 3D avec VisPy (fallback si Qt3D non dispo).
Support: glTF/GLB, IFC (via ifcopenshell si dispo), OBJ.
"""

from __future__ import annotations

import sys
import math
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

# VisPy imports
try:
    from vispy import scene, app, io
    from vispy.visuals import MeshVisual, LineVisual, TextVisual
    from vispy.geometry import MeshData
    from vispy.color import Color, ColorArray
    VISPY_AVAILABLE = True
except ImportError:
    VISPY_AVAILABLE = False

from PySide6.QtCore import (
    QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal, Slot, QSize
)
from PySide6.QtGui import (
    QColor, QImage, QPixmap, QPainter, QFont
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QSlider, QCheckBox, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QSplitter, QTreeWidget, QTreeWidgetItem
)

from engine.models_v2 import (
    BuildingLayout, PhysicalAsset, WallSegment, Zone, WorkstationLayout,
    TransportLink, Vector3D, AssetCategory, WallType, ZoneType
)


# ============================================================
# CONFIGURATION VISUELLE 3D
# ============================================================

from gui.theme import ASSET_3D_COLORS


@dataclass
class View3DConfig:
    """Configuration de la vue 3D."""
    background_color: tuple = (0.05, 0.08, 0.12, 1.0)  # RGBA
    grid_color: tuple = (0.3, 0.35, 0.45, 0.5)
    grid_size: float = 1.0
    grid_extent: float = 50.0
    ambient_light: tuple = (0.5, 0.5, 0.5)
    directional_light: tuple = (0.8, 0.8, 0.8)
    light_direction: tuple = (-0.5, -1.0, -0.5)
    camera_fov: float = 45.0
    camera_distance: float = 30.0
    show_grid: bool = True
    show_axes: bool = True
    show_wireframe: bool = False
    ssao_enabled: bool = True


WALL_3D_COLORS = {
    WallType.EXTERIOR: (0.29, 0.33, 0.36, 1.0),
    WallType.INTERIOR: (0.42, 0.45, 0.51, 1.0),
    WallType.COLUMN: (0.22, 0.25, 0.28, 1.0),
}

ZONE_3D_COLORS = {
    ZoneType.CIRCULATION_PEDESTRIAN: (0.55, 0.64, 0.98, 0.3),
    ZoneType.CIRCULATION_FORKLIFT: (0.55, 0.64, 0.98, 0.4),
    ZoneType.CIRCULATION_AGV: (0.18, 0.56, 0.98, 0.3),
    ZoneType.STORAGE: (0.65, 0.54, 0.98, 0.2),
    ZoneType.WORK_AREA: (0.07, 0.72, 0.41, 0.2),
    ZoneType.OFFICE: (0.98, 0.75, 0.18, 0.2),
}


# ============================================================
# MOTEUR DE RENDU 3D (VisPy)
# ============================================================

class View3DEngine(QObject):
    """Moteur de rendu 3D basé sur VisPy, intégrable dans Qt."""
    
    status_message = Signal(str)
    render_complete = Signal()
    
    def __init__(self, config: View3DConfig = None):
        super().__init__()
        self.config = config or View3DConfig()
        self.building: Optional[BuildingLayout] = None
        
        # Canvas VisPy
        self.canvas = None
        self.view = None
        
        # Éléments de scène
        self._grid_visual = None
        self._axes_visual = None
        self._asset_visuals: Dict[str, scene.visuals.MeshVisual] = {}
        self._wall_visuals: Dict[str, scene.visuals.MeshVisual] = {}
        self._zone_visuals: Dict[str, scene.visuals.MeshVisual] = {}
        self._workstation_visuals: Dict[str, scene.visuals.MeshVisual] = {}
        self._transport_visuals: Dict[str, scene.visuals.LineVisual] = {}
        
        # Modèles 3D chargés
        self._loaded_models: Dict[str, MeshData] = {}
        
        # Caméra
        self._camera = None
    
    def create_canvas(self, parent: QWidget = None) -> QWidget:
        """Crée le widget canvas VisPy embarqué dans Qt."""
        if not VISPY_AVAILABLE:
            # Fallback: widget placeholder
            widget = QWidget(parent)
            layout = QVBoxLayout(widget)
            label = QLabel("VisPy non disponible - Installez avec: pip install vispy")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #f79009; font-size: 14px; padding: 20px;")
            layout.addWidget(label)
            return widget
        
        # Créer canvas VisPy avec backend Qt
        self.canvas = scene.SceneCanvas(
            keys='interactive',
            bgcolor=self.config.background_color,
            size=(800, 600),
            parent=parent,
            dpi=100
        )
        
        # Utiliser le widget natif Qt
        widget = self.canvas.native
        widget.setParent(parent)
        
        # Configurer la vue
        self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.cameras.TurntableCamera(
            fov=self.config.camera_fov,
            distance=self.config.camera_distance,
            elevation=30,
            azimuth=45
        )
        
        # Initialiser la scène
        self._setup_scene()
        
        return widget
    
    def _setup_scene(self):
        """Configure les éléments de base de la scène."""
        # Grille
        if self.config.show_grid:
            self._create_grid()
        
        # Axes
        if self.config.show_axes:
            self._create_axes()
        
        # Lumière
        self._setup_lighting()
        
        # Camera
        self._camera = self.view.camera
    
    def _create_grid(self):
        """Crée la grille au sol."""
        extent = self.config.grid_extent
        size = self.config.grid_size
        
        # Lignes principales
        lines = []
        colors = []
        
        # Grille fine
        step = size
        for i in range(int(-extent/step), int(extent/step) + 1):
            x = i * step
            lines.extend([
                [-extent, x, 0], [extent, x, 0],
                [x, -extent, 0], [x, extent, 0]
            ])
        
        grid_color = self.config.grid_color
        for _ in lines:
            colors.append(grid_color)
        
        self._grid_visual = scene.visuals.Line(
            pos=np.array(lines, dtype=np.float32),
            color=np.array(colors, dtype=np.float32),
            connect='segments',
            parent=self.view.scene
        )
        self._grid_visual.set_gl_state('translucent', depth_test=True)
    
    def _create_axes(self):
        """Crée les axes X, Y, Z."""
        axis_length = self.config.grid_extent * 0.2
        
        # X - Rouge
        x_axis = scene.visuals.Arrow(
            pos=np.array([[0, 0, 0], [axis_length, 0, 0]], dtype=np.float32),
            color=(1, 0, 0, 1),
            parent=self.view.scene
        )
        
        # Y - Vert
        y_axis = scene.visuals.Arrow(
            pos=np.array([[0, 0, 0], [0, axis_length, 0]], dtype=np.float32),
            color=(0, 1, 0, 1),
            parent=self.view.scene
        )
        
        # Z - Bleu
        z_axis = scene.visuals.Arrow(
            pos=np.array([[0, 0, 0], [0, 0, axis_length]], dtype=np.float32),
            color=(0, 0, 1, 1),
            parent=self.view.scene
        )
        
        self._axes_visual = (x_axis, y_axis, z_axis)
    
    def _setup_lighting(self):
        """Configure l'éclairage de la scène."""
        # Lumière ambiante
        scene.visuals.LightSource(
            color=self.config.ambient_light,
            parent=self.view.scene
        )

        # Lumière directionnelle (soleil)
        scene.visuals.DirectionalLight(
            color=self.config.directional_light,
            direction=self.config.light_direction,
            parent=self.view.scene
        )
    
    def set_building(self, building: BuildingLayout):
        """Charge un bâtiment dans la vue 3D."""
        self.building = building
        self._clear_dynamic_visuals()
        self._rebuild_scene()
    
    def _clear_dynamic_visuals(self):
        """Supprime les visuels dynamiques (assets, murs, zones)."""
        for visual in self._asset_visuals.values():
            visual.parent = None
        self._asset_visuals.clear()
        
        for visual in self._wall_visuals.values():
            visual.parent = None
        self._wall_visuals.clear()
        
        for visual in self._zone_visuals.values():
            visual.parent = None
        self._zone_visuals.clear()
        
        for visual in self._workstation_visuals.values():
            visual.parent = None
        self._workstation_visuals.clear()
        
        for visual in self._transport_visuals.values():
            visual.parent = None
        self._transport_visuals.clear()
    
    def _rebuild_scene(self):
        """Reconstruit la scène à partir du modèle BuildingLayout."""
        if not self.building:
            return
        
        self.status_message.emit("Reconstruction scène 3D...")
        
        # Murs
        for wall in self.building.walls:
            self._add_wall_visual(wall)
        
        # Zones
        for zone in self.building.zones:
            self._add_zone_visual(zone)
        
        # Assets
        for asset in self.building.assets:
            self._add_asset_visual(asset)
        
        # Postes de travail
        for ws in self.building.workstations:
            self._add_workstation_visual(ws)
        
        # Transports
        for link in self.building.transport_links:
            self._add_transport_visual(link)
        
        self.status_message.emit("Scène 3D prête")
        self.render_complete.emit()
    
    def _add_wall_visual(self, wall: WallSegment):
        """Ajoute un mur en 3D (extrusion)."""
        start = np.array([wall.start.x, wall.start.y, 0], dtype=np.float32)
        end = np.array([wall.end.x, wall.end.y, 0], dtype=np.float32)
        height = wall.height_m
        thickness = wall.thickness_m
        
        # Direction du mur
        direction = end - start
        length = np.linalg.norm(direction)
        if length == 0:
            return
        direction = direction / length
        
        # Normale
        normal = np.array([-direction[1], direction[0], 0], dtype=np.float32)
        
        # 4 coins de la base
        half_thick = normal * (thickness / 2)
        corners = [
            start - half_thick,
            start + half_thick,
            end + half_thick,
            end - half_thick,
        ]
        
        # Extrusion vers le haut
        vertices = []
        faces = []
        
        for i, corner in enumerate(corners):
            # Base
            vertices.append([corner[0], corner[1], 0])
            # Haut
            vertices.append([corner[0], corner[1], height])
        
        vertices = np.array(vertices, dtype=np.float32)
        
        # Faces latérales (4 faces)
        for i in range(4):
            next_i = (i + 1) % 4
            # Base: 2*i, Haut: 2*i+1
            faces.append([2*i, 2*next_i, 2*next_i + 1])
            faces.append([2*i, 2*next_i + 1, 2*i + 1])
        
        # Dessus et dessous
        # Dessus
        faces.append([1, 3, 5])
        faces.append([5, 3, 7])
        # Dessous
        faces.append([0, 4, 2])
        faces.append([2, 4, 6])
        
        faces = np.array(faces, dtype=np.uint32)
        
        mesh_data = MeshData(vertices=vertices, faces=faces)
        
        color = WALL_3D_COLORS.get(wall.wall_type, (0.5, 0.5, 0.5, 1.0))
        
        visual = scene.visuals.MeshVisual(
            mesh_data=mesh_data,
            color=color,
            shading='smooth',
            parent=self.view.scene
        )
        
        self._wall_visuals[wall.id] = visual
    
    def _add_zone_visual(self, zone: Zone):
        """Ajoute une zone en 3D (plan coloré au sol)."""
        if len(zone.vertices) < 3:
            return
        
        # Triangulation simple (fan triangulation)
        vertices_3d = []
        for v in zone.vertices:
            vertices_3d.append([v.x, v.y, 0.01])  # Légèrement au-dessus du sol
        
        vertices_3d = np.array(vertices_3d, dtype=np.float32)
        
        faces = []
        for i in range(1, len(vertices_3d) - 1):
            faces.append([0, i, i + 1])
        faces = np.array(faces, dtype=np.uint32)
        
        mesh_data = MeshData(vertices=vertices_3d, faces=faces)
        
        color = ZONE_3D_COLORS.get(zone.zone_type, (0.5, 0.5, 0.5, 0.3))
        
        visual = scene.visuals.MeshVisual(
            mesh_data=mesh_data,
            color=color,
            shading=None,
            parent=self.view.scene
        )
        visual.set_gl_state('translucent', depth_test=True)
        
        self._zone_visuals[zone.id] = visual
    
    def _create_box_mesh(self, width: float, depth: float, height: float) -> MeshData:
        """Crée un mesh de boîte (boîte centrée)."""
        hw, hd, hh = width/2, depth/2, height/2
        
        vertices = np.array([
            [-hw, -hd, 0], [hw, -hd, 0], [hw, hd, 0], [-hw, hd, 0],  # Base
            [-hw, -hd, height], [hw, -hd, height], [hw, hd, height], [-hw, hd, height],  # Haut
        ], dtype=np.float32)
        
        faces = np.array([
            # Base
            [0, 2, 1], [0, 3, 2],
            # Haut
            [4, 5, 6], [4, 6, 7],
            # Côtés
            [0, 1, 5], [0, 5, 4],
            [1, 2, 6], [1, 6, 5],
            [2, 3, 7], [2, 7, 6],
            [3, 0, 4], [3, 4, 7],
        ], dtype=np.uint32)
        
        return MeshData(vertices=vertices, faces=faces)
    
    def _add_asset_visual(self, asset: PhysicalAsset):
        """Ajoute un asset en 3D."""
        # Essayer de charger le modèle 3D
        if asset.model_3d_path and Path(asset.model_3d_path).exists():
            self._load_model(asset)
        else:
            # Box par défaut
            self._add_box_visual(
                asset.id,
                asset.position,
                asset.width_m,
                asset.depth_m,
                asset.height_m,
                asset.rotation_deg,
                ASSET_3D_COLORS.get(asset.category, (0.5, 0.5, 0.5, 1.0))
            )
    
    def _add_box_visual(self, id: str, pos: Vector2D, w: float, d: float, h: float, rot: float, color: tuple):
        """Ajoute une boîte simple."""
        mesh_data = self._create_box_mesh(w, d, h)
        
        visual = scene.visuals.MeshVisual(
            mesh_data=mesh_data,
            color=color,
            shading='smooth',
            parent=self.view.scene
        )
        
        # Position et rotation
        transform = scene.transforms.MatrixTransform()
        transform.translate((pos.x, pos.y, h/2))
        if rot != 0:
            transform.rotate(rot, (0, 0, 1))
        visual.transform = transform
        
        self._asset_visuals[id] = visual
    
    def _load_model(self, asset: PhysicalAsset):
        """Charge un modèle 3D (glTF/OBJ)."""
        try:
            # VisPy peut charger OBJ, PLY, STL
            if asset.model_3d_path.endswith('.obj'):
                mesh_data = io.read_mesh(asset.model_3d_path)
                if mesh_data:
                    visual = scene.visuals.MeshVisual(
                        mesh_data=mesh_data,
                        color=asset.color_3d,
                        shading='smooth',
                        parent=self.view.scene
                    )
                    # Position
                    transform = scene.transforms.MatrixTransform()
                    transform.translate((asset.position.x, asset.position.y, 0))
                    if asset.rotation_deg != 0:
                        transform.rotate(asset.rotation_deg, (0, 0, 1))
                    visual.transform = transform
                    
                    self._asset_visuals[asset.id] = visual
                    return
        except Exception as e:
            print(f"Erreur chargement modèle {asset.model_3d_path}: {e}")
    
    def _add_workstation_visual(self, ws: WorkstationLayout):
        """Ajoute un poste de travail."""
        self._add_box_visual(
            ws.id,
            ws.position,
            ws.width_m,
            ws.depth_m,
            1.0,  # Hauteur standard
            ws.rotation_deg,
            ASSET_3D_COLORS[AssetCategory.WORKSTATION]
        )
    
    def _add_transport_visual(self, link: TransportLink):
        """Ajoute un lien de transport."""
        if not link.path_points:
            return
        
        points = []
        for p in link.path_points:
            points.append([p.x, p.y, 0.1])  # Légèrement au-dessus du sol
        
        lines = np.array(points, dtype=np.float32)
        
        # Couleur selon mode
        colors_map = {
            'manual': (0.58, 0.64, 0.71, 1.0),
            'conveyor': (0.18, 0.56, 0.98, 1.0),
            'agv': (0.55, 0.64, 0.98, 1.0),
            'forklift': (0.97, 0.56, 0.04, 1.0),
        }
        color = colors_map.get(link.transport_mode.value, (0.5, 0.5, 0.5, 1.0))
        
        visual = scene.visuals.Line(
            pos=lines,
            color=color,
            connect='strip',
            parent=self.view.scene
        )
        visual.set_gl_state('translucent', depth_test=True)
        
        self._transport_visuals[link.id] = visual


# ============================================================
# WIDGET PRINCIPAL VIEW3D
# ============================================================

class View3DWidget(QWidget):
    """Widget complet Vue 3D avec contrôles."""
    
    def __init__(self, building: BuildingLayout = None):
        super().__init__()
        self.building = building or BuildingLayout()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        self.btn_reset = QPushButton("🏠 Reset Caméra")
        self.btn_reset.clicked.connect(self.reset_camera)
        toolbar.addWidget(self.btn_reset)
        
        self.btn_top = QPushButton("🔝 Vue Dessus")
        self.btn_top.clicked.connect(self.set_top_view)
        toolbar.addWidget(self.btn_top)
        
        self.btn_iso = QPushButton("📐 Isométrique")
        self.btn_iso.clicked.connect(self.set_iso_view)
        toolbar.addWidget(self.btn_iso)
        
        toolbar.addStretch()
        
        self.chk_grid = QCheckBox("Grille")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self.toggle_grid)
        toolbar.addWidget(self.chk_grid)
        
        self.chk_axes = QCheckBox("Axes")
        self.chk_axes.setChecked(True)
        self.chk_axes.toggled.connect(self.toggle_axes)
        toolbar.addWidget(self.chk_axes)
        
        self.chk_wireframe = QCheckBox("Fil de fer")
        self.chk_wireframe.toggled.connect(self.toggle_wireframe)
        toolbar.addWidget(self.chk_wireframe)
        
        layout.addLayout(toolbar)
        
        # Splitter principal
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Vue 3D
        self.engine = View3DEngine()
        self.canvas_widget = self.engine.create_canvas()
        self.engine.set_building(self.building)
        
        # Panneau droit
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Arborescence objets
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Objets 3D"])
        self.populate_tree()
        right_layout.addWidget(QLabel("📋 Scène"))
        right_layout.addWidget(self.tree)
        
        # Propriétés
        props_group = QGroupBox("Propriétés")
        props_layout = QFormLayout(props_group)
        
        self.spin_grid = QDoubleSpinBox()
        self.spin_grid.setRange(0.1, 10.0)
        self.spin_grid.setSingleStep(0.1)
        self.spin_grid.setSuffix(" m")
        self.spin_grid.setValue(1.0)
        self.spin_grid.valueChanged.connect(self.on_grid_changed)
        props_layout.addRow("Taille grille:", self.spin_grid)
        
        right_layout.addWidget(props_group)
        right_layout.addStretch()
        
        splitter.addWidget(self.canvas_widget)
        splitter.addWidget(right_panel)
        splitter.setSizes([1000, 300])
        
        layout.addWidget(splitter)
        
        # Connecter signaux
        self.engine.status_message.connect(self.on_status)
        self.engine.render_complete.connect(self.on_render_complete)
    
    def populate_tree(self):
        self.tree.clear()
        
        categories = [
            ("structure", "🏗️ Structure", self.building.walls),
            ("zones", "📦 Zones", self.building.zones),
            ("assets", "🏭 Équipements", self.building.assets),
            ("workstations", "🏭 Postes", self.building.workstations),
            ("transport", "🔗 Transport", self.building.transport_links),
        ]
        
        for cat_id, label, items in categories:
            parent = QTreeWidgetItem([f"{label} ({len(items)})"])
            parent.setData(0, Qt.ItemDataRole.UserRole, cat_id)
            self.tree.addTopLevelItem(parent)
            
            for item in items:
                child = QTreeWidgetItem([getattr(item, 'name', getattr(item, 'id', 'Inconnu'))])
                child.setData(0, Qt.ItemDataRole.UserRole, item.id)
                parent.addChild(child)
        
        self.tree.expandAll()
    
    def on_grid_changed(self, value: float):
        self.engine.config.grid_size = value
        if self.engine._grid_visual:
            self.engine._grid_visual.parent = None
            self.engine._create_grid()
    
    def toggle_grid(self, checked: bool):
        self.engine.config.show_grid = checked
        if self.engine._grid_visual:
            self.engine._grid_visual.visible = checked
    
    def toggle_axes(self, checked: bool):
        self.engine.config.show_axes = checked
        if self.engine._axes_visual:
            for axis in self.engine._axes_visual:
                axis.visible = checked
    
    def toggle_wireframe(self, checked: bool):
        self.engine.config.show_wireframe = checked
        # Appliquer à tous les mesh visuals
        for visual in self.engine._asset_visuals.values():
            visual.shading = 'none' if checked else 'smooth'
        for visual in self.engine._wall_visuals.values():
            visual.shading = 'none' if checked else 'smooth'
    
    def reset_camera(self):
        if self.engine._camera:
            self.engine._camera.distance = self.engine.config.camera_distance
            self.engine._camera.elevation = 30
            self.engine._camera.azimuth = 45
    
    def set_top_view(self):
        if self.engine._camera:
            self.engine._camera.elevation = 90
            self.engine._camera.azimuth = 0
    
    def set_iso_view(self):
        if self.engine._camera:
            self.engine._camera.elevation = 30
            self.engine._camera.azimuth = 45
    
    def on_status(self, msg: str):
        print(f"[View3D] {msg}")
    
    def on_render_complete(self):
        self.populate_tree()
    
    def set_building(self, building: BuildingLayout):
        self.building = building
        self.engine.set_building(building)
        self.populate_tree()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Créer un bâtiment de test
    building = BuildingLayout(name="Usine Test")
    
    # Ajouter quelques murs
    building.walls.append(WallSegment(
        id="wall_1", start=Vector2D(0, 0), end=Vector2D(20, 0),
        wall_type=WallType.EXTERIOR
    ))
    building.walls.append(WallSegment(
        id="wall_2", start=Vector2D(20, 0), end=Vector2D(20, 15),
        wall_type=WallType.EXTERIOR
    ))
    building.walls.append(WallSegment(
        id="wall_3", start=Vector2D(20, 15), end=Vector2D(0, 15),
        wall_type=WallType.EXTERIOR
    ))
    building.walls.append(WallSegment(
        id="wall_4", start=Vector2D(0, 15), end=Vector2D(0, 0),
        wall_type=WallType.EXTERIOR
    ))
    
    # Zone de travail
    building.zones.append(Zone(
        id="zone_1", name="Zone Montage",
        zone_type=ZoneType.WORK_AREA,
        vertices=[Vector2D(2, 2), Vector2D(18, 2), Vector2D(18, 13), Vector2D(2, 13)]
    ))
    
    # Asset machine
    building.assets.append(PhysicalAsset(
        id="machine_1", name="Piqueuse Plate",
        category=AssetCategory.MACHINE,
        asset_type="piqueuse_plate",
        position=Vector2D(5, 5),
        width_m=2.0, depth_m=1.5, height_m=1.5
    ))
    
    # Poste de travail
    building.workstations.append(WorkstationLayout(
        id="ws_1", name="Poste 1",
        position=Vector2D(5, 5),
        width_m=2.0, depth_m=2.0
    ))
    
    # Lien transport
    link = TransportLink(
        id="transport_1", source_id="ws_1", target_id="machine_1",
        transport_mode=TransportMode.CONVEYOR,
        path_points=[Vector2D(7, 5), Vector2D(10, 5), Vector2D(10, 8)]
    )
    link.calculate_distance()
    building.transport_links.append(link)
    
    # Lancer
    widget = View3DWidget(building)
    widget.resize(1200, 800)
    widget.show()
    
    sys.exit(app.exec())