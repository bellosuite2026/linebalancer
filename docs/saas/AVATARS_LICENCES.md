# Personnages et accessoires de la simulation — origine et licences

Style « détaillé » de la page Simulation (vue 2D et vue 3D), livré le 2026-11-13.

| Élément | Fichier | Origine | Licence |
|---|---|---|---|
| Ouvriers low-poly (opératrice, agent de liaison, contrôleuse, mécanicien) : bassin, cuisses, tibias + chaussures, torse, bras, mains, tête, cheveux / chignon, casquette, tablier, porte-bloc, caisse à outils, tabouret | web/src/lib/avatars3d.ts | Généré par le code (géométries three.js : boîtes, cylindres, icosaèdres) | Code du projet (aucune ressource tierce) |
| Animations marche, couture assise, travail debout, portage, poussée de chariot, attente, pause assise, réparation à genou | web/src/lib/avatars3d.ts (fonction `pose`) | Cinématique procédurale (angles sinusoïdaux) | Code du projet |
| Chariot de l'agent de liaison, paquet plié avec lien, matelas de coupe, palette de cartons | web/src/lib/avatars3d.ts | Généré par le code | Code du projet |
| Détails des machines (cônes de fil, lampe LED, pédale, tiroir, bac de pièces ; fer + centrale ; table lumineuse) | web/src/lib/machines3d.ts (`addMachineDetails`) | Généré par le code | Code du projet |
| Bulles d'état (sablier, tasse, engrenage, clé) et pictogrammes 2D vus de dessus | web/src/lib/simIcons.ts | Dessin canvas 2D par le code (pas de police d'emoji ni d'image) | Code du projet |
| three.js | dépendance npm | three.js | MIT |

Aucun modèle Mixamo, Sketchfab ou autre fichier externe n'est utilisé. Si des modèles CC0 (ex. Kenney, Quaternius) sont ajoutés plus tard, les lister ici avec leur URL et leur licence.

## Fonctionnement
- Réglage « Style simple / Style détaillé » dans la barre de la page Simulation, mémorisé dans le navigateur (`localStorage` `tlb.sim.style`, détaillé par défaut).
- Le module 3D des personnages est un chunk séparé (`avatars3d-*.js`, ~7 Ko) chargé seulement en style détaillé.
- Une seule InstancedMesh par partie du corps : ~20 appels de dessin quel que soit l'effectif (jusqu'à 324 personnages).
- Rôles : contrôleuse = opératrice dont le poste principal est un contrôle (catégorie « controle » ou libellé / type / opérations contenant contrôle, inspection, visite, vérif) ; agent de liaison = transporteur du modèle ; mécanicien = apparaît à côté d'une machine en panne pendant la panne ; opératrice = les autres.
- Poses : machine à coudre = assise sur tabouret ; repassage, table, contrôle = debout ; marche, portage d'un paquet, poussée du chariot, attente (bulle sablier), pause (assise, bulle tasse), mise en route (bulle engrenage), panne (mécanicien à genou + bulle clé).
