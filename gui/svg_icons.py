"""
Module pour charger les icônes SVG des machines et nœuds.
"""
from pathlib import Path
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import QSize
from PySide6.QtSvg import QSvgRenderer

# Chemin vers les assets
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Mapping type de machine -> fichier SVG
MACHINE_SVG_MAP = {
    "piqueuse_plate": "machines/piqueuse_plate.svg",
    "piqueuse_2_aiguilles": "machines/piqueuse_2_aiguilles.svg",
    "surjeteuse_3_fils": "machines/surjeteuse_3_fils.svg",
    "surjeteuse_4_fils": "machines/surjeteuse_4_fils.svg",
    "surjeteuse_5_fils": "machines/surjeteuse_5_fils.svg",
    "piqueuse_boutonniere": "machines/piqueuse_boutonniere.svg",
    "piqueuse_boutonniere_simple": "machines/piqueuse_boutonniere_simple.svg",
    "piqueuse_bouton": "machines/piqueuse_bouton.svg",
    "piqueuse_ourlet": "machines/piqueuse_ourlet.svg",
    "piqueuse_galon": "machines/piqueuse_galon.svg",
    "presse_vapeur": "machines/presse_vapeur.svg",
    "repasseuse_tunnel": "machines/repasseuse_tunnel.svg",
    "table_controle": "machines/table_controle.svg",
    "table_travail": "machines/table_travail.svg",
    "fer_vapeur": "machines/fer_vapeur.svg",
    "decoupe_laser": "machines/decoupe_laser.svg",
    "rack_palettes_3n": "machines/rack_palettes_3n.svg",
    "rack_palettes_4n": "machines/rack_palettes_4n.svg",
    "rack_cantilever": "machines/rack_cantilever.svg",
    "convoyeur_bande": "machines/convoyeur_bande.svg",
    "agv_station": "machines/agv_station.svg",
}

# Mapping type de nœud -> fichier SVG (pour les types de nœuds génériques)
NODE_TYPE_SVG_MAP = {
    "operation": "machines/piqueuse_plate.svg",
    "workstation": "machines/table_travail.svg",
    "worker": "workers/worker_default.svg",
    "machine": "machines/piqueuse_plate.svg",
    "section": "machines/table_controle.svg",
}

# Cache pour les pixmaps chargés
_PIXMAP_CACHE = {}


def _load_pixmap(svg_path: str, size: int | QSize = 64) -> QPixmap:
    """Charge un SVG et retourne un QPixmap de la taille demandée."""
    # Handle both int and QSize
    if isinstance(size, QSize):
        w, h = size.width(), size.height()
    else:
        w = h = size
    cache_key = f"{svg_path}_{w}x{h}"
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]
    
    full_path = Path(__file__).resolve().parent / "assets" / svg_path
    if not full_path.exists():
        # Fallback: créer un pixmap vide
        pixmap = QPixmap(w, h)
        pixmap.fill()
        _PIXMAP_CACHE[cache_key] = pixmap
        return pixmap
    
    renderer = QSvgRenderer(str(full_path))
    pixmap = QPixmap(w, h)
    pixmap.fill()
    
    from PySide6.QtGui import QPainter
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    
    _PIXMAP_CACHE[cache_key] = pixmap
    return pixmap


def get_machine_pixmap(machine_type: str, size: int = 64) -> QPixmap:
    """Retourne le pixmap pour un type de machine."""
    svg_path = MACHINE_SVG_MAP.get(machine_type, "machines/piqueuse_plate.svg")
    return _load_pixmap(svg_path, size)


def get_node_type_pixmap(node_type: str, size: int = 64) -> QPixmap:
    """Retourne le pixmap pour un type de nœud."""
    svg_path = NODE_TYPE_SVG_MAP.get(node_type, "machines/piqueuse_plate.svg")
    return _load_pixmap(svg_path, size)


def get_machine_icon(machine_type: str, size: int = 32) -> QIcon:
    """Retourne une QIcon pour un type de machine."""
    pixmap = get_machine_pixmap(machine_type, size)
    return QIcon(pixmap)


def get_node_type_icon(node_type: str, size: int = 32) -> QIcon:
    """Retourne une QIcon pour un type de nœud."""
    pixmap = get_node_type_pixmap(node_type, size)
    return QIcon(pixmap)


def clear_cache():
    """Vide le cache des pixmaps."""
    global _PIXMAP_CACHE
    _PIXMAP_CACHE.clear()


def preload_all(size: int = 64):
    """Précharge tous les pixmaps."""
    for machine_type in MACHINE_SVG_MAP:
        get_machine_pixmap(machine_type, size)
    for node_type in NODE_TYPE_SVG_MAP:
        get_node_type_pixmap(node_type, size)
    print(f"✅ {len(MACHINE_SVG_MAP) + len(NODE_TYPE_SVG_MAP)} icônes préchargées ({size}px)")