"""
Thème visuel et constantes partagées de l'application.
Source unique pour les couleurs, styles et icônes.
"""

from PySide6.QtGui import QColor

from engine.models_v2 import AssetCategory, WallType

# ============================================================
# COULEURS
# ============================================================

C_BG = "#0b1020"
C_CANVAS = "#0f172a"
C_PANEL = "#111827"
C_CARD = "#182235"
C_CARD_HOVER = "#251c23"
C_BORDER = "#263244"
C_BORDER_STRONG = "#4a5872"
C_TEXT = "#e5e7eb"
C_MUTED = "#94a3b8"
C_ACCENT = "#ff6d5a"
C_ACCENT2 = "#8da2fb"
C_DANGER = "#f97066"
C_WARN = "#f79009"
C_SUCCESS = "#12b76a"
C_VA = "#12b76a"
C_NVA = "#f97066"
C_ATTENTE = "#f79009"

NODE_TYPE_COLORS = {
    "operation": "#2e90fa",
    "workstation": "#7a5af8",
    "worker": "#12b76a",
    "machine": "#f79009",
    "section": "#06aed4",
    "layout_machine": "#f79009",
    "layout_section": "#06aed4",
    "layout_flow": "#ff6d5a",
    "wall": "#6b7280",
    "door": "#8da2fb",
    "zone_circulation": "#8da2fb",
    "rack": "#f79009",
    "conveyor": "#2e90fa",
    "agv_path": "#8da2fb",
}

STATUS_COLORS = {
    "idle": "#64748b",
    "running": "#8da2fb",
    "success": "#12b76a",
    "error": "#f97066",
    "warning": "#f79009",
}

# Palette de couleurs par POSTE (station) pour la vue logique équilibrée.
# Distincte et bien contrastée pour différencier visuellement les postes.
STATION_COLORS = [
    "#2e90fa",  # bleu
    "#12b76a",  # vert
    "#f79009",  # orange
    "#7a5af8",  # violet
    "#06aed4",  # cyan
    "#f97066",  # rouge corail
    "#e879c9",  # rose
    "#a3e635",  # lime
    "#fbbf24",  # ambre
    "#22d3ee",  # turquoise
    "#c084fc",  # lavande
    "#fb7185",  # rose fuchsia
]


def station_color(station: int) -> str:
    """Retourne la couleur d'un poste (1-indexé), cyclique si > palettes."""
    if station is None:
        return C_MUTED
    try:
        idx = int(station) - 1
    except (TypeError, ValueError):
        return C_MUTED
    if idx < 0:
        idx = 0
    return STATION_COLORS[idx % len(STATION_COLORS)]

NODE_ICONS = {
    "operation": "⚙️",
    "workstation": "🏭",
    "worker": "👷",
    "machine": "🔧",
    "section": "📦",
    "layout_machine": "🏭",
    "layout_section": "📦",
    "layout_flow": "➡️",
    "wall": "🧱",
    "door": "🚪",
    "zone_circulation": "🛣️",
    "rack": "📦",
    "conveyor": "🔄",
    "agv_path": "🤖",
}

ASSET_3D_COLORS = {
    AssetCategory.MACHINE: (0.97, 0.43, 0.35, 1.0),
    AssetCategory.CONVEYOR: (0.18, 0.56, 0.98, 1.0),
    AssetCategory.RACK: (0.65, 0.54, 0.98, 1.0),
    AssetCategory.AGV: (0.55, 0.64, 0.98, 1.0),
    AssetCategory.WORKSTATION: (0.07, 0.72, 0.41, 1.0),
    AssetCategory.SAFETY: (0.98, 0.44, 0.40, 1.0),
    AssetCategory.STRUCTURAL: (0.42, 0.45, 0.51, 1.0),
}

WALL_3D_COLORS = {
    WallType.EXTERIOR: (0.29, 0.33, 0.36, 1.0),
    WallType.INTERIOR: (0.42, 0.45, 0.51, 1.0),
    WallType.COLUMN: (0.25, 0.28, 0.32, 1.0),
}

# ============================================================
# DIMENSIONS NŒUDS
# ============================================================

NODE_W = 240
NODE_H = 100
PORT_R = 8
PORT_Y = 50

# ============================================================
# STYLESHEET GLOBAL
# ============================================================

STYLESHEET = """
* { font-family: "Segoe UI Variable", "Segoe UI", sans-serif; }
QMainWindow, QWidget#root { background: #0b1020; }
QWidget { color: #e5e7eb; font-size: 13px; background: #0b1020; }
QLabel#brandMark {
    background: transparent; color: #ff6d5a; font-weight: 900;
    border: 2px solid #ff6d5a; border-radius: 10px; padding: 3px 7px; font-size: 14px;
}
QLabel#brandTitle { color: #e5e7eb; font-size: 18px; font-weight: 750; }
QLabel#versionBadge {
    color: #94a3b8; background: #182235; border: 1px solid #263244;
    border-radius: 8px; padding: 2px 8px; font-size: 11px;
}
QLabel#panelHeading { color: #94a3b8; font-size: 11px; font-weight: 800; letter-spacing: 1px; }
QFrame#panel { background: #111827; border: 1px solid #263244; border-radius: 16px; }
QFrame#topbar { background: #111827; border-bottom: 1px solid #263244; }
QFrame#hsep { background: #263244; max-height: 1px; min-height: 1px; }
QSplitter { background: #0b1020; }
QSplitter::handle { background: #0b1020; width: 2px; height: 4px; }
QSplitter::handle:hover { background: #ff6d5a; }

QPushButton {
    background: #111827; border: 1px solid #263244; border-radius: 9px;
    padding: 8px 14px; color: #e5e7eb; font-weight: 600;
}
QPushButton:hover { background: #182235; border-color: #4a5872; }
QPushButton#primary { background: #ff6d5a; color: white; border: none; font-weight: 800; }
QPushButton#primary:hover { background: #ff826f; }
QPushButton#primary:disabled { background: #5a2b2c; color: #9f6a66; }
QPushButton#danger { background: #111827; border: 1px solid #263244; }
QPushButton#danger:hover { border-color: #f97066; color: #f97066; }
QPushButton#palette {
    text-align: left; padding: 10px 12px; font-weight: 650;
    background: transparent; border-color: transparent; border-radius: 10px;
}
QPushButton#palette:hover { background: #251c23; border-color: #6b363c; color: #ffad9f; }
QPushButton#toolButton {
    background: #111827; border: 1px solid #263244; border-radius: 6px;
    padding: 6px 10px; font-size: 12px;
}
QPushButton#toolButton:hover { background: #182235; border-color: #8da2fb; }
QPushButton#toolButton:checked { background: #8da2fb; color: white; border-color: #8da2fb; }

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background: #111827; border: 1px solid #263244; border-radius: 9px;
    padding: 6px 9px; selection-background-color: #8da2fb;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus { border-color: #8da2fb; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #111827; border: 1px solid #263244; selection-background-color: #24304a;
    color: #e5e7eb; outline: none;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 6px; border: 1px solid #263244; background: #111827; }
QCheckBox::indicator:checked { background: #ff6d5a; border-color: #ff6d5a; }

QSlider::groove:horizontal { height: 5px; background: #253145; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #ff6d5a; border-radius: 3px; }
QSlider::handle:horizontal { background: #111827; border: 1px solid #ff6d5a; width: 15px; height: 15px; margin: -6px 0; border-radius: 8px; }

QListWidget { background: transparent; border: none; }
QListWidget::item {
    background: #182235; border: 1px solid #263244; border-radius: 10px;
    padding: 7px 10px; margin-bottom: 6px;
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #344258; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QGraphicsView { border: 1px solid #263244; border-radius: 16px; background: #0f172a; }

QLabel#metric { font-size: 13px; color: #94a3b8; }
QLabel#metricValue { font-size: 15px; font-weight: 850; color: #e5e7eb; }
QPlainTextEdit#terminal {
    font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
    background: #111827; color: #e5e7eb; border-color: #263244;
}
QTableWidget {
    background: #111827; border: 1px solid #263244; border-radius: 8px;
    gridline-color: #263244; selection-background-color: #24304a;
}
QHeaderView::section {
    background: #182235; color: #94a3b8; padding: 6px; border: 1px solid #263244;
    font-weight: 700; font-size: 11px;
}
QTabWidget::pane { border: 1px solid #263244; border-radius: 8px; background: #111827; }
QTabBar::tab {
    background: #182235; color: #94a3b8; padding: 8px 16px; margin-right: 4px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 600;
}
QTabBar::tab:selected { background: #ff6d5a; color: white; }
QTabBar::tab:hover { background: #251c23; color: #e5e7eb; }
QGroupBox {
    border: 1px solid #263244; border-radius: 8px; margin-top: 12px; padding-top: 8px;
    font-weight: 600; color: #e5e7eb;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QTreeWidget { background: #111827; border: 1px solid #263244; border-radius: 8px; }
QTreeWidget::item { padding: 4px; }
QTreeWidget::item:selected { background: #ff6d5a; color: white; }
QProgressBar {
    border: 1px solid #263244; border-radius: 6px; background: #111827;
    text-align: center; color: #e5e7eb;
}
QProgressBar::chunk { background: #ff6d5a; border-radius: 6px; }
QDockWidget { titlebar-close-icon: url(close.png); titlebar-normal-icon: url(undock.png); }
QDockWidget::title { background: #111827; color: #e5e7eb; padding: 6px; font-weight: 600; }
QStatusBar { background: #111827; border-top: 1px solid #263244; color: #94a3b8; }

QMenuBar {
    background: #111827; color: #e5e7eb; border-bottom: 1px solid #263244;
    padding: 4px 8px; font-size: 13px;
}
QMenuBar::item {
    background: transparent; padding: 6px 12px; border-radius: 6px; color: #e5e7eb;
}
QMenuBar::item:selected { background: #251c23; color: #e5e7eb; }
QMenuBar::item:pressed { background: #ff6d5a; color: white; }

QMenu {
    background: #111827; border: 1px solid #263244; border-radius: 8px;
    padding: 4px; color: #e5e7eb;
}
QMenu::item {
    background: transparent; padding: 8px 24px 8px 16px; border-radius: 6px; color: #e5e7eb;
}
QMenu::item:selected { background: #251c23; color: #e5e7eb; }
QMenu::separator { height: 1px; background: #263244; margin: 4px 8px; }
QMenu::icon { padding-left: 4px; }

QToolBar { background: #111827; border: none; spacing: 4px; padding: 4px; }
QToolButton { background: #182235; border: 1px solid #263244; border-radius: 6px;
    padding: 6px 10px; color: #e5e7eb; font-size: 12px; }
QToolButton:hover { background: #251c23; border-color: #ff6d5a; }
QToolButton:checked { background: #8da2fb; color: white; border-color: #8da2fb; }
QToolButton:pressed { background: #ff6d5a; color: white; }
"""
