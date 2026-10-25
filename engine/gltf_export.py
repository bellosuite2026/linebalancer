"""
Exportation d'un BuildingLayout au format glTF 2.0 (.gltf).

Générateur autonome (sans dépendance externe) : le buffer binaire est
encodé en base64 et inclus directement dans le JSON du .gltf, ce qui
produit un fichier unique et portable.

Pour chaque entité du layout une primitive 3D est créée :
  - PhysicalAsset / WorkstationLayout : boîte (width x depth x height)
  - WallSegment                    : boîte mince le long du segment
  - Zone                           : prisme extrudé d'un polygone 2D
"""
from __future__ import annotations

import base64
import json
import math
import struct
from typing import Any, Dict, List, Tuple

from engine.models_v2 import (
    BuildingLayout, PhysicalAsset, WallSegment, Zone, WorkstationLayout,
)


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> Tuple[float, float, float, float]:
    """Convertit un code hex (#rrggbb ou #rrggbbaa) en tuple RGBA 0..1."""
    if not hex_color:
        return (0.55, 0.63, 0.98, alpha)
    h = hex_color.lstrip("#")
    if len(h) >= 6:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    else:
        r = g = b = 0.55
    return (r, g, b, alpha)


def _box_mesh(cx: float, cy: float, w: float, d: float, h: float) -> Tuple[List[float], List[int]]:
    """Boîte centrée en (cx, cy) sur le plan XZ, de la base y=0 au sommet y=h.

    Retourne (positions flat xyz, faces triangulaires).
    """
    hw, hd = w / 2.0, d / 2.0
    # 8 sommets : (x, y, z) avec z = profondeur (plan), y = hauteur
    verts: List[Tuple[float, float, float]] = [
        (cx - hw, 0.0, cy - hd), (cx + hw, 0.0, cy - hd),
        (cx + hw, 0.0, cy + hd), (cx - hw, 0.0, cy + hd),
        (cx - hw, h, cy - hd), (cx + hw, h, cy - hd),
        (cx + hw, h, cy + hd), (cx - hw, h, cy + hd),
    ]
    flat = [v for p in verts for v in p]
    faces = [
        0, 1, 2, 0, 2, 3,    # base
        4, 6, 5, 4, 7, 6,    # haut
        0, 3, 7, 0, 7, 4,    # côté -x
        1, 5, 6, 1, 6, 2,    # côté +x
        3, 2, 6, 3, 6, 7,    # côté +z
        0, 4, 5, 0, 5, 1,    # côté -z
    ]
    return flat, faces


def _rotated_box(cx: float, cy: float, w: float, d: float, h: float,
                 rot_deg: float) -> Tuple[List[float], List[int]]:
    """Boîte avec rotation autour de l'axe Y (plan) centrée en (cx, cy)."""
    hw, hd = w / 2.0, d / 2.0
    a = math.radians(rot_deg)
    ca, sa = math.cos(a), math.sin(a)

    def rot(x: float, z: float) -> Tuple[float, float]:
        # rotation dans le plan XZ
        return (cx + x * ca - z * sa, cy + x * sa + z * ca)

    corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    base = [rot(x, z) for (x, z) in corners]
    top = [(x, h, z) for (x, z) in base]
    pts = base + top
    flat = [p for v in pts for p in v]
    faces = [
        0, 1, 2, 0, 2, 3,
        4, 6, 5, 4, 7, 6,
        0, 3, 7, 0, 7, 4,
        1, 5, 6, 1, 6, 2,
        3, 2, 6, 3, 6, 7,
        0, 4, 5, 0, 5, 1,
    ]
    return flat, faces


def _wall_mesh(wall: WallSegment) -> Tuple[List[float], List[int]]:
    """Boîte mince le long d'un segment mur (épaisseur ~thickness_m)."""
    sx, sy = wall.start.x, wall.start.y
    ex, ey = wall.end.x, wall.end.y
    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return [], []
    nx, ny = -dy / length, dx / length  # normale unitaire
    t = getattr(wall, "thickness_m", 0.2) or 0.2
    h = wall.height_m or 3.0
    ht = t / 2.0

    def corner(along: float, off: float, y: float) -> Tuple[float, float, float]:
        x = sx + dx * along + nx * off
        z = sy + dy * along + ny * off
        return (x, y, z)

    verts = [
        corner(0.0, -ht, 0.0), corner(1.0, -ht, 0.0),
        corner(1.0, ht, 0.0), corner(0.0, ht, 0.0),
        corner(0.0, -ht, h), corner(1.0, -ht, h),
        corner(1.0, ht, h), corner(0.0, ht, h),
    ]
    flat = [v for p in verts for v in p]
    faces = [
        0, 1, 2, 0, 2, 3,
        4, 6, 5, 4, 7, 6,
        0, 3, 7, 0, 7, 4,
        1, 5, 6, 1, 6, 2,
        3, 2, 6, 3, 6, 7,
        0, 4, 5, 0, 5, 1,
    ]
    return flat, faces


def _zone_prism(zone: Zone, height: float = 0.2) -> Tuple[List[float], List[int]]:
    """Prisme extrudé d'un polygone 2D (base y=0, sommet y=height)."""
    verts = zone.vertices
    n = len(verts)
    if n < 3:
        return [], []
    flat: List[float] = []
    # sommets de base puis de sommet
    for v in verts:
        flat.extend([v.x, 0.0, v.y])
    for v in verts:
        flat.extend([v.x, height, v.y])
    faces: List[int] = []
    # base (sens inverse)
    for i in range(1, n - 1):
        faces.extend([0, i + 1, i])
    # haut
    for i in range(1, n - 1):
        faces.extend([n, n + i, n + i + 1])
    # côtés
    for i in range(n):
        j = (i + 1) % n
        faces.extend([i, j, n + j, i, n + j, n + i])
    return flat, faces


def export_layout_to_gltf(building: BuildingLayout, path: str) -> str:
    """Exporte un BuildingLayout vers un fichier glTF 2.0.

    Retourne le chemin du fichier généré.
    """
    meshes: List[Dict[str, Any]] = []
    nodes: List[Dict[str, Any]] = []
    materials: List[Dict[str, Any]] = []

    def add_primitive(flat: List[float], faces: List[int], hex_color: str,
                      alpha: float = 1.0):
        if not flat or not faces:
            return
        mat_idx = len(materials)
        r, g, b, a = _hex_to_rgba(hex_color, alpha)
        materials.append({
            "name": f"mat_{mat_idx}",
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b, a],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.8,
            },
            "doubleSided": True,
        })
        # sommets float32, indices uint32
        v_bytes = b"".join(struct.pack("<f", v) for v in flat)
        i_bytes = b"".join(struct.pack("<I", idx) for idx in faces)
        meshes.append({
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1,
                "material": mat_idx,
                "mode": 4,
            }],
            "name": f"mesh_{len(meshes)}",
        })
        # Le node pointe vers le mesh ; les coords sont déjà en monde
        nodes.append({"mesh": len(meshes) - 1, "name": f"node_{len(nodes)}"})
        # On stocke les buffers par mesh (1 buffer / mesh) pour simplifier
        return v_bytes, i_bytes

    # Construction des primitives + collecte des buffers
    buffers_data: List[Tuple[bytes, bytes]] = []

    # Assets
    for asset in building.assets:
        flat, faces = _rotated_box(
            asset.position.x, asset.position.y,
            asset.width_m, asset.depth_m, asset.height_m,
            asset.rotation_deg,
        )
        res = add_primitive(flat, faces, getattr(asset, "color_3d", "#8da2fb"))
        if res:
            buffers_data.append(res)

    # Postes de travail
    for ws in building.workstations:
        flat, faces = _rotated_box(
            ws.position.x, ws.position.y,
            ws.width_m, ws.depth_m, 1.0, ws.rotation_deg,
        )
        res = add_primitive(flat, faces, "#6366f1")
        if res:
            buffers_data.append(res)

    # Murs
    for wall in building.walls:
        flat, faces = _wall_mesh(wall)
        res = add_primitive(flat, faces, getattr(wall, "color", "#94a3b8"))
        if res:
            buffers_data.append(res)

    # Zones (prismes translucides)
    for zone in building.zones:
        flat, faces = _zone_prism(zone, height=0.2)
        res = add_primitive(flat, faces, zone.color, alpha=0.35)
        if res:
            buffers_data.append(res)

    # Assemblage des buffers (1 buffer par primitive)
    buffers = []
    buffer_views = []
    accessors = []
    bin_cursor = 0
    for (v_bytes, i_bytes) in buffers_data:
        # alignement 4 octets pour les vues
        if bin_cursor % 4 != 0:
            pad = 4 - (bin_cursor % 4)
            v_bytes = b"\x00" * pad + v_bytes
            bin_cursor += pad
        v_offset = bin_cursor
        v_len = len(v_bytes)
        bin_cursor += v_len
        if bin_cursor % 4 != 0:
            pad = 4 - (bin_cursor % 4)
            i_bytes = b"\x00" * pad + i_bytes
            bin_cursor += pad
        i_offset = bin_cursor
        i_len = len(i_bytes)
        bin_cursor += i_len

        buffers.append(v_bytes + i_bytes)
        # POSITION bufferView
        buffer_views.append({
            "buffer": len(buffers) - 1,
            "byteOffset": v_offset,
            "byteLength": v_len,
            "target": 34962,  # ARRAY_BUFFER
        })
        pos_bv = len(buffer_views) - 1
        # indices bufferView
        buffer_views.append({
            "buffer": len(buffers) - 1,
            "byteOffset": i_offset,
            "byteLength": i_len,
            "target": 34963,  # ELEMENT_ARRAY_BUFFER
        })
        idx_bv = len(buffer_views) - 1

        nv = v_len // 12  # float32 * 3
        accessor_pos = {
            "bufferView": pos_bv,
            "componentType": 5126,  # FLOAT
            "count": nv,
            "type": "VEC3",
            "min": [0, 0, 0],
            "max": [1, 1, 1],
        }
        accessors.append(accessor_pos)
        accessor_idx = {
            "bufferView": idx_bv,
            "componentType": 5125,  # UNSIGNED_INT
            "count": i_len // 4,
            "type": "SCALAR",
        }
        accessors.append(accessor_idx)

    # Les accessors 0/1 de chaque mesh doivent correspondre dans l'ordre
    # add_primitive a empilé mesh puis node ; on ré-indexe proprement :
    # reconstruct meshes primitives avec les bons accessors.
    # (Ordre : pour chaque primitive -> POSITION accessor pair, indices impair)
    rebuilt_meshes = []
    acc_idx = 0
    for m in meshes:
        prim = dict(m["primitives"][0])
        prim["attributes"] = {"POSITION": acc_idx}
        prim["indices"] = acc_idx + 1
        rebuilt_meshes.append({"primitives": [prim], "name": m["name"]})
        acc_idx += 2

    # Buffers : on a un buffer par primitive mais ses 2 vues pointent dedans.
    # On référence chaque buffer avec sa taille totale.
    gltf_buffers = []
    for b in buffers:
        gltf_buffers.append({
            "byteLength": len(b),
            "uri": "data:application/octet-stream;base64," + base64.b64encode(b).decode("ascii"),
        })

    gltf = {
        "asset": {"version": "2.0", "generator": "Textile Line Balancer"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(rebuilt_meshes)))}],
        "nodes": [{"mesh": i, "name": f"node_{i}"} for i in range(len(rebuilt_meshes))],
        "meshes": rebuilt_meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": gltf_buffers,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(gltf, f, indent=2, ensure_ascii=False)
    return path


# Ré-export pour compat typage
__all__ = ["export_layout_to_gltf"]
