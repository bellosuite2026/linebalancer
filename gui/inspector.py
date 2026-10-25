"""
Inspecteur unifié pour les 3 vues (Logique + Layout 2D + View 3D).

Extrait de gui/main.py (Phase 2 - découpage GUI). Responsable de l'édition
des propriétés du nœud/objet sélectionné dans le panneau latéral droit.
"""
from __future__ import annotations

from typing import Optional, Any, TYPE_CHECKING

from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QLabel

from gui.debug_logger import debug as log_debug
from gui.layout_view_2d import DoorItem, WallItem, ZoneItem

from engine.models_v2 import Vector2D, AssetCategory, ViewMode
from engine.models import Operation

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFrame, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox,
    QCheckBox, QColorDialog, QToolButton,
)

if TYPE_CHECKING:
    from gui.node_editor import NodeEditor
    from gui.layout_view_2d import LayoutView2D

from gui.theme import C_MUTED, C_TEXT, C_BORDER, C_CARD, C_ACCENT, C_ACCENT2, NODE_TYPE_COLORS, NODE_ICONS


# ============================================================
# UNIFIED INSPECTOR (Logical + Layout 2D + View 3D)
# ============================================================

class UnifiedInspector(QWidget):
    """Panneau d'inspecteur unifie pour les 3 vues."""

    def __init__(self, editor: NodeEditor, layout_view=None, view3d=None, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.layout_view = layout_view
        self.view3d = view3d
        self.current_node = None
        self.widgets = {}
        self.current_view_mode = ViewMode.LOGICAL
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header with SVG preview
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(48, 48)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setStyleSheet(
            "background: #182235; border: 1px solid #263244; border-radius: 6px; padding: 4px;"
        )
        self.icon_preview.hide()
        header_row.addWidget(self.icon_preview)
        self.header = QLabel("Aucune sélection")
        self.header.setObjectName("panelHeading")
        self.header.setWordWrap(True)
        self.header.setMinimumHeight(28)
        header_row.addWidget(self.header, 1)
        layout.addLayout(header_row)

        # Form scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.form_widget = QWidget()
        self.form_widget.setObjectName("paletteWidget")
        self.config_layout = QFormLayout(self.form_widget)
        self.config_layout.setSpacing(10)
        self.config_layout.setContentsMargins(4, 4, 4, 4)
        # Better label/field ratio - labels take ~40%, fields ~60%
        self.config_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.config_layout.setFormAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.config_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        scroll.setWidget(self.form_widget)
        layout.addWidget(scroll, 1)  # stretch factor = 1

        # Apply button
        self.btn_apply = QPushButton("✅ Appliquer")
        self.btn_apply.clicked.connect(self._apply_changes)
        layout.addWidget(self.btn_apply)

        # Actions
        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton("🗑️ Supprimer")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.clicked.connect(self.delete_node)
        self.btn_toggle = QPushButton("⏸️ Désactiver")
        self.btn_toggle.clicked.connect(self.toggle_node)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_toggle)
        layout.addLayout(btn_layout)

    def set_view_mode(self, mode: ViewMode):
        self.current_view_mode = mode

    def on_logical_node_selected(self, node_id: str):
        if self.current_view_mode != ViewMode.LOGICAL:
            return
        node = next((n for n in self.editor.workflow.get("nodes", []) if n["id"] == node_id), None)
        self.set_node(node)

    def on_layout_selection_changed(self, selected_items: list):
        if self.current_view_mode != ViewMode.LAYOUT_2D:
            log_debug("Inspector: ignored (not LAYOUT_2D mode)")
            return
        log_debug(f"Inspector: received {len(selected_items)} item(s)")
        try:
            if len(selected_items) == 1:
                item = selected_items[0]
                tname = type(item).__name__
                has = f"asset={hasattr(item,'asset')} zone={hasattr(item,'zone')} wall={hasattr(item,'wall')} door={hasattr(item,'door')}"
                log_debug(f"  type={tname} {has}")
                if hasattr(item, 'asset'):
                    log_debug(f"  → set_layout_node(asset id={item.asset.id})")
                    self.set_layout_node(item.asset)
                elif hasattr(item, 'zone'):
                    log_debug(f"  → set_layout_node(zone id={item.zone.id})")
                    self.set_layout_node(item.zone)
                elif hasattr(item, 'door'):
                    log_debug(f"  → set_layout_door(door id={item.door.id})")
                    self.set_layout_door(item.door)
                elif hasattr(item, 'wall'):
                    log_debug(f"  → set_layout_node(wall id={item.wall.id})")
                    self.set_layout_node(item.wall)
                else:
                    log_debug(f"  ⚠ aucun attribut connu — appel set_node(None)")
                    self.set_node(None)
            else:
                log_debug(f"  → clear (0 or >1 items)")
                self.set_node(None)
        except Exception as e:
            log_debug(f"  ⚠ ERREUR dans on_layout_selection_changed: {e}")
            import traceback
            log_debug(f"  ⚠ {traceback.format_exc()}")
            self.set_node(None)

    def set_node(self, node: Optional[dict]):
        self.current_node = node
        self.clear_config()
        self.icon_preview.hide()

        if node is None:
            self.header.setText("Aucune selection")
            return

        self.header.setText(f"{NODE_ICONS.get(node['type'], '📦')} {node['title']} ({node['id']})")

        # Type & ID
        self.add_readonly("Type", node["type"])
        self.add_readonly("ID", node["id"])

        # Position
        pos_row = QHBoxLayout()
        self.widgets["x"] = QSpinBox()
        self.widgets["x"].setRange(-10000, 10000)
        self.widgets["x"].setValue(node["x"])
        self.widgets["x"].valueChanged.connect(lambda v: self.update_node_pos(v, "x"))
        self.widgets["y"] = QSpinBox()
        self.widgets["y"].setRange(-10000, 10000)
        self.widgets["y"].setValue(node["y"])
        self.widgets["y"].valueChanged.connect(lambda v: self.update_node_pos(v, "y"))
        pos_row.addWidget(QLabel("X:"))
        pos_row.addWidget(self.widgets["x"])
        pos_row.addWidget(QLabel("Y:"))
        pos_row.addWidget(self.widgets["y"])
        self.config_layout.addRow("Position", pos_row)

        # Config fields based on node type
        config = node.get("config", {})
        if node["type"] in ["operation", "workstation", "worker", "machine", "section"]:
            self.add_logical_config(config)
        elif node["type"] in ["layout_machine", "layout_section", "layout_flow", "wall", "door", "zone_circulation", "rack", "conveyor",
                              "agv_path", "machine", "workstation", "section"]:
            self.add_layout_config(config, node["type"])

    def _set_icon_preview(self, machine_type: str):
        from gui.svg_icons import get_machine_pixmap
        pixmap = get_machine_pixmap(machine_type, 48)
        if not pixmap.isNull():
            self.icon_preview.setPixmap(pixmap)
            self.icon_preview.show()
        else:
            self.icon_preview.hide()

    def set_layout_node(self, obj: Any):
        """Set inspector for a layout object (asset, zone, wall)."""
        self.current_node = obj
        self.clear_config()

        if hasattr(obj, 'asset_type'):  # PhysicalAsset
            self.header.setText(f"🏭 {obj.name} ({obj.id})")
            self.add_readonly("Type", "Asset")
            self.add_readonly("ID", obj.id)
            self.add_readonly("Category", obj.category.value)
            self.add_readonly("Asset Type", obj.asset_type)
            self._set_icon_preview(obj.machine_type or obj.asset_type)

            pos_row = QHBoxLayout()
            w_x, spin_x = self._create_stepper_field(-10000, 10000, obj.position.x, 1, "", lambda v: self.update_layout_asset_pos(v, "x"))
            spin_x.setDecimals(3)
            self.widgets["x"] = spin_x
            w_y, spin_y = self._create_stepper_field(-10000, 10000, obj.position.y, 1, "", lambda v: self.update_layout_asset_pos(v, "y"))
            spin_y.setDecimals(3)
            self.widgets["y"] = spin_y
            w_rot, spin_rot = self._create_stepper_field(-360, 360, obj.rotation_deg, 1, "°", lambda v: self.update_layout_asset_rot(v))
            spin_rot.setDecimals(1)
            self.widgets["rot"] = spin_rot
            pos_row.addWidget(QLabel("X:"))
            pos_row.addWidget(w_x)
            pos_row.addWidget(QLabel("Y:"))
            pos_row.addWidget(w_y)
            pos_row.addWidget(QLabel("Rot:"))
            pos_row.addWidget(w_rot)
            self.config_layout.addRow("Position", pos_row)

            w_w, spin_w = self._create_stepper_field(0.1, 50, obj.width_m, 0.1, " m", lambda v: self.update_layout_asset_dim(v, "width"))
            spin_w.setDecimals(3)
            self.widgets["width"] = spin_w
            w_d, spin_d = self._create_stepper_field(0.1, 50, obj.depth_m, 0.1, " m", lambda v: self.update_layout_asset_dim(v, "depth"))
            spin_d.setDecimals(3)
            self.widgets["depth"] = spin_d
            w_h, spin_h = self._create_stepper_field(0.1, 20, obj.height_m, 0.1, " m", lambda v: self.update_layout_asset_dim(v, "height"))
            spin_h.setDecimals(3)
            self.widgets["height"] = spin_h
            dim_row = QHBoxLayout()
            dim_row.addWidget(QLabel("L:"))
            dim_row.addWidget(w_w)
            dim_row.addWidget(QLabel("l:"))
            dim_row.addWidget(w_d)
            dim_row.addWidget(QLabel("H:"))
            dim_row.addWidget(w_h)
            self.config_layout.addRow("Dimensions", dim_row)

            self.widgets["layer"] = QLineEdit(obj.layer)
            self.widgets["layer"].textChanged.connect(lambda v: self.update_layout_asset_meta("layer", v))
            self.config_layout.addRow("Layer", self.widgets["layer"])

            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setStyleSheet(f"background: {obj.color_3d}; border: 1px solid #263244; border-radius: 4px;")
            color_btn.clicked.connect(lambda: self.pick_color(obj, "color_3d"))
            self.config_layout.addRow("Couleur 3D", color_btn)

            if obj.metadata.get("clearances"):
                cl = obj.metadata["clearances"]
                for k in ["front", "rear", "left", "right"]:
                    w_sp, sp = self._create_stepper_field(0, 10, cl.get(k, 0), 0.1, " m", lambda v, key=k: self.update_clearance(obj, key, v))
                    sp.setDecimals(2)
                    self.config_layout.addRow(f"Dég. {k.capitalize()}", w_sp)

        elif hasattr(obj, 'zone_type'):  # Zone
            try:
                self.header.setText(f"📐 {obj.name} ({obj.id})")
                self.add_readonly("Type", "Zone")
                self.add_readonly("Zone Type", obj.zone_type.value if hasattr(obj.zone_type, 'value') else obj.zone_type)
                self.add_readonly("ID", obj.id)

                # Name field (editable)
                _name = QLineEdit(obj.name)
                _name.textChanged.connect(lambda v: self.update_zone_name(obj, v))
                self.widgets["name"] = _name
                self.config_layout.addRow("Nom", _name)

                bbox = obj.bounding_box()
                zone_w = max(0.1, bbox.max_x - bbox.min_x)
                zone_h = max(0.1, bbox.max_y - bbox.min_y)
                w_w, spin_w = self._create_stepper_field(0.1, 100, zone_w, 0.1, " m", lambda v: self.update_zone_dim(obj, "width", v))
                spin_w.setDecimals(2)
                self.widgets["width"] = spin_w
                self.config_layout.addRow("Largeur", w_w)

                w_h, spin_h = self._create_stepper_field(0.1, 100, zone_h, 0.1, " m", lambda v: self.update_zone_dim(obj, "height", v))
                spin_h.setDecimals(2)
                self.widgets["height"] = spin_h
                self.config_layout.addRow("Hauteur", w_h)

                _color_btn = QPushButton()
                _color_btn.setFixedSize(24, 24)
                _color_btn.setStyleSheet(f"background: {obj.color}; border: 1px solid #263244; border-radius: 4px;")
                _color_btn.clicked.connect(lambda: self._pick_zone_color(obj))
                self.config_layout.addRow("Couleur", _color_btn)

                # Font size controls
                _fs_row = QHBoxLayout()
                font_size = obj.metadata.get("font_size", 100)
                self.widgets["font_size"] = font_size
                _fs_minus = QPushButton("−")
                _fs_minus.setFixedSize(28, 28)
                _fs_minus.setToolTip("Réduire la police")
                _fs_plus = QPushButton("+")
                _fs_plus.setFixedSize(28, 28)
                _fs_plus.setToolTip("Agrandir la police")
                _fs_label = QLabel(f"{int(font_size)} px")
                self.widgets["font_size_label"] = _fs_label
                _fs_label.setMinimumWidth(40)
                _fs_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                _fs_row.addWidget(_fs_minus)
                _fs_row.addWidget(_fs_label)
                _fs_row.addWidget(_fs_plus)
                _fs_row.addStretch()
                _fs_minus.clicked.connect(lambda: self.update_zone_font_size(obj, -8))
                _fs_plus.clicked.connect(lambda: self.update_zone_font_size(obj, 8))
                self.config_layout.addRow("Police", _fs_row)

                log_debug(f"  ✓ zone config completed ({self.config_layout.rowCount()} rows)")
            except Exception as e:
                log_debug(f"  ⚠ ERREUR zone config: {e}")
                self.clear_config()
                self.add_readonly("Type", "Zone")
                self.add_readonly("Erreur", str(e))

        elif hasattr(obj, 'wall_type'):  # WallSegment
            self.header.setText(f"🧱 Mur {obj.id}")
            self.add_readonly("Type", "Wall")
            self.add_readonly("Wall Type", obj.wall_type.value)
            self.add_readonly("ID", obj.id)

            w_len, spin_len = self._create_stepper_field(
                0.05, 100.0, obj.length(), 0.1, " m",
                lambda v: self.update_wall_length(obj, v)
            )
            self.widgets["length"] = spin_len
            self.config_layout.addRow("Longueur", w_len)

            w_ang, spin_ang = self._create_stepper_field(
                -180.0, 180.0, obj.angle_deg(), 1.0, " °",
                lambda v: self.update_wall_angle(obj, v)
            )
            self.widgets["angle"] = spin_ang
            self.config_layout.addRow("Angle", w_ang)

            w_thick, spin_thick = self._create_stepper_field(
                0.05, 1.0, obj.thickness_m, 0.05, " m",
                lambda v: self.update_wall_dim(obj, "thickness", v)
            )
            self.widgets["thickness"] = spin_thick
            self.config_layout.addRow("Épaisseur", w_thick)

            w_h, spin_h = self._create_stepper_field(
                2.0, 10.0, obj.height_m, 0.1, " m",
                lambda v: self.update_wall_dim(obj, "height", v)
            )
            self.widgets["height"] = spin_h
            self.config_layout.addRow("Hauteur", w_h)

    def add_logical_config(self, config: dict):
        """Add config fields for logical nodes."""
        for key, value in config.items():
            if key in ["op_id", "ws_id", "worker_id", "machine_type", "section_id", "name"]:
                w = QLineEdit(str(value))
                w.textChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow(key.replace("_", " ").title(), w)
            elif key in ["duration", "efficiency"]:
                if key == "efficiency":
                    w, spin = self._create_stepper_field(0, 2, float(value), 0.1, " x", lambda v, k=key: self.update_node_config(k, v))
                    spin.setDecimals(2)
                else:
                    w, spin = self._create_stepper_field(0, 1000, float(value), 1, " min", lambda v, k=key: self.update_node_config(k, v))
                    spin.setDecimals(2)
                self.widgets[key] = spin
                self.config_layout.addRow(key.replace("_", " ").title(), w)
            elif key in ["available", "enabled"]:
                w = QCheckBox()
                w.setChecked(bool(value))
                w.toggled.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow(key.replace("_", " ").title(), w)
            elif key in ["predecessors", "skills"]:
                w = QLineEdit(str(value))
                w.setPlaceholderText("Séparez par des virgules")
                w.textChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow(key.replace("_", " ").title(), w)
            elif key == "task_type":
                w = QComboBox()
                w.addItems(["VA", "NVA", "NNVA", "Attente"])
                w.setCurrentText(str(value))
                w.currentTextChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow("Type tâche", w)
            elif key == "max_workers":
                w = QSpinBox()
                w.setRange(1, 10)
                w.setValue(int(value))
                w.valueChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow("Max ouvriers", w)

    def add_layout_config(self, config: dict, node_type: str):
        """Add config fields for layout nodes."""
        for key, value in config.items():
            if key in ["machine_type", "name", "section", "section_id", "flow_type", "door_type",
                       "zone_type", "rack_type", "conveyor_type", "path_type", "wall_type"]:
                w = QLineEdit(str(value))
                w.textChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow(key.replace("_", " ").title(), w)
            elif key in ["width_mm", "height_mm", "length_mm", "depth_mm", "thickness_mm", "levels",
                         "cadence_pieces_h", "speed_m_min", "speed_m_s"]:
                w = QSpinBox()
                w.setRange(0, 100000)
                if "speed" in key:
                    w.setSuffix(" m/min" if "min" in key else " m/s")
                elif "mm" in key:
                    w.setSuffix(" mm")
                elif "levels" in key:
                    w.setSuffix(" niveaux")
                w.setValue(int(value))
                w.valueChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow(key.replace("_", " ").title(), w)
            elif key in ["rotation_deg"]:
                w = QDoubleSpinBox()
                w.setRange(-360, 360)
                w.setDecimals(1)
                w.setSuffix("°")
                w.setValue(float(value))
                w.valueChanged.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow("Rotation", w)
            elif key in ["color", "couleur"]:
                color_btn = QPushButton()
                color_btn.setFixedSize(24, 24)
                color_btn.setStyleSheet(f"background: {value}; border: 1px solid #263244; border-radius: 4px;")
                color_btn.clicked.connect(lambda checked, k=key: self.pick_config_color(k))
                self.widgets[key] = color_btn
                self.config_layout.addRow("Couleur", color_btn)
            elif key in ["available", "enabled"]:
                w = QCheckBox()
                w.setChecked(bool(value))
                w.toggled.connect(lambda v, k=key: self.update_node_config(k, v))
                self.widgets[key] = w
                self.config_layout.addRow(key.title(), w)

    def pick_config_color(self, key: str):
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor()
        if color.isValid():
            self.update_node_config(key, color.name())
            self.widgets[key].setStyleSheet(f"background: {color.name()}; border: 1px solid #263244; border-radius: 4px;")

    def pick_color(self, obj: Any, attr: str):
        from PySide6.QtWidgets import QColorDialog
        current = getattr(obj, attr)
        color = QColorDialog.getColor(QColor(current) if isinstance(current, str) else QColor(*[int(c*255) for c in current[:3]]))
        if color.isValid():
            setattr(obj, attr, color.name())
            if self.layout_view:
                self.layout_view.viewport().update()

    def add_readonly(self, label: str, value: str):
        w = QLineEdit(str(value))
        w.setReadOnly(True)
        w.setStyleSheet("background: #182235; color: #94a3b8; padding: 4px 8px; border: 1px solid #263244; border-radius: 4px;")
        w.setMinimumWidth(180)
        # Make label bold for readability
        label_widget = QLabel(f"<b>{label}</b>")
        label_widget.setStyleSheet("color: #e5e7eb;")
        self.config_layout.addRow(label_widget, w)

    def clear_config(self):
        log_debug(f"  clear_config (was {self.config_layout.rowCount()} rows, {len(self.widgets)} widgets)")
        while self.config_layout.rowCount() > 0:
            self.config_layout.removeRow(0)
        self.widgets.clear()

    def _apply_changes(self):
        if self.layout_view:
            self.layout_view.building_changed.emit()

    def _create_stepper_field(self, minimum, maximum, value, step, suffix, callback):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        spin.editingFinished.connect(lambda: callback(spin.value()))

        btn_down = QToolButton()
        btn_down.setText("−")
        btn_down.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_down.clicked.connect(lambda: spin.stepDown())

        btn_up = QToolButton()
        btn_up.setText("+")
        btn_up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_up.clicked.connect(lambda: spin.stepUp())

        layout.addWidget(btn_down)
        layout.addWidget(spin)
        layout.addWidget(btn_up)

        return widget, spin

    def update_node_pos(self, value: int, axis: str):
        if self.current_node:
            self.current_node[axis] = value
            self.editor.persist()

    def update_node_config(self, key: str, value: Any):
        if self.current_node and "config" in self.current_node:
            self.current_node["config"][key] = value
            self.editor.persist()

    def update_layout_asset_pos(self, value: float, axis: str):
        if self.current_node and hasattr(self.current_node, 'position'):
            setattr(self.current_node.position, axis, value)
            if self.layout_view:
                self.layout_view.viewport().update()

    def update_layout_asset_rot(self, value: float):
        if self.current_node and hasattr(self.current_node, 'rotation_deg'):
            self.current_node.rotation_deg = value
            if self.layout_view:
                self.layout_view.viewport().update()

    def update_layout_asset_dim(self, value: float, dim: str):
        if self.current_node and hasattr(self.current_node, dim):
            setattr(self.current_node, dim + "_m", value)
            if self.layout_view:
                self.layout_view.viewport().update()

    def update_layout_asset_meta(self, key: str, value: str):
        if self.current_node and hasattr(self.current_node, 'metadata'):
            self.current_node.metadata[key] = value
            if self.layout_view:
                self.layout_view.viewport().update()

    def update_clearance(self, obj: Any, key: str, value: float):
        if obj.metadata.get("clearances"):
            obj.metadata["clearances"][key] = value
            if self.layout_view:
                self.layout_view.viewport().update()

    def update_zone_dim(self, zone, dim: str, value: float):
        setattr(zone, dim + "_m", value)

        if dim == "width":
            bbox = zone.bounding_box()
            current_width = bbox.max_x - bbox.min_x
            if current_width <= 0:
                return
            ratio = value / current_width
            cx = (bbox.min_x + bbox.max_x) / 2
            for v in zone.vertices:
                v.x = cx + (v.x - cx) * ratio
        elif dim == "height":
            bbox = zone.bounding_box()
            current_height = bbox.max_y - bbox.min_y
            if current_height <= 0:
                return
            ratio = value / current_height
            cy = (bbox.min_y + bbox.max_y) / 2
            for v in zone.vertices:
                v.y = cy + (v.y - cy) * ratio

        if self.layout_view:
            for item in self.layout_view.scene().items():
                if isinstance(item, ZoneItem) and item.zone.id == zone.id:
                    item._update_polygon()
                    break

    def update_zone_font_size(self, zone, delta: int):
        current = zone.metadata.get("font_size", 0)
        bbox = zone.bounding_box()
        zone_w = (bbox.max_x - bbox.min_x) * 1000
        zone_h = (bbox.max_y - bbox.min_y) * 1000
        max_px = max(20, max(zone_w, zone_h) * 0.5)
        if current == 0:
            current = max(20, min(zone_w, zone_h) * 0.08)
            current = min(current, max_px)
        new_size = max(16, min(max_px, current + delta))
        zone.metadata["font_size"] = new_size
        lbl = self.widgets.get("font_size_label")
        if lbl:
            lbl.setText(f"{int(new_size)} px")
        if self.layout_view:
            for item in self.layout_view.scene().items():
                if isinstance(item, ZoneItem) and item.zone.id == zone.id:
                    item._update_name_text()
                    break

    def _pick_zone_color(self, zone):
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor(zone.color) if isinstance(zone.color, str) else QColor(*[int(c*255) for c in zone.color[:3]]))
        if color.isValid():
            zone.color = color.name()
            if self.layout_view:
                for item in self.layout_view.scene().items():
                    if isinstance(item, ZoneItem) and item.zone.id == zone.id:
                        item._update_polygon()
                        break

    def update_zone_name(self, zone, value: str):
        zone.name = value
        self.header.setText(f"📐 {value} ({zone.id})")
        name_w = self.widgets.get("name")
        if name_w:
            name_w.blockSignals(True)
            name_w.setText(value)
            name_w.blockSignals(False)
        if self.layout_view:
            for item in self.layout_view.scene().items():
                if isinstance(item, ZoneItem) and item.zone.id == zone.id:
                    item._update_name_text()
                    break

    def _find_wall_item(self, wall_id: str):
        """Cherche le WallItem dans la scène par son id."""
        if not self.layout_view:
            return None
        for item in self.layout_view.scene().items():
            if isinstance(item, WallItem) and item.wall.id == wall_id:
                return item
        return None

    def update_wall_dim(self, wall, dim: str, value: float):
        setattr(wall, dim + "_m", value)
        if self.layout_view:
            wi = self._find_wall_item(wall.id)
            if wi:
                wi._update_path()
                wi.update()

    def update_wall_length(self, wall, value: float):
        wall.set_length(value)
        if self.layout_view:
            wi = self._find_wall_item(wall.id)
            if wi:
                wi._update_path()
                wi.update()

    def update_wall_angle(self, wall, value: float):
        center = wall.center()
        d = (wall.end - wall.start).normalized()
        rotated = d.rotated(value - wall.angle_deg())
        half_len = wall.length() / 2
        wall.start = center - rotated * half_len
        wall.end = center + rotated * half_len
        if self.layout_view:
            wi = self._find_wall_item(wall.id)
            if wi:
                wi._update_path()
                wi.update()

    def set_layout_door(self, door: Door):
        """Set inspector for a door."""
        log_debug(
            f"set_layout_door: id={door.id} type={door.door_type} "
            f"pos={door.position_ratio:.2f} w={door.width_m} h={door.height_m} "
            f"swing={door.swing_side}/{door.opening_direction}/{door.swing_angle_deg}°"
        )
        self.current_node = door
        self.clear_config()
        
        self.header.setText(f"🚪 Porte: {door.id}")
        self.add_readonly("Type", "Door")
        self.add_readonly("ID", door.id)
        
        type_combo = QComboBox()
        type_combo.addItems(["swing", "sliding", "rollup"])
        type_combo.setCurrentText(door.door_type)
        type_combo.currentTextChanged.connect(lambda v: self.update_door_prop(door, "door_type", v))
        self.config_layout.addRow("Type:", type_combo)
        
        w_pos, spin_pos = self._create_stepper_field(0.0, 1.0, door.position_ratio, 0.01, "", lambda v: self.update_door_prop(door, "position_ratio", v))
        spin_pos.setDecimals(2)
        self.widgets["position_ratio"] = spin_pos
        self.config_layout.addRow("Position:", w_pos)
        
        w_w, spin_w = self._create_stepper_field(0.5, 5.0, door.width_m, 0.1, " m", lambda v: self.update_door_prop(door, "width_m", v))
        spin_w.setDecimals(2)
        self.widgets["width_m"] = spin_w
        self.config_layout.addRow("Largeur:", w_w)
        
        w_h, spin_h = self._create_stepper_field(1.5, 5.0, door.height_m, 0.1, " m", lambda v: self.update_door_prop(door, "height_m", v))
        spin_h.setDecimals(2)
        self.widgets["height_m"] = spin_h
        self.config_layout.addRow("Hauteur:", w_h)
        
        if door.door_type == "swing":
            side_combo = QComboBox()
            side_combo.addItems(["left", "right"])
            side_combo.setCurrentText(door.swing_side)
            side_combo.currentTextChanged.connect(lambda v: self.update_door_prop(door, "swing_side", v))
            self.config_layout.addRow("Côté:", side_combo)
            
            dir_combo = QComboBox()
            dir_combo.addItems(["inward", "outward"])
            dir_combo.setCurrentText(door.opening_direction)
            dir_combo.currentTextChanged.connect(lambda v: self.update_door_prop(door, "opening_direction", v))
            self.config_layout.addRow("Direction:", dir_combo)
            
            w_ang, spin_ang = self._create_stepper_field(30.0, 180.0, door.swing_angle_deg, 5.0, " °", lambda v: self.update_door_prop(door, "swing_angle_deg", v))
            spin_ang.setDecimals(0)
            self.config_layout.addRow("Angle ouverture:", w_ang)
    
    def update_door_prop(self, door, key, value):
        setattr(door, key, value)
        if self.layout_view:
            for item in self.layout_view.scene().items():
                if isinstance(item, DoorItem) and item.door.id == door.id:
                    self.layout_view.update_door_item(item)
                    break
    
    def delete_node(self):
        if self.current_node and hasattr(self.current_node, 'id'):
            if self.current_view_mode == ViewMode.LOGICAL:
                self.editor.remove_node(self.current_node["id"])
            elif self.current_view_mode == ViewMode.LAYOUT_2D and self.layout_view:
                building = self.layout_view.building
                if hasattr(self.current_node, 'asset_type'):
                    building.assets = [a for a in building.assets if a.id != self.current_node.id]
                elif hasattr(self.current_node, 'zone_type'):
                    building.zones = [z for z in building.zones if z.id != self.current_node.id]
                elif hasattr(self.current_node, 'wall_type'):
                    building.walls = [w for w in building.walls if w.id != self.current_node.id]
                elif hasattr(self.current_node, 'wall_id'):
                    building.doors = [d for d in building.doors if d.id != self.current_node.id]
                self.layout_view.rebuild_scene()
            self.set_node(None)

    def toggle_node(self):
        if self.current_node and hasattr(self.current_node, 'id'):
            if self.current_view_mode == ViewMode.LOGICAL:
                self.editor.toggle_node(self.current_node["id"])
