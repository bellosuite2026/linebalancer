"""
Modèles de données étendus pour Digital Factory Suite (3 Vues interconnectées).
Architecture: Vue Logique (Flow/VSM) <-> Vue Implantation 2D (Layout) <-> Vue 3D Temps Réel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from pathlib import Path
import json


# ============================================================
# ENUMS DE BASE
# ============================================================

class ViewMode(str, Enum):
    LOGICAL = "logical"           # Vue Logique (Flow/VSM)
    LAYOUT_2D = "layout_2d"       # Vue Implantation 2D
    VIEW_3D = "view_3d"           # Vue 3D Temps Réel


class AssetCategory(str, Enum):
    MACHINE = "machine"
    CONVEYOR = "conveyor"
    RACK = "rack"
    AGV = "agv"
    WORKSTATION = "workstation"
    SAFETY = "safety"
    STRUCTURAL = "structural"


class WallType(str, Enum):
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    COLUMN = "column"


class ZoneType(str, Enum):
    CIRCULATION_PEDESTRIAN = "circulation_pedestrian"
    CIRCULATION_FORKLIFT = "circulation_forklift"
    CIRCULATION_AGV = "circulation_agv"
    STORAGE = "storage"
    WORK_AREA = "work_area"
    OFFICE = "office"


class TransportMode(str, Enum):
    MANUAL = "manual"
    CONVEYOR = "conveyor"
    AGV = "agv"
    FORKLIFT = "forklift"


class TaskType(str, Enum):
    VA = "VA"              # Valeur Ajoutée
    NVA = "NVA"            # Non Valeur Ajoutée (Gaspillage)
    ATTENTE = "ATTENTE"    # Temps d'attente


class OperatorRole(str, Enum):
    OPERATOR = "operator"
    LOGISTICIAN = "logistician"
    SUPERVISOR = "supervisor"
    MAINTENANCE = "maintenance"


class AnimationState(str, Enum):
    IDLE = "idle"
    WALK = "walk"
    WORK = "work"
    TRANSPORT = "transport"


# ============================================================
# GÉOMÉTRIE
# ============================================================

@dataclass
class Vector2D:
    """Position 2D en mètres."""
    x: float = 0.0
    y: float = 0.0
    
    def to_tuple(self) -> tuple:
        return (self.x, self.y)
    
    def distance_to(self, other: "Vector2D") -> float:
        return ((self.x - other.x)**2 + (self.y - other.y)**2)**0.5
    
    def __add__(self, other: "Vector2D") -> "Vector2D":
        return Vector2D(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other: "Vector2D") -> "Vector2D":
        return Vector2D(self.x - other.x, self.y - other.y)
    
    def __mul__(self, scalar: float) -> "Vector2D":
        return Vector2D(self.x * scalar, self.y * scalar)
    
    def to_qpointf(self):
        from PySide6.QtCore import QPointF
        return QPointF(self.x * 1000, self.y * 1000)  # mm pour Qt
    
    @classmethod
    def from_qpointf(cls, pt, scale=0.001):
        return cls(pt.x() * scale, pt.y() * scale)
    
    def dot(self, other: "Vector2D") -> float:
        return self.x * other.x + self.y * other.y
    
    def cross(self, other: "Vector2D") -> float:
        return self.x * other.y - self.y * other.x
    
    def length(self) -> float:
        return (self.x**2 + self.y**2)**0.5
    
    def normalized(self) -> "Vector2D":
        l = self.length()
        if l < 1e-9:
            return Vector2D(0.0, 0.0)
        return Vector2D(self.x / l, self.y / l)
    
    def angle_deg(self) -> float:
        import math
        return math.degrees(math.atan2(self.y, self.x))
    
    def rotated(self, angle_deg: float) -> "Vector2D":
        import math
        rad = math.radians(angle_deg)
        c, s = math.cos(rad), math.sin(rad)
        return Vector2D(self.x * c - self.y * s, self.x * s + self.y * c)


@dataclass
class Vector3D:
    """Position 3D en mètres."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    
    def to_tuple(self) -> tuple:
        return (self.x, self.y, self.z)


@dataclass
class BoundingBox2D:
    """Boîte englobante 2D alignée aux axes (mètres)."""
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    
    @property
    def width(self) -> float:
        return self.max_x - self.min_x
    
    @property
    def height(self) -> float:
        return self.max_y - self.min_y
    
    @property
    def center(self) -> Vector2D:
        return Vector2D((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)
    
    def contains(self, point: Vector2D) -> bool:
        return self.min_x <= point.x <= self.max_x and self.min_y <= point.y <= self.max_y
    
    def intersects(self, other: "BoundingBox2D") -> bool:
        return not (self.max_x < other.min_x or self.min_x > other.max_x or
                   self.max_y < other.min_y or self.min_y > other.max_y)
    
    def expanded(self, margin: float) -> "BoundingBox2D":
        return BoundingBox2D(
            self.min_x - margin, self.min_y - margin,
            self.max_x + margin, self.max_y + margin
        )


# ============================================================
# ASSETS PHYSIQUES (2D/3D)
# ============================================================

@dataclass
class PhysicalAsset:
    """Asset physique (machine, convoyeur, rack, etc.) avec propriétés 2D/3D."""
    id: str
    name: str
    category: AssetCategory
    asset_type: str              # ex: "piqueuse_plate", "surjeteuse_5_fils", "rack_palettes_3n"
    
    # Dimensions physiques (mètres)
    width_m: float = 1.0
    depth_m: float = 1.0
    height_m: float = 2.0
    
    # Position 2D (Layout)
    position: Vector2D = field(default_factory=Vector2D)
    rotation_deg: float = 0.0
    layer: str = "equipment"     # equipment, structure, circulation, annotation
    
    # Propriétés 3D
    model_3d_path: str = ""      # Chemin vers fichier .gltf/.glb/.ifc
    color_3d: str = "#8da2fb"
    
    # Propriétés fonctionnelles
    machine_type: str = ""       # Pour correspondance avec opérations
    capacity: float = 0.0        # Capacité (pièces/h pour machine, palettes pour rack)
    speed_m_s: float = 0.0       # Vitesse (convoyeur, AGV)
    
    # Contraintes
    fixed: bool = False          # Ne peut pas être déplacé
    locked: bool = False         # Verrouillé par l'utilisateur
    snap_to_grid: bool = True
    
    # Métadonnées
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def bounding_box(self) -> BoundingBox2D:
        """Boîte englobante alignée aux axes (ignore rotation pour simplifier)."""
        hw = self.width_m / 2
        hd = self.depth_m / 2
        return BoundingBox2D(
            self.position.x - hw, self.position.y - hd,
            self.position.x + hw, self.position.y + hd
        )
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "category": self.category.value,
            "asset_type": self.asset_type,
            "width_m": self.width_m, "depth_m": self.depth_m, "height_m": self.height_m,
            "position": {"x": self.position.x, "y": self.position.y},
            "rotation_deg": self.rotation_deg, "layer": self.layer,
            "model_3d_path": self.model_3d_path, "color_3d": self.color_3d,
            "machine_type": self.machine_type, "capacity": self.capacity,
            "speed_m_s": self.speed_m_s, "fixed": self.fixed, "locked": self.locked,
            "snap_to_grid": self.snap_to_grid, "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PhysicalAsset":
        return cls(
            id=data["id"], name=data["name"], category=AssetCategory(data["category"]),
            asset_type=data["asset_type"],
            width_m=data.get("width_m", 1.0), depth_m=data.get("depth_m", 1.0),
            height_m=data.get("height_m", 2.0),
            position=Vector2D(**data.get("position", {"x": 0, "y": 0})),
            rotation_deg=data.get("rotation_deg", 0.0), layer=data.get("layer", "equipment"),
            model_3d_path=data.get("model_3d_path", ""), color_3d=data.get("color_3d", "#8da2fb"),
            machine_type=data.get("machine_type", ""), capacity=data.get("capacity", 0.0),
            speed_m_s=data.get("speed_m_s", 0.0), fixed=data.get("fixed", False),
            locked=data.get("locked", False), snap_to_grid=data.get("snap_to_grid", True),
            metadata=data.get("metadata", {}),
        )


# ============================================================
# STRUCTURE BÂTIMENT
# ============================================================

@dataclass
class WallSegment:
    """Segment de mur (ligne droite)."""
    id: str
    start: Vector2D
    end: Vector2D
    wall_type: WallType = WallType.INTERIOR
    thickness_m: float = 0.2
    height_m: float = 3.0
    layer: str = "structure"
    color: str = "#6b7280"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def length(self) -> float:
        return self.start.distance_to(self.end)
    
    def center(self) -> Vector2D:
        return Vector2D((self.start.x + self.end.x) / 2, (self.start.y + self.end.y) / 2)
    
    def direction(self) -> Vector2D:
        return (self.end - self.start).normalized()
    
    def angle_deg(self) -> float:
        return self.direction().angle_deg()
    
    def set_length(self, new_length: float):
        if new_length < 0.001:
            return
        d = self.direction()
        self.end = self.start + d * new_length
    
    def is_parallel_to(self, other: "WallSegment", tolerance_deg: float = 5.0) -> bool:
        a1 = self.angle_deg()
        a2 = other.angle_deg()
        diff = abs(a1 - a2) % 180.0
        return diff < tolerance_deg or diff > 180.0 - tolerance_deg
    
    def is_perpendicular_to(self, other: "WallSegment", tolerance_deg: float = 5.0) -> bool:
        a1 = self.angle_deg()
        a2 = other.angle_deg()
        diff = abs(a1 - a2) % 90.0
        return diff < tolerance_deg or diff > 90.0 - tolerance_deg
    
    def angle_with(self, other: "WallSegment") -> float:
        d1 = self.direction()
        d2 = other.direction()
        import math
        dot = d1.dot(d2)
        return math.degrees(math.acos(max(-1.0, min(1.0, dot))))
    
    def is_colinear_with(self, other: "WallSegment", tolerance_m: float = 0.1) -> bool:
        if not self.is_parallel_to(other):
            return False
        d = self.direction()
        v = other.start - self.start
        proj = abs(v.dot(d))
        perp_dist = abs(v.cross(d))
        return proj <= self.length() + other.length() and perp_dist < tolerance_m
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "start": {"x": self.start.x, "y": self.start.y},
            "end": {"x": self.end.x, "y": self.end.y},
            "wall_type": self.wall_type.value, "thickness_m": self.thickness_m,
            "height_m": self.height_m, "layer": self.layer, "color": self.color,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "WallSegment":
        return cls(
            id=data["id"],
            start=Vector2D(**data["start"]), end=Vector2D(**data["end"]),
            wall_type=WallType(data.get("wall_type", "interior")),
            thickness_m=data.get("thickness_m", 0.2), height_m=data.get("height_m", 3.0),
            layer=data.get("layer", "structure"), color=data.get("color", "#6b7280"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Door:
    """Porte sur un mur (représentation architecturale)."""
    id: str
    wall_id: str
    position_ratio: float = 0.5     # 0.0 à 1.0 le long du mur
    width_m: float = 1.0
    height_m: float = 2.1
    door_type: str = "swing"        # swing, sliding, rollup
    swing_side: str = "right"       # left, right (pour swing)
    opening_direction: str = "inward"  # inward, outward (pour swing)
    swing_angle_deg: float = 90.0   # angle d'ouverture (swing)
    frame_width_m: float = 0.08     # largeur du cadre de porte
    name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "wall_id": self.wall_id, "position_ratio": self.position_ratio,
            "width_m": self.width_m, "height_m": self.height_m,
            "door_type": self.door_type, "swing_side": self.swing_side,
            "opening_direction": self.opening_direction,
            "swing_angle_deg": self.swing_angle_deg,
            "frame_width_m": self.frame_width_m,
            "name": self.name, "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Door":
        return cls(
            id=data["id"], wall_id=data["wall_id"], position_ratio=data.get("position_ratio", 0.5),
            width_m=data.get("width_m", 1.0), height_m=data.get("height_m", 2.1),
            door_type=data.get("door_type", "swing"),
            swing_side=data.get("swing_side", "right"),
            opening_direction=data.get("opening_direction", "inward"),
            swing_angle_deg=data.get("swing_angle_deg", 90.0),
            frame_width_m=data.get("frame_width_m", 0.08),
            name=data.get("name", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DimensionLayout:
    """Cote linéaire de dimension (Annotation)."""
    id: str
    start: Vector2D
    end: Vector2D
    text_pos: Vector2D
    distance_m: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start": {"x": self.start.x, "y": self.start.y},
            "end": {"x": self.end.x, "y": self.end.y},
            "text_pos": {"x": self.text_pos.x, "y": self.text_pos.y},
            "distance_m": self.distance_m,
            "metadata": self.metadata,
        }
        
    @classmethod
    def from_dict(cls, data: dict) -> "DimensionLayout":
        return cls(
            id=data["id"],
            start=Vector2D(**data["start"]),
            end=Vector2D(**data["end"]),
            text_pos=Vector2D(**data["text_pos"]),
            distance_m=data.get("distance_m", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Zone:
    """Zone délimitée (polygone)."""
    id: str
    name: str
    zone_type: ZoneType
    vertices: List[Vector2D] = field(default_factory=list)
    color: str = "#2c7a7b"
    opacity: float = 0.3
    layer: str = "zones"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.zone_type, ZoneType):
            try:
                self.zone_type = ZoneType(self.zone_type)
            except (ValueError, TypeError):
                self.zone_type = ZoneType.WORK_AREA
    
    def area(self) -> float:
        if len(self.vertices) < 3:
            return 0.0
        area = 0.0
        for i in range(len(self.vertices)):
            j = (i + 1) % len(self.vertices)
            area += self.vertices[i].x * self.vertices[j].y
            area -= self.vertices[j].x * self.vertices[i].y
        return abs(area) / 2.0
    
    def centroid(self) -> Vector2D:
        if not self.vertices:
            return Vector2D()
        n = len(self.vertices)
        if n < 3:
            return Vector2D(sum(v.x for v in self.vertices) / n, sum(v.y for v in self.vertices) / n)
            
        area = 0.0
        cx = 0.0
        cy = 0.0
        for i in range(n):
            p1 = self.vertices[i]
            p2 = self.vertices[(i + 1) % n]
            factor = (p1.x * p2.y - p2.x * p1.y)
            area += factor
            cx += (p1.x + p2.x) * factor
            cy += (p1.y + p2.y) * factor
            
        area = area * 0.5
        if abs(area) < 1e-9:
            return Vector2D(sum(v.x for v in self.vertices) / n, sum(v.y for v in self.vertices) / n)
            
        cx = cx / (6.0 * area)
        cy = cy / (6.0 * area)
        return Vector2D(cx, cy)
    
    def contains_point(self, point: Vector2D) -> bool:
        if len(self.vertices) < 3:
            return False
        inside = False
        for i in range(len(self.vertices)):
            j = (i + 1) % len(self.vertices)
            vi, vj = self.vertices[i], self.vertices[j]
            if ((vi.y > point.y) != (vj.y > point.y)) and \
               (point.x < (vj.x - vi.x) * (point.y - vi.y) / (vj.y - vi.y) + vi.x):
                inside = not inside
        return inside
    
    def bounding_box(self) -> BoundingBox2D:
        if not self.vertices:
            return BoundingBox2D()
        xs = [v.x for v in self.vertices]
        ys = [v.y for v in self.vertices]
        return BoundingBox2D(min(xs), min(ys), max(xs), max(ys))
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "zone_type": self.zone_type.value,
            "vertices": [{"x": v.x, "y": v.y} for v in self.vertices],
            "color": self.color, "opacity": self.opacity, "layer": self.layer,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Zone":
        return cls(
            id=data["id"], name=data["name"], zone_type=ZoneType(data["zone_type"]),
            vertices=[Vector2D(**v) for v in data.get("vertices", [])],
            color=data.get("color", "#2c7a7b"), opacity=data.get("opacity", 0.3),
            layer=data.get("layer", "zones"), metadata=data.get("metadata", {}),
        )


# ============================================================
# RESSOURCES HUMAINES
# ============================================================

@dataclass
class OperatorProfile:
    """Profil opérateur avec anthropométrie et compétences."""
    id: str
    name: str
    avatar_id: str = "default"
    
    # Anthropométrie
    height_m: float = 1.75
    shoulder_width_m: float = 0.45
    reach_radius_m: float = 0.75
    walk_speed_m_s: float = 1.3
    
    # Compétences
    skills: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    efficiency: float = 1.0
    
    # Affectation
    role: OperatorRole = OperatorRole.OPERATOR
    assigned_station_id: str = ""
    assigned_zone_id: str = ""
    is_mobile: bool = False       # Logisticien mobile
    
    # Animation 3D
    animation_state: AnimationState = AnimationState.IDLE
    current_position_3d: Vector3D = field(default_factory=Vector3D)
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "avatar_id": self.avatar_id,
            "height_m": self.height_m, "shoulder_width_m": self.shoulder_width_m,
            "reach_radius_m": self.reach_radius_m, "walk_speed_m_s": self.walk_speed_m_s,
            "skills": self.skills, "certifications": self.certifications,
            "efficiency": self.efficiency, "role": self.role.value,
            "assigned_station_id": self.assigned_station_id,
            "assigned_zone_id": self.assigned_zone_id, "is_mobile": self.is_mobile,
            "animation_state": self.animation_state.value,
            "current_position_3d": {"x": self.current_position_3d.x, "y": self.current_position_3d.y, "z": self.current_position_3d.z},
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "OperatorProfile":
        return cls(
            id=data["id"], name=data["name"], avatar_id=data.get("avatar_id", "default"),
            height_m=data.get("height_m", 1.75), shoulder_width_m=data.get("shoulder_width_m", 0.45),
            reach_radius_m=data.get("reach_radius_m", 0.75), walk_speed_m_s=data.get("walk_speed_m_s", 1.3),
            skills=data.get("skills", []), certifications=data.get("certifications", []),
            efficiency=data.get("efficiency", 1.0), role=OperatorRole(data.get("role", "operator")),
            assigned_station_id=data.get("assigned_station_id", ""),
            assigned_zone_id=data.get("assigned_zone_id", ""), is_mobile=data.get("is_mobile", False),
            animation_state=AnimationState(data.get("animation_state", "idle")),
            current_position_3d=Vector3D(**data.get("current_position_3d", {"x": 0, "y": 0, "z": 0})),
            metadata=data.get("metadata", {}),
        )


# ============================================================
# FLUX DE PROCESSUS (VA/NVA) - YAMAZUMI
# ============================================================

@dataclass
class ProcessTask:
    """Tâche élémentaire pour Yamazumi (VA/NVA/Attente)."""
    id: str
    name: str
    duration_s: float
    task_type: TaskType = TaskType.VA
    description: str = ""
    required_skills: List[str] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    ergonomic_score: float = 0.0        # 0-10 (RULA/REBA)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def color(self) -> str:
        colors = {
            TaskType.VA: "#12b76a",
            TaskType.NVA: "#f97066",
            TaskType.ATTENTE: "#f79009",
        }
        return colors.get(self.task_type, "#94a3b8")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "duration_s": self.duration_s,
            "task_type": self.task_type.value, "description": self.description,
            "required_skills": self.required_skills, "required_tools": self.required_tools,
            "ergonomic_score": self.ergonomic_score, "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProcessTask":
        return cls(
            id=data["id"], name=data["name"], duration_s=data["duration_s"],
            task_type=TaskType(data.get("task_type", "VA")), description=data.get("description", ""),
            required_skills=data.get("required_skills", []), required_tools=data.get("required_tools", []),
            ergonomic_score=data.get("ergonomic_score", 0.0), metadata=data.get("metadata", {}),
        )


@dataclass
class WorkstationLayout:
    """Poste de travail enrichi pour layout + Yamazumi."""
    id: str
    name: str
    position: Vector2D = field(default_factory=Vector2D)
    rotation_deg: float = 0.0
    width_m: float = 2.0
    depth_m: float = 2.0
    
    # Équipements assignés
    asset_ids: List[str] = field(default_factory=list)
    
    # Opérateurs assignés
    operator_ids: List[str] = field(default_factory=list)
    
    # Tâches (Yamazumi)
    tasks: List[ProcessTask] = field(default_factory=list)
    
    # Flux
    input_zone_id: str = ""
    output_zone_id: str = ""
    
    # Calculé
    cycle_time_s: float = 0.0
    va_time_s: float = 0.0
    nva_time_s: float = 0.0
    wait_time_s: float = 0.0
    efficiency: float = 0.0
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_task_time(self) -> float:
        return sum(t.duration_s for t in self.tasks)
    
    @property
    def va_ratio(self) -> float:
        if self.total_task_time == 0:
            return 0.0
        return self.va_time_s / self.total_task_time
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "position": {"x": self.position.x, "y": self.position.y},
            "rotation_deg": self.rotation_deg, "width_m": self.width_m, "depth_m": self.depth_m,
            "asset_ids": self.asset_ids, "operator_ids": self.operator_ids,
            "tasks": [t.to_dict() for t in self.tasks],
            "input_zone_id": self.input_zone_id, "output_zone_id": self.output_zone_id,
            "cycle_time_s": self.cycle_time_s, "va_time_s": self.va_time_s,
            "nva_time_s": self.nva_time_s, "wait_time_s": self.wait_time_s,
            "efficiency": self.efficiency, "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "WorkstationLayout":
        return cls(
            id=data["id"], name=data["name"],
            position=Vector2D(**data.get("position", {"x": 0, "y": 0})),
            rotation_deg=data.get("rotation_deg", 0.0),
            width_m=data.get("width_m", 2.0), depth_m=data.get("depth_m", 2.0),
            asset_ids=data.get("asset_ids", []), operator_ids=data.get("operator_ids", []),
            tasks=[ProcessTask.from_dict(t) for t in data.get("tasks", [])],
            input_zone_id=data.get("input_zone_id", ""), output_zone_id=data.get("output_zone_id", ""),
            cycle_time_s=data.get("cycle_time_s", 0.0), va_time_s=data.get("va_time_s", 0.0),
            nva_time_s=data.get("nva_time_s", 0.0), wait_time_s=data.get("wait_time_s", 0.0),
            efficiency=data.get("efficiency", 0.0), metadata=data.get("metadata", {}),
        )


# ============================================================
# RÉSEAU DE TRANSPORT
# ============================================================

@dataclass
class TransportLink:
    """Lien de transport entre deux points."""
    id: str
    source_id: str
    target_id: str
    transport_mode: TransportMode = TransportMode.MANUAL
    path_points: List[Vector2D] = field(default_factory=list)  # Points de passage
    distance_m: float = 0.0
    speed_m_s: float = 1.3
    capacity_p_h: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def transit_time_s(self) -> float:
        if self.speed_m_s <= 0:
            return 0.0
        return self.distance_m / self.speed_m_s * 60
    
    def calculate_distance(self):
        """Calcule la distance totale le long du chemin."""
        if len(self.path_points) < 2:
            self.distance_m = 0.0
            return
        dist = 0.0
        for i in range(len(self.path_points) - 1):
            dist += self.path_points[i].distance_to(self.path_points[i + 1])
        self.distance_m = dist
    
    def to_dict(self) -> dict:
        return {
            "id": self.id, "source_id": self.source_id, "target_id": self.target_id,
            "transport_mode": self.transport_mode.value,
            "path_points": [{"x": p.x, "y": p.y} for p in self.path_points],
            "distance_m": self.distance_m, "speed_m_s": self.speed_m_s,
            "capacity_p_h": self.capacity_p_h, "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TransportLink":
        return cls(
            id=data["id"], source_id=data["source_id"], target_id=data["target_id"],
            transport_mode=TransportMode(data.get("transport_mode", "manual")),
            path_points=[Vector2D(**p) for p in data.get("path_points", [])],
            distance_m=data.get("distance_m", 0.0), speed_m_s=data.get("speed_m_s", 1.3),
            capacity_p_h=data.get("capacity_p_h", 0.0), metadata=data.get("metadata", {}),
        )


# ============================================================
# LAYOUT COMPLET DU BÂTIMENT
# ============================================================

@dataclass
class BuildingLayout:
    """Structure complète du bâtiment pour la Vue Implantation 2D/3D."""
    name: str = "Usine"
    grid_size_m: float = 1.0
    snap_enabled: bool = True
    units: str = "meters"  # meters, millimeters
    
    walls: List[WallSegment] = field(default_factory=list)
    doors: List[Door] = field(default_factory=list)
    zones: List[Zone] = field(default_factory=list)
    assets: List[PhysicalAsset] = field(default_factory=list)
    workstations: List[WorkstationLayout] = field(default_factory=list)
    operators: List[OperatorProfile] = field(default_factory=list)
    transport_links: List[TransportLink] = field(default_factory=list)
    dimensions: List[DimensionLayout] = field(default_factory=list)
    
    # Origine et rotation du bâtiment
    origin: Vector2D = field(default_factory=Vector2D)
    rotation_deg: float = 0.0
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> List[str]:
        """Vérifie la cohérence du layout. Retourne la liste des erreurs."""
        errors: List[str] = self.validate_geometry()
        asset_ids = {a.id for a in self.assets}
        ws_ids = {w.id for w in self.workstations}

        # IDs dupliqués
        if len(asset_ids) != len(self.assets):
            errors.append("IDs d'assets dupliqués dans le layout")
        if len(ws_ids) != len(self.workstations):
            errors.append("IDs de postes (layout) dupliqués")

        # Postes référençant des assets inexistants
        for ws in self.workstations:
            for aid in ws.asset_ids:
                if aid and aid not in asset_ids:
                    errors.append(f"Poste {ws.id}: asset référencé '{aid}' inexistant")
            for oid in ws.operator_ids:
                if not any(o.id == oid for o in self.operators):
                    errors.append(f"Poste {ws.id}: opérateur référencé '{oid}' inexistant")

        # Zones: au moins 3 sommets
        for z in self.zones:
            if len(z.vertices) < 3:
                errors.append(f"Zone {z.id}: moins de 3 sommets (polygone invalide)")

        # Murs: références de portes valides
        wall_ids = {w.id for w in self.walls}
        for d in self.doors:
            if d.wall_id and d.wall_id not in wall_ids:
                errors.append(f"Porte {d.id}: mur référencé '{d.wall_id}' inexistant")

        return errors
    
    def validate_geometry(self) -> List[str]:
        """Vérifie la cohérence géométrique 2D des murs."""
        errors: List[str] = []
        walls = self.walls
        
        if not walls:
            return errors
        
        for w in walls:
            if w.length() < 0.05:
                errors.append(f"Mur {w.id}: longueur trop courte ({w.length():.2f} m < 0.05 m)")
        
        parallel_groups: Dict[float, List[WallSegment]] = {}
        for w in walls:
            angle = round(w.angle_deg() / 90.0) * 90.0 % 180.0
            key = angle
            if key not in parallel_groups:
                parallel_groups[key] = []
            parallel_groups[key].append(w)
        
        for angle_key, group in parallel_groups.items():
            if len(group) > 1:
                lengths = [w.length() for w in group]
                avg_len = sum(lengths) / len(lengths)
                for w in group:
                    if abs(w.length() - avg_len) > 0.3 and avg_len > 0.5:
                        errors.append(
                            f"Mur {w.id}: longueur {w.length():.2f} m dévie de la moyenne "
                            f"du groupe parallèle ({avg_len:.2f} m)"
                        )
        
        for i in range(len(walls)):
            for j in range(i + 1, len(walls)):
                wi, wj = walls[i], walls[j]
                if self._segments_intersect(wi.start, wi.end, wj.start, wj.end):
                    inter = self._segment_intersection(wi.start, wi.end, wj.start, wj.end)
                    if inter is not None:
                        errors.append(f"Mur {wi.id} et {wj.id}: intersection détectée en {inter}")
        
        return errors
    
    @staticmethod
    def _walls_connected(w1: "WallSegment", w2: "WallSegment", tolerance_m: float = 0.1) -> bool:
        pts1 = [w1.start, w1.end]
        pts2 = [w2.start, w2.end]
        for p1 in pts1:
            for p2 in pts2:
                if p1.distance_to(p2) < tolerance_m:
                    return True
        return False
    
    @staticmethod
    def _segments_intersect(a1: Vector2D, a2: Vector2D, b1: Vector2D, b2: Vector2D) -> bool:
        def orient(p, q, r):
            return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)
        
        o1 = orient(a1, a2, b1)
        o2 = orient(a1, a2, b2)
        o3 = orient(b1, b2, a1)
        o4 = orient(b1, b2, a2)
        
        if o1 * o2 < 0 and o3 * o4 < 0:
            return True
        return False
    
    @staticmethod
    def _segment_intersection(a1: Vector2D, a2: Vector2D, b1: Vector2D, b2: Vector2D) -> Optional[Vector2D]:
        d1 = a2 - a1
        d2 = b2 - b1
        denom = d1.cross(d2)
        if abs(denom) < 1e-9:
            return None
        t = (b1 - a1).cross(d2) / denom
        if 0.0 <= t <= 1.0:
            return a1 + d1 * t
        return None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name, "grid_size_m": self.grid_size_m,
            "snap_enabled": self.snap_enabled, "units": self.units,
            "walls": [w.to_dict() for w in self.walls],
            "doors": [d.to_dict() for d in self.doors],
            "zones": [z.to_dict() for z in self.zones],
            "assets": [a.to_dict() for a in self.assets],
            "workstations": [w.to_dict() for w in self.workstations],
            "operators": [o.to_dict() for o in self.operators],
            "transport_links": [t.to_dict() for t in self.transport_links],
            "dimensions": [d.to_dict() for d in self.dimensions],
            "origin": {"x": self.origin.x, "y": self.origin.y},
            "rotation_deg": self.rotation_deg, "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BuildingLayout":
        return cls(
            name=data.get("name", "Usine"), grid_size_m=data.get("grid_size_m", 1.0),
            snap_enabled=data.get("snap_enabled", True), units=data.get("units", "meters"),
            walls=[WallSegment.from_dict(w) for w in data.get("walls", [])],
            doors=[Door.from_dict(d) for d in data.get("doors", [])],
            zones=[Zone.from_dict(z) for z in data.get("zones", [])],
            assets=[PhysicalAsset.from_dict(a) for a in data.get("assets", [])],
            workstations=[WorkstationLayout.from_dict(w) for w in data.get("workstations", [])],
            operators=[OperatorProfile.from_dict(o) for o in data.get("operators", [])],
            transport_links=[TransportLink.from_dict(t) for t in data.get("transport_links", [])],
            dimensions=[DimensionLayout.from_dict(d) for d in data.get("dimensions", [])],
            origin=Vector2D(**data.get("origin", {"x": 0, "y": 0})),
            rotation_deg=data.get("rotation_deg", 0.0), metadata=data.get("metadata", {}),
        )


# ============================================================
# PROJET UNIFIÉ (3 VUES)
# ============================================================

@dataclass
class UnifiedProject:
    """Projet unifié contenant les 3 vues synchronisées."""
    name: str = "Nouveau Projet"
    version: str = "2.0"
    
    # Vue Logique (existante)
    logical_nodes: List[Dict[str, Any]] = field(default_factory=list)
    logical_edges: List[List[str]] = field(default_factory=list)
    
    # Vue Implantation 2D
    building_layout: BuildingLayout = field(default_factory=BuildingLayout)
    
    # Vue 3D (références aux assets 3D)
    view3d_settings: Dict[str, Any] = field(default_factory=dict)
    
    # Synchronisation
    last_sync_timestamp: float = 0.0
    
    def validate(self) -> List[str]:
        """Vérifie la cohérence globale du projet unifié."""
        errors: List[str] = []

        # Nœuds logiques: au moins les opérations
        op_nodes = [n for n in self.logical_nodes if n.get("type") == "operation"]
        if not op_nodes:
            errors.append("Aucune opération définie dans la vue logique")

        # Références d'arêtes valides
        node_ids = {n.get("id") for n in self.logical_nodes}
        for edge in self.logical_edges:
            if len(edge) < 2 or edge[0] not in node_ids or edge[1] not in node_ids:
                errors.append(f"Arête logique invalide: {edge}")

        # Validation du layout d'implantation
        errors.extend(self.building_layout.validate())
        return errors
    
    def to_json(self) -> str:
        data = {
            "name": self.name, "version": self.version,
            "logical_nodes": self.logical_nodes, "logical_edges": self.logical_edges,
            "building_layout": self.building_layout.to_dict(),
            "view3d_settings": self.view3d_settings,
            "last_sync_timestamp": self.last_sync_timestamp,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "UnifiedProject":
        data = json.loads(json_str)
        project = cls(
            name=data.get("name", "Nouveau Projet"),
            version=data.get("version", "2.0"),
            logical_nodes=data.get("logical_nodes", []),
            logical_edges=data.get("logical_edges", []),
            building_layout=BuildingLayout.from_dict(data.get("building_layout", {})),
            view3d_settings=data.get("view3d_settings", {}),
            last_sync_timestamp=data.get("last_sync_timestamp", 0.0),
        )
        return project
    
    def save(self, filepath: str):
        Path(filepath).write_text(self.to_json(), encoding="utf-8")
    
    @classmethod
    def load(cls, filepath: str) -> "UnifiedProject":
        return cls.from_json(Path(filepath).read_text(encoding="utf-8"))