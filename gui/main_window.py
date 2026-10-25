#!/usr/bin/env python3
"""
Fenêtre principale de l'application Textile Line Balancer.
Compose les barres d'outils, le workspace, les panneaux latéraux et la barre d'équilibrage.
"""
from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMenuBar, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from engine.models import BalancingResult, SolverAlgorithm
from engine.models_v2 import (
    AssetCategory, BuildingLayout, PhysicalAsset, Zone,
    TransportLink, TransportMode, Vector2D, ViewMode, WorkstationLayout,
    ZoneType,
)

from gui.balance_bar import BalanceBar
from gui.debug_logger import LogPanel, setup_logger
from gui.inspector import UnifiedInspector
from gui.layout_toolbar import TextileLayoutStandards, LayoutToolBar
from gui.layout_view_2d import LayoutView2D
from gui.node_editor import NodeEditor, NODE_BLUEPRINTS, default_workflow, load_project, save_project
from gui.theme import (
    C_BORDER, C_MUTED,
    ASSET_3D_COLORS, STYLESHEET,
)
from gui.viz_widgets import YamazumiChart, SpaghettiDiagram, TimelineGantt, ResultsTab

import gui.project_io as project_io


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Textile Line Balancer — Digital Factory Suite")
        self.resize(1600, 1000)
        self.setStyleSheet(STYLESHEET)

        self.current_view_mode = ViewMode.LOGICAL
        self.view3d = None
        self._last_result = None
        self.balance_variants = []  # historique des équilibrages (comparatif)

        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_topbar(main_layout)
        self._build_workspace(main_layout)
        self._build_bottom_bar(main_layout)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Prêt")

        self._setup_menu()

        # Layout toolbar (for Layout 2D mode)
        self.layout_toolbar = LayoutToolBar(self.layout_view)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.layout_toolbar)
        self.layout_toolbar.hide()

    def _build_topbar(self, parent_layout):
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(48)
        tb_layout = QHBoxLayout(topbar)
        tb_layout.setContentsMargins(12, 4, 12, 4)
        tb_layout.setSpacing(8)

        brand = QLabel("TLB")
        brand.setObjectName("brandMark")
        tb_layout.addWidget(brand)

        title = QLabel("Textile Line Balancer")
        title.setObjectName("brandTitle")
        tb_layout.addWidget(title)

        version = QLabel("v2.0 — Digital Factory Suite")
        version.setObjectName("versionBadge")
        tb_layout.addWidget(version)

        tb_layout.addStretch()

        # View mode tabs
        self.view_btns = {}
        view_modes = [
            (ViewMode.LOGICAL, "Logique", "1"),
            (ViewMode.LAYOUT_2D, "Implantation 2D", "2"),
            (ViewMode.VIEW_3D, "Vue 3D", "3"),
        ]
        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        for mode, name, shortcut in view_modes:
            btn = QPushButton(name)
            btn.setObjectName("toolButton")
            btn.setCheckable(True)
            btn.setToolTip(f"{name} ({shortcut})")
            btn.clicked.connect(lambda checked, m=mode: self.set_view_mode(m))
            self.view_btns[mode] = btn
            view_group.addButton(btn)
            tb_layout.addWidget(btn)
        self.view_btns[ViewMode.LOGICAL].setChecked(True)

        tb_layout.addSpacing(16)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet(f"color: {C_BORDER};")
        tb_layout.addWidget(sep1)

        for text, tip, slot in [
            ("Nouveau", "Nouveau projet (Ctrl+N)", lambda: project_io.action_new_project(self)),
            ("Ouvrir", "Ouvrir projet (Ctrl+O)", lambda: project_io.action_load_project(self)),
            ("Sauver", "Sauvegarder (Ctrl+S)", lambda: project_io.action_save_project(self)),
            ("📷 Export PNG", "Enregistrer la vue 2D en PNG", self._save_2d_view),
        ]:
            btn = QPushButton(text)
            btn.setObjectName("toolButton")
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            tb_layout.addWidget(btn)

        tb_layout.addSpacing(16)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"color: {C_BORDER};")
        tb_layout.addWidget(sep2)

        self.zoom_out_btn = QPushButton("Zoom −")
        self.zoom_out_btn.setObjectName("toolButton")
        self.zoom_out_btn.setToolTip("Zoom − (Ctrl+Molette)")
        self.zoom_out_btn.clicked.connect(lambda: self._zoom_active_view(0.8))
        tb_layout.addWidget(self.zoom_out_btn)

        self.zoom_reset_btn = QPushButton("Ajuster")
        self.zoom_reset_btn.setObjectName("toolButton")
        self.zoom_reset_btn.setToolTip("Ajuster vue (F)")
        self.zoom_reset_btn.clicked.connect(self._zoom_fit_active)
        tb_layout.addWidget(self.zoom_reset_btn)

        self.zoom_in_btn = QPushButton("Zoom +")
        self.zoom_in_btn.setObjectName("toolButton")
        self.zoom_in_btn.setToolTip("Zoom + (Ctrl+Molette)")
        self.zoom_in_btn.clicked.connect(lambda: self._zoom_active_view(1.2))
        tb_layout.addWidget(self.zoom_in_btn)

        tb_layout.addSpacing(16)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet(f"color: {C_BORDER};")
        tb_layout.addWidget(sep3)

        self.btn_gen_flow = QPushButton("🔗 Générer flux")
        self.btn_gen_flow.setObjectName("toolButton")
        self.btn_gen_flow.setToolTip("Générer les liens de transport depuis la vue logique")
        self.btn_gen_flow.clicked.connect(self._generate_transport_links)
        tb_layout.addWidget(self.btn_gen_flow)

        self.btn_flow_sim = QPushButton("▶ Flux")
        self.btn_flow_sim.setObjectName("toolButton")
        self.btn_flow_sim.setToolTip("Afficher/Masquer l'animation du flux matière")
        self.btn_flow_sim.setCheckable(True)
        self.btn_flow_sim.toggled.connect(self._toggle_flow_simulation)
        tb_layout.addWidget(self.btn_flow_sim)

        parent_layout.addWidget(topbar)

    def _build_workspace(self, parent_layout):
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(2)

        # ---- Left sidebar ----
        self.left_sidebar = QWidget()
        self.left_sidebar.setMinimumWidth(40)
        self.left_sidebar.setMaximumWidth(280)
        left_layout = QVBoxLayout(self.left_sidebar)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        self.left_toggle = QPushButton("◀")
        self.left_toggle.setObjectName("toolButton")
        self.left_toggle.setFixedHeight(28)
        self.left_toggle.setToolTip("Masquer/Afficher palette (P)")
        self.left_toggle.clicked.connect(self._toggle_left_sidebar)
        left_layout.addWidget(self.left_toggle)

        self.palette_stack = QStackedWidget()
        left_layout.addWidget(self.palette_stack, 1)

        # Page 0: Logical palette
        logical_palette = QWidget()
        lpal_layout = QVBoxLayout(logical_palette)
        lpal_layout.setContentsMargins(4, 4, 4, 4)
        lpal_layout.setSpacing(8)

        heading = QLabel("PALETTE")
        heading.setObjectName("panelHeading")
        lpal_layout.addWidget(heading)

        self._logical_group = QGroupBox("Vue Logique")
        lg_layout = QVBoxLayout(self._logical_group)
        lg_layout.setSpacing(4)
        self._palette_click_counter = 0
        for ntype, bp in NODE_BLUEPRINTS.items():
            if ntype in ("operation", "workstation", "worker", "machine", "section"):
                from gui.node_editor import PaletteNodeButton
                btn = PaletteNodeButton(ntype, bp["title"])
                btn.setObjectName("palette")
                btn.clicked.connect(lambda checked, nt=ntype: self._add_node_from_palette(nt))
                lg_layout.addWidget(btn)
        lpal_layout.addWidget(self._logical_group)
        lpal_layout.addStretch()
        self.palette_stack.addWidget(logical_palette)

        # Page 1: Layout 2D palette
        layout_palette = QWidget()
        lpal2_layout = QVBoxLayout(layout_palette)
        lpal2_layout.setContentsMargins(4, 4, 4, 4)
        lpal2_layout.setSpacing(8)

        heading2 = QLabel("PALETTE IMPLANTATION")
        heading2.setObjectName("panelHeading")
        lpal2_layout.addWidget(heading2)

        self._layout_group = QGroupBox("Bibliothèque Assets")
        lg2_layout = QVBoxLayout(self._layout_group)
        lg2_layout.setSpacing(4)

        asset_types = [
            ("Machine: Piqueuse plate", "piqueuse_plate", AssetCategory.MACHINE),
            ("Machine: Surjeteuse 3 fils", "surjeteuse_3_fils", AssetCategory.MACHINE),
            ("Machine: Surjeteuse 5 fils", "surjeteuse_5_fils", AssetCategory.MACHINE),
            ("Machine: Piqueuse boutonnière", "piqueuse_boutonniere", AssetCategory.MACHINE),
            ("Machine: Découpe laser", "decoupe_laser", AssetCategory.MACHINE),
            ("Machine: Presse vapeur", "presse_vapeur", AssetCategory.MACHINE),
            ("Rack: Palettes 3N", "rack_palettes_3n", AssetCategory.RACK),
            ("Rack: Palettes 4N", "rack_palettes_4n", AssetCategory.RACK),
            ("Rack: Cantilever", "rack_cantilever", AssetCategory.RACK),
            ("Convoyeur: Bande", "convoyeur_bande", AssetCategory.CONVEYOR),
            ("Station AGV", "agv_station", AssetCategory.AGV),
            ("Table travail", "table_travail", AssetCategory.WORKSTATION),
        ]
        for label, asset_type, cat in asset_types:
            btn = QPushButton(label)
            btn.setObjectName("palette")
            btn.setToolTip(f"Insérer {label}")
            btn.clicked.connect(lambda checked, at=asset_type, c=cat: self.insert_asset_from_palette(at, c))
            lg2_layout.addWidget(btn)
        lg2_layout.addStretch()
        lpal2_layout.addWidget(self._layout_group)
        lpal2_layout.addStretch()
        self.palette_stack.addWidget(layout_palette)

        # Page 2: 3D placeholder
        empty_3d = QWidget()
        e3d_layout = QVBoxLayout(empty_3d)
        e3d_label = QLabel("Vue 3D : utilisez la barre d'outils supérieure")
        e3d_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e3d_label.setStyleSheet(f"color: {C_MUTED};")
        e3d_layout.addWidget(e3d_label)
        self.palette_stack.addWidget(empty_3d)

        # Collapsed page
        empty_widget = QWidget()
        self.palette_stack.addWidget(empty_widget)
        self.palette_stack.setCurrentIndex(0)
        self.left_sidebar_expanded = True

        # ---- Center workspace ----
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.setMinimumWidth(600)

        # Vue logique multi-onglets : chaque équilibrage ouvre un nouvel onglet
        # dérivé, l'onglet d'origine restant intact pour comparaison.
        self.logical_tabs = QTabWidget()
        self.logical_tabs.setObjectName("logicalTabs")
        self.logical_tabs.setTabsClosable(True)
        self.logical_tabs.setMovable(False)
        self.editor = NodeEditor()
        self.editor.setObjectName("editor_original")
        self.logical_tabs.addTab(self.editor, "Logique (origine)")
        self.logical_tabs.currentChanged.connect(self._on_logical_tab_changed)
        self.logical_tabs.tabCloseRequested.connect(self._on_logical_tab_close)
        self.workspace_stack.addWidget(self.logical_tabs)

        self.layout_view = LayoutView2D(BuildingLayout())
        self.workspace_stack.addWidget(self.layout_view)

        self.view3d_placeholder = QWidget()
        v3d_layout = QVBoxLayout(self.view3d_placeholder)
        v3d_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v3d_label = QLabel("Vue 3D\nCliquez sur l'onglet pour initialiser")
        v3d_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v3d_label.setStyleSheet(f"color: {C_MUTED}; font-size: 18px;")
        v3d_layout.addWidget(v3d_label)
        self.workspace_stack.addWidget(self.view3d_placeholder)
        self.workspace_stack.setCurrentIndex(0)

        # ---- Right sidebar ----
        self.right_sidebar = QWidget()
        self.right_sidebar.setMinimumWidth(40)
        right_layout = QVBoxLayout(self.right_sidebar)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        self.right_toggle = QPushButton("▶")
        self.right_toggle.setObjectName("toolButton")
        self.right_toggle.setFixedHeight(28)
        self.right_toggle.setToolTip("Masquer/Afficher inspecteur (I)")
        self.right_toggle.clicked.connect(self._toggle_right_sidebar)
        right_layout.addWidget(self.right_toggle)

        self.debug_toggle = QPushButton("🐛 Debug")
        self.debug_toggle.setObjectName("toolButton")
        self.debug_toggle.setFixedHeight(24)
        self.debug_toggle.setCheckable(True)
        self.debug_toggle.setToolTip("Afficher/Masquer le panneau de logs de débogage")
        self.debug_toggle.toggled.connect(self._toggle_debug_panel)
        right_layout.addWidget(self.debug_toggle)

        self.right_stack = QStackedWidget()
        right_layout.addWidget(self.right_stack, 1)

        self.debug_panel = LogPanel()
        self.debug_panel.setVisible(False)
        self.debug_panel.setMaximumHeight(250)
        right_layout.addWidget(self.debug_panel)

        right_content = QWidget()
        rc_layout = QVBoxLayout(right_content)
        rc_layout.setContentsMargins(4, 4, 4, 4)
        rc_layout.setSpacing(8)

        # Vertical splitter for inspector + results
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.setHandleWidth(4)

        self.inspector = UnifiedInspector(self.editor, self.layout_view, None)
        self.inspector.setMinimumHeight(120)
        self.right_splitter.addWidget(self.inspector)

        self.yamazumi = YamazumiChart(self.editor)
        self.spaghetti = SpaghettiDiagram(self.editor, self.layout_view)
        self.gantt = TimelineGantt(self.editor)
        self.results_tab = ResultsTab(self.editor, self.yamazumi, self.spaghetti, self.gantt)
        self.results_tab.setMinimumHeight(200)
        self.right_splitter.addWidget(self.results_tab)

        self.right_splitter.setSizes([300, 400])
        rc_layout.addWidget(self.right_splitter)

        self.right_stack.addWidget(right_content)
        empty_right = QWidget()
        self.right_stack.addWidget(empty_right)
        self.right_stack.setCurrentIndex(0)
        self.right_sidebar_expanded = True

        # Assemble splitter
        self.main_splitter.addWidget(self.left_sidebar)
        self.main_splitter.addWidget(self.workspace_stack)
        self.main_splitter.addWidget(self.right_sidebar)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([240, 1000, 320])

        parent_layout.addWidget(self.main_splitter, 1)

    def _build_bottom_bar(self, parent_layout):
        self.bottom_bar = BalanceBar(self)
        parent_layout.addWidget(self.bottom_bar)

    # ------------------------------------------------------------------
    # Signals & Wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.editor.node_selected.connect(self.inspector.on_logical_node_selected)
        self.editor.project_changed.connect(self.on_project_changed)
        self.editor.view_mode_changed.connect(self.on_view_mode_changed)
        self.layout_view.selection_changed.connect(self.inspector.on_layout_selection_changed)
        self.layout_view.building_changed.connect(
            lambda: self.bottom_bar.terminal.log("✅ Changements appliqués")
        )
        setup_logger(self.debug_panel)

        self.bottom_bar.btn_run.clicked.connect(self._on_run_clicked)
        self.bottom_bar.btn_stop.clicked.connect(self.stop_balance)
        self.bottom_bar.btn_export_gltf.clicked.connect(lambda: project_io.action_export_gltf(self))
        self.bottom_bar.balance_finished.connect(self._on_balance_finished)
        self.bottom_bar.balance_error.connect(self._on_balance_error)
        self.bottom_bar.btn_simulate.clicked.connect(self._on_simulate_clicked)
        self.bottom_bar.simulation_finished.connect(self._on_simulation_finished)
        self.bottom_bar.btn_export_sim_pdf.clicked.connect(self._on_export_sim_pdf)
        self.bottom_bar.btn_export_pdf.clicked.connect(self._on_export_pdf)

    def _on_run_clicked(self):
        self.bottom_bar.run_balance(self.editor.workflow)

    # ------------------------------------------------------------------
    # View management
    # ------------------------------------------------------------------

    def set_view_mode(self, mode: ViewMode):
        self.current_view_mode = mode
        self.editor.set_view_mode(mode)
        self.inspector.set_view_mode(mode)

        for m, btn in self.view_btns.items():
            btn.setChecked(m == mode)

        if mode == ViewMode.LOGICAL:
            self.workspace_stack.setCurrentIndex(0)
            self.palette_stack.setCurrentIndex(0)
            self.layout_toolbar.hide()
            self.editor.setFocus()
        elif mode == ViewMode.LAYOUT_2D:
            self.workspace_stack.setCurrentIndex(1)
            self.palette_stack.setCurrentIndex(1)
            self.layout_toolbar.show()
            self.layout_view.setFocus()
        elif mode == ViewMode.VIEW_3D:
            self.workspace_stack.setCurrentIndex(2)
            self.palette_stack.setCurrentIndex(2)
            self.layout_toolbar.hide()
            self.create_3d_view()

        if mode != ViewMode.VIEW_3D:
            self.inspector.view3d = None

        self.status.showMessage(f"Mode: {mode.value}")

    def create_3d_view(self):
        if self.view3d is None:
            try:
                from gui.view3d import View3DWidget
                self.view3d = View3DWidget()
                self.inspector.view3d = self.view3d
            except ImportError:
                QMessageBox.warning(self, "Vue 3D", "VisPy non installe. Vue 3D indisponible.")

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _zoom_active_view(self, factor: float):
        if self.current_view_mode == ViewMode.LOGICAL:
            self.editor.scale(factor, factor)
        elif self.current_view_mode == ViewMode.LAYOUT_2D:
            from PySide6.QtWidgets import QGraphicsView
            QGraphicsView.scale(self.layout_view, factor, factor)

    def _zoom_fit_active(self):
        if self.current_view_mode == ViewMode.LOGICAL:
            self.editor.fit_all()
        elif self.current_view_mode == ViewMode.LAYOUT_2D:
            items = self.layout_view.scene().itemsBoundingRect()
            self.layout_view.fitInView(items, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Sidebar toggles
    # ------------------------------------------------------------------

    def _toggle_left_sidebar(self):
        self.left_sidebar_expanded = not self.left_sidebar_expanded
        self.palette_stack.setCurrentIndex(0 if self.left_sidebar_expanded else 1)
        self.left_toggle.setText("▶" if self.left_sidebar_expanded else "◀")
        if self.left_sidebar_expanded:
            self.left_sidebar.setMaximumWidth(280)
            sizes = self.main_splitter.sizes()
            self.main_splitter.setSizes([240, sizes[1], sizes[2]])
        else:
            self.left_sidebar.setMaximumWidth(40)
            sizes = self.main_splitter.sizes()
            self.main_splitter.setSizes([40, sizes[1], sizes[2]])

    def _toggle_right_sidebar(self):
        self.right_sidebar_expanded = not self.right_sidebar_expanded

    def _toggle_debug_panel(self, visible: bool):
        self.debug_panel.setVisible(visible)
        self.debug_toggle.setText("🐛 Debug ON" if visible else "🐛 Debug")
        self.right_stack.setCurrentIndex(0 if self.right_sidebar_expanded else 1)
        self.right_toggle.setText("◀" if self.right_sidebar_expanded else "▶")
        if self.right_sidebar_expanded:
            self.right_sidebar.setMaximumWidth(420)
            sizes = self.main_splitter.sizes()
            self.main_splitter.setSizes([sizes[0], sizes[1], 320])
        else:
            self.right_sidebar.setMaximumWidth(40)
            sizes = self.main_splitter.sizes()
            self.main_splitter.setSizes([sizes[0], sizes[1], 40])

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("1"), self, lambda: self.set_view_mode(ViewMode.LOGICAL))
        QShortcut(QKeySequence("2"), self, lambda: self.set_view_mode(ViewMode.LAYOUT_2D))
        QShortcut(QKeySequence("3"), self, lambda: self.set_view_mode(ViewMode.VIEW_3D))
        QShortcut(QKeySequence("P"), self, self._toggle_left_sidebar)
        QShortcut(QKeySequence("I"), self, self._toggle_right_sidebar)
        QShortcut(QKeySequence("C"), self, self.editor.center_view)
        QShortcut(QKeySequence("A"), self, self.editor.fit_selection)
        QShortcut(QKeySequence("F"), self, self._zoom_fit_active)
        QShortcut(QKeySequence("Ctrl++"), self, lambda: self._zoom_active_view(1.2))
        QShortcut(QKeySequence("Ctrl+-"), self, lambda: self._zoom_active_view(0.8))
        QShortcut(QKeySequence("Ctrl+0"), self, self._zoom_fit_active)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _setup_menu(self):
        mbar = self.menuBar()

        file_menu = mbar.addMenu("Fichier")
        file_menu.addAction("Nouveau projet", lambda: project_io.action_new_project(self), "Ctrl+N")
        file_menu.addAction("Ouvrir...", lambda: project_io.action_load_project(self), "Ctrl+O")
        file_menu.addAction("Enregistrer", lambda: project_io.action_save_project(self), "Ctrl+S")
        file_menu.addSeparator()
        file_menu.addAction("Sauvegarder implantation 2D", lambda: project_io.action_save_layout(self))
        file_menu.addAction("Charger implantation 2D", lambda: project_io.action_load_layout(self))
        file_menu.addSeparator()
        file_menu.addAction("Importer SAM", lambda: project_io.action_import_sam(self))
        file_menu.addAction("Importer Postes", lambda: project_io.action_import_workstations(self))
        file_menu.addAction("Importer Ouvriers", lambda: project_io.action_import_workers(self))
        file_menu.addSeparator()
        file_menu.addAction("Quitter", self.close, "Ctrl+Q")

        edit_menu = mbar.addMenu("Edition")
        edit_menu.addAction("Annuler", self._on_undo, "Ctrl+Z")
        edit_menu.addAction("Retablir", self._on_redo, "Ctrl+Y")
        edit_menu.addSeparator()
        edit_menu.addAction("Couper", self.editor.cut_selection, "Ctrl+X")
        edit_menu.addAction("Copier", self.editor.copy_selection, "Ctrl+C")
        edit_menu.addAction("Coller", self.editor.paste_selection, "Ctrl+V")
        edit_menu.addAction("Dupliquer", self.editor.duplicate_selection, "Ctrl+D")
        edit_menu.addAction("Supprimer", self.editor.delete_selection, "Del")
        edit_menu.addSeparator()
        edit_menu.addAction("Aligner horizontalement", self.editor.align_horizontal)
        edit_menu.addAction("Aligner verticalement", self.editor.align_vertical)
        edit_menu.addAction("Repartir horizontalement", self.editor.distribute_horizontal)
        edit_menu.addAction("Repartir verticalement", self.editor.distribute_vertical)

        view_menu = mbar.addMenu("Affichage")
        view_menu.addAction("Centrer vue", self.editor.center_view, "C")
        view_menu.addAction("Ajuster selection", self.editor.fit_selection, "A")
        view_menu.addAction("Ajuster tout", self.editor.fit_all, "F")
        view_menu.addSeparator()
        view_menu.addAction("Vue Logique", lambda: self.set_view_mode(ViewMode.LOGICAL), "1")
        view_menu.addAction("Implantation 2D", lambda: self.set_view_mode(ViewMode.LAYOUT_2D), "2")
        view_menu.addAction("Vue 3D", lambda: self.set_view_mode(ViewMode.VIEW_3D), "3")

        tools_menu = mbar.addMenu("Outils")
        tools_menu.addAction("Equilibrer ligne (RPW)", lambda: self.bottom_bar.run_balance(self.editor.workflow, "rpw"))
        tools_menu.addAction("Equilibrer ligne (CP-SAT)", lambda: self.bottom_bar.run_balance(self.editor.workflow, "cp-sat"))
        tools_menu.addSeparator()
        tools_menu.addAction("Generer layout 2D auto", self.generate_layout_2d)
        tools_menu.addAction("Exporter vers 3D (glTF)", lambda: project_io.action_export_gltf(self))

        help_menu = mbar.addMenu("Aide")
        help_menu.addAction("Raccourcis clavier", self.show_shortcuts)
        help_menu.addAction("A propos", self.show_about)

    # ------------------------------------------------------------------
    # Project events
    # ------------------------------------------------------------------

    def on_project_changed(self):
        self.bottom_bar.terminal.log("Projet modifie")

    def on_view_mode_changed(self, mode: str):
        pass

    # ------------------------------------------------------------------
    # Balance results
    # ------------------------------------------------------------------

    def stop_balance(self):
        self.bottom_bar.stop_balance()

    def _on_balance_finished(self, result: BalancingResult):
        self._last_result = result
        self.results_tab.set_result(result)
        self.bottom_bar.btn_export_pdf.setEnabled(result.success)
        if result.success:
            # Enregistre la variante pour le tableau comparatif
            objective = self.bottom_bar.objective_combo.currentText()
            variant = {
                "label": objective,
                "solver": result.solver_used,
                "stations": result.stations_used,
                "cycle_time": result.actual_cycle_time,
                "efficiency": result.efficiency,
                "balance_delay": result.balance_delay,
            }
            self.balance_variants.append(variant)
            self.results_tab.set_variants(self.balance_variants)

            # Ouvre une NOUVELLE vue logique dérivée (onglet) sans toucher
            # à la vue d'origine, afin de pouvoir comparer les deux.
            self._open_balanced_logical_view(result, variant)
            # Auto-export PDF dans le dossier du projet
            from pathlib import Path
            try:
                from engine.report_generator import BalanceReport
                pdf_dir = Path("results")
                pdf_dir.mkdir(exist_ok=True)
                pdf_path = pdf_dir / f"rapport_{result.problem.name}_{__import__('datetime').datetime.now():%H%M%S}.pdf"
                BalanceReport.balance_result(result, pdf_path)
                self.bottom_bar.terminal.log(f"📄 Rapport PDF: {pdf_path}")
            except Exception as e:
                self.bottom_bar.terminal.log(f"⚠️  PDF non généré: {e}")

    def _on_export_pdf(self):
        if self._last_result is None:
            return
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le rapport PDF", str(Path.home() / "rapport_equilibrage.pdf"),
            "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            from engine.report_generator import BalanceReport
            BalanceReport.balance_result(self._last_result, Path(path))
            self.bottom_bar.terminal.log(f"✅ PDF exporté: {path}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erreur PDF", str(e))

    def _on_export_sim_pdf(self):
        if self.results_tab.current_simulation is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "PDF Simulation", "Lancez d'abord une simulation")
            return
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le rapport de simulation PDF",
            str(Path.home() / "rapport_simulation.pdf"), "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            from engine.report_generator import BalanceReport
            name = self._last_result.problem.name if self._last_result else "Simulation"
            BalanceReport.simulation_report(self.results_tab.current_simulation, Path(path), name)
            self.bottom_bar.terminal.log(f"✅ PDF simulation exporté: {path}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erreur PDF Simulation", str(e))

    def _on_simulate_clicked(self):
        result = self.results_tab.current_result
        if result is None or not result.success:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Simulation", "Lancez d'abord un equilibrage reussi")
            return
        self.bottom_bar.run_simulation(result)

    def _on_simulation_finished(self, sim_result):
        from engine.simulation import SimulationResult
        self.bottom_bar.terminal.log(sim_result.summary())
        self.results_tab.current_simulation = sim_result
        # Auto-export PDF de simulation
        try:
            from engine.report_generator import BalanceReport
            from pathlib import Path
            pdf_dir = Path("results")
            pdf_dir.mkdir(exist_ok=True)
            name = self._last_result.problem.name if self._last_result else "Simulation"
            pdf_path = pdf_dir / f"simulation_{name}_{__import__('datetime').datetime.now():%H%M%S}.pdf"
            BalanceReport.simulation_report(sim_result, pdf_path, name)
            self.bottom_bar.terminal.log(f"📄 Rapport simulation PDF: {pdf_path}")
        except Exception as e:
            self.bottom_bar.terminal.log(f"⚠️  PDF simulation non généré: {e}")

    def _on_undo(self):
        if self.current_view_mode == ViewMode.LAYOUT_2D:
            self.layout_view.undo()
        else:
            self.editor.undo()

    def _on_redo(self):
        if self.current_view_mode == ViewMode.LAYOUT_2D:
            self.layout_view.redo()
        else:
            self.editor.redo()

    def _on_balance_error(self, error: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Erreur", error)

    # ------------------------------------------------------------------
    # Vues logiques multi-onglets
    # ------------------------------------------------------------------

    def _on_logical_tab_changed(self, index: int):
        """Synchronise l'éditeur actif et les panneaux dépendants."""
        widget = self.logical_tabs.widget(index)
        if widget is not None:
            self.editor = widget
        self._sync_editors_to_active()

    def _on_logical_tab_close(self, index: int):
        """Empêche la fermeture de l'onglet d'origine."""
        if index == 0:
            self.bottom_bar.terminal.log("L'onglet d'origine ne peut pas être fermé")
            return
        widget = self.logical_tabs.widget(index)
        self.logical_tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        if self.logical_tabs.count() > 0:
            self._on_logical_tab_changed(self.logical_tabs.currentIndex())

    def _sync_editors_to_active(self):
        """Repointe l'inspecteur et les widgets de visualisation vers l'éditeur
        logique actif (onglet courant)."""
        editor = self.editor
        self.inspector.editor = editor
        self.inspector.on_logical_node_selected(editor.selected_id)
        self.yamazumi.editor = editor
        self.spaghetti.editor = editor
        self.gantt.editor = editor
        self.results_tab.editor = editor

    def _open_balanced_logical_view(self, result: BalancingResult, variant: dict = None):
        """Crée une vue logique dérivée reflétant l'équilibrage, dans un nouvel
        onglet. La vue dérivée est TOUJOURS construite à partir de la vue de
        départ (onglet 0, « origine »), quelle que soit la vue active, afin que
        chaque changement d'objectif produise une comparaison reproductible par
        rapport au même point de départ."""
        import copy
        origin = self.logical_tabs.widget(0)
        base_workflow = copy.deepcopy(origin.workflow if origin is not None else self.editor.workflow)
        balanced = NodeEditor(workflow=base_workflow, derived=True)
        balanced.node_selected.connect(self.inspector.on_logical_node_selected)
        balanced.sync_from_balance_result(result)

        # Nom d'onglet explicite : objectif + clés pour comparer d'un coup d'œil
        if variant is not None:
            label = (f"{variant['label']} · {variant['stations']} postes · "
                     f"{variant['cycle_time']:.1f}min · {variant['efficiency']:.0f}%")
        else:
            label = f"Équilibré · {result.stations_used} postes"
        n = self.logical_tabs.count()
        tab_index = self.logical_tabs.addTab(balanced, label)
        self.logical_tabs.setCurrentIndex(tab_index)
        self.editor = balanced
        self._sync_editors_to_active()
        self.set_view_mode(ViewMode.LOGICAL)
        self.bottom_bar.terminal.log(
            f"✨ Nouvelle vue logique '{label}' créée depuis la vue de départ "
            f"(origine conservée pour comparaison)"
        )

    # ------------------------------------------------------------------
        # Layout generation & asset insertion
    # ------------------------------------------------------------------

    def _save_2d_view(self):
        """Exporte la vue 2D courante en PNG."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la vue 2D", "", "PNG (*.png);;JPEG (*.jpg)")
        if path:
            img = self.layout_view.grab().toImage()
            img.save(path)

    @staticmethod
    def _factory_bounds(existing: BuildingLayout):
        """Calcule la zone disponible dans le plan d'usine."""
        margin = 1.0  # marge intérieure

        # 1. Par les zones WORK_AREA
        work_zones = [z for z in existing.zones if z.zone_type == ZoneType.WORK_AREA]
        if work_zones:
            best = max(work_zones, key=lambda z: z.area())
            bb = best.bounding_box()
            return {
                "x_min": bb.min_x + margin,
                "x_max": bb.max_x - margin,
                "y_min": bb.min_y + margin,
                "y_max": bb.max_y - margin,
                "label": best.name,
            }

        # 2. Par les murs (périmètre du bâtiment)
        if existing.walls:
            xs = [w.start.x for w in existing.walls] + [w.end.x for w in existing.walls]
            ys = [w.start.y for w in existing.walls] + [w.end.y for w in existing.walls]
            return {
                "x_min": min(xs) + margin,
                "x_max": max(xs) - margin,
                "y_min": min(ys) + margin,
                "y_max": max(ys) - margin,
                "label": "bâtiment",
            }

        # 3. Par les assets existants
        if existing.assets:
            xs = [a.position.x for a in existing.assets]
            ys = [a.position.y for a in existing.assets]
            return {
                "x_min": min(xs) - 1.0,
                "x_max": max(xs) + 5.0,
                "y_min": min(ys) - 1.0,
                "y_max": max(ys) + 5.0,
                "label": "zone existante",
            }

        return None

    def generate_layout_2d(self):
        if not self.editor.workflow.get("nodes"):
            QMessageBox.warning(self, "Attention", "Aucun noeud dans le projet")
            return

        existing = self.layout_view.layout_data
        existing_name = existing.name or "Usine"

        preserved = {
            "walls": existing.walls[:],
            "doors": existing.doors[:],
            "zones": existing.zones[:],
            "dimensions": existing.dimensions[:],
            "transport_links": existing.transport_links[:],
        }

        # ── Collecte des nœuds pertinents ──────────────────────────
        machine_nodes: list[dict] = []
        workstation_nodes: list[dict] = []
        operation_nodes: list[dict] = []
        section_nodes: list[dict] = {}
        for n in self.editor.workflow["nodes"]:
            if not n.get("enabled", True):
                continue
            t = n["type"]
            if t == "machine":
                machine_nodes.append(n)
            elif t == "workstation":
                workstation_nodes.append(n)
            elif t == "operation":
                operation_nodes.append(n)
            elif t in ("section", "layout_section"):
                c = n.get("config", {})
                section_nodes[c.get("section_id", n["id"])] = n

        # ── Vérification des prérequis ─────────────────────────────
        missing_zones: set[str] = set()
        sections_used = {op.get("config", {}).get("section", "") for op in operation_nodes}
        sections_used.discard("")
        existing_zone_ids = {z.name for z in existing.zones}
        for sec in sections_used:
            if sec not in existing_zone_ids:
                # Vérifie si un nœud section existe avec ce nom
                if sec not in section_nodes and sec not in existing_zone_ids:
                    missing_zones.add(sec)

        missing_machine_types: set[str] = set()
        ops_by_mt: dict[str, list[dict]] = {}
        for op in operation_nodes:
            mt = op.get("config", {}).get("machine_type", "")
            if mt:
                ops_by_mt.setdefault(mt, []).append(op)

        existing_asset_types = {a.asset_type for a in existing.assets}
        existing_machine_types = {a.machine_type for a in existing.assets if a.machine_type}
        for mt in ops_by_mt:
            if mt not in existing_machine_types and mt not in existing_asset_types:
                # Pas encore d'asset pour ce type machine
                if not any(n.get("config", {}).get("machine_type") == mt for n in machine_nodes):
                    missing_machine_types.add(mt)

        if missing_zones:
            zones_str = ", ".join(f"«{z}»" for z in sorted(missing_zones))
            reply = QMessageBox.question(
                self, "Zones manquantes",
                f"Les sections suivantes n'ont pas de zone délimitée dans le plan : {zones_str}.\n"
                "Voulez-vous les créer automatiquement ?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                for sec in missing_zones:
                    z = Zone(
                        id=f"zone_{sec.lower().replace(' ', '_')}",
                        name=sec,
                        zone_type=ZoneType.WORK_AREA,
                        vertices=[
                            Vector2D(1.0, 1.0), Vector2D(14.0, 1.0),
                            Vector2D(14.0, 10.0), Vector2D(1.0, 10.0),
                        ],
                        color="#2c7a7b",
                    )
                    preserved["zones"].append(z)
                    self.bottom_bar.terminal.log(f"🏭 Zone créée: {sec}")
            else:
                self.bottom_bar.terminal.log("⚠️  Placement sans zones — risque de chevauchement")

        if missing_machine_types:
            mt_list = ", ".join(f"«{m}»" for m in sorted(missing_machine_types))
            QMessageBox.information(
                self, "Types machine manquants",
                f"Des opérations utilisent des types machine sans nœud correspondant : {mt_list}.\n"
                "Des assets seront créés automatiquement pour ces types."
            )

        bounds = self._factory_bounds(existing)
        if bounds is None:
            bounds = {"x_min": 1.0, "x_max": 15.0, "y_min": 1.0, "y_max": 8.0, "label": "défaut"}

        # ── Zones d'exclusion : entrées/sorties ────────────────────
        door_keepout: list[tuple[float, float, float, float]] = []
        wall_by_id = {w.id: w for w in existing.walls}
        for d in existing.doors:
            wall = wall_by_id.get(d.wall_id)
            if wall is None:
                continue
            dx = wall.end.x - wall.start.x
            dy = wall.end.y - wall.start.y
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            mid_x = wall.start.x + d.position_ratio * dx
            mid_y = wall.start.y + d.position_ratio * dy
            kw = d.width_m + 1.0
            kd = 1.5
            door_keepout.append((mid_x - kw / 2, mid_y - kd / 2, kw, kd))

        def _in_door_keepout(x: float, y: float, w: float, d: float) -> bool:
            for kx, ky, kw, kd in door_keepout:
                if (x + w / 2 > kx and x - w / 2 < kx + kw
                        and y + d / 2 > ky and y - d / 2 < ky + kd):
                    return True
            return False

        # ── Collision BBOX ────────────────────────────────────────
        existing_boxes: list[tuple[float, float, float, float, str]] = []
        for a in existing.assets:
            existing_boxes.append((
                a.position.x - a.width_m / 2, a.position.y - a.depth_m / 2,
                a.position.x + a.width_m / 2, a.position.y + a.depth_m / 2,
                a.id,
            ))

        def _bbox_collides(bx: float, by: float, bw: float, bd: float,
                           exclude_id: str = "") -> bool:
            l1, t1, r1, bot1 = bx - bw / 2, by - bd / 2, bx + bw / 2, by + bd / 2
            for l2, t2, r2, bot2, eid in existing_boxes:
                if eid == exclude_id:
                    continue
                if l1 < r2 and r1 > l2 and t1 < bot2 and bot1 > t2:
                    return True
            return False

        # ── Construit les nœuds machine depuis les opérations ──────
        existing_source_nodes = {
            a.metadata.get("source_node", "") for a in existing.assets
        }
        # Crée un nœud machine virtuel pour chaque type machine utilisé
        # qui n'a pas encore de nœud dédié
        used_machine_types = {n.get("config", {}).get("machine_type", "") for n in machine_nodes}
        used_machine_types.discard("")
        for mt, ops in ops_by_mt.items():
            if mt not in used_machine_types:
                virtual_id = f"auto_mt_{mt}"
                if virtual_id not in existing_source_nodes:
                    machine_nodes.append({
                        "id": virtual_id,
                        "type": "machine",
                        "title": mt.replace("_", " ").title(),
                        "config": {"machine_type": mt, "name": mt.replace("_", " ").title(),
                                    "section": ops[0].get("config", {}).get("section", "")},
                    })

        # ── Placement dans la grille ───────────────────────────────
        edge_map: dict[str, list[str]] = {}
        for e in self.editor.workflow.get("edges", []):
            src, dst = e[0], e[1]
            edge_map.setdefault(src, []).append(dst)
            edge_map.setdefault(dst, []).append(src)

        new_assets: list[PhysicalAsset] = []
        new_workstations: list[WorkstationLayout] = []

        area_w = bounds["x_max"] - bounds["x_min"]
        row_height = 2.5
        col_spacing = 1.5
        machines_per_row = max(1, int(area_w / 2.5))

        # Crée un asset pour chaque WORKSTATION (1 asset = 1 poste physique)
        # puis place les nœuds machine comme références de type
        # On parcourt d'abord les workstation_nodes pour créer les assets,
        # puis les machine_nodes comme références supplémentaires
        place_nodes = list(workstation_nodes)
        # Ajoute les machine_nodes qui n'ont pas de workstation associée
        ws_machine_types = {n.get("config", {}).get("machine_type", "") for n in workstation_nodes}
        for mn in machine_nodes:
            if mn.get("config", {}).get("machine_type", "") not in ws_machine_types:
                place_nodes.append(mn)

        for i, node in enumerate(place_nodes):
            node_id = node["id"]
            if node_id in existing_source_nodes:
                continue
            cfg = node.get("config", {})
            machine_type = cfg.get("machine_type", "piqueuse_plate")
            clearances = TextileLayoutStandards.get_machine_clearance(machine_type)
            mw = clearances["width"]
            md = clearances["depth"]

            row = i // machines_per_row
            col = i % machines_per_row
            cx = bounds["x_min"] + col * (mw + col_spacing) + mw / 2
            cy = bounds["y_min"] + row * row_height + md / 2

            tries = 0
            while (_in_door_keepout(cx, cy, mw, md) or _bbox_collides(cx, cy, mw, md)) and tries < 40:
                cx += mw + col_spacing
                if cx > bounds["x_max"] - mw / 2:
                    cx = bounds["x_min"] + mw / 2
                    cy += row_height
                tries += 1

            asset = PhysicalAsset(
                id=f"asset_{node_id}",
                name=cfg.get("name", node["title"]),
                category=AssetCategory.MACHINE,
                asset_type=machine_type,
                width_m=mw, depth_m=md, height_m=clearances["height"],
                position=Vector2D(cx, cy),
                rotation_deg=0, layer="equipment",
                color_3d=ASSET_3D_COLORS.get(AssetCategory.MACHINE, "#8da2fb"),
                machine_type=machine_type,
                metadata={"clearances": clearances, "source_node": node_id},
            )
            new_assets.append(asset)
            existing_boxes.append((
                cx - mw / 2, cy - md / 2, cx + mw / 2, cy + md / 2, asset.id
            ))

        # Place les WorkstationLayout à côté de leur asset
        for node in workstation_nodes:
            node_id = node["id"]
            if node_id in existing_source_nodes:
                continue
            cfg = node.get("config", {})
            machine_type = cfg.get("machine_type", "")

            neighbor_ids = edge_map.get(node_id, [])
            linked_asset = None
            for nid in neighbor_ids:
                for a in reversed(new_assets + existing.assets):
                    if a.metadata.get("source_node", "") == nid:
                        linked_asset = a
                        break
                if linked_asset:
                    break
            if linked_asset is None and machine_type:
                for a in reversed(new_assets + existing.assets):
                    if a.machine_type == machine_type:
                        linked_asset = a
                        break

            ws_x = (linked_asset.position.x + linked_asset.width_m / 2 + 1.0) if linked_asset else bounds["x_min"] + 1.0
            ws_y = linked_asset.position.y if linked_asset else bounds["y_min"] + 2.0
            ws = WorkstationLayout(
                id=f"ws_{node_id}",
                name=cfg.get("name", node["title"]),
                position=Vector2D(ws_x, ws_y),
                width_m=1.5, depth_m=1.5,
                asset_ids=[linked_asset.id] if linked_asset else [],
                metadata={"source_node": node_id},
            )
            new_workstations.append(ws)

        if not new_assets and not new_workstations:
            self.bottom_bar.terminal.log("Aucun nouvel element a generer (deja presents)")
            return

        layout = BuildingLayout(
            name=existing_name,
            grid_size_m=existing.grid_size_m,
            snap_enabled=existing.snap_enabled,
            units=existing.units,
            walls=preserved["walls"],
            doors=preserved["doors"],
            zones=preserved["zones"],
            assets=existing.assets + new_assets,
            workstations=existing.workstations + new_workstations,
            operators=existing.operators[:],
            transport_links=preserved["transport_links"],
            dimensions=preserved["dimensions"],
            origin=existing.origin,
            metadata=existing.metadata.copy(),
        )

        self.layout_view.set_layout(layout)
        self.set_view_mode(ViewMode.LAYOUT_2D)
        self.bottom_bar.terminal.log(
            f"Layout 2D enrichi: {len(new_assets)} machine(s), "
            f"{len(new_workstations)} poste(s) de travail places dans {bounds['label']} "
            f"(total {len(layout.assets)} assets, {len(layout.workstations)} postes)"
        )

    def _add_node_from_palette(self, node_type: str):
        offset = self._palette_click_counter * 30
        self._palette_click_counter += 1
        center = self.editor.mapToScene(self.editor.viewport().rect().center())
        pos = center + QPointF(offset - 150, offset - 60)
        self.editor.add_node(node_type, pos)

    def _generate_transport_links(self):
        """Génère les liens de transport depuis les edges de la vue logique."""
        edges = self.editor.workflow.get("edges", [])
        nodes = self.editor.workflow.get("nodes", [])
        if not edges:
            self.bottom_bar.terminal.log("Aucun edge dans la vue logique")
            return

        node_map = {n["id"]: n for n in nodes}

        # Build asset lookup: d'abord par source_node, puis par nom
        asset_by_source: dict[str, PhysicalAsset] = {}
        asset_by_name: dict[str, list[PhysicalAsset]] = {}
        for asset in self.layout_view.layout_data.assets:
            src = asset.metadata.get("source_node", "")
            if src:
                asset_by_source[src] = asset
            name_key = asset.name.lower().strip()
            asset_by_name.setdefault(name_key, []).append(asset)

        # Build workstation lookup
        ws_by_source: dict[str, WorkstationLayout] = {}
        for ws in self.layout_view.layout_data.workstations:
            src = ws.metadata.get("source_node", "")
            if src:
                ws_by_source[src] = ws

        def _find_asset(node_id: str) -> PhysicalAsset | None:
            a = asset_by_source.get(node_id)
            if a:
                return a
            node = node_map.get(node_id)
            if node:
                candidates = asset_by_name.get(node["title"].lower().strip(), [])
                if candidates:
                    return candidates[0]
                cfg_name = node.get("config", {}).get("name", "")
                if cfg_name:
                    candidates = asset_by_name.get(cfg_name.lower().strip(), [])
                    if candidates:
                        return candidates[0]
            return None

        def _find_position(node_id: str) -> Vector2D | None:
            a = _find_asset(node_id)
            if a:
                return a.position
            ws = ws_by_source.get(node_id)
            if ws:
                return ws.position
            return None

        def _find_entity_id(node_id: str) -> str | None:
            a = _find_asset(node_id)
            if a:
                return a.id
            ws = ws_by_source.get(node_id)
            if ws:
                return ws.id
            return None

        count = 0
        new_links = []
        edge_mode_map = {
            "conveyor": TransportMode.CONVEYOR,
            "agv": TransportMode.AGV,
            "forklift": TransportMode.FORKLIFT,
        }
        for edge in edges:
            from_id, to_id = edge[0], edge[1]
            src_pos = _find_position(from_id)
            dst_pos = _find_position(to_id)
            if src_pos is None or dst_pos is None:
                continue
            src_entity = _find_entity_id(from_id)
            dst_entity = _find_entity_id(to_id)
            if src_entity is None or dst_entity is None:
                continue

            edge_type = edge[2] if len(edge) > 2 else "default"
            mode = edge_mode_map.get(edge_type, TransportMode.MANUAL)

            pts = [Vector2D(src_pos.x, src_pos.y), Vector2D(dst_pos.x, dst_pos.y)]
            link = TransportLink(
                id=f"flow_{from_id}_{to_id}",
                source_id=src_entity,
                target_id=dst_entity,
                transport_mode=mode,
                path_points=pts,
            )
            link.calculate_distance()
            new_links.append(link)
            count += 1

        if not new_links:
            self.bottom_bar.terminal.log(
                "Aucun lien genere: verifiez que les assets ont un source_node ou un nom correspondant aux noeuds logiques"
            )
            return

        self.layout_view.layout_data.transport_links = new_links
        self.layout_view.rebuild_scene()
        self.layout_view.building_changed.emit()
        self.bottom_bar.terminal.log(
            f"Liens de transport generes: {count} (sur {len(edges)} edges)"
        )

    def _toggle_flow_simulation(self, checked: bool):
        if checked:
            if not self.layout_view.layout_data.transport_links:
                self.bottom_bar.terminal.log("Aucun lien de transport — cliquez d'abord sur 'Generer flux'")
                self.btn_flow_sim.setChecked(False)
                return
            self.layout_view.start_flow_animation()
            self.btn_flow_sim.setText("⏹ Flux")
            self.bottom_bar.terminal.log("Animation flux matiere demarree")
        else:
            self.layout_view.stop_flow_animation()
            self.btn_flow_sim.setText("▶ Flux")
            self.bottom_bar.terminal.log("Animation flux matiere arretee")

    def insert_asset_from_palette(self, asset_type: str, category: AssetCategory):
        clearances = TextileLayoutStandards.get_machine_clearance(asset_type)
        asset = PhysicalAsset(
            id=f"{asset_type}_{int(time.time()*1000)%10000}",
            name=asset_type.replace("_", " ").title(),
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
            metadata={"clearances": clearances},
        )
        self.layout_view.set_pending_asset(asset)
        self.set_view_mode(ViewMode.LAYOUT_2D)
        self.bottom_bar.terminal.log(f"Prêt à placer: {asset.name} - Cliquez dans la vue 2D")

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def show_shortcuts(self):
        shortcuts = """
        <b>Raccourcis clavier :</b><br/><br/>
        <b>Navigation :</b><br/>
        C — Centrer la vue<br/>
        A — Ajuster la selection<br/>
        F — Ajuster tout<br/>
        Molette + Ctrl — Zoom<br/><br/>
        <b>Edition :</b><br/>
        Ctrl+Z / Ctrl+Y — Annuler / Retablir<br/>
        Ctrl+C / Ctrl+V / Ctrl+X — Copier / Coller / Couper<br/>
        Ctrl+D — Dupliquer<br/>
        Suppr — Supprimer<br/><br/>
        <b>Alignement :</b><br/>
        H — Aligner horizontalement<br/>
        V — Aligner verticalement<br/><br/>
        <b>Vues :</b><br/>
        1 — Vue Logique<br/>
        2 — Implantation 2D<br/>
        3 — Vue 3D<br/>
        """
        QMessageBox.information(self, "Raccourcis clavier", shortcuts)

    def show_about(self):
        QMessageBox.about(self, "A propos",
            "<h3>Textile Line Balancer v2.0</h3>"
            "<p>Digital Factory Suite pour l'industrie textile</p>"
            "<p>Equilibrage de lignes, Implantation 2D, Simulation 3D</p>"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self.bottom_bar.close_runner()
        event.accept()
