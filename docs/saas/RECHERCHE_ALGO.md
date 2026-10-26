# Recherche documentaire : enrichir le moteur d'équilibrage (v2.2)

Date : 26/10/2026. Objet : pourquoi l'ancien moteur donnait « 1 opération = 1 ouvrier » sur la gamme
dos de pantalon (7 opérations, 7 machines différentes) et ce que la littérature et la pratique
atelier recommandent. Sources ouvertes uniquement (articles en accès libre, résumés publics,
documentation OR-Tools, blogs techniques confection). « Texte lu » = page ouverte et lue ;
« résumé » = seul le résumé public a été consulté.

## 1. Constat sur l'ancien moteur

- RPW et CP-SAT imposaient **un seul type de machine par station** et **un seul poste physique**
  par station. Avec 7 opérations sur 7 machines différentes, chaque changement de machine ouvrait
  une station : 7 stations, charges 18 à 84 %.
- RPW verrouillait aussi la **section** de la station (Finissage / Traçage / Couture / Montage).
- Les ouvriers étaient affectés après coup, sans tenir compte de ceux déjà pris : une station
  pouvait rester sans ouvrier (station 6, compétence « piquer » déjà consommée).
- CP-SAT : l'affectation des postes était gloutonne ; une station manuelle pouvait prendre une
  piqueuse dont une autre station avait besoin (bug connu, test xfail).

## 2. Ce que dit la pratique atelier

| Pratique | Source |
|---|---|
| Combiner les opérations courtes sur le **même type de machine**, dans l'ordre si possible ; **fractionner** les opérations longues entre plusieurs opérateurs ; **partager un opérateur** entre deux opérations sur une machine ou des **machines voisines** ; donner les opérations les plus chargées aux opérateurs les plus rapides. « Un opérateur ne peut partager du travail entre une piqueuse et une surjeteuse que si les deux sont à son poste. » | TextileNotes, *Line Balancing in Garment Manufacturing* (texte lu) : https://textilenotes.com/industrial-engineering/line-balancing |
| Exemple chiffré : une jupe, 7 opérateurs ; en partageant le travail surjeteuse entre 3 opérateurs et le travail recouvreuse entre 2, l'efficacité d'équilibrage passe de 75 % à 92,3 %. | idem |
| Ligne de confection : « chaque ouvrier peut utiliser au plus trois machines différentes » ; modèle en nombres entiers en 2 phases (opérations + machines aux stations, puis ouvriers aux stations selon leur aptitude) ; postes parallèles autorisés. Partage de travail (work sharing) : un opérateur termine son opération puis donne 10 min/h à l'opération goulot, sur une machine du même type. | Morshed & Palash, *Assembly Line Balancing ... Work Sharing Method in Apparel Industry*, GJRE 2014 (texte lu, CC BY-NC) : https://globaljournals.org/GJRE_Volume14/4-Assembly-Line-Balancing.pdf |
| Matrice de polyvalence : rendement de chaque opérateur **par opération ou par compétence**, mesuré sur l'historique ; méthodes « opérations difficiles d'abord », « personnes d'abord », combinée. | Online Clothing Study / Kontrollis, *Line Balancing Tool Based on Operator Skill Matrix* (texte lu) : https://onlineclothingstudy.com/line-balancing-tool-based-on-operator/ |
| Fusionner les opérations qui partagent la même ressource ; matrice de polyvalence pour aligner tâches et compétences ; simulation pour valider. | Abay Garment (Gondar), Heliyon 2024, accès libre (résumé + extraits) : https://pmc.ncbi.nlm.nih.gov/articles/PMC10788436 |
| Opérateurs notés de 75 % à 125 % selon vitesse et compétence pour l'équilibrage. | Bongomin et al., *Engineering Reports* 2020, accès libre (extraits) : https://onlinelibrary.wiley.com/doi/full/10.1002/eng2.12157 |
| Équilibrage de ligne confection par PLNE (CPLEX) appliqué en atelier. | Kong, Ning & Kong, arXiv 2502.17508 (résumé) : https://arxiv.org/abs/2502.17508 |

## 3. Modèles de recherche opérationnelle utiles

| Problème | Idée retenue | Source |
|---|---|---|
| **SALBP-1 / SALBP-2** | Type 1 : minimiser le nombre de stations à cadence donnée (objectif par défaut du moteur). Type 2 : minimiser la cadence à nombre de stations donné (notre recherche dichotomique « cadence minimale »). | Morshed & Palash 2014 (texte lu) |
| **ALWABP** (worker assignment) | Les temps dépendent de l'ouvrier, certaines paires ouvrier/tâche sont interdites ; double affectation tâches→stations et ouvriers→stations. | Miralles et al. 2008 (résumé) : http://dl.acm.org/doi/10.1016/j.dam.2005.12.012 ; Borba & Ritt, arXiv 1308.0299 (résumé) : https://arxiv.org/abs/1308.0299 |
| **Multi-manned ALBP** | Plusieurs ouvriers sur une même station ; modèle CP de type II plus efficace que la PLNE. | Çil & Kizilay, *Computers & OR* 2020 (résumé) : https://doi.org/10.1016/j.cor.2020.105069 |
| **Multi-manned + main-d'œuvre hétérogène** | Combinaison MALBP + ALWABP. | IJPR 2024 (résumé) : https://www.tandfonline.com/doi/full/10.1080/00207543.2024.2347572 |
| **Tâches à plusieurs opérateurs** | Modèles PLNE et CP pour types I et II. | Esin, thèse METU 2007 (résumé) : https://open.metu.edu.tr/handle/11511/17046 |
| **Ouvriers qui se déplacent + postes parallèles** | Modèle CP avec ressources partagées entre postes et stations en parallèle. | Pucel & Roussel, CP 2024, accès libre CC BY : https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.CP.2024.23 |
| **OR-Tools CP-SAT** | Solveur entier : toutes les contraintes en entiers (on multiplie les minutes par 100), statuts OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN. | https://developers.google.com/optimization/cp/cp_solver (texte lu) |

## 4. Ce qui a été implémenté (moteur v2.2)

Nouveau module `engine/resources.py`, utilisé par RPW et CP-SAT.

1. **Stations multi-machines.** Une station = un ouvrier qui peut tenir jusqu'à
   `max_machines_per_station` machines voisines (3 par défaut, comme dans Morshed & Palash).
   Chaque type de machine de la station consomme un poste physique de ce type. Option
   `machine_change_time` : minutes par pièce ajoutées par machine supplémentaire (déplacement).
   CP-SAT : variables z[type, station], capacité par type, au plus `max_machines_per_station`
   types par station ; à nombre de postes égal, l'objectif préfère moins de machines par station.
2. **Opérations partagées** (`split_mode = "share"`, par défaut). Une opération plus longue que la
   cadence est découpée en parts pleines (= cadence) et un **reliquat combinable** avec d'autres
   opérations sur un autre poste du même type. Ex. 7 min à cadence 5 : un ouvrier fait 5 min, le
   reliquat de 2 min va avec une autre opération : 3 ouvriers au lieu de 4. Le résultat indique la
   part de chaque station (`shares`). L'ancien dédoublement égal reste disponible
   (`split_mode = "parallel"`).
3. **Ouvriers : compétences + rendement.**
   - Pendant la construction, RPW vérifie par **couplage** (condition de Hall) qu'il reste un
     ouvrier distinct qualifié pour chaque station : plus de station créée « sans ouvrier » par
     oubli des ouvriers déjà pris.
   - Affectation finale **optimale** (méthode hongroise) : chaque ouvrier doit maîtriser TOUTES les
     compétences de sa station ; parmi les qualifiés, les meilleurs rendements vont aux stations
     les plus chargées. Chaque station indique `worker_time` (temps réel = SAM / rendement).
   - **Matrice de polyvalence** : `Worker.skill_levels` = rendement par compétence (ex.
     `{"surjeter": 0.8}`), sinon `efficiency`.
   - CP-SAT : un ouvrier par station (x postes parallèles), qualifié pour toutes les opérations de
     la station ; un ouvrier = une station.
4. **Diagnostic `SKILL_CAPACITY`** (avant calcul) : pour chaque groupe d'opérations, les ouvriers
   capables d'en faire au moins une doivent suffire à cadence donnée. Exemple réel : OP030, OP040,
   OP060 (piquer/surjeter, 10,8 min) n'ont que 2 ouvriers ; il en faut 3 à 5 min.
5. **Sections** : préférence par défaut (`section_policy = "prefer"`), stricte en option.
6. **RPW multi-départ** : la construction est rejouée avec des variantes plus prudentes (réserve de
   postes rares, sections strictes, puis 1 machine par station = ancien comportement) et la
   meilleure solution conforme est gardée.
7. **Bug CP-SAT corrigé** : postes affectés type par type (stations machines d'abord ; une station
   manuelle ne prend qu'un poste dont personne n'a besoin et n'exige pas de poste). Stations CP-SAT
   numérotées sans trou. Test xfail retiré.

## 5. Résultats

| Cas | Ancien moteur | v2.2 |
|---|---|---|
| Dos de pantalon, cadence 5, ouvriers polyvalents (ou sans liste d'ouvriers) | 7 stations, 52 % | **5 stations, 73,2 %** (OP010+OP020 sur thermo-presse + marqueur ; OP060+OP070 sur piqueuse + machine à passants) |
| Dos de pantalon, effectif réel de Karim | 7 stations, station 6 sans ouvrier | Diagnostic clair : cadence 5 intenable, 2 ouvriers seulement pour piquer/surjeter (10,8 min) |
| Effectif réel + 2 formations (Opérateur Thermo → marquage ; Opérateur Passants → piqûre plate) | – | **5 opérateurs, 73,2 %, conforme** (RPW et CP-SAT) |
| Chemise exemple, cadence 4,5 | 12 stations | RPW 10, CP-SAT 9 (conformes) |
| Veste exemple, sans postes, 8 opérateurs théoriques | 16 (CP-SAT) / 17 (RPW) avec 1 machine par station | 9 stations (RPW et CP-SAT) |

## 6. Limites et pistes

- Les opérations d'une station restent **consécutives dans la gamme** (contrainte de précédence
  classique). Le partage « en arrière » (un ouvrier fait OP030 puis aide sur OP060) n'est pas
  modélisé ; il demanderait des stocks tampons entre postes (piste : variante U / ouvriers
  mobiles, Pucel & Roussel 2024).
- Le partage n'est automatique que pour les opérations **plus longues que la cadence**. Partager
  une opération courte entre deux ouvriers pour gagner un opérateur (exemple TextileNotes) n'est
  pas encore proposé.
- Le rendement des ouvriers sert à l'affectation et au calcul du temps réel ; la faisabilité se
  calcule sur les SAM (sinon une ligne serait refusée pour un ouvrier à 85 %).
- La proximité physique des machines n'est pas connue : `machine_change_time` est forfaitaire.
  Piste : lire l'implantation 2D (engine/models_v2) pour un temps de déplacement réel.
- RPW reste une heuristique ; CP-SAT donne l'optimum dans la limite de temps.
