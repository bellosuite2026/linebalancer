"""Bibliothèque de machines et d'équipements de confection (v3.0).

Source unique : engine.workshop.MACHINE_CATALOG en dérive, et l'interface web reçoit une copie générée
(scripts/build_machine_library.py → web/src/lib/machineLibrary.ts).

Chaque entrée : libellé, catégorie, encombrement réel par défaut (w = longueur de la table le long de
l'opératrice, d = profondeur, h = hauteur hors tout, en mètres ; modifiables machine par machine sur le
plan), type de machine de la gamme servi (`machine_type`, "" = pas un poste de travail), familles
d'opérations du catalogue que la machine peut réaliser (`ops`), forme du modèle 3D paramétrique
(`shape`), sigle 2D et source des dimensions (voir docs/saas/BIBLIOTHEQUE_MACHINES.md).
"""
from __future__ import annotations

CATEGORIES = {
    "piqure": "Piqûre (point noué)", "surjet": "Surjet / recouvrement / chaînette", "auto": "Automatiques et spéciales",
    "coupe": "Coupe", "repassage": "Thermocollage et repassage", "controle": "Contrôle et finition",
    "logistique": "Manutention et stockage",
}

# key, label, cat, w, d, h, machine_type, ops (familles du catalogue), shape, short, source
_ROWS = [
    # --- piqûre
    ("piqueuse_plate", "Piqueuse plate 1 aiguille", "piqure", 1.20, 0.60, 1.25, "piqueuse_plate", ["piqueuse_plate"], "sew_flat", "PP", "table"),
    ("piqueuse_2_aiguilles", "Piqueuse 2 aiguilles", "piqure", 1.20, 0.60, 1.25, "piqueuse_2_aiguilles", ["piqueuse_2_aiguilles", "piqueuse_plate"], "sew_flat", "2A", "table"),
    ("piqueuse_triple_entrainement", "Piqueuse à triple entraînement", "piqure", 1.20, 0.60, 1.30, "piqueuse_triple_entrainement", ["piqueuse_plate"], "sew_flat", "TE", "table"),
    ("piqueuse_colonne", "Piqueuse à colonne", "piqure", 1.20, 0.55, 1.35, "piqueuse_colonne", ["piqueuse_plate"], "sew_post", "CO", "table"),
    ("piqueuse_bras", "Piqueuse à bras (canon)", "piqure", 1.20, 0.55, 1.30, "piqueuse_bras", ["piqueuse_plate"], "sew_arm", "BR", "table"),
    ("zigzag", "Zigzag", "piqure", 1.20, 0.55, 1.25, "zigzag", ["zigzag"], "sew_flat", "ZZ", "table"),
    # --- surjet, recouvrement, chaînette
    ("surjeteuse_3_fils", "Surjeteuse 3 fils", "surjet", 1.05, 0.55, 1.20, "surjeteuse_3_fils", ["surjeteuse_4_fils"], "sew_overlock", "S3", "juki_tl"),
    ("surjeteuse_4_fils", "Surjeteuse 4 fils", "surjet", 1.05, 0.55, 1.20, "surjeteuse_4_fils", ["surjeteuse_4_fils"], "sew_overlock", "S4", "juki_tl"),
    ("surjeteuse_5_fils", "Surjeteuse 5 fils (point de sécurité)", "surjet", 1.10, 0.55, 1.20, "surjeteuse_5_fils", ["surjeteuse_4_fils"], "sew_overlock", "S5", "juki_tl"),
    ("recouvreuse", "Recouvreuse plateau", "surjet", 1.20, 0.54, 1.25, "recouvreuse", ["recouvreuse"], "sew_flat", "RC", "siruba"),
    ("recouvreuse_bras", "Recouvreuse à bras", "surjet", 1.20, 0.54, 1.30, "recouvreuse_bras", ["recouvreuse"], "sew_arm", "RB", "siruba"),
    ("chainette", "Chaînette multi-aiguilles", "surjet", 1.20, 0.60, 1.30, "chainette", ["chainette"], "sew_flat", "CH", "table"),
    ("point_invisible", "Point invisible / ourleuse", "surjet", 1.05, 0.55, 1.15, "point_invisible", ["piqueuse_plate"], "sew_overlock", "PI", "speedway"),
    ("feed_off_arm", "Feed-off-the-arm (jean)", "surjet", 1.05, 0.55, 1.35, "feed_off_arm", ["chainette"], "sew_arm", "FA", "estamac"),
    ("pose_elastique", "Pose élastique / ceinture (multi-aiguilles)", "surjet", 1.20, 0.60, 1.30, "pose_elastique", ["chainette"], "sew_flat", "PE", "table"),
    # --- automatiques et spéciales
    ("piqueuse_boutonniere", "Boutonnière droite", "auto", 1.20, 0.66, 1.20, "piqueuse_boutonniere", ["piqueuse_boutonniere"], "sew_auto", "BN", "juki_lk"),
    ("boutonniere_oeillet", "Boutonnière à œillet", "auto", 1.20, 0.80, 1.30, "boutonniere_oeillet", ["piqueuse_boutonniere"], "sew_auto", "BO", "estimation"),
    ("piqueuse_bouton", "Pose-boutons", "auto", 1.20, 0.66, 1.16, "piqueuse_bouton", ["piqueuse_bouton"], "sew_auto", "PB", "juki_lk"),
    ("bride", "Bartack / brides", "auto", 1.20, 0.66, 1.20, "bride", ["bride"], "sew_auto", "BT", "juki_lk"),
    ("pose_passants", "Pose-passants", "auto", 1.20, 0.80, 1.30, "pose_passants", ["bride"], "sew_auto", "PS", "estimation"),
    ("machine_poches_auto", "Machine à poches automatique", "auto", 1.40, 1.75, 1.35, "machine_poches_auto", ["piqueuse_plate", "piqueuse_2_aiguilles"], "sew_station", "MP", "juki_ps"),
    ("machine_pinces", "Machine à pinces", "auto", 1.20, 1.00, 1.30, "machine_pinces", ["piqueuse_plate"], "sew_station", "MZ", "estimation"),
    # --- coupe
    ("table_coupe", "Table de coupe / matelassage", "coupe", 6.00, 1.80, 0.90, "table_coupe", ["manuel"], "cutting_table", "TC", "litex"),
    ("chariot_matelasseur", "Chariot matelasseur", "coupe", 2.40, 0.90, 1.30, "chariot_matelasseur", ["manuel"], "spreader", "CM", "estimation"),
    ("coupe_automatique", "Coupe automatique (CAO)", "coupe", 3.82, 2.62, 1.40, "coupe_automatique", ["manuel"], "cutter_cad", "CA", "lectra"),
    ("scie_ruban", "Scie à ruban", "coupe", 1.32, 1.20, 1.80, "scie_ruban", ["manuel"], "bandknife", "SR", "rexel"),
    ("table_travail", "Table de préparation / paquetage", "coupe", 1.60, 0.80, 0.90, "table_travail", ["manuel"], "table", "TP", "estimation"),
    # --- thermocollage et repassage
    ("presse_thermocollage", "Presse / thermocolleuse en continu", "repassage", 1.70, 1.10, 1.10, "presse_thermocollage", ["presse_thermocollage"], "fusing", "TH", "meyer"),
    ("table_repassage", "Table à repasser aspirante", "repassage", 1.55, 0.58, 0.95, "table_repassage", ["fer_repassage"], "ironing", "FR", "fagor"),
    ("mannequin_vapeur", "Mannequin vapeur (form finisher)", "repassage", 1.20, 1.00, 1.90, "mannequin_vapeur", ["fer_repassage"], "mannequin", "MV", "estimation"),
    ("presse_finition", "Presse de finition", "repassage", 1.40, 0.90, 1.40, "presse_finition", ["fer_repassage"], "press", "PF", "estimation"),
    # --- contrôle et finition
    ("table_controle", "Contrôle qualité / table d'inspection", "controle", 1.50, 0.80, 0.90, "table_controle", ["manuel"], "inspection", "CQ", "estimation"),
    ("detecteur_aiguilles", "Détecteur de métaux / aiguilles (convoyeur)", "controle", 1.80, 0.90, 1.10, "detecteur_aiguilles", ["manuel"], "detector", "DA", "cerebro"),
    ("etiqueteuse_emballage", "Étiquetage / emballage", "controle", 1.80, 0.90, 0.90, "etiqueteuse_emballage", ["manuel"], "packing", "EM", "estimation"),
    # --- manutention et stockage (pas des postes de travail)
    ("rack_encours", "Rack d'encours", "logistique", 1.20, 0.50, 1.80, "", [], "rack", "RK", "estimation"),
    ("chariot", "Chariot de paquets", "logistique", 1.00, 0.60, 0.95, "", [], "cart", "CR", "estimation"),
    ("convoyeur_suspendu", "Convoyeur suspendu (UPS type Eton), poste", "logistique", 1.50, 1.00, 2.20, "", [], "conveyor", "UP", "eton"),
    ("palette_carton", "Palette / cartons", "logistique", 1.20, 0.80, 1.00, "", [], "pallet", "PA", "palette"),
]

SOURCES = {
    "table": "Plateau industriel standard 1 200 × 550–600 mm (Jack A4 120×54 cm, Speedway 50×120 cm, Singer 712G 120×54 cm, Estamac 47,2×23,6 in = 1 200 × 600 mm).",
    "juki_tl": "Table industrielle Juki 1 050 × 550 × 750 mm (dépliant Juki TL-2300) ; surjeteuses sur plateau court.",
    "siruba": "Tables Siruba pour recouvreuses C007/F007 : 1 200 × 540 mm.",
    "speedway": "Plateaux pré-découpés Speedway (point invisible, bartack, colonne, bras) 50 × 120 cm.",
    "estamac": "Estamac : plateau dédié plus petit pour feed-off-the-arm (KB).",
    "juki_lk": "Juki LK-1903B/BR35 (pose-boutons) : 1 200 × 660 × 1 155 mm avec table standard.",
    "juki_ps": "Juki série PS (machines à gabarit / poches) : de 1 060 × 1 330 à 2 100 × 2 326 mm (h. table 830 mm).",
    "litex": "Tables de matelassage 1,80 m × 12,50 m (Litex Riga) ; largeur 1,8–2,6 m + 1,2 m d'allée (Serkon).",
    "lectra": "Lectra VectorFashion iX : 3,82 × 2,62 m hors tout, fenêtre de coupe 1,7 m.",
    "rexel": "Scie à ruban Rexel R500 : 1 320 × 1 200 × 1 800 mm hors tout (plateau 1 200 × 1 000).",
    "meyer": "Thermocolleuse en continu Meyer RPS-L600 : 1 660 × 1 090 × 450 mm (+ table de chargement).",
    "fagor": "Table de finition aspirante Fagor MRP-A-C : 1 550 × 580 × 950 mm (plateau 1 200 × 400).",
    "cerebro": "Détecteur d'aiguilles à convoyeur : passage 500–600 mm × 100 mm (Cerebro, Elite).",
    "eton": "Eton Systems (Opta) : convoyeur suspendu à porte-pièces adressables, postes modulaires.",
    "palette": "Palette Europe EPAL 1 200 × 800 mm.",
    "estimation": "Estimation d'après des fiches fabricants (à vérifier sur votre machine) ; modifiable.",
}

LIBRARY: dict[str, dict] = {
    k: {"label": label, "category": cat, "w": w, "d": d, "h": h, "machine_type": mt, "ops": ops, "shape": shape,
        "short": short, "source": src}
    for k, label, cat, w, d, h, mt, ops, shape, short, src in _ROWS
}

# Familles interchangeables (repli de l'association station → machine du plan, signalé dans les notes)
FAMILIES = {
    "surjeteuse": {"surjeteuse_3_fils", "surjeteuse_4_fils", "surjeteuse_5_fils", "surjeteuse"},
    "repassage": {"table_repassage", "fer_repassage", "presse_vapeur", "repassage", "mannequin_vapeur", "presse_finition"},
    "table": {"table_travail", "table_controle", "manuel", "table", "table_preparation", "etiqueteuse_emballage"},
    "piqueuse": {"piqueuse_plate", "piqueuse", "piqueuse_1_aiguille", "plate", "piqueuse_triple_entrainement",
                 "piqueuse_colonne", "piqueuse_bras"},
    "thermo": {"presse_thermocollage", "thermocolleuse", "thermocollage"},
    "bouton": {"piqueuse_bouton", "pose_bouton", "pose_boutons", "boutons"},
    "boutonniere": {"piqueuse_boutonniere", "boutonniere", "boutonniere_oeillet"},
    "bride": {"bride", "bartack", "brides", "pose_passants"},
    "double": {"piqueuse_2_aiguilles", "double_aiguille", "2_aiguilles"},
    "recouvreuse": {"recouvreuse", "recouvreuse_bras"},
    "chainette": {"chainette", "feed_off_arm", "pose_elastique"},
}
