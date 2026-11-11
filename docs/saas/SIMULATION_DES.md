# Simulation à événements discrets (v3.1, type FlexSim) — phases 1 et 2

Module séparé des solveurs d'équilibrage : `engine/des/` (SimPy, déterministe avec graine).

## Objets
| Objet | Rôle | Réglages |
|---|---|---|
| Source | lance les paquets selon l'ordre de coupe (lots modèle/taille/quantité) | pièces par paquet, flux tiré ou intervalle, plafond d'encours (CONWIP), encours de départ |
| File (chariot d'encours) | devant chaque poste, FIFO, retouches en tête | capacité (paquets) |
| Poste / processeur | 1..n serveurs ; temps = SAM / (efficience ligne × rendement opérateur) | loi constante / normale tronquée / triangulaire / lognormale, mise en route au changement de lot, pannes MTBF/MTTR (exponentielles) + pannes planifiées, défauts % → retouche au poste choisi |
| Opérateur | ressource mobile : marche (≈ 1 m/s) jusqu'au poste qui l'appelle, tient plusieurs postes voisins (affectation de l'équilibrage), porte les paquets si le poste suivant est loin | vitesse de marche, seuil de port |
| Transporteur (agent de liaison / chariot) | ramasse jusqu'à `capacity` paquets au même poste et les dépose | nombre, capacité, vitesse, temps de chargement |
| Sortie | compte les pièces, temps de traversée | — |
| Équipe | pauses : tout s'arrête | durée, pauses |

Chemins : grille de passage du plan d'atelier (`engine/workshop.py`, murs/poteaux/machines contournés, portes ouvertes), Dijkstra multi-cibles (`engine/des/paths.py`) ; sans plan : ligne droite.

## Sorties
- Trace horodatée (`trace.events`) : états des postes, lieux des paquets, déplacements et états des acteurs ; `trace.paths` = polylignes ; plafonnée (90 000 événements par simulation, répartis entre scénarios).
- Statistiques : états par poste (travail, attente matière, bloqué aval, panne, mise en route, attente opérateur, pause, transfert) en %, files moyenne/max, utilisation et distance des opérateurs (Gantt), transporteurs, encours dans le temps, débit horaire et cumulé vs objectif (60 / cycle du calcul), temps de traversée (histogramme, p90), goulot (poste le plus actif ; à ±1 point, la plus forte charge par serveur), conservation des pièces.
- Expérimentateur : jusqu'à 3 scénarios × 20 réplications (graines), moyenne ± IC 95 % (Student).

## API
`GET /v1/orgs/{org}/runs/{id}/des/model[?plan_id]`, `POST /v1/orgs/{org}/runs/{id}/des` (202, tâche de fond), `GET …/des/simulations`, `GET /v1/orgs/{org}/simulations/{sid}`, `GET …/simulations/{sid}/des.xlsx|des.pdf`. Stockage : `twin_simulations` (`kind = 'des'`, `layout` = modèle). Budget Render gratuit : postes × minutes × réplications × scénarios ≤ 864 000 (réplications réduites au-delà).

## Interface
`/simulation/:runId` : réglages du modèle, scénarios, lecture 2D (canvas) + 3D (three.js, InstancedMesh, décor fusionné par matériau) synchronisées, x1–x600, tableaux de bord, exports.

## Limites de la phase 1 (pistes des phases suivantes)
- Ligne série (ordre des stations) ; pas de branches parallèles ni d'assemblage de sous-ensembles.
- Pas de logique personnalisée par blocs (Process Flow), pas d'optimiseur automatique (OptQuest), import CAO = DXF des murs seulement, pas de VR.
- Pauses communes à toute l'équipe ; pannes indépendantes par poste ; opérateurs non qualifiés non modélisés hors absences (reprise par la voisine la moins chargée).

## Phase 2.1 — Convoyeur suspendu (UPS type Eton / INA), livré le 2026-11-11
Modules : `engine/des/conveyor.py` (géométrie, réglages) et `engine/des/conveyor_sim.py` (comportement, mixin du simulateur).

| Élément | Modèle |
|---|---|
| Rail | boucle principale fermée (sommets ; angles arrondis en courbes de rayon réglable ; tronçons droits / courbes), sens unique, hauteur réglable. Dessinée sur le plan d'atelier (outil « Convoyeur » de /atelier/plan, élément `rail`) ou générée autour des postes. |
| Dérivations | une par poste : aiguillage d'entrée sur la boucle (projection du chariot d'encours du poste), tampon = **limite d'encours par station** (cintres), aiguillage de sortie. |
| Cintres (porte-pièces) | adressables (C001…), capacité en pièces, nombre réglable (0 = auto : postes × (encours + 1) + 4). |
| Chargement / déchargement | stations sur la boucle près de l'entrée / de la sortie ; stock de cintres vides au chargement ; temps de chargement / déchargement. |
| Mouvement | vitesse du rail (m/min), temps d'aiguillage (s) + longueur de la dérivation ; place sur la boucle = longueur / espacement mini (accumulation et blocage : un poste reste « bloqué aval » tant que le cintre ne peut pas rentrer sur la boucle). |
| Routage | selon la gamme (étape par étape) ; poste plein → tour supplémentaire (recirculation) ; **réaffectation dynamique** vers le poste le moins chargé parmi ceux qui ont la compétence : postes d'une même opération partagée, postes dont une opératrice a toutes les compétences ET les machines de l'étape, ou postes déclarés interchangeables. |
| Pilotage du lancement | un cintre n'est chargé que si la boucle porte moins de `max_on_rail` cintres (auto = 2 par poste) et en gardant une réserve de places pour les sorties de postes (pas d'interblocage). |
| Défauts | cintre entier défectueux → repart par le rail vers le poste de retouche ; défauts partiels → retouche portée à la main. |

Indicateurs : occupation du rail (moyenne / max), cintres en circulation, temps sur rail vs aux postes par cintre, tours supplémentaires par poste, réaffectations, cintres déchargés, distance parcourue. Animation 2D (rail violet, flèches de sens, aiguillages ◆, cintres ● pleins/vides, pièces suspendues) et 3D (rail à sa hauteur, poteaux, cintres et pièces suspendues). Scénario comparatif : bouton « Comparer paquets / chariots et convoyeur suspendu » (ou champ « Convoyeur » de chaque scénario, surcharge `{"conveyor": {"enabled": true|false}}`).

Équivalence d'encours de départ : sur convoyeur, l'encours de départ (paquets × pièces) est réparti sur des cintres dans la limite d'encours de chaque poste.

Exemple (dos de pantalon de Karim, équilibrage RPW à la cadence 8 : 6 postes, goulot poste 3 « piquer pinces + assemblage fourche » 7,7 min, journée 8 h, 5 réplications) :

| | Paquets de 10 / chariots | Convoyeur suspendu (1 pc/cintre) | UPS + surjeteuse au poste 5 (W004 qualifiée) |
|---|---|---|---|
| Pièces / jour | 70 (dont encours de départ) | 66 | 97 (réaffectation dynamique : 591 cintres) |
| Encours moyen | 179 pcs | 23 pcs | 28 pcs |
| Traversée moyenne | 383 min | 146 min | 134 min |

Limites : un seul convoyeur par modèle ; pas de croisement entre boucles ni d'ascenseurs ; l'aiguillage de la boucle est modélisé par un temps (pas de collision fine entre cintres) ; la marche des opératrices au poste n'est pas modifiée par le convoyeur.

## Phase 2.2 — Logique personnalisée par blocs (type Process Flow), livrée le 2026-11-11
Moteur : `engine/des/flow.py` (SimPy, déterministe avec graine). Page `/flux/:runId` (bouton « Process Flow » d'un calcul, lien depuis la simulation 3D) : éditeur visuel @xyflow/react (MIT, chargé à part).

| Bloc | Rôle | Paramètres |
|---|---|---|
| Source | lance les paquets de l'ordre de coupe | lots (modèle, taille, couleur, quantité), pièces par paquet, intervalle (0 = tiré), produits en cours max |
| File | attente FIFO | capacité (0 = illimitée) |
| Opération | travail | min/pièce, serveurs, file devant, mise en route, ressource prise pendant l'opération, **poste du plan lié** (animation) |
| Retard | attente sans capacité | minutes |
| Décision | branche | probabilités / attribut (valeurs par sortie) / condition (attribut op valeur) |
| Séparation | sous-composants (devant, dos, manches…) | composants (un par sortie) |
| Assemblage | attend une pièce de chaque branche | appariement : même produit, même lot, même taille (ou attribut) |
| Contrôle | opération + défauts | % défauts → sortie « retouche » (boucle de retouche autorisée) |
| Groupage / dégroupage | lots de transfert | taille du groupe, même attribut |
| Prendre / libérer ressource | opérateur, machine, chariot | ressource, quantité |
| Attribut | taille, couleur, modèle… | fixer ou tirer au hasard (valeurs + poids) |
| Sortie | produits finis | — |

- Génération automatique depuis la gamme : précédences des opérations → graphe des stations (réduction transitive) → séparation là où plusieurs branches partent, assemblage là où elles se rejoignent ; sans précédence exploitable : ligne en série.
- Validation : types, sorties reliées, au moins 2 entrées par assemblage, branches orphelines (non alimentées) ou sans issue, cycles (erreur sauf boucle passant par une décision ou un contrôle = avertissement), ressources déclarées.
- Exécution (`POST …/runs/{id}/flow/simulate`, tâche de fond, `twin_simulations.kind = 'flow'`), réplications + IC 95 %. Conservation des pièces : chaque jeton porte la part de produit qu'il représente (séparation en k = 1/k chacun, assemblage = somme).
- Animation : jetons présents par bloc (● n) au fil du temps ; les blocs d'opération liés à un poste colorent ce poste sur le plan (travail / attente / bloqué).
- Stockage : table `process_flows` (migration 20261111000009, RLS par atelier : membres en lecture, owner/admin/methodes/chef_ligne en écriture).
- Limites : pas de sous-graphes réutilisables ; une seule loi de temps par opération ; les opérateurs ne se déplacent pas dans ce mode (ressources abstraites) ; animation du plan limitée aux états des postes liés.
