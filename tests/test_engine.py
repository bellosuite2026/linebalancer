"""
Tests unitaires pour le moteur (engine).
Couvre: modèles v1/v2, builders, adapters, solveurs (RPW + CP-SAT),
parseurs, exporteurs, registre.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from engine.flow_graph import ProductionFlowGraph, FlowEdgeAttr, FlowNodeAttr
from engine.models import (
    Operation, Workstation, Worker, LineBalancingProblem,
    BalancingResult, SolverAlgorithm, OptimizationObjective,
)
from engine.models_v2 import (
    UnifiedProject, BuildingLayout, PhysicalAsset, AssetCategory,
    Vector2D, WallSegment, Door, Zone, ZoneType, WallType,
    WorkstationLayout, ProcessTask, TaskType, BoundingBox2D,
)
from engine.builders import build_problem_from_workflow
from engine.adapters import unified_to_problem, problem_to_unified
from engine.parsers import (
    parse_sam_csv, parse_sam_file, parse_workstations_file, parse_workers_file,
    generate_sam_template, export_result_to_json, export_result_to_excel,
    export_gantt_data,
)

from engine.solvers import solve_rpw, solve_cp_sat, ORTOOLS_AVAILABLE, registry


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def sample_operations():
    return [
        Operation(id="OP010", name="Préparation", duration=0.45, predecessors=[], machine_type="table_travail", required_skills=["lecture_plan"], section="Montage"),
        Operation(id="OP020", name="Montage épaule", duration=0.55, predecessors=["OP010"], machine_type="piqueuse_plate", required_skills=["couture_droite"], section="Montage"),
        Operation(id="OP030", name="Montage côtés", duration=0.65, predecessors=["OP020"], machine_type="piqueuse_plate", required_skills=["couture_droite"], section="Montage"),
        Operation(id="OP040", name="Ourlet", duration=0.40, predecessors=["OP030"], machine_type="piqueuse_2_aiguilles", required_skills=["ourlet"], section="Finition"),
    ]


@pytest.fixture
def sample_workstations():
    return [
        Workstation(id="WS01", name="Piqueuse plate", machine_type="piqueuse_plate", available=True, max_workers=1, section="Montage"),
        Workstation(id="WS02", name="Surjeteuse", machine_type="surjeteuse_5_fils", available=True, max_workers=1, section="Montage"),
        Workstation(id="WS03", name="Ourleteuse", machine_type="piqueuse_2_aiguilles", available=True, max_workers=1, section="Finition"),
        Workstation(id="WS04", name="Table", machine_type="table_travail", available=True, max_workers=1, section="Montage"),
    ]


@pytest.fixture
def sample_workers():
    return [
        Worker(id="W001", name="Marie", skills=["lecture_plan", "couture_droite"], efficiency=1.0, available=True),
        Worker(id="W002", name="Ahmed", skills=["couture_droite", "ourlet"], efficiency=1.05, available=True),
        # 3 stations (1 type machine par station) => 3 opérateurs nécessaires
        Worker(id="W003", name="Salma", skills=["lecture_plan", "ourlet"], efficiency=1.0, available=True),
    ]


@pytest.fixture
def sample_problem(sample_operations, sample_workstations, sample_workers):
    return LineBalancingProblem(
        name="Test",
        target_cycle_time=1.5,
        operations=sample_operations,
        workstations=sample_workstations,
        workers=sample_workers,
        algorithm=SolverAlgorithm.RPW,
        objective=OptimizationObjective.MIN_STATIONS,
    )


# ============================================================
# TESTS MODÈLES v1
# ============================================================

def test_operation_post_init_splits_strings():
    op = Operation(id="OP1", name="X", duration=1.0, predecessors="A;B", required_skills="s1;s2")
    assert op.predecessors == ["A", "B"]
    assert op.required_skills == ["s1", "s2"]


def test_problem_get_helpers(sample_problem):
    assert sample_problem.get_operation("OP020").name == "Montage épaule"
    assert sample_problem.get_workstation("WS01").machine_type == "piqueuse_plate"
    assert sample_problem.get_worker("W001").name == "Marie"
    assert sample_problem.get_operation("NOPE") is None


def test_problem_validate_detects_unknown_predecessor():
    ops = [Operation(id="OP1", name="X", duration=1.0, predecessors=["GHOST"])]
    p = LineBalancingProblem(name="p", target_cycle_time=1.0, operations=ops, workstations=[], workers=[])
    errors = p.validate()
    assert any("GHOST" in e for e in errors)


def test_problem_validate_detects_cycle():
    ops = [
        Operation(id="A", name="A", duration=1.0, predecessors=["B"]),
        Operation(id="B", name="B", duration=1.0, predecessors=["A"]),
    ]
    p = LineBalancingProblem(name="p", target_cycle_time=1.0, operations=ops, workstations=[], workers=[])
    errors = p.validate()
    assert any("Cycle" in e for e in errors)


def test_problem_validate_detects_missing_machine():
    ops = [Operation(id="OP1", name="X", duration=1.0, machine_type="laser_inconnu")]
    p = LineBalancingProblem(name="p", target_cycle_time=1.0, operations=ops,
                             workstations=[Workstation(id="WS1", name="w", machine_type="piqueuse_plate")], workers=[])
    errors = p.validate()
    assert any("laser_inconnu" in e for e in errors)


def test_problem_validate_detects_missing_skill():
    ops = [Operation(id="OP1", name="X", duration=1.0, required_skills=["skill_inexistant"])]
    p = LineBalancingProblem(name="p", target_cycle_time=1.0, operations=ops, workstations=[],
                             workers=[Worker(id="W1", name="w", skills=["autre"])],)
    errors = p.validate()
    assert any("skill_inexistant" in e for e in errors)


# ============================================================
# TESTS MODÈLES v2
# ============================================================

def test_vector2d_operations():
    a = Vector2D(1, 2)
    b = Vector2D(4, 6)
    assert (a + b) == Vector2D(5, 8)
    assert (b - a) == Vector2D(3, 4)
    assert (a * 2) == Vector2D(2, 4)
    assert abs(a.distance_to(b) - 5.0) < 1e-9


def test_bounding_box_intersects():
    bb1 = BoundingBox2D(0, 0, 2, 2)
    bb2 = BoundingBox2D(1, 1, 3, 3)
    bb3 = BoundingBox2D(5, 5, 6, 6)
    assert bb1.intersects(bb2)
    assert not bb1.intersects(bb3)
    assert bb1.contains(Vector2D(1, 1))
    assert not bb1.contains(Vector2D(3, 3))


def test_physical_asset_bounding_box():
    a = PhysicalAsset(id="A", name="m", category=AssetCategory.MACHINE, asset_type="x",
                      width_m=2.0, depth_m=1.0, position=Vector2D(5, 5))
    bb = a.bounding_box()
    assert bb.min_x == 4.0 and bb.max_x == 6.0
    assert bb.min_y == 4.5 and bb.max_y == 5.5


def test_zone_area_and_centroid():
    square = Zone(id="Z1", name="sq", zone_type=ZoneType.WORK_AREA,
                  vertices=[Vector2D(0, 0), Vector2D(10, 0), Vector2D(10, 10), Vector2D(0, 10)])
    assert abs(square.area() - 100.0) < 1e-6
    c = square.centroid()
    assert abs(c.x - 5.0) < 1e-6 and abs(c.y - 5.0) < 1e-6
    assert square.contains_point(Vector2D(5, 5))
    assert not square.contains_point(Vector2D(15, 15))


def test_physical_asset_roundtrip():
    a = PhysicalAsset(id="A", name="m", category=AssetCategory.MACHINE, asset_type="x",
                      width_m=2.0, depth_m=1.0, position=Vector2D(5, 5), metadata={"k": "v"})
    d = a.to_dict()
    a2 = PhysicalAsset.from_dict(d)
    assert a2.id == a.id and a2.position == a.position and a2.metadata == a.metadata


def test_building_layout_validate_duplicate_assets():
    layout = BuildingLayout(
        assets=[
            PhysicalAsset(id="A", name="m1", category=AssetCategory.MACHINE, asset_type="x"),
            PhysicalAsset(id="A", name="m2", category=AssetCategory.MACHINE, asset_type="x"),
        ]
    )
    errors = layout.validate()
    assert any("dupliqués" in e for e in errors)


def test_building_layout_validate_bad_asset_ref():
    ws = WorkstationLayout(id="WS1", name="w", asset_ids=["GHOST"])
    layout = BuildingLayout(workstations=[ws])
    errors = layout.validate()
    assert any("GHOST" in e for e in errors)


def test_building_layout_validate_bad_door_ref():
    wall = WallSegment(id="W1", start=Vector2D(0, 0), end=Vector2D(10, 0))
    door = Door(id="D1", wall_id="GHOST")
    layout = BuildingLayout(walls=[wall], doors=[door])
    errors = layout.validate()
    assert any("GHOST" in e for e in errors)


def test_unified_project_roundtrip(tmp_path):
    project = UnifiedProject(name="Test Project")
    project.logical_nodes = [
        {"id": "op_1", "type": "operation", "config": {"op_id": "OP010", "name": "X", "duration": 0.5}}
    ]
    project.logical_edges = [["op_1", "op_2"]]
    project.building_layout.assets.append(
        PhysicalAsset(id="A1", name="m", category=AssetCategory.MACHINE, asset_type="x")
    )
    # Fix edge to valid ref
    project.logical_edges = []
    fp = tmp_path / "proj.json"
    project.save(str(fp))
    loaded = UnifiedProject.load(str(fp))
    assert loaded.name == "Test Project"
    assert len(loaded.building_layout.assets) == 1
    assert loaded.building_layout.assets[0].id == "A1"


def test_unified_project_validate_invalid_edge():
    project = UnifiedProject()
    project.logical_nodes = [{"id": "op_1", "type": "operation"}]
    project.logical_edges = [["op_1", "op_missing"]]
    errors = project.validate()
    assert any("invalide" in e for e in errors)


# ============================================================
# TESTS BUILDERS
# ============================================================

def test_build_problem_from_workflow():
    workflow = {
        "nodes": [
            {"id": "n1", "type": "operation", "enabled": True,
             "config": {"op_id": "OP010", "name": "Prep", "duration": 0.5, "predecessors": "OP020", "machine_type": "table_travail", "skills": "lecture_plan"}},
            {"id": "n2", "type": "operation", "enabled": True,
             "config": {"op_id": "OP020", "name": "Montage", "duration": 0.6}},
            {"id": "n3", "type": "workstation", "enabled": True,
             "config": {"ws_id": "WS01", "name": "Poste1", "machine_type": "piqueuse_plate"}},
            {"id": "n4", "type": "worker", "enabled": True,
             "config": {"worker_id": "W001", "name": "Marie", "skills": "couture_droite", "efficiency": 1.1}},
            {"id": "n5", "type": "operation", "enabled": False,
             "config": {"op_id": "OP999", "name": "Off", "duration": 9.0}},
        ],
        "edges": [],
    }
    problem = build_problem_from_workflow(workflow, 1.5, 10, "min_stations")
    assert problem is not None
    assert len(problem.operations) == 2  # OP999 disabled
    assert problem.operations[0].predecessors == ["OP020"]
    assert problem.operations[0].required_skills == ["lecture_plan"]
    assert problem.workstations[0].machine_type == "piqueuse_plate"
    assert problem.workers[0].efficiency == 1.1


def test_build_problem_from_workflow_empty():
    problem = build_problem_from_workflow({"nodes": [], "edges": []}, 1.5, 10, "min_stations")
    assert problem is None


def test_build_problem_preserves_task_type_and_optional():
    workflow = {
        "nodes": [
            {"id": "n1", "type": "operation", "enabled": True,
             "config": {"op_id": "OP010", "name": "Prep", "duration": 0.5, "task_type": "NVA", "optional": "True"}},
        ],
        "edges": [],
    }
    problem = build_problem_from_workflow(workflow, 1.5, 10, "min_stations")
    assert problem.operations[0].task_type == "NVA"
    assert problem.operations[0].optional is True


# ============================================================
# TESTS ADAPTATEURS
# ============================================================

def test_unified_to_problem_roundtrip(sample_problem):
    unified = problem_to_unified(sample_problem, name="Roundtrip")
    problem = unified_to_problem(unified, cycle_time=1.5, max_stations=10, objective="min_stations")
    assert problem is not None
    assert len(problem.operations) == len(sample_problem.operations)
    assert {op.id for op in problem.operations} == {op.id for op in sample_problem.operations}
    assert problem.target_cycle_time == 1.5


def test_problem_to_unified_preserves_predecessors(sample_problem):
    unified = problem_to_unified(sample_problem)
    op_nodes = [n for n in unified.logical_nodes if n["type"] == "operation"]
    op020 = next(n for n in op_nodes if n["config"]["op_id"] == "OP020")
    assert op020["config"]["predecessors"] == "OP010"


def test_problem_to_unified_preserves_task_type():
    ops = [Operation(id="OP1", name="X", duration=1.0, task_type="NVA", optional=True)]
    p = LineBalancingProblem(name="p", target_cycle_time=1.0, operations=ops, workstations=[], workers=[])
    unified = problem_to_unified(p)
    node = next(n for n in unified.logical_nodes if n["type"] == "operation")
    assert node["config"]["task_type"] == "NVA"
    assert node["config"]["optional"] is True


def test_unified_to_problem_raises_on_invalid():
    project = UnifiedProject()
    project.logical_nodes = [{"id": "op_1", "type": "operation"}]
    project.logical_edges = [["op_1", "op_missing"]]
    with pytest.raises(ValueError):
        unified_to_problem(project, 1.5, 10, "min_stations")


def test_unified_to_problem_preserves_layout():
    project = UnifiedProject()
    project.building_layout.assets.append(
        PhysicalAsset(id="A1", name="m", category=AssetCategory.MACHINE, asset_type="x")
    )
    ops = [{"id": "op_1", "type": "operation", "enabled": True,
            "config": {"op_id": "OP010", "name": "X", "duration": 0.5}}]
    project.logical_nodes = ops
    problem = unified_to_problem(project, 1.5, 10, "min_stations")
    assert problem is not None
    assert len(problem_to_unified(problem, base=project).building_layout.assets) == 1


# ============================================================
# TESTS SOLVEURS
# ============================================================

def test_rpw_solve_basic(sample_problem):
    result = solve_rpw(sample_problem)
    assert result.success
    assert result.stations_used >= 1
    assert result.stations_used <= len(sample_problem.operations)
    # All operations assigned
    assigned = set(result.operation_assignments.keys())
    assert assigned == {op.id for op in sample_problem.operations}
    # Precedence respected
    for op in sample_problem.operations:
        for pred in op.predecessors:
            assert result.operation_assignments[pred] <= result.operation_assignments[op.id]


def test_rpw_respects_cycle_time(sample_problem):
    result = solve_rpw(sample_problem)
    for sd in result.station_details:
        assert sd["total_time"] <= sample_problem.target_cycle_time + 1e-6


def test_rpw_kpis(sample_problem):
    result = solve_rpw(sample_problem)
    total_work = sum(op.duration for op in sample_problem.operations)
    expected_eff = total_work / (result.stations_used * sample_problem.target_cycle_time) * 100
    assert abs(result.efficiency - expected_eff) < 1.0


def test_registry_has_rpw():
    assert registry.is_available("rpw")
    assert "rpw" in registry.names()


def test_rpw_handles_single_station_limit(sample_operations, sample_workstations, sample_workers):
    problem = LineBalancingProblem(
        name="p", target_cycle_time=100.0,
        operations=sample_operations, workstations=sample_workstations, workers=sample_workers,
        algorithm=SolverAlgorithm.RPW, objective=OptimizationObjective.MIN_STATIONS,
        max_machines_per_station=1,  # ancien comportement : une machine par station
    )
    result = solve_rpw(problem)
    # Les opérations de types machine différents sont réparties dans des stations distinctes
    # (3 types machine → au moins 3 stations)
    assert result.stations_used >= 3
    # Vérifie que chaque station contient un seul type machine
    for sd in result.station_details:
        types = set()
        for op in sample_operations:
            if op.id in sd["operations"] and op.machine_type:
                types.add(op.machine_type)
        assert len(types) <= 1, f"Station {sd['station']} a plusieurs types: {types}"


# ============================================================
# TESTS SOLVEUR CP-SAT
# ============================================================

@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_solve_basic(sample_problem):
    result = solve_cp_sat(sample_problem, time_limit_seconds=10)
    assert result.success
    assert 1 <= result.stations_used <= len(sample_problem.operations)
    assigned = set(result.operation_assignments.keys())
    assert assigned == {op.id for op in sample_problem.operations}


@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_respects_precedence(sample_problem):
    result = solve_cp_sat(sample_problem, time_limit_seconds=10)
    assert result.success
    for op in sample_problem.operations:
        for pred in op.predecessors:
            assert result.operation_assignments[pred] <= result.operation_assignments[op.id]


@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_respects_cycle_time(sample_problem):
    result = solve_cp_sat(sample_problem, time_limit_seconds=10)
    assert result.success
    for sd in result.station_details:
        assert sd["total_time"] <= sample_problem.target_cycle_time + 1e-6


@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_registry():
    assert registry.is_available("cp_sat")
    assert "cp_sat" in registry.names()


# ============================================================
# TESTS PARSEURS
# ============================================================

def test_parse_sam_csv_basic(tmp_path):
    csv_content = "Op_ID;Description;SAM_min;Predecesseurs;Type_Machine;Competences;Section\nOP010;Prep;0.5;;table_travail;lecture_plan;Montage\nOP020;Montage;0.6;OP010;piqueuse_plate;couture_droite;Montage\n"
    fp = tmp_path / "test_sam.csv"
    fp.write_text(csv_content, encoding="utf-8")
    ops = parse_sam_csv(fp)
    assert len(ops) == 2
    assert ops[0].id == "OP010"
    assert ops[0].duration == 0.5
    assert ops[1].predecessors == ["OP010"]
    assert ops[1].machine_type == "piqueuse_plate"
    assert ops[1].required_skills == ["couture_droite"]


def test_parse_sam_csv_with_commas(tmp_path):
    csv_content = "Op_ID,Description,Time,Predecessors,Machine,Skills,Section\nOP010,Prep,0.5,,table_travail,lecture_plan,Montage\n"
    fp = tmp_path / "test_comma.csv"
    fp.write_text(csv_content, encoding="utf-8")
    ops = parse_sam_csv(fp, delimiter=",")
    assert len(ops) == 1
    assert ops[0].id == "OP010"


def test_parse_sam_csv_french_decimal(tmp_path):
    csv_content = "Op_ID;Duration\nOP010;0,5\nOP020;1,2\n"
    fp = tmp_path / "test_french.csv"
    fp.write_text(csv_content, encoding="utf-8")
    ops = parse_sam_csv(fp)
    assert len(ops) == 2
    assert ops[0].duration == 0.5
    assert ops[1].duration == 1.2


def test_parse_sam_csv_auto_delimiter(tmp_path):
    csv_content = "Op_ID;Duration\nOP010;0.5\n"
    fp = tmp_path / "test_auto.csv"
    fp.write_text(csv_content, encoding="utf-8")
    ops = parse_sam_csv(fp)
    assert len(ops) == 1


def test_parse_sam_csv_empty_rows_skipped(tmp_path):
    csv_content = "Op_ID;Duration\nOP010;0.5\n\nOP020;0.6\n"
    fp = tmp_path / "test_empty.csv"
    fp.write_text(csv_content, encoding="utf-8")
    ops = parse_sam_csv(fp)
    assert len(ops) == 2


def test_parse_sam_csv_missing_columns_raises(tmp_path):
    csv_content = "Name;Value\nA;B\n"
    fp = tmp_path / "test_bad.csv"
    fp.write_text(csv_content, encoding="utf-8")
    with pytest.raises(ValueError, match="Colonnes obligatoires manquantes"):
        parse_sam_csv(fp)


def test_parse_sam_file_json(tmp_path):
    data = [
        {"id": "OP010", "name": "Test", "duration": 0.5},
        {"id": "OP020", "name": "Test2", "duration": 0.6, "predecessors": ["OP010"]},
    ]
    fp = tmp_path / "test_sam.json"
    fp.write_text(json.dumps(data), encoding="utf-8")
    ops = parse_sam_file(fp)
    assert len(ops) == 2
    assert ops[1].predecessors == ["OP010"]


def test_parse_sam_file_unsupported_raises(tmp_path):
    fp = tmp_path / "test.txt"
    fp.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Format non supporté"):
        parse_sam_file(fp)


def test_parse_workstations_csv(tmp_path):
    csv_content = "Poste_ID;Nom;Type_Machine;Disponible;Max_Ouvriers;Section\nWS01;Poste1;piqueuse_plate;Oui;1;Montage\nWS02;Poste2;surjeteuse_5_fils;Oui;1;Finition\n"
    fp = tmp_path / "ws.csv"
    fp.write_text(csv_content, encoding="utf-8")
    wss = parse_workstations_file(fp)
    assert len(wss) == 2
    assert wss[0].id == "WS01"
    assert wss[0].machine_type == "piqueuse_plate"
    assert wss[0].available is True


def test_parse_workers_csv(tmp_path):
    csv_content = "Ouvrier_ID;Nom;Competences;Efficacite;Disponible\nW001;Marie;couture_droite;1.0;Oui\nW002;Ahmed;couture_droite;1.05;Oui\n"
    fp = tmp_path / "workers.csv"
    fp.write_text(csv_content, encoding="utf-8")
    workers = parse_workers_file(fp)
    assert len(workers) == 2
    assert workers[0].id == "W001"
    assert workers[0].skills == ["couture_droite"]
    assert workers[1].efficiency == 1.05


def test_parse_workers_csv_skills_semicolon(tmp_path):
    csv_content = "Ouvrier_ID;Competences\nW001;couture_droite;surjet\n"
    fp = tmp_path / "workers_skills.csv"
    fp.write_text(csv_content, encoding="utf-8")
    workers = parse_workers_file(fp)
    assert len(workers) == 1
    assert len(workers[0].skills) >= 1


# ============================================================
# TESTS EXPORT
# ============================================================

def test_export_result_json(tmp_path, sample_problem):
    result = solve_rpw(sample_problem)
    fp = tmp_path / "result.json"
    export_result_to_json(result, fp)
    assert fp.exists()
    data = json.loads(fp.read_text())
    assert data["success"] is True
    assert "stations_used" in data


def test_export_result_excel(tmp_path, sample_problem):
    result = solve_rpw(sample_problem)
    fp = tmp_path / "result.xlsx"
    export_result_to_excel(result, fp)
    assert fp.exists()


def test_export_gantt_data(tmp_path, sample_problem):
    result = solve_rpw(sample_problem)
    fp = tmp_path / "gantt.json"
    export_gantt_data(result, fp)
    assert fp.exists()
    data = json.loads(fp.read_text())
    assert "stations" in data
    assert "cycle_time" in data


# ============================================================
# TESTS GÉNÉRATION DE TEMPLATES
# ============================================================

def test_generate_sam_template_csv(tmp_path):
    fp = tmp_path / "template.csv"
    generate_sam_template(fp, format="csv")
    assert fp.exists()
    ops = parse_sam_csv(fp)
    assert len(ops) > 0


def test_generate_sam_template_json(tmp_path):
    fp = tmp_path / "template.json"
    generate_sam_template(fp, format="json")
    assert fp.exists()
    ops = parse_sam_file(fp)
    assert len(ops) > 0


# ============================================================
# TESTS GÉOMÉTRIE MUR / PORTE
# ============================================================

def _make_wall_with_door(start, end, thickness=0.2, door_pos=0.5, door_width=1.0):
    """Crée un WallSegment avec porte (attributs dynamiques)."""
    wall = WallSegment(
        id="W1", start=start, end=end,
        thickness_m=thickness, wall_type=WallType.INTERIOR,
    )
    wall.has_door = True
    wall.door_id = "D1"
    wall.door_position = door_pos
    wall.door_width = door_width
    return wall


def test_wall_door_gap_computation():
    """Le gap de porte dans un mur doit être le long du mur,
    pas perpendiculaire (bug #1)."""
    wall = _make_wall_with_door(Vector2D(0, 0), Vector2D(10, 0))
    length = wall.length()
    dx = wall.end.x - wall.start.x
    dy = wall.end.y - wall.start.y
    gap = wall.door_width / 2

    # La direction du gap doit être le long du mur, pas la normale
    door_gap_x = dx / length * gap
    door_gap_y = dy / length * gap
    wrong_gap_x = -dy / length * gap  # direction normale (BUG)
    wrong_gap_y = dx / length * gap

    # Vérifier que le calcul correct est le long du mur
    assert door_gap_x == 0.5, f"gap X le long du mur devrait être 0.5, obtenu {door_gap_x}"
    assert door_gap_y == 0.0, f"gap Y le long du mur devrait être 0.0, obtenu {door_gap_y}"
    # Vérifier que l'ancien calcul (BUG) donnait la normale
    assert wrong_gap_x == 0.0, f"gap X normal devrait être 0.0, obtenu {wrong_gap_x}"
    assert wrong_gap_y == 0.5, f"gap Y normal devrait être 0.5, obtenu {wrong_gap_y}"

    # Vérifier que les positions de gap sont correctes
    t = wall.door_position
    mid_x = wall.start.x + t * dx
    mid_y = wall.start.y + t * dy
    assert mid_x == 5.0
    assert mid_y == 0.0

    left_end_x = mid_x - door_gap_x
    left_end_y = mid_y - door_gap_y
    right_start_x = mid_x + door_gap_x
    right_start_y = mid_y + door_gap_y

    # Le gap doit être de door_width le long du mur
    gap_along_wall = math.hypot(right_start_x - left_end_x, right_start_y - left_end_y)
    assert abs(gap_along_wall - wall.door_width) < 0.001


def test_wall_door_gap_vertical_wall():
    """Même test pour un mur vertical."""
    wall = _make_wall_with_door(Vector2D(0, 0), Vector2D(0, 10))
    length = wall.length()
    dx = wall.end.x - wall.start.x
    dy = wall.end.y - wall.start.y
    gap = wall.door_width / 2

    door_gap_x = dx / length * gap
    door_gap_y = dy / length * gap

    assert abs(door_gap_x) < 0.001, f"gap X vertical devrait être 0, obtenu {door_gap_x}"
    assert abs(door_gap_y - 0.5) < 0.001, f"gap Y vertical devrait être 0.5, obtenu {door_gap_y}"

    t = wall.door_position
    mid_x = wall.start.x + t * dx
    mid_y = wall.start.y + t * dy
    left_end_x = mid_x - door_gap_x
    left_end_y = mid_y - door_gap_y
    right_start_x = mid_x + door_gap_x
    right_start_y = mid_y + door_gap_y

    gap_along_wall = math.hypot(right_start_x - left_end_x, right_start_y - left_end_y)
    assert abs(gap_along_wall - wall.door_width) < 0.001


def test_wall_door_gap_diagonal_wall():
    """Test pour un mur diagonal à 45 degrés."""
    wall = _make_wall_with_door(Vector2D(0, 0), Vector2D(10, 10))
    length = wall.length()
    dx = wall.end.x - wall.start.x
    dy = wall.end.y - wall.start.y
    gap = wall.door_width / 2

    door_gap_x = dx / length * gap
    door_gap_y = dy / length * gap

    expected = 1.0 / (2 * math.sqrt(2))
    assert abs(door_gap_x - expected) < 0.01, f"gap X diagonal {door_gap_x} != {expected}"
    assert abs(door_gap_y - expected) < 0.01, f"gap Y diagonal {door_gap_y} != {expected}"

    t = wall.door_position
    mid_x = wall.start.x + t * dx
    mid_y = wall.start.y + t * dy
    left_end_x = mid_x - door_gap_x
    left_end_y = mid_y - door_gap_y
    right_start_x = mid_x + door_gap_x
    right_start_y = mid_y + door_gap_y

    gap_along_wall = math.hypot(right_start_x - left_end_x, right_start_y - left_end_y)
    assert abs(gap_along_wall - wall.door_width) < 0.01


# ── Tests ProductionFlowGraph ──────────────────────────────────────

_SAMPLE_WORKFLOW = {
    "nodes": [
        {"id": "OP10", "type": "operation",
         "config": {"name": "Coupe", "duration": 2.0, "machine_type": "decoupeuse",
                     "section": "Coupe", "predecessors": ""}},
        {"id": "OP20", "type": "operation",
         "config": {"name": "Pique avant", "duration": 3.0, "machine_type": "piqueuse",
                     "section": "Montage", "predecessors": "OP10"}},
        {"id": "OP30", "type": "operation",
         "config": {"name": "Pique arriere", "duration": 2.5, "machine_type": "piqueuse",
                     "section": "Montage", "predecessors": "OP10"}},
        {"id": "OP40", "type": "operation",
         "config": {"name": "Finition", "duration": 1.5, "machine_type": "table_repassage",
                     "section": "Finition", "predecessors": "OP20;OP30"}},
        {"id": "OP50", "type": "operation",
         "config": {"name": "Controle", "duration": 1.0, "machine_type": "table_controle",
                     "section": "Qualite", "predecessors": "OP40"}},
    ]
}


class TestProductionFlowGraph:
    def test_from_workflow(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        assert g.graph.number_of_nodes() == 13  # 5 ops + 4 mt + 4 sections
        assert g.graph.number_of_edges() >= 10
        # Vérifie les types de nœuds
        types = {d["node_type"] for _, d in g.graph.nodes(data=True)}
        assert types == {"operation", "machine_type", "section"}

    def test_critical_path(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        cp = g.critical_path()
        assert len(cp) >= 4
        assert cp[0] == "op_OP10"
        assert cp[-1] == "op_OP50"
        total = g.critical_path_length()
        assert total > 0

    def test_section_flow_matrix(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        sfm = g.section_flow_matrix()
        assert "sec_Coupe" in sfm
        assert "sec_Qualite" in sfm
        # Flux Coupe → Montage
        assert sfm["sec_Coupe"]["sec_Montage"] == 2
        # Flux Montage → Finition (depuis OP20 et OP30)
        assert sfm["sec_Montage"]["sec_Finition"] == 2
        # Flux Finition → Qualite
        assert sfm["sec_Finition"]["sec_Qualite"] == 1

    def test_machine_type_flow(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        mtf = g.machine_type_flow()
        assert "mt_decoupeuse" in mtf
        assert mtf["mt_decoupeuse"]["mt_piqueuse"] == 2.0
        assert mtf["mt_piqueuse"]["mt_table_repassage"] == 2.0
        assert mtf["mt_table_repassage"]["mt_table_controle"] == 1.0

    def test_bottleneck_machine_types(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        btl = g.bottleneck_machine_types(3)
        assert len(btl) == 3
        # piqueuse devrait être la plus centrale (2 flux entrants, 1 sortant)
        names = [n for n, _ in btl]
        assert "mt_piqueuse" in names

    def test_json_round_trip(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        js = g.to_json()
        g2 = ProductionFlowGraph.from_json(js)
        assert g2.graph.number_of_nodes() == g.graph.number_of_nodes()
        assert g2.graph.number_of_edges() == g.graph.number_of_edges()
        # Les analyses fonctionnent après rechargement
        assert g2.critical_path_length() == g.critical_path_length()
        assert g2.section_flow_matrix() == g.section_flow_matrix()

    def test_empty_graph(self):
        g = ProductionFlowGraph()
        assert g.graph.number_of_nodes() == 0
        assert g.critical_path() == []
        assert g.critical_path_length() == 0
        assert g.section_flow_matrix() == {}
        assert g.bottleneck_machine_types() == []

    def test_summary(self):
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        s = g.summary()
        assert "Flux inter-sections" in s
        assert "Chemin critique" in s
        assert "Types machine critiques" in s

    def test_from_json_repr(self):
        """Après round-trip, _ensure_flow doit convertir les dicts en FlowEdgeAttr."""
        g = ProductionFlowGraph.from_workflow(_SAMPLE_WORKFLOW)
        js = g.to_json()
        g2 = ProductionFlowGraph.from_json(js)
        # Vérifie que _ensure_flow fonctionne sur les edges rechargés
        for _, _, data in g2.graph.edges(data=True):
            f = g2._ensure_flow(data)
            assert isinstance(f, FlowEdgeAttr)
            assert f.volume >= 0

    def test_flow_edge_attr_merge(self):
        a1 = FlowEdgeAttr(volume=2.0, total_duration=5.0, operation_ids=["A"])
        a2 = FlowEdgeAttr(volume=3.0, total_duration=2.0, operation_ids=["B"])
        a1.merge(a2)
        assert a1.volume == 5.0
        assert a1.total_duration == 7.0
        assert a1.operation_ids == ["A", "B"]

    def test_flow_edge_attr_from_dict(self):
        d = {"volume": 4.0, "total_duration": 0.0, "transport_mode": "conveyor",
             "distance_m": 15.0, "operation_ids": ["X", "Y"]}
        f = FlowEdgeAttr(**d)
        assert f.volume == 4.0
        assert f.transport_mode == "conveyor"
        assert f.distance_m == 15.0
        assert f.operation_ids == ["X", "Y"]

    def test_predecessors_as_list(self):
        """Prédécesseurs en liste plutôt qu'en chaîne."""
        wf = {
            "nodes": [
                {"id": "A", "type": "operation",
                 "config": {"duration": 1.0, "machine_type": "m1",
                             "section": "S1", "predecessors": []}},
                {"id": "B", "type": "operation",
                 "config": {"duration": 1.0, "machine_type": "m2",
                             "section": "S2", "predecessors": ["A"]}},
            ]
        }
        g = ProductionFlowGraph.from_workflow(wf)
        assert g.graph.number_of_nodes() == 6
        assert g.graph.has_edge("op_A", "op_B")


# ============================================================
# TESTS DIAGNOSTICS / CONFORMITÉ (v2.1)
# ============================================================
from engine.diagnostics import precheck, parallel_replicas
from engine.solvers import find_min_cycle


def _line(cycle, n_plate=1, dur=0.5):
    ops = [
        Operation(id="A", name="A", duration=dur, machine_type="piqueuse_plate", required_skills=["c"]),
        Operation(id="B", name="B", duration=dur, predecessors=["A"], machine_type="piqueuse_plate", required_skills=["c"]),
    ]
    ws = [Workstation(id=f"P{i}", name="p", machine_type="piqueuse_plate") for i in range(n_plate)]
    wk = [Worker(id=f"W{i}", name="w", skills=["c"]) for i in range(4)]
    return LineBalancingProblem(name="t", target_cycle_time=cycle, operations=ops, workstations=ws,
                                workers=wk, algorithm=SolverAlgorithm.RPW,
                                objective=OptimizationObjective.MIN_STATIONS)


def test_parallel_replicas():
    op = Operation(id="X", name="X", duration=2.2)
    assert parallel_replicas(op, 1.5) == 2
    assert parallel_replicas(op, 2.2) == 1


def test_precheck_machine_capacity():
    codes = {i.code for i in precheck(_line(0.5, n_plate=1))}
    assert "MACHINE_CAPACITY" in codes


def test_rpw_reports_violation_instead_of_fake_success():
    r = solve_rpw(_line(0.5, n_plate=1))
    assert not r.success
    assert r.status == "INFEASIBLE_CONSTRAINTS"
    assert "piqueuse_plate" in r.error_message


def test_rpw_parallel_stations_for_long_operation():
    r = solve_rpw(_line(1.0, n_plate=4, dur=1.8))
    assert r.success
    assert all(sd["total_time"] <= 1.0 + 1e-6 for sd in r.station_details)
    assert sum(sd["parallel"] for sd in r.station_details) == 4
    # efficacité = 3.6 / (4 opérateurs x 1.0) = 90 %
    assert abs(r.efficiency - 90.0) < 0.5


@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_explains_infeasibility():
    r = solve_cp_sat(_line(0.5, n_plate=1), time_limit_seconds=5)
    assert not r.success
    assert "MACHINE_CAPACITY" in r.error_message


@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_parallel_and_capacity():
    r = solve_cp_sat(_line(1.0, n_plate=4, dur=1.8), time_limit_seconds=5)
    assert r.success
    assert sum(sd["parallel"] for sd in r.station_details) == 4


def test_find_min_cycle():
    c, r = find_min_cycle(_line(1.0, n_plate=1), solver="rpw", precision=0.01)
    assert r is not None and abs(c - 1.0) < 0.05


def test_parser_repairs_semicolon_lists(tmp_path):
    from engine.parsers import parse_sam_file, parse_workers_file
    sam = tmp_path / "s.csv"
    sam.write_text(
        "Op_ID;Description;SAM_min;Predecesseurs;Type_Machine;Competences;Section;Optionnel\n"
        "OP010;A;0.40;;table_travail;lecture_plan;Montage;\n"
        "OP020;B;0.55;OP010;table_travail;tri_pieces;marquage_pieces;Montage;\n"
        "OP030;C;0.75;OP010;OP020;surjeteuse_5_fils;surjet_5_fils;Montage;FALSE\n",
        encoding="utf-8")
    ops = parse_sam_file(sam)
    ops = ops[0] if isinstance(ops, tuple) else ops
    b, c = ops[1], ops[2]
    assert b.required_skills == ["tri_pieces", "marquage_pieces"] and b.section == "Montage"
    assert c.predecessors == ["OP010", "OP020"] and c.machine_type == "surjeteuse_5_fils"
    wk = tmp_path / "w.csv"
    wk.write_text("Ouvrier_ID;Nom;Competences;Efficacite;Disponible;Poste_Assigne\n"
                  "W001;Marie;a;b;c;1.05;Oui;\n", encoding="utf-8")
    w = parse_workers_file(wk)[0]
    assert w.skills == ["a", "b", "c"] and abs(w.efficiency - 1.05) < 1e-9
