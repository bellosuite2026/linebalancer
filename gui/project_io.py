"""
Opérations de gestion de projet (import/export/chargement).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from engine.parsers import parse_sam_file, parse_workstations_file, parse_workers_file

if TYPE_CHECKING:
    from gui.main_window import MainWindow


def action_new_project(main: MainWindow):
    main.editor.workflow = default_workflow_copy()
    main.editor.rebuild()
    main.inspector.set_node(None)
    main.results_tab.current_result = None
    main.results_tab.btn_export_excel.setEnabled(False)
    main.results_tab.btn_export_json.setEnabled(False)
    main.results_tab.btn_export_gantt.setEnabled(False)
    from engine.models_v2 import BuildingLayout
    main.layout_view.set_layout(BuildingLayout(name="Nouveau Projet"))


def default_workflow_copy():
    from gui.node_editor import default_workflow
    return default_workflow()


def action_load_project(main: MainWindow):
    path, _ = QFileDialog.getOpenFileName(main, "Charger projet", "", "JSON (*.json)")
    if not path:
        return
    try:
        from engine.models_v2 import UnifiedProject
        project = UnifiedProject.load(path)
        main.editor.workflow = {
            "nodes": project.logical_nodes,
            "edges": project.logical_edges,
        }
        main.editor.rebuild()
        main.inspector.set_node(None)
        if project.building_layout and (project.building_layout.assets or project.building_layout.zones or project.building_layout.walls):
            main.layout_view.set_layout(project.building_layout)
        main.bottom_bar.terminal.log(f"Projet charge: {path}")
    except Exception as e:
        QMessageBox.critical(main, "Erreur", str(e))


def action_save_project(main: MainWindow):
    path, _ = QFileDialog.getSaveFileName(main, "Sauvegarder projet", "projet.json", "JSON (*.json)")
    if not path:
        return
    try:
        from engine.models_v2 import UnifiedProject, BuildingLayout
        workflow = main.editor.workflow
        project = UnifiedProject(
            name=Path(path).stem,
            logical_nodes=workflow.get("nodes", []),
            logical_edges=workflow.get("edges", []),
            building_layout=main.layout_view.layout_data,
        )
        project.save(path)
        main.bottom_bar.terminal.log(f"Projet sauve: {path}")
    except Exception as e:
        QMessageBox.critical(main, "Erreur", str(e))


def action_import_sam(main: MainWindow):
    path, _ = QFileDialog.getOpenFileName(main, "Importer SAM", "", "CSV (*.csv)")
    if not path:
        return
    try:
        ops = parse_sam_file(path)
        main.bottom_bar.terminal.log(f"SAM importe: {len(ops)} operations")
        for op in ops:
            main.editor.add_node("operation")
            for node in main.editor.workflow.get("nodes", []):
                if node["type"] == "operation" and not node["config"].get("op_id"):
                    node["config"]["op_id"] = op.op_id
                    node["config"]["name"] = op.name
                    node["config"]["duration"] = op.duration
                    node["config"]["predecessors"] = ",".join(op.predecessors)
                    node["config"]["machine_type"] = op.machine_type
                    node["config"]["skills"] = ",".join(op.skills)
                    node["config"]["task_type"] = op.task_type
                    break
        main.editor.rebuild()
    except Exception as e:
        QMessageBox.critical(main, "Erreur", str(e))


def action_import_workstations(main: MainWindow):
    path, _ = QFileDialog.getOpenFileName(main, "Importer Postes", "", "CSV (*.csv)")
    if not path:
        return
    try:
        ws = parse_workstations_file(path)
        main.bottom_bar.terminal.log(f"Postes importes: {len(ws)}")
    except Exception as e:
        QMessageBox.critical(main, "Erreur", str(e))


def action_import_workers(main: MainWindow):
    path, _ = QFileDialog.getOpenFileName(main, "Importer Ouvriers", "", "CSV (*.csv)")
    if not path:
        return
    try:
        workers = parse_workers_file(path)
        main.bottom_bar.terminal.log(f"Ouvriers importes: {len(workers)}")
    except Exception as e:
        QMessageBox.critical(main, "Erreur", str(e))


def action_export_gltf(main: MainWindow):
    if not main.layout_view.layout_data.assets:
        QMessageBox.warning(main, "Attention", "Aucun layout 2D a exporter")
        return
    path, _ = QFileDialog.getSaveFileName(main, "Exporter glTF", "layout.gltf", "glTF (*.gltf *.glb)")
    if path:
        try:
            main.layout_view.export_gltf(path)
            main.bottom_bar.terminal.log(f"Exporte glTF: {path}")
        except Exception as e:
            QMessageBox.critical(main, "Erreur", str(e))


def action_save_layout(main: MainWindow):
    """Sauvegarde le layout 2D (BuildingLayout) dans un fichier .tlb-layout."""
    layout = main.layout_view.layout_data
    if not layout.assets and not layout.zones and not layout.walls:
        QMessageBox.warning(main, "Attention", "Aucun contenu 2D a sauvegarder")
        return
    path, _ = QFileDialog.getSaveFileName(
        main, "Sauvegarder implantation 2D", "implantation.tlb-layout",
        "Layout 2D (*.tlb-layout);;JSON (*.json)",
    )
    if not path:
        return
    try:
        data = layout.to_dict()
        data["_format"] = "tlb-layout-v1"
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        main.bottom_bar.terminal.log(f"Layout 2D sauvegarde: {path}")
    except Exception as e:
        QMessageBox.critical(main, "Erreur", str(e))


def action_load_layout(main: MainWindow):
    """Charge un layout 2D (.tlb-layout) et l'applique a la vue courante."""
    path, _ = QFileDialog.getOpenFileName(
        main, "Charger implantation 2D", "",
        "Layout 2D (*.tlb-layout);;JSON (*.json)",
    )
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "walls" not in data and "assets" not in data and "zones" not in data:
            QMessageBox.warning(main, "Erreur", "Format de fichier layout invalide")
            return

        from engine.models_v2 import BuildingLayout
        layout = BuildingLayout.from_dict(data)
        main.layout_view.set_layout(layout)
        main.bottom_bar.terminal.log(f"Layout 2D charge: {path} ({len(layout.assets)} assets, {len(layout.zones)} zones)")
    except Exception as e:
        QMessageBox.critical(main, "Erreur", f"Impossible de charger le layout:\n{e}")
