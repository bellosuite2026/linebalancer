# Bibliothèque de machines (v3.0)

Source unique : `engine/machine_library.py` (copie web générée : `python scripts/build_machine_library.py` → `web/src/lib/machineLibrary.ts`, vérifiée par `tests/test_des.py`).
Encombrement par défaut = table / équipement hors tout, en mètres (w le long de l'opératrice, d en profondeur, h hauteur). Toutes les valeurs sont modifiables machine par machine dans l'éditeur de plan. Chaque machine a un symbole 2D (`web/src/components/MachineSymbol.tsx`) et un modèle 3D paramétrique léger (`web/src/lib/machines3d.ts`).

`machine_type` = type de machine de la gamme servi (association station → machine du plan) ; `ops` = familles d'opérations du catalogue (web/public/catalogue/operations.json) que la machine peut réaliser. Les équipements de manutention n'ont pas de `machine_type` (pas des postes de travail).

## Piqûre (point noué)

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `piqueuse_plate` | Piqueuse plate 1 aiguille | 1.2 × 0.6 × 1.25 | piqueuse_plate | piqueuse_plate | table |
| `piqueuse_2_aiguilles` | Piqueuse 2 aiguilles | 1.2 × 0.6 × 1.25 | piqueuse_2_aiguilles | piqueuse_2_aiguilles, piqueuse_plate | table |
| `piqueuse_triple_entrainement` | Piqueuse à triple entraînement | 1.2 × 0.6 × 1.3 | piqueuse_triple_entrainement | piqueuse_plate | table |
| `piqueuse_colonne` | Piqueuse à colonne | 1.2 × 0.55 × 1.35 | piqueuse_colonne | piqueuse_plate | table |
| `piqueuse_bras` | Piqueuse à bras (canon) | 1.2 × 0.55 × 1.3 | piqueuse_bras | piqueuse_plate | table |
| `zigzag` | Zigzag | 1.2 × 0.55 × 1.25 | zigzag | zigzag | table |

## Surjet / recouvrement / chaînette

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `surjeteuse_3_fils` | Surjeteuse 3 fils | 1.05 × 0.55 × 1.2 | surjeteuse_3_fils | surjeteuse_4_fils | juki_tl |
| `surjeteuse_4_fils` | Surjeteuse 4 fils | 1.05 × 0.55 × 1.2 | surjeteuse_4_fils | surjeteuse_4_fils | juki_tl |
| `surjeteuse_5_fils` | Surjeteuse 5 fils (point de sécurité) | 1.1 × 0.55 × 1.2 | surjeteuse_5_fils | surjeteuse_4_fils | juki_tl |
| `recouvreuse` | Recouvreuse plateau | 1.2 × 0.54 × 1.25 | recouvreuse | recouvreuse | siruba |
| `recouvreuse_bras` | Recouvreuse à bras | 1.2 × 0.54 × 1.3 | recouvreuse_bras | recouvreuse | siruba |
| `chainette` | Chaînette multi-aiguilles | 1.2 × 0.6 × 1.3 | chainette | chainette | table |
| `point_invisible` | Point invisible / ourleuse | 1.05 × 0.55 × 1.15 | point_invisible | piqueuse_plate | speedway |
| `feed_off_arm` | Feed-off-the-arm (jean) | 1.05 × 0.55 × 1.35 | feed_off_arm | chainette | estamac |
| `pose_elastique` | Pose élastique / ceinture (multi-aiguilles) | 1.2 × 0.6 × 1.3 | pose_elastique | chainette | table |

## Automatiques et spéciales

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `piqueuse_boutonniere` | Boutonnière droite | 1.2 × 0.66 × 1.2 | piqueuse_boutonniere | piqueuse_boutonniere | juki_lk |
| `boutonniere_oeillet` | Boutonnière à œillet | 1.2 × 0.8 × 1.3 | boutonniere_oeillet | piqueuse_boutonniere | estimation |
| `piqueuse_bouton` | Pose-boutons | 1.2 × 0.66 × 1.16 | piqueuse_bouton | piqueuse_bouton | juki_lk |
| `bride` | Bartack / brides | 1.2 × 0.66 × 1.2 | bride | bride | juki_lk |
| `pose_passants` | Pose-passants | 1.2 × 0.8 × 1.3 | pose_passants | bride | estimation |
| `machine_poches_auto` | Machine à poches automatique | 1.4 × 1.75 × 1.35 | machine_poches_auto | piqueuse_plate, piqueuse_2_aiguilles | juki_ps |
| `machine_pinces` | Machine à pinces | 1.2 × 1.0 × 1.3 | machine_pinces | piqueuse_plate | estimation |

## Coupe

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `table_coupe` | Table de coupe / matelassage | 6.0 × 1.8 × 0.9 | table_coupe | manuel | litex |
| `chariot_matelasseur` | Chariot matelasseur | 2.4 × 0.9 × 1.3 | chariot_matelasseur | manuel | estimation |
| `coupe_automatique` | Coupe automatique (CAO) | 3.82 × 2.62 × 1.4 | coupe_automatique | manuel | lectra |
| `scie_ruban` | Scie à ruban | 1.32 × 1.2 × 1.8 | scie_ruban | manuel | rexel |
| `table_travail` | Table de préparation / paquetage | 1.6 × 0.8 × 0.9 | table_travail | manuel | estimation |

## Thermocollage et repassage

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `presse_thermocollage` | Presse / thermocolleuse en continu | 1.7 × 1.1 × 1.1 | presse_thermocollage | presse_thermocollage | meyer |
| `table_repassage` | Table à repasser aspirante | 1.55 × 0.58 × 0.95 | table_repassage | fer_repassage | fagor |
| `mannequin_vapeur` | Mannequin vapeur (form finisher) | 1.2 × 1.0 × 1.9 | mannequin_vapeur | fer_repassage | estimation |
| `presse_finition` | Presse de finition | 1.4 × 0.9 × 1.4 | presse_finition | fer_repassage | estimation |

## Contrôle et finition

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `table_controle` | Contrôle qualité / table d'inspection | 1.5 × 0.8 × 0.9 | table_controle | manuel | estimation |
| `detecteur_aiguilles` | Détecteur de métaux / aiguilles (convoyeur) | 1.8 × 0.9 × 1.1 | detecteur_aiguilles | manuel | cerebro |
| `etiqueteuse_emballage` | Étiquetage / emballage | 1.8 × 0.9 × 0.9 | etiqueteuse_emballage | manuel | estimation |

## Manutention et stockage

| Clé | Machine | L × P × H (m) | Type gamme | Familles d'opérations | Source |
|---|---|---|---|---|---|
| `rack_encours` | Rack d'encours | 1.2 × 0.5 × 1.8 | — | — | estimation |
| `chariot` | Chariot de paquets | 1.0 × 0.6 × 0.95 | — | — | estimation |
| `convoyeur_suspendu` | Convoyeur suspendu (UPS type Eton), poste | 1.5 × 1.0 × 2.2 | — | — | eton |
| `palette_carton` | Palette / cartons | 1.2 × 0.8 × 1.0 | — | — | palette |

## Sources des dimensions

- **table** : Plateau industriel standard 1 200 × 550–600 mm (Jack A4 120×54 cm, Speedway 50×120 cm, Singer 712G 120×54 cm, Estamac 47,2×23,6 in = 1 200 × 600 mm).
- **juki_tl** : Table industrielle Juki 1 050 × 550 × 750 mm (dépliant Juki TL-2300) ; surjeteuses sur plateau court.
- **siruba** : Tables Siruba pour recouvreuses C007/F007 : 1 200 × 540 mm.
- **speedway** : Plateaux pré-découpés Speedway (point invisible, bartack, colonne, bras) 50 × 120 cm.
- **estamac** : Estamac : plateau dédié plus petit pour feed-off-the-arm (KB).
- **juki_lk** : Juki LK-1903B/BR35 (pose-boutons) : 1 200 × 660 × 1 155 mm avec table standard.
- **juki_ps** : Juki série PS (machines à gabarit / poches) : de 1 060 × 1 330 à 2 100 × 2 326 mm (h. table 830 mm).
- **litex** : Tables de matelassage 1,80 m × 12,50 m (Litex Riga) ; largeur 1,8–2,6 m + 1,2 m d'allée (Serkon).
- **lectra** : Lectra VectorFashion iX : 3,82 × 2,62 m hors tout, fenêtre de coupe 1,7 m.
- **rexel** : Scie à ruban Rexel R500 : 1 320 × 1 200 × 1 800 mm hors tout (plateau 1 200 × 1 000).
- **meyer** : Thermocolleuse en continu Meyer RPS-L600 : 1 660 × 1 090 × 450 mm (+ table de chargement).
- **fagor** : Table de finition aspirante Fagor MRP-A-C : 1 550 × 580 × 950 mm (plateau 1 200 × 400).
- **cerebro** : Détecteur d'aiguilles à convoyeur : passage 500–600 mm × 100 mm (Cerebro, Elite).
- **eton** : Eton Systems (Opta) : convoyeur suspendu à porte-pièces adressables, postes modulaires.
- **palette** : Palette Europe EPAL 1 200 × 800 mm.
- **estimation** : Estimation d'après des fiches fabricants (à vérifier sur votre machine) ; modifiable.

Pages consultées (novembre 2026) :

- Juki LK-1903B/BR35, manuel : https://www.juki.co.jp/industrial_j/download_j/manual_j/lk1900b/menu/lk1903b_br35/pdf/instruction_eg.pdf
- Juki série PS (dimensions) : https://www.juki.co.jp/industrial_e/admin/pdata/filedata/590/psseries.pdf
- Juki TL-2300 (table industrielle 1050 × 550 × 750) : https://juki.fi/wp-content/uploads/2025/09/Leaflet-Juki-TL-2300.pdf
- Tables Siruba pour recouvreuses : https://siruba.nt-rt.ru/images/manuals/stol2.pdf
- Plateaux Speedway / Supra Sewing (50 × 120 cm) : https://www.speedwaysewing.com/parts/speedway-industrial-sewing-table-stand
- Estamac (plateaux, feed-off-the-arm) : https://www.estamac.com/industrial-sewing-tables
- Jack A4 120 × 54 cm : https://jdyongxi.en.made-in-china.com/product/cRVpYBWPgKkQ/China-Jack-A4-Industrial-Sewing-Machine-Table-and-Steel-Stand-with-Plywood-Top.html
- Lectra VectorFashion iX : https://www.iigm.com/pub/media/catalog/product/file/technical-datasheet-vectorfashion-ix-series-en.pdf
- Scie à ruban Rexel R500 : https://www.rexelpoland.com/en/catalog/pdf/band-knife-machine-r500
- Meyer RPS-L (thermocolleuse en continu) : https://exhibitorsearch.messefrankfurt.com/images/original/document_downloads/10000008202601/0011002409/1705493102951_3663229069.pdf
- Tables à repasser Fagor : https://www.fagorprofessional.pl/documents/20127/548317/05_FINISHING.pdf/44b68de6-8b4a-5e6c-6fd4-95455c33f109?t=1581602820692
- Détecteur d'aiguilles à convoyeur : https://www.aajjo.com/product/cerebro-conveyor-type-needle-detector-in-tiruppur-cerebro-garment-finishing-equipments
- Salle de coupe (largeur de tables, allées) : https://www.serkonmakina.com/en/cutting-room-setup/ ; https://litex-riga.com/en/technologies
- Eton Systems (UPS) : https://www.etonsystems.com/en/industries/garments
