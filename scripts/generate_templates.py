#!/usr/bin/env python3
"""
Générateur de fichiers modèles SAM, Postes, Ouvriers.
Usage: python scripts/generate_templates.py [--output-dir data/templates] [--formats csv xlsx]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.parsers import generate_sam_template, generate_workstations_template, generate_workers_template


def main():
    parser = argparse.ArgumentParser(description="Génère fichiers modèles pour équilibrage ligne textile")
    parser.add_argument("--output-dir", default="data/templates", help="Dossier de sortie")
    parser.add_argument("--formats", nargs="+", choices=["csv", "xlsx", "json"], default=["csv"],
                        help="Formats à générer")
    parser.add_argument("--prefix", default="template", help="Préfixe noms fichiers")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Génération modèles dans: {output_dir}")
    print(f"📄 Formats: {', '.join(args.formats)}")
    print()
    
    for fmt in args.formats:
        print(f"--- Format: {fmt} ---")
        
        # SAM
        sam_path = output_dir / f"{args.prefix}_sam.{fmt}"
        generate_sam_template(sam_path, format=fmt)
        
        # Postes
        ws_path = output_dir / f"{args.prefix}_workstations.{fmt}"
        generate_workstations_template(ws_path, format=fmt)
        
        # Ouvriers
        wk_path = output_dir / f"{args.prefix}_workers.{fmt}"
        generate_workers_template(wk_path, format=fmt)
        
        print()
    
    print("✅ Modèles générés avec succès!")
    print(f"   📋 {output_dir}/{args.prefix}_sam.csv        # Vos opérations + temps + précédence")
    print(f"   🏭 {output_dir}/{args.prefix}_workstations.csv # Vos machines disponibles")
    print(f"   👥 {output_dir}/{args.prefix}_workers.csv     # Vos ouvriers + compétences")
    print()
    print("👉 Prochaines étapes:")
    print("   1. Remplissez les 3 fichiers avec vos données réelles")
    print("   2. Lancez l'équilibrage: python scripts/balance.py --sam ... --workstations ... --workers ...")


if __name__ == "__main__":
    main()