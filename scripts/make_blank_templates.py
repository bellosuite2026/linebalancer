"""Génère les modèles VIDES à télécharger (web/public/modeles/*_vide.xlsx|.csv).

Usage : python scripts/make_blank_templates.py
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "modeles"

SPECS = {
    "modele_gamme_SAM_vide": ("Gamme", [
        ("Op_ID", True, 10, "Identifiant unique de l'opération (ex. OP010)."),
        ("Description", False, 40, "Désignation de l'opération."),
        ("SAM_min", True, 10, "Temps standard en minutes par pièce (ex. 0,45)."),
        ("Predecesseurs", False, 18, "Op_ID à terminer avant, séparés par des virgules. Vide = début de gamme."),
        ("Type_Machine", False, 18, "Machine nécessaire (ex. piqueuse_plate). Doit correspondre aux postes."),
        ("Competences", False, 28, "Compétences requises, séparées par des virgules."),
        ("Section", False, 12, "Section ou zone (ex. Montage, Finition)."),
        ("Optionnel", False, 10, "Oui / Non (Non par défaut)."),
    ]),
    "modele_postes_vide": ("Postes", [
        ("Poste_ID", True, 10, "Identifiant unique du poste (ex. WS01)."),
        ("Nom", False, 30, "Nom du poste."),
        ("Type_Machine", True, 18, "Type de machine installée (mêmes mots que dans la gamme)."),
        ("Disponible", False, 11, "Oui / Non (Oui par défaut)."),
        ("Max_Ouvriers", False, 12, "Nombre d'ouvriers maximum sur ce poste (1 par défaut)."),
        ("Section", False, 12, "Section ou zone."),
    ]),
    "modele_ouvriers_vide": ("Ouvriers", [
        ("Ouvrier_ID", True, 11, "Identifiant unique (ex. W001)."),
        ("Nom", False, 22, "Nom ou prénom."),
        ("Competences", True, 40, "Compétences maîtrisées, séparées par des virgules (mêmes mots que dans la gamme)."),
        ("Efficacite", False, 11, "1 = 100 %, 0,9 = 90 % (1 par défaut)."),
        ("Disponible", False, 11, "Oui / Non (Oui par défaut)."),
        ("Poste_Assigne", False, 14, "Poste_ID imposé (facultatif)."),
    ]),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    head = PatternFill("solid", fgColor="1F4E79")
    req = PatternFill("solid", fgColor="C0392B")
    for name, (title, cols) in SPECS.items():
        wb = Workbook()
        ws = wb.active
        ws.title = title
        for i, (col, required, width, help_) in enumerate(cols, 1):
            c = ws.cell(row=1, column=i, value=col)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = req if required else head
            c.alignment = Alignment(vertical="center")
            c.comment = Comment(("Obligatoire. " if required else "") + help_, "Line Balancer")
            ws.column_dimensions[c.column_letter].width = width
        ws.freeze_panes = "A2"
        for i, (col, *_r) in enumerate(cols, 1):
            if col in ("Optionnel", "Disponible"):
                dv = DataValidation(type="list", formula1='"Oui,Non"', allow_blank=True)
                ws.add_data_validation(dv)
                letter = ws.cell(row=1, column=i).column_letter
                dv.add(f"{letter}2:{letter}1000")
        aide = wb.create_sheet("Aide")
        aide["A1"] = f"Modèle {title} – Textile Line Balancer"
        aide["A1"].font = Font(bold=True, size=13, color="1F4E79")
        aide["A2"] = "Remplissez l'onglet « " + title + " » à partir de la ligne 2. En-têtes rouges = obligatoires. Ne renommez pas les colonnes."
        for r, (col, required, _w, help_) in enumerate(cols, 4):
            aide.cell(row=r, column=1, value=col).font = Font(bold=True)
            aide.cell(row=r, column=2, value="Obligatoire" if required else "Facultatif")
            aide.cell(row=r, column=3, value=help_)
        aide.column_dimensions["A"].width = 16
        aide.column_dimensions["B"].width = 13
        aide.column_dimensions["C"].width = 90
        wb.save(OUT / f"{name}.xlsx")
        (OUT / f"{name}.csv").write_text(";".join(c[0] for c in cols) + "\n", encoding="utf-8-sig")
    print("Modèles vides générés dans", OUT)


if __name__ == "__main__":
    main()
