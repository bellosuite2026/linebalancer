"""Simulation à événements discrets de l'atelier (v3.0, type FlexSim) — module séparé des solveurs.

- model.py         : format du modèle (Source, Files, Postes, Opérateurs, Transporteurs, Sortie), bornes.
- distributions.py : lois de variabilité (constante, normale tronquée, triangulaire, lognormale).
- paths.py         : graphe de déplacement (grille du plan d'atelier, plus courts chemins).
- builder.py       : génération automatique du modèle depuis un calcul + une implantation / un plan.
- sim.py           : simulateur SimPy (trace horodatée + statistiques FlexSim-like).
- experiment.py    : réplications, scénarios, intervalle de confiance 95 %.
"""
from engine.des.builder import build_model, ensure_paths
from engine.des.experiment import run_experiment, run_scenario
from engine.des.model import ModelError, apply_overrides, normalize_model
from engine.des.sim import Simulator, simulate

__all__ = ["build_model", "ensure_paths", "run_experiment", "run_scenario", "ModelError", "apply_overrides",
           "normalize_model", "Simulator", "simulate"]
