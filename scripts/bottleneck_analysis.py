#!/usr/bin/env python3
"""
Analyse des goulets d'étranglement par poste de travail.

Utilise Pandas pour charger et analyser les temps de cycle
depuis un résultat d'équilibrage (JSON) ou directement depuis
les fichiers SAM + postes de travail.

Usage:
  python scripts/bottleneck_analysis.py --result results/balance_result.json
  python scripts/bottleneck_analysis.py --sam data/samples/sam_chemise_homme.csv \
                                        --workstations data/samples/workstations_chemise.csv \
                                        --workers data/samples/workers_chemise.csv \
                                        --cycle-time 1.5 --solver rpw
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("pandas est requis: pip install pandas")
    sys.exit(1)

HAS_EXCEL = False
try:
    import openpyxl  # noqa: F401

    HAS_EXCEL = True
except ImportError:
    pass


def load_from_result_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def compute_bottleneck_kpis(stations: list[dict], target_cycle: float) -> pd.DataFrame:
    """Calcule les KPIs par station et retourne un DataFrame."""
    rows = []
    for s in stations:
        load_pct = s.get("load_pct", 0.0)
        total_time = s.get("total_time", 0.0)
        rows.append(
            {
                "station": s["station"],
                "workstation": s.get("workstation", ""),
                "total_time_min": total_time,
                "load_pct": load_pct,
                "delta_cible_min": total_time - target_cycle,
                "delta_cible_pct": (total_time - target_cycle) / target_cycle * 100,
                "n_operations": len(s.get("operations", [])),
                "n_workers": len(s.get("workers", [])),
                "operations": ", ".join(s.get("operations", [])),
                "workers": ", ".join(s.get("workers", [])),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["is_bottleneck"] = df["total_time_min"] > target_cycle * 1.01
    df["is_near_bottleneck"] = (df["total_time_min"] >= target_cycle * 0.9) & (
        df["total_time_min"] <= target_cycle * 1.01
    )
    df["idle_min"] = (target_cycle - df["total_time_min"]).clip(lower=0)
    df["idle_pct"] = (df["idle_min"] / target_cycle * 100).round(1)
    return df


def extract_operation_details(result: dict) -> pd.DataFrame:
    """Extrait les opérations avec leur durée et affectation."""
    ops = result.get("problem", {}).get("operations", [])
    assignments = result.get("operation_assignments", {})
    rows = []
    for op in ops:
        rows.append(
            {
                "op_id": op["id"],
                "name": op["name"],
                "duration_min": op["duration"],
                "machine_type": op.get("machine_type", ""),
                "section": op.get("section", ""),
                "station": assignments.get(op["id"], -1),
            }
        )
    return pd.DataFrame(rows)


def extract_resource_matrix(result: dict) -> pd.DataFrame:
    """Matrice opérations × stations (pour analyse détaillée)."""
    ops = result.get("problem", {}).get("operations", [])
    assignments = result.get("operation_assignments", {})
    stations = result.get("station_details", [])
    n_stations = max((s["station"] for s in stations), default=0)

    rows = []
    for op in ops:
        station = assignments.get(op["id"], -1)
        row = {
            "op_id": op["id"],
            "name": op["name"],
            "duration_min": op["duration"],
            "machine_type": op.get("machine_type", ""),
            "section": op.get("section", ""),
        }
        for s in range(1, n_stations + 1):
            key = f"station_{s}"
            if station == s:
                row[key] = op["duration"]
            else:
                row[key] = 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_by_attribute(df_ops: pd.DataFrame, by: str) -> pd.DataFrame:
    """Agrège le temps par attribut (machine_type, section, etc.)."""
    grouped = df_ops.groupby(by).agg(
        total_duration_min=("duration_min", "sum"),
        n_operations=("op_id", "count"),
    ).reset_index()
    grouped.columns = [by, "total_duration_min", "n_operations"]
    return grouped.sort_values("total_duration_min", ascending=False)


def bottleneck_impact_analysis(df_stations: pd.DataFrame) -> pd.DataFrame:
    """Analyse l'impact de chaque goulot sur la ligne."""
    if df_stations.empty:
        return df_stations
    df = df_stations.copy()
    total_idle = df["idle_min"].sum()
    df["bottleneck_share_pct"] = (df["total_time_min"] / df["total_time_min"].sum() * 100).round(1)
    df["impact_idle_pct"] = np.where(
        total_idle > 0,
        (df["idle_min"] / total_idle * 100).round(1),
        0.0,
    )
    return df


def print_report(df_stations: pd.DataFrame, df_ops: pd.DataFrame, target_cycle: float):
    """Affiche le rapport d'analyse dans la console."""
    print("=" * 72)
    print("🔍 ANALYSE DES GOULETS D'ÉTRANGLEMENT")
    print("=" * 72)
    print(f"⏱️  Temps de cycle cible: {target_cycle:.3f} min ({60 / target_cycle:.1f} pièces/h)")
    print()

    if df_stations.empty:
        print("⚠️  Aucune donnée station disponible.")
        return

    # Vue d'ensemble
    print("📊 RÉSUMÉ DES POSTES")
    print("-" * 72)
    summary = df_stations[
        ["station", "workstation", "total_time_min", "load_pct", "n_operations", "n_workers"]
    ].copy()
    summary.columns = [
        "Poste", "Machine", "Tps cycle (min)", "Charge (%)", "#Ops", "#Ouvriers"
    ]
    print(summary.to_string(index=False))
    print()

    # Goulets
    bottlenecks = df_stations[df_stations["is_bottleneck"]]
    near_bottlenecks = df_stations[df_stations["is_near_bottleneck"]]

    if not bottlenecks.empty:
        print("🔴 GOULETS D'ÉTRANGLEMENT (dépassement du temps de cycle cible)")
        print("-" * 72)
        for _, row in bottlenecks.iterrows():
            over = row["delta_cible_min"]
            print(
                f"  ⚠️  Poste {int(row['station'])} "
                f"({row['workstation'] or 'non assigné'}): "
                f"{row['total_time_min']:.3f} min "
                f"(+{over:.3f} min, {row['load_pct']:.1f}%)"
            )
        print()
    else:
        print("✅ Aucun goulot d'étranglement détecté.")
        print()

    if not near_bottlenecks.empty:
        print("🟡 POSTES PROCHES DE LA LIMITE (≥ 90 % charge)")
        print("-" * 72)
        for _, row in near_bottlenecks.iterrows():
            print(
                f"  ⚡ Poste {int(row['station'])} "
                f"({row['workstation'] or 'non assigné'}): "
                f"{row['total_time_min']:.3f} min ({row['load_pct']:.1f}%)"
            )
        print()

    # Impact des goulets
    df_impact = bottleneck_impact_analysis(df_stations)
    print("📈 IMPACT SUR LA LIGNE")
    print("-" * 72)
    top = df_impact.nlargest(3, "bottleneck_share_pct")
    for _, row in top.iterrows():
        print(
            f"  Poste {int(row['station'])} "
            f"→ {row['bottleneck_share_pct']:.1f}% du temps total de la ligne, "
            f"temps mort: {row['idle_min']:.3f} min/poste"
        )
    print()

    # Statistiques globales
    print("📉 STATISTIQUES GLOBALES")
    print("-" * 72)
    print(f"  Stations:                     {len(df_stations)}")
    print(f"  Temps poste moyen:            {df_stations['total_time_min'].mean():.3f} min")
    print(f"  Temps poste min:              {df_stations['total_time_min'].min():.3f} min")
    print(f"  Temps poste max:              {df_stations['total_time_min'].max():.3f} min")
    print(f"  Écart-type temps poste:       {df_stations['total_time_min'].std():.3f} min")
    print(f"  Charge moyenne:               {df_stations['load_pct'].mean():.1f}%")
    print(f"  Charge min:                   {df_stations['load_pct'].min():.1f}%")
    print(f"  Charge max:                   {df_stations['load_pct'].max():.1f}%")
    print(f"  Temps mort total ligne:       {df_stations['idle_min'].sum():.3f} min/pièce")
    total_idle_pct = df_stations["idle_min"].sum() / (target_cycle * len(df_stations)) * 100
    print(f"  Taux d'attente global:        {total_idle_pct:.1f}%")
    print()

    # Répartition section
    if not df_ops.empty:
        print("🏭 RÉPARTITION PAR SECTION")
        print("-" * 72)
        sec_df = analyze_by_attribute(df_ops, "section")
        sec_df.columns = ["Section", "Temps total (min)", "Nb opérations"]
        sec_df["% du total"] = (sec_df["Temps total (min)"] / sec_df["Temps total (min)"].sum() * 100).round(1)
        print(sec_df.to_string(index=False))
        print()

        print("⚙️  RÉPARTITION PAR TYPE MACHINE")
        print("-" * 72)
        mt_df = analyze_by_attribute(df_ops, "machine_type")
        mt_df.columns = ["Type machine", "Temps total (min)", "Nb opérations"]
        mt_df["% du total"] = (mt_df["Temps total (min)"] / mt_df["Temps total (min)"].sum() * 100).round(1)
        print(mt_df.to_string(index=False))
        print()

    # Recommandations
    print("💡 RECOMMANDATIONS")
    print("-" * 72)
    if not bottlenecks.empty:
        total_over = bottlenecks["delta_cible_min"].sum()
        print(f"  • Réduire le temps des {len(bottlenecks)} postes goulots "
              f"(excédent total: {total_over:.3f} min/pièce)")
        print(f"    → Augmenter la capacité (ajout ouvrier, meilleure méthode)")
        print(f"    → Réaffecter des opérations aux postes voisins (si possible)")
    else:
        print(f"  • La ligne est équilibrée, pas de goulot majeur.")
    if not near_bottlenecks.empty:
        print(f"  • Surveiller les {len(near_bottlenecks)} postes proches de la limite.")
    if df_stations["idle_min"].sum() > 0:
        worst_idle = df_stations.nlargest(1, "idle_min").iloc[0]
        print(
            f"  • Poste {int(worst_idle['station'])} a le plus de temps mort "
            f"({worst_idle['idle_min']:.3f} min). "
            f"Envisager de lui ajouter des opérations."
        )
    print()


def export_report(df_stations: pd.DataFrame, df_ops: pd.DataFrame, path: Path, target_cycle: float, project_name: str = "Analyse"):
    """Exporte les résultats : CSV + PDF."""
    path.mkdir(parents=True, exist_ok=True)

    df_stations.to_csv(path / "stations.csv", index=False, sep=";")
    df_ops.to_csv(path / "operations.csv", index=False, sep=";")
    print(f"💾 CSV exporté dans {path}/")

    if HAS_EXCEL:
        xlsx_path = path / "bottleneck_analysis.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            df_stations.to_excel(writer, sheet_name="Postes", index=False)
            df_ops.to_excel(writer, sheet_name="Opérations", index=False)
        print(f"💾 Excel exporté: {xlsx_path}")

    # PDF
    try:
        from engine.report_generator import BalanceReport
        stations_dict = df_stations.to_dict(orient="records")
        ops_dict = df_ops.to_dict(orient="records")
        pdf_path = path / "bottleneck_analysis.pdf"
        BalanceReport.bottleneck_analysis(stations_dict, ops_dict, target_cycle, pdf_path, project_name)
        print(f"💾 PDF exporté: {pdf_path}")
    except ImportError:
        print("⚠️  reportlab non installé, PDF ignoré (pip install reportlab)")
    except Exception as e:
        print(f"⚠️  Erreur PDF: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyse des goulets d'étranglement (Pandas)"
    )
    parser.add_argument(
        "--result", "-r", type=Path,
        help="Fichier résultat JSON (sortie de balance.py --export)"
    )
    parser.add_argument("--sam", "-s", type=Path, help="Fichier SAM CSV")
    parser.add_argument("--workstations", "-w", type=Path, help="Fichier postes CSV")
    parser.add_argument("--workers", "-k", type=Path, help="Fichier ouvriers CSV")
    parser.add_argument("--cycle-time", "-c", type=float, help="Temps de cycle cible (min)")
    parser.add_argument(
        "--solver", choices=["rpw", "cp-sat"], default="rpw",
        help="Algorithme d'équilibrage"
    )
    parser.add_argument("--export", "-e", type=Path, help="Dossier d'export CSV/Excel")
    parser.add_argument("--verbose", "-v", action="store_true", help="Afficher les matrices détaillées")

    args = parser.parse_args()

    # ── Chargement des données ──────────────────────────────────
    result: dict = {}
    target_cycle: float = 0.0

    if args.result:
        if not args.result.exists():
            print(f"❌ Fichier introuvable: {args.result}")
            sys.exit(1)
        result = load_from_result_json(args.result)
        target_cycle = result.get("problem", {}).get("target_cycle_time", 0.0)
        if args.verbose:
            print(f"📥 Résultat chargé: {args.result}")
    elif args.sam and args.workstations and args.workers and args.cycle_time:
        from engine.parsers import create_problem_from_sam
        from engine.solvers import solve_rpw, solve_cp_sat

        target_cycle = args.cycle_time
        solver_algo = args.solver
        print(f"📥 Chargement SAM: {args.sam}")
        problem = create_problem_from_sam(
            sam_path=args.sam,
            workstations_path=args.workstations,
            workers_path=args.workers,
            target_cycle_time=target_cycle,
        )
        print(f"   → {len(problem.operations)} opérations, "
              f"{len(problem.workstations)} postes, "
              f"{len(problem.workers)} ouvriers")
        print(f"🔧 Résolution ({solver_algo})...")
        if solver_algo == "rpw":
            result_obj = solve_rpw(problem)
        else:
            result_obj = solve_cp_sat(problem)
        result = json.loads(result_obj.to_json())
        print("   ✅ Équilibrage terminé")
    else:
        parser.print_help()
        print()
        print("⚠️  Fournissez --result OU l'ensemble --sam + --workstations + --workers + --cycle-time")
        sys.exit(1)

    if target_cycle <= 0:
        print("⚠️  Temps de cycle cible non disponible ou invalide")
        target_cycle = max(
            (s.get("total_time", 0) for s in result.get("station_details", [])),
            default=1.0,
        )
        print(f"   → Utilisation du temps max observé: {target_cycle:.3f} min")

    # ── Analyse ─────────────────────────────────────────────────
    stations = result.get("station_details", [])
    df_stations = compute_bottleneck_kpis(stations, target_cycle)
    df_ops = extract_operation_details(result)
    df_matrix = extract_resource_matrix(result)

    print_report(df_stations, df_ops, target_cycle)

    if args.verbose and not df_matrix.empty:
        print("📋 MATRICE OPÉRATIONS × STATIONS")
        print("-" * 72)
        station_cols = [c for c in df_matrix.columns if c.startswith("station_")]
        show_cols = ["op_id", "name", "duration_min", "machine_type", "section"] + station_cols
        print(df_matrix[show_cols].to_string(index=False))
        print()

    # ── Export ───────────────────────────────────────────────────
    if args.export:
        export_report(df_stations, df_ops, args.export, target_cycle)


if __name__ == "__main__":
    main()
