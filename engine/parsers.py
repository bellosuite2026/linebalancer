"""
Parsers pour fichiers SAM (Standard Allowed Minutes) - formats courants textile.
Formats supportés:
- CSV standard (colonnnes: OpID, Description, Time, Predecessors, Machine, Skills, Section)
- Excel (.xlsx) même structure
- Format GSD/ProSMV export
- Format MODAPTS export
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional
from dataclasses import asdict

from engine.models import Operation, Workstation, Worker, LineBalancingProblem, SolverAlgorithm, OptimizationObjective


# Colonnes attendues dans le CSV SAM (insensible à la casse, aliases)
SAM_COLUMN_MAPPING = {
    "op_id": ["op_id", "operation_id", "id", "code", "ref", "numero", "num", "op_id", "op-id"],
    "name": ["name", "description", "designation", "libelle", "operation", "task", "description"],
    "duration": ["duration", "time", "sam", "sah", "standard_time", "std_time", "minutes", "min", "value", "sam_min", "sam_min"],
    "predecessors": ["predecessors", "predecessor", "pre", "prev", "dependencies", "depends_on", "antecedents", "predecesseurs"],
    "machine_type": ["machine_type", "machine", "equipment", "machine_code", "equipement", "type_machine", "type_machine"],
    "skills": ["skills", "skill", "competences", "competence", "qualification", "qualifications", "competences"],
    "section": ["section", "department", "atelier", "area", "zone", "workshop", "section"],
    "optional": ["optional", "facultatif", "option", "optionnel"],
}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")


def _match_column(headers: list[str], possible_names: list[str]) -> Optional[int]:
    norm_headers = [_normalize_header(h) for h in headers]
    for i, h in enumerate(norm_headers):
        if h in possible_names:
            return i
    return None



_OP_ID_RE = __import__("re").compile(r"^[A-Za-z]{0,6}[-_]?\d+[A-Za-z]?$")


def _repair_overflow(row: list, n_headers: int, list_cols: list) -> list:
    """Répare une ligne CSV dont une colonne « liste » (prédécesseurs, compétences)
    a été écrite avec le même séparateur que le fichier (ex. « a;b » dans un CSV « ; »).
    Les cellules en trop sont fusionnées (avec « , ») dans la bonne colonne liste.
    `list_cols` : indices des colonnes liste, dans l'ordre ; une colonne de
    prédécesseurs (marquée par un tuple ('pred', idx)) n'absorbe que des IDs d'opération."""
    row = list(row)
    extra = len(row) - n_headers
    if extra <= 0:
        return row
    for spec in list_cols:
        if extra <= 0:
            break
        if spec is None:
            continue
        is_pred = isinstance(spec, tuple)
        idx = spec[1] if is_pred else spec
        if idx is None or idx >= len(row):
            continue
        if is_pred:
            k = 0
            while idx + k < len(row) and _OP_ID_RE.match(str(row[idx + k]).strip() or "-"):
                k += 1
            take = min(max(0, k - 1), extra)
        else:
            take = extra
        if take:
            merged = ",".join(c.strip() for c in row[idx: idx + take + 1] if str(c).strip())
            row = row[:idx] + [merged] + row[idx + take + 1:]
            extra -= take
    # reste éventuel : cellules vides finales superflues (« ;; » en fin de ligne)
    while extra > 0 and row and not str(row[-1]).strip():
        row = row[:-1]
        extra -= 1
    return row


def parse_sam_csv(filepath: Path, delimiter: str = ";") -> list[Operation]:
    """
    Parse un fichier CSV SAM et retourne la liste des opérations.
    Détecte automatiquement le délimiteur si pas fourni.
    """
    operations = []
    
    with filepath.open("r", encoding="utf-8-sig") as f:
        # Détecter délimiteur
        sample = f.read(2048)
        f.seek(0)
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=";,\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            pass  # Utilise delimiter par défaut
        
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)
    
    if not rows:
        raise ValueError("Fichier vide")
    
    headers = rows[0]
    data_rows = rows[1:]
    
    # Mapping colonnes
    col_op_id = _match_column(headers, SAM_COLUMN_MAPPING["op_id"])
    col_name = _match_column(headers, SAM_COLUMN_MAPPING["name"])
    col_duration = _match_column(headers, SAM_COLUMN_MAPPING["duration"])
    col_predecessors = _match_column(headers, SAM_COLUMN_MAPPING["predecessors"])
    col_machine = _match_column(headers, SAM_COLUMN_MAPPING["machine_type"])
    col_skills = _match_column(headers, SAM_COLUMN_MAPPING["skills"])
    col_section = _match_column(headers, SAM_COLUMN_MAPPING["section"])
    col_optional = _match_column(headers, SAM_COLUMN_MAPPING["optional"])
    
    if col_op_id is None or col_duration is None:
        raise ValueError(f"Colonnes obligatoires manquantes. Trouvées: {headers}. "
                         f"Requis: OpID, Duration. Mapping: OpID={col_op_id}, Duration={col_duration}")
    
    for i, row in enumerate(data_rows, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        row = _repair_overflow(row, len(headers), [("pred", col_predecessors), col_skills])
        
        try:
            op_id = row[col_op_id].strip() if col_op_id < len(row) else f"OP{i}"
            if not op_id:
                continue
            
            name = row[col_name].strip() if col_name is not None and col_name < len(row) else op_id
            
            # Durée: gérer virgule décimale française
            duration_str = row[col_duration].strip().replace(",", ".") if col_duration < len(row) else "0"
            duration = float(duration_str) if duration_str else 0.0
            
            predecessors = []
            if col_predecessors is not None and col_predecessors < len(row):
                pred_str = row[col_predecessors].strip()
                if pred_str:
                    predecessors = [p.strip() for p in pred_str.replace(",", ";").split(";") if p.strip()]
            
            machine_type = ""
            if col_machine is not None and col_machine < len(row):
                machine_type = row[col_machine].strip()
            
            skills = []
            if col_skills is not None and col_skills < len(row):
                skills_str = row[col_skills].strip()
                if skills_str:
                    skills = [s.strip() for s in skills_str.replace(",", ";").split(";") if s.strip()]
            
            section = ""
            if col_section is not None and col_section < len(row):
                section = row[col_section].strip()
            
            optional = False
            if col_optional is not None and col_optional < len(row):
                opt_str = row[col_optional].strip().lower()
                optional = opt_str in ("1", "true", "oui", "yes", "x")
            
            operations.append(Operation(
                id=op_id,
                name=name,
                duration=duration,
                predecessors=predecessors,
                machine_type=machine_type,
                required_skills=skills,
                section=section,
                optional=optional,
            ))
        except Exception as e:
            print(f"⚠️  Ligne {i} ignorée: {e} | Row: {row}")
    
    return operations


def parse_sam_excel(filepath: Path, sheet_name: Optional[str] = None) -> list[Operation]:
    """Parse un fichier Excel SAM (requiert openpyxl)."""
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl requis: pip install openpyxl")
    
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Feuille vide")
    
    headers = [str(h) if h else "" for h in rows[0]]
    data_rows = [[str(c) if c is not None else "" for c in row] for row in rows[1:]]
    
    # Réutiliser la logique CSV
    col_op_id = _match_column(headers, SAM_COLUMN_MAPPING["op_id"])
    col_name = _match_column(headers, SAM_COLUMN_MAPPING["name"])
    col_duration = _match_column(headers, SAM_COLUMN_MAPPING["duration"])
    col_predecessors = _match_column(headers, SAM_COLUMN_MAPPING["predecessors"])
    col_machine = _match_column(headers, SAM_COLUMN_MAPPING["machine_type"])
    col_skills = _match_column(headers, SAM_COLUMN_MAPPING["skills"])
    col_section = _match_column(headers, SAM_COLUMN_MAPPING["section"])
    col_optional = _match_column(headers, SAM_COLUMN_MAPPING["optional"])
    
    if col_op_id is None or col_duration is None:
        raise ValueError(f"Colonnes obligatoires manquantes. Headers: {headers}")
    
    operations = []
    for i, row in enumerate(data_rows, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        
        op_id = row[col_op_id].strip() if col_op_id < len(row) else f"OP{i}"
        if not op_id:
            continue
        
        name = row[col_name].strip() if col_name is not None and col_name < len(row) else op_id
        duration = float(row[col_duration].strip().replace(",", ".")) if col_duration < len(row) and row[col_duration].strip() else 0.0
        
        predecessors = []
        if col_predecessors is not None and col_predecessors < len(row):
            pred_str = row[col_predecessors].strip()
            if pred_str:
                predecessors = [p.strip() for p in pred_str.replace(",", ";").split(";") if p.strip()]
        
        machine_type = row[col_machine].strip() if col_machine is not None and col_machine < len(row) else ""
        skills = []
        if col_skills is not None and col_skills < len(row):
            s = row[col_skills].strip()
            if s:
                skills = [sk.strip() for sk in s.replace(",", ";").split(";") if sk.strip()]
        section = row[col_section].strip() if col_section is not None and col_section < len(row) else ""
        optional = False
        if col_optional is not None and col_optional < len(row):
            opt = row[col_optional].strip().lower()
            optional = opt in ("1", "true", "oui", "yes", "x")
        
        operations.append(Operation(
            id=op_id, name=name, duration=duration, predecessors=predecessors,
            machine_type=machine_type, required_skills=skills, section=section, optional=optional
        ))
    
    return operations


def parse_sam_file(filepath: Path) -> list[Operation]:
    """Auto-détecte le format et parse."""
    suffix = filepath.suffix.lower()
    if suffix == ".csv":
        return parse_sam_csv(filepath)
    elif suffix in (".xlsx", ".xls"):
        return parse_sam_excel(filepath)
    elif suffix == ".json":
        # Format JSON natif
        with filepath.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [Operation(**op) for op in data]
    else:
        raise ValueError(f"Format non supporté: {suffix}. Utilisez .csv, .xlsx ou .json")


def create_problem_from_sam(
    sam_path: Path,
    workstations_path: Path,
    workers_path: Path,
    target_cycle_time: float,
    problem_name: str = "",
    algorithm: SolverAlgorithm = SolverAlgorithm.CP_SAT,
    objective: OptimizationObjective = OptimizationObjective.MIN_STATIONS,
) -> LineBalancingProblem:
    """Charge un problème complet depuis 3 fichiers (SAM + postes + ouvriers)."""
    operations = parse_sam_file(sam_path)
    workstations = parse_workstations_file(workstations_path)
    workers = parse_workers_file(workers_path)
    
    name = problem_name or sam_path.stem
    
    problem = LineBalancingProblem(
        name=name,
        target_cycle_time=target_cycle_time,
        operations=operations,
        workstations=workstations,
        workers=workers,
        algorithm=algorithm,
        objective=objective,
    )
    
    errors = problem.validate()
    if errors:
        print(f"⚠️  Avertissements validation pour '{name}':")
        for err in errors:
            print(f"   - {err}")
    
    return problem


# --- Parsers pour postes de travail et ouvriers ---

WORKSTATION_COLUMNS = {
    "id": ["id", "code", "station_id", "poste_id"],
    "name": ["name", "nom", "designation", "libelle"],
    "machine_type": ["machine_type", "machine", "equipment", "type_machine", "equipement"],
    "available": ["available", "disponible", "actif", "active"],
    "max_workers": ["max_workers", "max_ouvriers", "capacity", "capacite"],
    "section": ["section", "department", "atelier", "area", "zone"],
}

WORKER_COLUMNS = {
    "id": ["id", "code", "worker_id", "matricule", "employee_id", "ouvrier_id", "ouvrier-id", "operateur_id", "operateur-id", "personnel_id"],
    "name": ["name", "nom", "prenom", "full_name", "nom_complet"],
    "skills": ["skills", "skill", "competences", "competence", "qualifications", "qualification", "competence"],
    "efficiency": ["efficiency", "efficacite", "performance", "coefficient", "ratio"],
    "available": ["available", "disponible", "actif", "active", "present"],
    "assigned_station": ["assigned_station", "poste", "station", "affectation"],
}


def _parse_generic_csv(filepath: Path, column_map: dict) -> list[dict]:
    """Parse CSV générique avec mapping colonnes."""
    with filepath.open("r", encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=";,\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ";"
        
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = list(reader)
    
    if not rows:
        return []
    
    # Normaliser headers
    fieldnames = reader.fieldnames or []
    norm_to_original = {_normalize_header(h): h for h in fieldnames}
    
    # Trouver indices
    col_indices = {}
    for key, possible in column_map.items():
        for p in possible:
            norm_p = _normalize_header(p)
            if norm_p in norm_to_original:
                col_indices[key] = norm_to_original[norm_p]
                break
    
    results = []
    for row in rows:
        item = {}
        for key, col in col_indices.items():
            item[key] = row.get(col, "").strip()
        results.append(item)
    
    return results


def parse_workstations_file(filepath: Path) -> list[Workstation]:
    """Parse fichier postes (CSV/Excel/JSON)."""
    suffix = filepath.suffix.lower()
    if suffix == ".json":
        with filepath.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [Workstation(**ws) for ws in data]
    
    if suffix in (".xlsx", ".xls"):
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl requis: pip install openpyxl")
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h else "" for h in rows[0]]
        data_rows = [[str(c) if c is not None else "" for c in row] for row in rows[1:]]
    else:
        with filepath.open("r", encoding="utf-8-sig") as f:
            sample = f.read(2048)
            f.seek(0)
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample, delimiters=";,\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ";"
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)
        if not rows:
            return []
        headers = rows[0]
        data_rows = rows[1:]
    
    # Mapping colonnes
    col_map = {}
    norm_headers = [_normalize_header(h) for h in headers]
    for key, possible in WORKSTATION_COLUMNS.items():
        for p in possible:
            np = _normalize_header(p)
            if np in norm_headers:
                col_map[key] = norm_headers.index(np)
                break
    
    workstations = []
    for row in data_rows:
        ws_id = row[col_map.get("id", 0)] if "id" in col_map and col_map["id"] < len(row) else ""
        if not ws_id:
            continue
        name = row[col_map["name"]] if "name" in col_map and col_map["name"] < len(row) else ws_id
        machine_type = row[col_map["machine_type"]] if "machine_type" in col_map and col_map["machine_type"] < len(row) else ""
        available = True
        if "available" in col_map and col_map["available"] < len(row):
            av = row[col_map["available"]].strip().lower()
            available = av not in ("0", "false", "non", "no", "")
        max_workers = 1
        if "max_workers" in col_map and col_map["max_workers"] < len(row):
            try:
                max_workers = int(row[col_map["max_workers"]].strip() or "1")
            except ValueError:
                pass
        section = row[col_map["section"]] if "section" in col_map and col_map["section"] < len(row) else ""
        
        workstations.append(Workstation(
            id=ws_id, name=name, machine_type=machine_type,
            available=available, max_workers=max_workers, section=section
        ))
    
    return workstations


def parse_workers_file(filepath: Path) -> list[Worker]:
    """Parse fichier ouvriers (CSV/Excel/JSON)."""
    suffix = filepath.suffix.lower()
    if suffix == ".json":
        with filepath.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [Worker(**w) for w in data]
    
    if suffix in (".xlsx", ".xls"):
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl requis: pip install openpyxl")
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h else "" for h in rows[0]]
        data_rows = [[str(c) if c is not None else "" for c in row] for row in rows[1:]]
    else:
        with filepath.open("r", encoding="utf-8-sig") as f:
            sample = f.read(2048)
            f.seek(0)
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample, delimiters=";,\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ";"
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)
        if not rows:
            return []
        headers = rows[0]
        data_rows = rows[1:]
    
    col_map = {}
    norm_headers = [_normalize_header(h) for h in headers]
    for key, possible in WORKER_COLUMNS.items():
        for p in possible:
            np = _normalize_header(p)
            if np in norm_headers:
                col_map[key] = norm_headers.index(np)
                break
    
    workers = []
    for row in data_rows:
        if row and len(row) > len(headers):
            row = _repair_overflow(row, len(headers), [col_map.get("skills")])
        w_id = row[col_map.get("id", 0)] if "id" in col_map and col_map["id"] < len(row) else ""
        if not w_id:
            continue
        name = row[col_map["name"]] if "name" in col_map and col_map["name"] < len(row) else w_id
        
        skills = []
        if "skills" in col_map and col_map["skills"] < len(row):
            s = row[col_map["skills"]].strip()
            if s:
                skills = [sk.strip() for sk in s.replace(",", ";").split(";") if sk.strip()]
        
        efficiency = 1.0
        if "efficiency" in col_map and col_map["efficiency"] < len(row):
            try:
                efficiency = float(row[col_map["efficiency"]].strip().replace(",", ".") or "1.0")
            except ValueError:
                pass
        
        available = True
        if "available" in col_map and col_map["available"] < len(row):
            av = row[col_map["available"]].strip().lower()
            available = av not in ("0", "false", "non", "no", "")
        
        assigned_station = None
        if "assigned_station" in col_map and col_map["assigned_station"] < len(row):
            ass = row[col_map["assigned_station"]].strip()
            if ass:
                assigned_station = ass
        
        workers.append(Worker(
            id=w_id, name=name, skills=skills,
            efficiency=efficiency, available=available,
            assigned_station=assigned_station
        ))
    
    return workers


# --- Export ---

def export_problem_to_json(problem: LineBalancingProblem, filepath: Path) -> None:
    """Exporte le problème en JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        f.write(problem.to_json())


def export_result_to_json(result, filepath: Path) -> None:
    """Exporte le résultat en JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        f.write(result.to_json())


def export_result_to_excel(result, filepath: Path) -> None:
    """Exporte résultat détaillé en Excel (requiert openpyxl)."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise ImportError("openpyxl requis: pip install openpyxl")
    
    wb = openpyxl.Workbook()
    
    # Feuille Résumé
    ws_summary = wb.active
    ws_summary.title = "Résumé"
    headers = ["Indicateur", "Valeur"]
    ws_summary.append(headers)
    for cell in ws_summary[1]:
        cell.font = Font(bold=True)
    
    ws_summary.append(["Problème", result.problem.name])
    ws_summary.append(["Solveur", result.solver_used])
    ws_summary.append(["Statut", result.status])
    ws_summary.append(["Temps résolution (s)", round(result.solve_time_seconds, 2)])
    ws_summary.append(["Stations utilisées", result.stations_used])
    ws_summary.append(["Cycle time cible (min)", result.problem.target_cycle_time])
    ws_summary.append(["Cycle time réel (min)", round(result.actual_cycle_time, 2)])
    ws_summary.append(["Efficacité ligne (%)", round(result.efficiency, 1)])
    ws_summary.append(["Balance delay (%)", round(result.balance_delay, 1)])
    ws_summary.append(["Smoothness index", round(result.smoothness_index, 2)])
    
    # Feuille Détail stations
    ws_stations = wb.create_sheet("Détail Postes")
    st_headers = ["Station", "Temps total (min)", "Charge (%)", "Opérations", "Ouvriers", "Écart cible (min)"]
    ws_stations.append(st_headers)
    for cell in ws_stations[1]:
        cell.font = Font(bold=True)
    
    for sd in result.station_details:
        ws_stations.append([
            sd["station"],
            round(sd["total_time"], 2),
            round(sd["load_pct"], 1),
            ", ".join(sd["operations"]),
            ", ".join(sd["workers"]) if sd["workers"] else "—",
            round(sd["total_time"] - result.problem.target_cycle_time, 2),
        ])
    
    # Feuille Opérations
    ws_ops = wb.create_sheet("Opérations")
    op_headers = ["OpID", "Nom", "Durée", "Station assignée", "Prédécesseurs", "Machine", "Compétences", "Section"]
    ws_ops.append(op_headers)
    for cell in ws_ops[1]:
        cell.font = Font(bold=True)
    
    for op in result.problem.operations:
        station = result.operation_assignments.get(op.id, "—")
        ws_ops.append([
            op.id, op.name, op.duration, station,
            "; ".join(op.predecessors), op.machine_type,
            "; ".join(op.required_skills), op.section
        ])
    
    # Ajustement largeurs
    for ws in (ws_summary, ws_stations, ws_ops):
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb.save(filepath)


def export_gantt_data(result, filepath: Path) -> None:
    """Exporte données pour diagramme de Gantt (JSON pour JS)."""
    # Calcule dates début/fin relatives
    station_start = {}
    current_time = 0.0
    for sd in result.station_details:
        station_start[sd["station"]] = current_time
        current_time += sd["total_time"]
    
    gantt_data = {
        "problem": result.problem.name,
        "cycle_time": result.problem.target_cycle_time,
        "stations": []
    }
    
    for sd in result.station_details:
        st = sd["station"]
        ops = []
        t = 0.0
        for op_id in sd["operations"]:
            op = result.problem.get_operation(op_id)
            if op:
                ops.append({
                    "id": op.id,
                    "name": op.name,
                    "start": round(t, 3),
                    "end": round(t + op.duration, 3),
                    "duration": op.duration,
                })
                t += op.duration
        gantt_data["stations"].append({
            "station": st,
            "start": round(station_start[st], 3),
            "end": round(station_start[st] + sd["total_time"], 3),
            "operations": ops,
            "workers": sd["workers"],
        })
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(gantt_data, f, indent=2, ensure_ascii=False)


def generate_sam_template(filepath: Path, format: str = "csv") -> None:
    """Génère un fichier modèle SAM vide avec headers."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    if format == "csv":
        headers = [
            "Op_ID", "Description", "SAM_min", "Predecesseurs",
            "Type_Machine", "Competences", "Section", "Optionnel"
        ]
        examples = [
            ["OP010", "Préparation pièces", "0.45", "", "table_travail", "lecture_plan", "Montage", ""],
            ["OP020", "Montage corps-devant", "1.20", "OP010", "piqueuse_plate", "couture_droite", "Montage", ""],
            ["OP030", "Montage manches", "0.95", "OP010", "piqueuse_plate", "couture_droite", "Montage", ""],
            ["OP040", "Fermeture côtés", "0.80", "OP020;OP030", "surjeteuse_5_fils", "surjet", "Montage", ""],
            ["OP050", "Pose col", "1.10", "OP040", "piqueuse_plate", "couture_courbe", "Montage", ""],
            ["OP060", "Piqure col", "0.65", "OP050", "piqueuse_plate", "piqure_apparente", "Finition", ""],
            ["OP070", "Ourlet bas", "0.55", "OP040", "piqueuse_2_aiguilles", "ourlet", "Finition", ""],
            ["OP080", "Contrôle final", "0.30", "OP060;OP070", "table_controle", "controle_qualite", "Qualite", ""],
            ["OP090", "Repassage/Emballage", "0.40", "OP080", "presse_vapeur", "repassage", "Expedition", ""],
        ]
        with filepath.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            writer.writerows(examples)
    
    elif format == "xlsx":
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            raise ImportError("openpyxl requis: pip install openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "SAM"
        headers = [
            "Op_ID", "Description", "SAM_min", "Predecesseurs",
            "Type_Machine", "Competences", "Section", "Optionnel"
        ]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        examples = [
            ["OP010", "Préparation pièces", 0.45, "", "table_travail", "lecture_plan", "Montage", False],
            ["OP020", "Montage corps-devant", 1.20, "OP010", "piqueuse_plate", "couture_droite", "Montage", False],
            ["OP030", "Montage manches", 0.95, "OP010", "piqueuse_plate", "couture_droite", "Montage", False],
            ["OP040", "Fermeture côtés", 0.80, "OP020;OP030", "surjeteuse_5_fils", "surjet", "Montage", False],
            ["OP050", "Pose col", 1.10, "OP040", "piqueuse_plate", "couture_courbe", "Montage", False],
            ["OP060", "Piqure col", 0.65, "OP050", "piqueuse_plate", "piqure_apparente", "Finition", False],
            ["OP070", "Ourlet bas", 0.55, "OP040", "piqueuse_2_aiguilles", "ourlet", "Finition", False],
            ["OP080", "Contrôle final", 0.30, "OP060;OP070", "table_controle", "controle_qualite", "Qualite", False],
            ["OP090", "Repassage/Emballage", 0.40, "OP080", "presse_vapeur", "repassage", "Expedition", False],
        ]
        for row in examples:
            ws.append(row)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        wb.save(filepath)
    
    elif format == "json":
        examples = [
            {"id": "OP010", "name": "Préparation pièces", "duration": 0.45, "predecessors": [], "machine_type": "table_travail", "required_skills": ["lecture_plan"], "section": "Montage", "optional": False},
            {"id": "OP020", "name": "Montage corps-devant", "duration": 1.20, "predecessors": ["OP010"], "machine_type": "piqueuse_plate", "required_skills": ["couture_droite"], "section": "Montage", "optional": False},
            {"id": "OP030", "name": "Montage manches", "duration": 0.95, "predecessors": ["OP010"], "machine_type": "piqueuse_plate", "required_skills": ["couture_droite"], "section": "Montage", "optional": False},
            {"id": "OP040", "name": "Fermeture côtés", "duration": 0.80, "predecessors": ["OP020", "OP030"], "machine_type": "surjeteuse_5_fils", "required_skills": ["surjet"], "section": "Montage", "optional": False},
            {"id": "OP050", "name": "Pose col", "duration": 1.10, "predecessors": ["OP040"], "machine_type": "piqueuse_plate", "required_skills": ["couture_courbe"], "section": "Montage", "optional": False},
            {"id": "OP060", "name": "Piqure col", "duration": 0.65, "predecessors": ["OP050"], "machine_type": "piqueuse_plate", "required_skills": ["piqure_apparente"], "section": "Finition", "optional": False},
            {"id": "OP070", "name": "Ourlet bas", "duration": 0.55, "predecessors": ["OP040"], "machine_type": "piqueuse_2_aiguilles", "required_skills": ["ourlet"], "section": "Finition", "optional": False},
            {"id": "OP080", "name": "Contrôle final", "duration": 0.30, "predecessors": ["OP060", "OP070"], "machine_type": "table_controle", "required_skills": ["controle_qualite"], "section": "Qualite", "optional": False},
            {"id": "OP090", "name": "Repassage/Emballage", "duration": 0.40, "predecessors": ["OP080"], "machine_type": "presse_vapeur", "required_skills": ["repassage"], "section": "Expedition", "optional": False},
        ]
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("w", encoding="utf-8") as f:
            json.dump(examples, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Modèle SAM généré: {filepath}")


def generate_workstations_template(filepath: Path, format: str = "csv") -> None:
    """Génère modèle fichier postes de travail."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    if format == "csv":
        headers = ["Poste_ID", "Nom", "Type_Machine", "Disponible", "Max_Ouvriers", "Section"]
        examples = [
            ["WS01", "Poste préparation", "table_travail", "Oui", "1", "Montage"],
            ["WS02", "Piqueuse plate 1", "piqueuse_plate", "Oui", "1", "Montage"],
            ["WS03", "Piqueuse plate 2", "piqueuse_plate", "Oui", "1", "Montage"],
            ["WS04", "Surjeteuse 5 fils", "surjeteuse_5_fils", "Oui", "1", "Montage"],
            ["WS05", "Piqueuse 2 aiguilles", "piqueuse_2_aiguilles", "Oui", "1", "Finition"],
            ["WS06", "Poste contrôle", "table_controle", "Oui", "1", "Qualite"],
            ["WS07", "Presse vapeur", "presse_vapeur", "Oui", "1", "Expedition"],
        ]
        with filepath.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            writer.writerows(examples)
    
    elif format == "xlsx":
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            raise ImportError("openpyxl requis: pip install openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Postes"
        headers = ["Poste_ID", "Nom", "Type_Machine", "Disponible", "Max_Ouvriers", "Section"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        examples = [
            ["WS01", "Poste préparation", "table_travail", True, 1, "Montage"],
            ["WS02", "Piqueuse plate 1", "piqueuse_plate", True, 1, "Montage"],
            ["WS03", "Piqueuse plate 2", "piqueuse_plate", True, 1, "Montage"],
            ["WS04", "Surjeteuse 5 fils", "surjeteuse_5_fils", True, 1, "Montage"],
            ["WS05", "Piqueuse 2 aiguilles", "piqueuse_2_aiguilles", True, 1, "Finition"],
            ["WS06", "Poste contrôle", "table_controle", True, 1, "Qualite"],
            ["WS07", "Presse vapeur", "presse_vapeur", True, 1, "Expedition"],
        ]
        for row in examples:
            ws.append(row)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        wb.save(filepath)
    
    print(f"✅ Modèle postes généré: {filepath}")


def generate_workers_template(filepath: Path, format: str = "csv") -> None:
    """Génère modèle fichier ouvriers."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    if format == "csv":
        headers = ["Ouvrier_ID", "Nom", "Competences", "Efficacite", "Disponible", "Poste_Assigne"]
        examples = [
            ["W001", "Marie D.", "lecture_plan;couture_droite;couture_courbe", "1.0", "Oui", ""],
            ["W002", "Ahmed B.", "couture_droite;surjet", "1.05", "Oui", ""],
            ["W003", "Sophie L.", "couture_droite;piqure_apparente;ourlet", "0.95", "Oui", ""],
            ["W004", "Karim M.", "surjet;couture_droite", "1.1", "Oui", ""],
            ["W005", "Fatou S.", "controle_qualite;lecture_plan", "1.0", "Oui", ""],
            ["W006", "Youssef A.", "repassage;couture_droite", "1.0", "Oui", ""],
        ]
        with filepath.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            writer.writerows(examples)
    
    elif format == "xlsx":
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            raise ImportError("openpyxl requis: pip install openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Ouvriers"
        headers = ["Ouvrier_ID", "Nom", "Competences", "Efficacite", "Disponible", "Poste_Assigne"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        examples = [
            ["W001", "Marie D.", "lecture_plan;couture_droite;couture_courbe", 1.0, True, ""],
            ["W002", "Ahmed B.", "couture_droite;surjet", 1.05, True, ""],
            ["W003", "Sophie L.", "couture_droite;piqure_apparente;ourlet", 0.95, True, ""],
            ["W004", "Karim M.", "surjet;couture_droite", 1.1, True, ""],
            ["W005", "Fatou S.", "controle_qualite;lecture_plan", 1.0, True, ""],
            ["W006", "Youssef A.", "repassage;couture_droite", 1.0, True, ""],
        ]
        for row in examples:
            ws.append(row)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        wb.save(filepath)
    
    print(f"✅ Modèle ouvriers généré: {filepath}")