#!/usr/bin/env python3
"""
Équilibrage de ligne textile - Point d'entrée principal.
Usage:
  python scripts/balance.py --sam data/samples/sam_chemise_homme.csv \
                            --workstations data/templates/mon_projet_workstations.csv \
                            --workers data/templates/mon_projet_workers.csv \
                            --cycle-time 1.5 \
                            --solver rpw
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from engine.parsers import create_problem_from_sam
from engine.solvers import solve_rpw, solve_cp_sat, ORTOOLS_AVAILABLE
from engine.exporters import (
    export_result_to_excel, export_result_to_json, export_gantt_data,
    export_comparison_to_excel,
)
from engine.models import SolverAlgorithm, OptimizationObjective
from engine.capacity import ProductionTarget, enrich_result
from engine.scenarios import Scenario, run_scenarios


def main():
    parser = argparse.ArgumentParser(description="Équilibrage de ligne textile")
    parser.add_argument("--sam", "-s", required=True, help="Fichier SAM (CSV/Excel/JSON)")
    parser.add_argument("--workstations", "-w", required=True, help="Fichier postes de travail")
    parser.add_argument("--workers", "-k", required=True, help="Fichier ouvriers")
    parser.add_argument("--cycle-time", "-c", type=float, required=True, help="Temps de cycle cible (minutes)")
    parser.add_argument("--solver", choices=["rpw", "cp-sat"], default="rpw", help="Algorithme (défaut: rpw)")
    parser.add_argument("--objective", choices=["min-stations", "min-cycle-time", "max-efficiency", "balance-workload"],
                        default="min-stations", help="Objectif optimisation")
    parser.add_argument("--max-stations", type=int, help="Nombre max de stations")
    parser.add_argument("--time-limit", type=int, default=60, help="Limite temps solveur (secondes)")
    parser.add_argument("--output", "-o", default="results", help="Dossier résultats")
    parser.add_argument("--project-name", "-p", default="balance", help="Nom projet pour fichiers sortie")
    parser.add_argument("--export-excel", action="store_true", help="Exporter aussi en Excel")
    parser.add_argument("--export-gantt", action="store_true", help="Exporter données Gantt (JSON)")
    parser.add_argument("--export-pdf", action="store_true", help="Exporter le rapport PDF décisionnel")
    parser.add_argument("--verbose", "-v", action="store_true", help="Logs détaillés")
    # --- Aide à la décision ---
    parser.add_argument("--target-qty", type=int, help="Quantité commandée (pièces) — active l'analyse de capacité")
    parser.add_argument("--work-days", type=float, default=5.0, help="Jours de production disponibles (défaut: 5)")
    parser.add_argument("--hours-per-day", type=float, default=8.0, help="Heures productives/jour (défaut: 8)")
    parser.add_argument("--line-efficiency", type=float, default=0.85, help="Efficacité ligne attendue 0-1 (défaut: 0.85)")
    parser.add_argument("--labor-cost", type=float, help="Coût main-d'œuvre par minute (cout/pièce estimé)")
    parser.add_argument("--scenarios", help="Comparaison what-if: temps de cycle séparés par virgule (ex: '1.2,1.5,1.8')")
    parser.add_argument("--scenarios-solver", choices=["rpw", "cp-sat"], default="rpw",
                        help="Solveur utilisé pour les scénarios (défaut: rpw)")
    parser.add_argument("--no-recommendations", action="store_true", help="Désactiver les recommandations automatiques")
    parser.add_argument("--simulate", action="store_true", help="Lancer une simulation DES après l'équilibrage")
    parser.add_argument("--sim-parts", type=int, default=200, help="Pièces à simuler (défaut: 200)")
    
    args = parser.parse_args()
    
    # Vérifier fichiers
    for f in [args.sam, args.workstations, args.workers]:
        if not Path(f).exists():
            print(f"❌ Fichier non trouvé: {f}")
            sys.exit(1)
    
    # Mapper arguments
    solver_map = {"rpw": SolverAlgorithm.RPW, "cp-sat": SolverAlgorithm.CP_SAT}
    obj_map = {
        "min-stations": OptimizationObjective.MIN_STATIONS,
        "min-cycle-time": OptimizationObjective.MIN_CYCLE_TIME,
        "max-efficiency": OptimizationObjective.MAX_EFFICIENCY,
        "balance-workload": OptimizationObjective.BALANCE_WORKLOAD,
    }
    
    solver_algo = solver_map[args.solver]
    objective = obj_map[args.objective]
    
    if solver_algo == SolverAlgorithm.CP_SAT and not ORTOOLS_AVAILABLE:
        print("❌ OR-Tools non installé. Installez avec: pip install ortools")
        print("   Utilisez --solver rpw à la place.")
        sys.exit(1)
    
    print("=" * 60)
    print("⚖️  ÉQUILIBRAGE DE LIGNE TEXTILE")
    print("=" * 60)
    print(f"📁 SAM:           {args.sam}")
    print(f"🏭 Postes:        {args.workstations}")
    print(f"👥 Ouvriers:      {args.workers}")
    print(f"⏱️  Cycle cible:   {args.cycle_time:.2f} min")
    print(f"🔧 Solveur:       {args.solver.upper()}")
    print(f"🎯 Objectif:      {args.objective}")
    if args.max_stations:
        print(f"📊 Max stations:  {args.max_stations}")
    print()
    
    # Charger problème
    print("📥 Chargement des données...")
    start_load = time.time()
    try:
        problem = create_problem_from_sam(
            sam_path=Path(args.sam),
            workstations_path=Path(args.workstations),
            workers_path=Path(args.workers),
            target_cycle_time=args.cycle_time,
            problem_name=args.project_name,
            algorithm=solver_algo,
            objective=objective,
        )
        load_time = time.time() - start_load
        print(f"   ✅ {len(problem.operations)} opérations, {len(problem.workstations)} postes, {len(problem.workers)} ouvriers")
        print(f"   ⏱️  Chargement: {load_time:.2f}s")
    except Exception as e:
        print(f"❌ Erreur chargement: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    
    # Validation
    errors = problem.validate()
    if errors:
        print("⚠️  Avertissements validation:")
        for err in errors:
            print(f"   - {err}")
        print()
    
    # --- Cible de production (commande) ---
    target = None
    if args.target_qty:
        target = ProductionTarget(
            order_quantity=args.target_qty,
            work_days=args.work_days,
            hours_per_day=args.hours_per_day,
            line_efficiency=args.line_efficiency,
        )
        t_errors = target.validate()
        if t_errors:
            for e in t_errors:
                print(f"❌ Commande invalide: {e}")
            sys.exit(1)
        print("📦 Commande: ")
        print(f"   {target.order_quantity} pcs en {target.work_days:g} j "
              f"({target.hours_per_day:g} h/j) → takt {target.takt_time:.2f} min/pc, "
              f"cycle planifiable {target.required_cycle_time:.2f} min")
        print()
    
    # --- Mode comparaison de scénarios (what-if) ---
    if args.scenarios:
        try:
            cycle_times = [float(x.strip().replace(",", "."))
                           for x in args.scenarios.replace(";", " ").replace(" ", ",").split(",")
                           if x.strip()]
        except ValueError:
            print(f"❌ Scénarios invalides: '{args.scenarios}' (attendu: '1.2,1.5,1.8')")
            sys.exit(1)
        if not cycle_times:
            print("❌ Aucun temps de cycle fourni dans --scenarios")
            sys.exit(1)
        sc_seller = {"rpw": "rpw", "cp-sat": "cp_sat"}[args.scenarios_solver]
        if sc_seller == "cp_sat" and not ORTOOLS_AVAILABLE:
            print("❌ OR-Tools non installé (pip install ortools) — utilisez --scenarios-solver rpw")
            sys.exit(1)
        scenarios = Scenario.from_cycle_times(
            cycle_times, solver=sc_seller, time_limit_seconds=args.time_limit,
        )
        print(f"🔀 Comparaison de {len(scenarios)} scénarios...")
        comparison = run_scenarios(
            problem, scenarios, target=target, labor_cost_per_minute=args.labor_cost,
        )
        print()
        print(comparison.summary())
        print()
        output_dir_path = Path(args.output)
        output_dir_path.mkdir(parents=True, exist_ok=True)
        if args.export_excel:
            try:
                xlsx = output_dir_path / f"{args.project_name}_scenarios.xlsx"
                export_comparison_to_excel(comparison, xlsx)
                print(f"💾 Comparatif Excel: {xlsx}")
            except ImportError:
                print("⚠️  openpyxl non installé, export Excel ignoré (pip install openpyxl)")
        sys.exit(0)
    
    # Résoudre
    print(f"🔧 Résolution avec {args.solver.upper()}...")
    start_solve = time.time()
    
    try:
        if solver_algo == SolverAlgorithm.RPW:
            result = solve_rpw(problem, max_stations=args.max_stations)
        else:
            result = solve_cp_sat(
                problem,
                time_limit_seconds=args.time_limit,
                log_search=args.verbose,
            )
    except Exception as e:
        print(f"❌ Erreur résolution: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    
    solve_time = time.time() - start_solve
    print(f"   ⏱️  Temps résolution: {solve_time:.2f}s")
    print()
    
    # Enrichir : capacité (commande) + KPIs réalistes + recommandations
    enrich_result(
        result, target=target,
        labor_cost_per_minute=args.labor_cost,
        with_recommendations=not args.no_recommendations,
    )
    
    # Afficher résultats
    print(result.summary())
    print()
    
    # Exporter
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_file = output_dir / f"{args.project_name}_result.json"
    export_result_to_json(result, json_file)
    print(f"💾 Résultat JSON: {json_file}")
    
    if args.export_excel:
        try:
            excel_file = output_dir / f"{args.project_name}_result.xlsx"
            export_result_to_excel(result, excel_file)
            print(f"💾 Résultat Excel: {excel_file}")
        except ImportError:
            print("⚠️  openpyxl non installé, export Excel ignoré (pip install openpyxl)")
        except Exception as e:
            print(f"⚠️  Erreur export Excel: {e}")
    
    if args.export_gantt:
        gantt_file = output_dir / f"{args.project_name}_gantt.json"
        export_gantt_data(result, gantt_file)
        print(f"💾 Données Gantt: {gantt_file}")
    
    if args.export_pdf:
        try:
            from engine.report_generator import BalanceReport
            pdf_file = output_dir / f"{args.project_name}_rapport.pdf"
            BalanceReport.balance_result(result, pdf_file)
            print(f"💾 Rapport PDF: {pdf_file}")
        except RuntimeError as e:
            print(f"⚠️  PDF ignoré: {e}")
        except Exception as e:
            print(f"⚠️  Erreur export PDF: {e}")
    
    # Simulation DES optionnelle
    if args.simulate and result.success:
        print()
        print("🎬 Simulation à événements discrets...")
        try:
            from engine.simulation import SimulationEngine, SimulationConfig
            sim = SimulationEngine(
                result, SimulationConfig(num_parts=args.sim_parts, variability=0.1),
            )
            sim_result = sim.run()
            if sim_result.success:
                print(sim_result.summary())
            else:
                print(f"⚠️  Simulation échouée: {sim_result.error_message}")
            if args.export_pdf:
                try:
                    from engine.report_generator import BalanceReport
                    sim_pdf = output_dir / f"{args.project_name}_simulation.pdf"
                    BalanceReport.simulation_report(sim_result, sim_pdf,
                                                    project_name=args.project_name)
                    print(f"💾 Rapport simulation PDF: {sim_pdf}")
                except RuntimeError as e:
                    print(f"⚠️  PDF simulation ignoré: {e}")
        except ImportError:
            print("⚠️  simpy non installé, simulation ignorée (pip install simpy)")
    
    # Code retour
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()