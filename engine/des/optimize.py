"""Optimiseur de la simulation (phase 2.3, type OptQuest de FlexSim) — pur Python, séparé des solveurs.

Variables de décision (« gènes ») appliquées au modèle DES :
  - effectifs / affectations : renforts (+1 opératrice) sur des postes choisis, retraits d'opératrices dont le
    poste est repris par la voisine la moins chargée ;
  - taille de paquet ; encours max (plafond CONWIP en paquets = facteur × nombre de postes) ;
  - agents de liaison (transporteurs) ; nombre de cintres et encours par poste si convoyeur suspendu ;
  - placement des postes : variantes d'implantation (actuelle, ligne, U, échanges de postes sur des machines
    du même type pour raccourcir les trajets).

Objectifs (au choix) : pièces / jour (max), coût minute (TND par minute produite, min), encours moyen (min),
distance de marche + transport (min). Contraintes : débit minimal / heure, encours moyen max, effectif max,
coût minute max.

Recherche : NSGA-II léger (tri non dominé + distance d'encombrement, domination sous contraintes de Deb),
population initiale = référence + plan d'expériences (hypercube latin sur les gènes simples) ; chaque
évaluation = moyenne de réplications avec graines communes (CRN) ; budget de temps borné ; rappel de
progression à chaque génération.
"""
from __future__ import annotations

import copy
import math
import random
import time
from typing import Callable, Optional

from engine.des.builder import ensure_paths
from engine.des.experiment import ci
from engine.des.model import apply_overrides, normalize_model
from engine.des.sim import simulate

OBJECTIVES = {
    "pieces": {"label": "Pièces / jour", "sense": "max", "unit": "pcs"},
    "cost_minute": {"label": "Coût minute", "sense": "min", "unit": "TND/min"},
    "wip_avg": {"label": "Encours moyen", "sense": "min", "unit": "pcs"},
    "walk_m": {"label": "Marche + transport", "sense": "min", "unit": "m"},
}
BUNDLE_CHOICES = [5, 8, 10, 12, 15, 20, 25, 30]
WIP_FACTORS = [0, 1.0, 1.5, 2.0, 3.0, 4.0]            # 0 = pas de plafond (flux poussé)
CARRIER_FACTORS = [0, 2.0, 3.0, 4.0, 6.0]             # 0 = automatique
STATION_WIP_CHOICES = [2, 3, 4, 6, 8]

DEFAULTS = {
    "objectives": ["pieces", "cost_minute", "wip_avg", "walk_m"],
    "cost_per_minute": 0.06,          # TND par minute payée et par personne (≈ 3,6 TND/h charges comprises)
    "replications": 3, "time_budget_s": 45.0, "max_evals": 400, "population": 14, "seed": 7,
    "max_extra_operators": 2, "max_fewer_operators": 2, "max_transporters": 3,
    "vary": {"staffing": True, "bundle_size": True, "wip_cap": True, "transporters": True, "conveyor": True,
             "layout": True},
    "constraints": {"min_per_hour": None, "max_wip_avg": None, "max_people": None, "max_cost_minute": None},
}


def _num(v, default=None):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def normalize_config(cfg: Optional[dict]) -> dict:
    c = copy.deepcopy(DEFAULTS)
    cfg = cfg or {}
    objs = [o for o in cfg.get("objectives") or c["objectives"] if o in OBJECTIVES]
    c["objectives"] = list(dict.fromkeys(objs)) or ["pieces", "cost_minute"]
    if len(c["objectives"]) < 2:
        c["objectives"].append("cost_minute" if c["objectives"][0] != "cost_minute" else "pieces")
    c["cost_per_minute"] = max(0.0, min(10.0, _num(cfg.get("cost_per_minute"), c["cost_per_minute"])))
    c["replications"] = int(max(1, min(10, _num(cfg.get("replications"), c["replications"]))))
    c["time_budget_s"] = max(5.0, min(180.0, _num(cfg.get("time_budget_s"), c["time_budget_s"])))
    c["max_evals"] = int(max(10, min(2000, _num(cfg.get("max_evals"), c["max_evals"]))))
    c["population"] = int(max(6, min(40, _num(cfg.get("population"), c["population"]))))
    c["seed"] = int(_num(cfg.get("seed"), c["seed"]))
    for k in ("max_extra_operators", "max_fewer_operators"):
        c[k] = int(max(0, min(6, _num(cfg.get(k), c[k]))))
    c["max_transporters"] = int(max(0, min(6, _num(cfg.get("max_transporters"), c["max_transporters"]))))
    c["vary"].update({k: bool(v) for k, v in (cfg.get("vary") or {}).items() if k in c["vary"]})
    for k in c["constraints"]:
        v = (cfg.get("constraints") or {}).get(k)
        c["constraints"][k] = None if v in (None, "") else _num(v)
    return c


# --------------------------------------------------------------------------- placement
def _slot(st: dict) -> dict:
    return {k: st.get(k) for k in ("x", "y", "qx", "qy", "mx", "my", "rot", "machine", "machine_ids")}


def _pairs_len(model: dict) -> float:
    pos = {str(s["id"]): (float(s["x"]), float(s["y"])) for s in model["stations"]}
    route = [str(r) for r in model.get("route") or pos]
    d = sum(math.dist(pos[a], pos[b]) for a, b in zip(route, route[1:]))
    for o in model.get("operators") or []:
        sts = [str(s) for s in o.get("stations") or [] if str(s) in pos]
        d += 2 * sum(math.dist(pos[a], pos[b]) for a, b in zip(sts, sts[1:]))
    return d


def swap_variant(model: dict, max_rounds: int = 60) -> Optional[dict]:
    """Échanges de postes entre machines du même type (2-opt glouton sur les distances à vol d'oiseau :
    enchaînement de la gamme + trajets des opératrices qui tiennent plusieurs postes)."""
    m = copy.deepcopy(model)
    sts = m["stations"]
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(sts):
        groups.setdefault(str(s.get("machine_type") or s.get("machine") or ""), []).append(i)
    best = _pairs_len(m)
    start = best
    improved, rounds = True, 0
    while improved and rounds < max_rounds:
        improved, rounds = False, rounds + 1
        for idx in groups.values():
            for a in range(len(idx)):
                for b in range(a + 1, len(idx)):
                    i, j = idx[a], idx[b]
                    si, sj = _slot(sts[i]), _slot(sts[j])
                    sts[i].update(sj)
                    sts[j].update(si)
                    d = _pairs_len(m)
                    if d < best - 1e-6:
                        best, improved = d, True
                    else:
                        sts[i].update(si)
                        sts[j].update(sj)
    if best >= start - 0.5:
        return None
    m["paths"] = {}
    m["name"] = m.get("name") or "Ligne"
    return m


# --------------------------------------------------------------------------- application des gènes
def _people(model: dict) -> int:
    return len(model.get("operators") or []) + len(model.get("transporters") or [])


def remove_operators(model: dict, ids: list[str]) -> dict:
    """Retrait d'opératrices : chaque poste laissé vide est repris par la voisine (gamme) la moins chargée."""
    m = copy.deepcopy(model)
    gone = {str(i) for i in ids}
    if not gone:
        return m
    route = [str(s["id"]) for s in m["stations"]]
    m["operators"] = [o for o in m.get("operators") or [] if o["id"] not in gone]
    load = {o["id"]: 0.0 for o in m["operators"]}
    for st in m["stations"]:
        st["operators"] = [o for o in st.get("operators") or [] if o not in gone]
        for o in st["operators"]:
            load[o] = load.get(o, 0) + float(st.get("minutes") or 0) / max(1, len(st["operators"]))
    for st in m["stations"]:
        if st["operators"]:
            st["servers"] = max(1, min(int(st.get("servers") or 1), len(st["operators"])))
            continue
        i = route.index(str(st["id"]))
        cands = []
        for j in (i - 1, i + 1, i - 2, i + 2):
            if 0 <= j < len(route):
                cands += [o for o in next(s for s in m["stations"] if str(s["id"]) == route[j]).get("operators") or []]
            if cands:
                break
        if not cands:
            return model   # retrait impossible : modèle inchangé
        o = min(cands, key=lambda x: (load.get(x, 0), x))
        st["operators"], st["servers"] = [o], 1
        load[o] = load.get(o, 0) + float(st.get("minutes") or 0)
        for op in m["operators"]:
            if op["id"] == o and str(st["id"]) not in op["stations"]:
                op["stations"].append(str(st["id"]))
    return m


def add_helpers(model: dict, station_ids: list[str]) -> dict:
    m = copy.deepcopy(model)
    for sid in station_ids:
        st = next((s for s in m["stations"] if str(s["id"]) == str(sid)), None)
        if not st:
            continue
        rid = f"R{sid}"
        k = 1
        while any(o["id"] == rid for o in m.get("operators") or []):
            k += 1
            rid = f"R{sid}-{k}"
        st["operators"] = list(st.get("operators") or []) + [rid]
        st["servers"] = int(st.get("servers") or 1) + 1
        m.setdefault("operators", []).append({"id": rid, "name": f"Renfort poste {sid}", "efficiency": 1.0,
                                              "stations": [str(sid)], "skills": list(st.get("skills") or [])})
    return m


def genes_to_overrides(genes: dict, n_stations: int) -> dict:
    ov: dict = {}
    src: dict = {}
    if genes.get("bundle_size"):
        src["bundle_size"] = int(genes["bundle_size"])
    if genes.get("wip_factor") is not None:
        f = float(genes["wip_factor"])
        src["wip_cap_bundles"] = int(math.ceil(f * n_stations)) if f > 0 else None
    if src:
        ov["source"] = src
    if genes.get("transporters") is not None:
        ov["transporters"] = {"count": int(genes["transporters"]), "capacity": 4, "speed_m_per_min": 60, "load_min": 0.2}
    cv = {}
    if genes.get("carrier_factor") is not None:
        cv["carriers"] = int(math.ceil(float(genes["carrier_factor"]) * n_stations)) if genes["carrier_factor"] else 0
    if genes.get("station_wip") is not None:
        cv["station_wip"] = int(genes["station_wip"])
    if cv:
        ov["conveyor"] = cv
    return ov


def apply_genes(variants: list[dict], genes: dict, workshop_plan: Optional[dict] = None,
                path_cache: Optional[dict] = None) -> dict:
    """Modèle complet d'une solution (variante d'implantation + effectifs + réglages)."""
    v = int(genes.get("layout") or 0)
    base = variants[v if 0 <= v < len(variants) else 0]["model"]
    m = remove_operators(base, list(genes.get("fewer") or []))
    m = add_helpers(m, list(genes.get("helpers") or []))
    m = apply_overrides(m, genes_to_overrides(genes, len(m["stations"])))
    if path_cache is not None:
        m["paths"] = {**path_cache.setdefault(v, dict(m.get("paths") or {})), **(m.get("paths") or {})}
    m = ensure_paths(m, workshop_plan)
    if m.get("transporters"):
        from engine.des.builder import compute_paths
        have = m.get("paths") or {}
        route = [str(r) for r in m.get("route") or [s["id"] for s in m["stations"]]]
        keys = ["src"] + route
        if any(f"{min(a, b)}|{max(a, b)}" not in have for i, a in enumerate(keys) for b in keys[i + 1:]):
            m["paths"] = {**compute_paths(m, workshop_plan, True), **have}
    if path_cache is not None:
        path_cache[v].update(m.get("paths") or {})
    return m


def describe(genes: dict, base_genes: dict, variants: list[dict], model: dict) -> list[str]:
    out = []
    if genes.get("helpers"):
        out.append("Renfort au(x) poste(s) " + ", ".join(sorted(genes["helpers"], key=_k)))
    if genes.get("fewer"):
        names = {o["id"]: o.get("name") or o["id"] for o in variants[0]["model"].get("operators") or []}
        out.append("Sans " + ", ".join(names.get(i, i) for i in sorted(genes["fewer"])) + " (poste repris par la voisine)")
    if genes.get("bundle_size") != base_genes.get("bundle_size"):
        out.append(f"Paquets de {genes['bundle_size']}")
    if genes.get("wip_factor") != base_genes.get("wip_factor"):
        f = genes.get("wip_factor") or 0
        out.append(f"Encours max {math.ceil(f * len(model['stations']))} paquets" if f else "Encours sans plafond")
    if genes.get("transporters") != base_genes.get("transporters"):
        n = int(genes.get("transporters") or 0)
        out.append(f"{n} agent(s) de liaison" if n else "Sans agent de liaison")
    if genes.get("carrier_factor") != base_genes.get("carrier_factor"):
        f = genes.get("carrier_factor") or 0
        out.append(f"{math.ceil(f * len(model['stations']))} cintres" if f else "Cintres automatiques")
    if genes.get("station_wip") != base_genes.get("station_wip"):
        out.append(f"Encours {genes['station_wip']} cintres / poste")
    if int(genes.get("layout") or 0) != int(base_genes.get("layout") or 0):
        out.append("Implantation : " + variants[int(genes["layout"])]["name"])
    return out or ["Configuration actuelle"]


def _k(s: str):
    return (0, int(s)) if str(s).isdigit() else (1, str(s))


# --------------------------------------------------------------------------- évaluation
def evaluate(model: dict, cfg: dict, seeds: list[int]) -> dict:
    nm = normalize_model(model)
    sam = sum(float(s["minutes"]) for s in nm["stations"])
    T = float(nm["shift"]["minutes"])
    people = _people(nm)
    vals: dict[str, list[float]] = {k: [] for k in ("pieces", "per_hour", "wip_avg", "walk_m", "lead_time_avg",
                                                    "operator_util_avg", "cost_minute")}
    bott = []
    for sd in seeds:
        k = simulate(nm, sd, False)["kpis"]
        pcs = float(k["pieces"] or 0)
        vals["pieces"].append(pcs)
        vals["per_hour"].append(float(k["per_hour"] or 0))
        vals["wip_avg"].append(float(k["wip_avg"] or 0))
        vals["walk_m"].append(float(k["walk_m"] or 0) + float(k["transport_m"] or 0))
        if k.get("lead_time_avg") is not None and pcs > 0:
            vals["lead_time_avg"].append(float(k["lead_time_avg"]))
        vals["operator_util_avg"].append(float(k["operator_util_avg"] or 0))
        cost = cfg["cost_per_minute"] * people * T
        vals["cost_minute"].append(cost / (pcs * sam) if pcs > 0 and sam > 0 else 99.0)
        bott.append(k["bottleneck"])
    kpis = {k: ci(v) for k, v in vals.items()}
    mean = {k: (kpis[k]["mean"] if kpis[k]["mean"] is not None else (None if k == "lead_time_avg" else 0.0)) for k in kpis}
    mean["cost_minute"] = round(sum(vals["cost_minute"]) / len(vals["cost_minute"]), 4)
    kpis["cost_minute"]["mean"] = mean["cost_minute"]
    pcs_mean = mean["pieces"]
    mean["cost_piece"] = round(cfg["cost_per_minute"] * people * T / pcs_mean, 3) if pcs_mean else None
    mean["people"] = people
    mean["operators"] = len(nm["operators"])
    mean["transporters"] = len(nm["transporters"])
    mean["bottleneck"] = max(set(bott), key=bott.count)
    return {"kpis": kpis, "mean": mean}


def violation(mean: dict, cons: dict) -> float:
    v = 0.0
    if cons.get("min_per_hour") is not None and mean["per_hour"] < cons["min_per_hour"]:
        v += (cons["min_per_hour"] - mean["per_hour"]) / max(1.0, cons["min_per_hour"])
    if cons.get("max_wip_avg") is not None and mean["wip_avg"] > cons["max_wip_avg"]:
        v += (mean["wip_avg"] - cons["max_wip_avg"]) / max(1.0, cons["max_wip_avg"])
    if cons.get("max_people") is not None and mean["people"] > cons["max_people"]:
        v += (mean["people"] - cons["max_people"]) / max(1.0, cons["max_people"])
    if cons.get("max_cost_minute") is not None and mean["cost_minute"] > cons["max_cost_minute"]:
        v += (mean["cost_minute"] - cons["max_cost_minute"]) / max(1e-6, cons["max_cost_minute"])
    return round(v, 6)


def objective_vector(mean: dict, objs: list[str]) -> list[float]:
    return [(-mean[o] if OBJECTIVES[o]["sense"] == "max" else mean[o]) for o in objs]


# --------------------------------------------------------------------------- NSGA-II
def dominates(a: dict, b: dict) -> bool:
    if a["viol"] != b["viol"]:
        return a["viol"] < b["viol"]
    fa, fb = a["f"], b["f"]
    return all(x <= y for x, y in zip(fa, fb)) and any(x < y for x, y in zip(fa, fb))


def fronts(pop: list[dict]) -> list[list[int]]:
    n = len(pop)
    S = [[] for _ in range(n)]
    cnt = [0] * n
    out: list[list[int]] = [[]]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if dominates(pop[i], pop[j]):
                S[i].append(j)
            elif dominates(pop[j], pop[i]):
                cnt[i] += 1
        if cnt[i] == 0:
            out[0].append(i)
    k = 0
    while out[k]:
        nxt = []
        for i in out[k]:
            for j in S[i]:
                cnt[j] -= 1
                if cnt[j] == 0:
                    nxt.append(j)
        k += 1
        out.append(nxt)
    return out[:-1]


def crowding(pop: list[dict], idx: list[int]) -> dict[int, float]:
    d = {i: 0.0 for i in idx}
    if len(idx) <= 2:
        return {i: float("inf") for i in idx}
    for m in range(len(pop[idx[0]]["f"])):
        s = sorted(idx, key=lambda i: pop[i]["f"][m])
        lo, hi = pop[s[0]]["f"][m], pop[s[-1]]["f"][m]
        d[s[0]] = d[s[-1]] = float("inf")
        if hi - lo <= 1e-12:
            continue
        for a in range(1, len(s) - 1):
            d[s[a]] += (pop[s[a + 1]]["f"][m] - pop[s[a - 1]]["f"][m]) / (hi - lo)
    return d


class Space:
    """Domaine des gènes pour un modèle donné."""

    def __init__(self, variants: list[dict], cfg: dict):
        self.variants, self.cfg = variants, cfg
        m = normalize_model(variants[0]["model"])
        self.model = m
        self.n = len(m["stations"])
        self.station_ids = [s["id"] for s in m["stations"]]
        self.op_ids = [o["id"] for o in m["operators"]]
        self.conveyor = bool(m["conveyor"]["enabled"])
        vary = cfg["vary"]
        bs = int(m["source"]["bundle_size"])
        self.bundle = sorted(set(BUNDLE_CHOICES + [bs])) if vary["bundle_size"] and not self.conveyor else [bs]
        cap = m["source"].get("wip_cap_bundles")
        f0 = 0 if not cap else round(cap / max(1, self.n), 2)
        self.wipf = sorted(set(WIP_FACTORS + [f0])) if vary["wip_cap"] and not self.conveyor else [f0]
        t0 = len(m["transporters"])
        self.trans = list(range(0, max(t0, cfg["max_transporters"]) + 1)) if vary["transporters"] and not self.conveyor else [t0]
        c0 = 0 if not m["conveyor"].get("carriers") else round(m["conveyor"]["carriers"] / max(1, self.n), 2)
        self.carr = sorted(set(CARRIER_FACTORS + [c0])) if (self.conveyor and vary["conveyor"]) else [c0]
        w0 = int(m["conveyor"].get("station_wip") or 4)
        self.swip = sorted(set(STATION_WIP_CHOICES + [w0])) if (self.conveyor and vary["conveyor"]) else [w0]
        self.layouts = list(range(len(variants))) if vary["layout"] else [0]
        self.max_extra = cfg["max_extra_operators"] if vary["staffing"] else 0
        self.max_fewer = min(cfg["max_fewer_operators"], max(0, len(self.op_ids) - 1)) if vary["staffing"] else 0
        self.base = {"bundle_size": bs, "wip_factor": f0, "transporters": t0, "carrier_factor": c0, "station_wip": w0,
                     "layout": 0, "helpers": (), "fewer": ()}
        # postes les plus chargés = candidats aux renforts ; moins chargés = candidats aux retraits
        load = sorted(m["stations"], key=lambda s: -float(s["minutes"]) / max(1, int(s["servers"])))
        self.helper_pool = [s["id"] for s in load[: max(3, min(self.n, 8))]]
        light = sorted(m["operators"], key=lambda o: sum(float(s["minutes"]) / max(1, int(s["servers"]))
                                                         for s in m["stations"] if s["id"] in o["stations"]))
        self.fewer_pool = [o["id"] for o in light[: max(3, min(len(light), 8))]]

    def random(self, rng: random.Random) -> dict:
        g = {"bundle_size": rng.choice(self.bundle), "wip_factor": rng.choice(self.wipf),
             "transporters": rng.choice(self.trans), "carrier_factor": rng.choice(self.carr),
             "station_wip": rng.choice(self.swip), "layout": rng.choice(self.layouts)}
        g["helpers"] = tuple(sorted(rng.sample(self.helper_pool, rng.randint(0, min(self.max_extra, len(self.helper_pool)))), key=_k))
        g["fewer"] = tuple(sorted(rng.sample(self.fewer_pool, rng.randint(0, min(self.max_fewer, len(self.fewer_pool)))), key=_k))
        return self.fix(g)

    def lhs(self, rng: random.Random, n: int) -> list[dict]:
        """Plan d'expériences : hypercube latin sur les gènes simples, effectifs aléatoires."""
        cols = {}
        for key, dom in (("bundle_size", self.bundle), ("wip_factor", self.wipf), ("transporters", self.trans),
                         ("carrier_factor", self.carr), ("station_wip", self.swip), ("layout", self.layouts)):
            seq = [dom[int(i * len(dom) / n) % len(dom)] for i in range(n)]
            rng.shuffle(seq)
            cols[key] = seq
        out = []
        for i in range(n):
            g = self.random(rng)
            g.update({k: cols[k][i] for k in cols})
            out.append(self.fix(g))
        return out

    def fix(self, g: dict) -> dict:
        g = dict(g)
        g["helpers"] = tuple(sorted(set(g.get("helpers") or ()), key=_k))[: self.max_extra]
        g["fewer"] = tuple(sorted(set(g.get("fewer") or ()), key=_k))[: self.max_fewer]
        return g

    def mutate(self, g: dict, rng: random.Random, rate: float = 0.35) -> dict:
        g = dict(g)

        def step(dom, cur):
            if len(dom) <= 1:
                return cur
            i = dom.index(cur) if cur in dom else 0
            return dom[max(0, min(len(dom) - 1, i + rng.choice((-2, -1, 1, 2))))]
        for key, dom in (("bundle_size", self.bundle), ("wip_factor", self.wipf), ("transporters", self.trans),
                         ("carrier_factor", self.carr), ("station_wip", self.swip)):
            if rng.random() < rate:
                g[key] = step(dom, g[key])
        if rng.random() < rate and len(self.layouts) > 1:
            g["layout"] = rng.choice(self.layouts)
        for key, pool, mx in (("helpers", self.helper_pool, self.max_extra), ("fewer", self.fewer_pool, self.max_fewer)):
            if mx and rng.random() < rate:
                s = set(g[key])
                if s and (len(s) >= mx or rng.random() < 0.5):
                    s.discard(rng.choice(sorted(s)))
                else:
                    s.add(rng.choice(pool))
                g[key] = tuple(s)
        return self.fix(g)

    def cross(self, a: dict, b: dict, rng: random.Random) -> dict:
        return self.fix({k: (a[k] if rng.random() < 0.5 else b[k]) for k in a})


def key_of(g: dict) -> str:
    return "|".join(f"{k}={g[k]}" for k in sorted(g))


def optimize(variants: list[dict], config: Optional[dict] = None, workshop_plan: Optional[dict] = None,
             progress: Optional[Callable[[dict], None]] = None) -> dict:
    """variants : [{"name": "Implantation actuelle", "model": modèle}, ...] (la première = référence)."""
    cfg = normalize_config(config)
    variants = [{"name": str(v.get("name") or f"Variante {i + 1}")[:60], "model": normalize_model(v["model"])}
                for i, v in enumerate(variants)]
    rng = random.Random(cfg["seed"])
    space = Space(variants, cfg)
    seeds = [int(space.model["settings"]["seed"]) + r for r in range(cfg["replications"])]
    objs = cfg["objectives"]
    t0 = time.monotonic()
    cache: dict[str, dict] = {}
    paths: dict = {}
    history: list[dict] = []
    stop = {"why": "convergence"}

    def out_of_budget() -> bool:
        if time.monotonic() - t0 > cfg["time_budget_s"]:
            stop["why"] = "budget de temps"
            return True
        if len(cache) >= cfg["max_evals"]:
            stop["why"] = "nombre d'évaluations"
            return True
        return False

    def ev(g: dict) -> dict:
        k = key_of(g)
        if k not in cache:
            m = apply_genes(variants, g, workshop_plan, paths)
            r = evaluate(m, cfg, seeds)
            cache[k] = {"genes": g, "kpis": r["kpis"], "mean": r["mean"], "viol": violation(r["mean"], cfg["constraints"]),
                        "f": objective_vector(r["mean"], objs), "eval": len(cache) + 1}
        return cache[k]

    base = ev(space.base)
    P = cfg["population"]
    pop = [base] + [ev(g) for g in space.lhs(rng, P - 1) if not out_of_budget()]
    gen = 0

    def report():
        fr = fronts(pop)[0] if pop else []
        best = max((pop[i]["mean"]["pieces"] for i in fr), default=0)
        h = {"gen": gen, "evals": len(cache), "elapsed_s": round(time.monotonic() - t0, 1), "front": len(fr),
             "best_pieces": best}
        history.append(h)
        if progress:
            progress({**h, "budget_s": cfg["time_budget_s"],
                      "pct": min(99, round(100 * max(h["elapsed_s"] / cfg["time_budget_s"], len(cache) / cfg["max_evals"])))})

    report()
    stale = 0
    while not out_of_budget():
        gen += 1
        fr = fronts(pop)
        rank = {i: r for r, f in enumerate(fr) for i in f}
        crowd: dict[int, float] = {}
        for f in fr:
            crowd.update(crowding(pop, f))

        def tour() -> dict:
            i, j = rng.randrange(len(pop)), rng.randrange(len(pop))
            if rank[i] != rank[j]:
                return pop[i] if rank[i] < rank[j] else pop[j]
            return pop[i] if crowd[i] >= crowd[j] else pop[j]
        kids, tries = [], 0
        n_before = len(cache)
        while len(kids) < P and tries < P * 6 and not out_of_budget():
            tries += 1
            g = space.mutate(space.cross(tour()["genes"], tour()["genes"], rng), rng)
            kids.append(ev(g))
        stale = stale + 1 if len(cache) == n_before else 0
        union = {key_of(x["genes"]): x for x in pop + kids}
        allp = list(union.values())
        nxt = []
        for f in fronts(allp):
            if len(nxt) + len(f) <= P:
                nxt += [allp[i] for i in f]
            else:
                cd = crowding(allp, f)
                nxt += [allp[i] for i in sorted(f, key=lambda i: -cd[i])[: P - len(nxt)]]
                break
        pop = nxt
        report()
        if stale >= 3:          # plus aucune configuration nouvelle : domaine épuisé
            stop["why"] = "domaine exploré"
            break

    # front de Pareto sur toutes les évaluations (pas seulement la population finale)
    allv = list(cache.values())
    feas = [x for x in allv if x["viol"] == 0] or allv
    f0 = fronts(feas)[0]
    pareto = sorted((feas[i] for i in f0), key=lambda x: -x["mean"]["pieces"])
    base_genes = space.base

    def pack(x: dict, with_model: bool = False) -> dict:
        m = apply_genes(variants, x["genes"], workshop_plan, paths)
        d = {"key": key_of(x["genes"]), "genes": {k: (list(v) if isinstance(v, tuple) else v) for k, v in x["genes"].items()},
             "kpis": x["kpis"], "mean": x["mean"], "feasible": x["viol"] == 0, "violation": x["viol"],
             "changes": describe(x["genes"], base_genes, variants, m), "eval": x["eval"]}
        if with_model:
            d["overrides"] = genes_to_overrides(x["genes"], len(m["stations"]))
        return d

    sols = [pack(x, True) for x in pareto[:30]]
    for i, s in enumerate(sols):
        s["id"] = i + 1
        s["vs_base"] = {k: (round(s["mean"][k] - base["mean"][k], 4) if isinstance(base["mean"].get(k), (int, float))
                            and isinstance(s["mean"].get(k), (int, float)) else None)
                        for k in ("pieces", "cost_minute", "wip_avg", "walk_m", "people", "cost_piece")}
    cloud = [{"mean": {k: x["mean"][k] for k in ("pieces", "cost_minute", "wip_avg", "walk_m", "people")},
              "feasible": x["viol"] == 0} for x in allv[:600]]
    return {"engine": "opt-1.0", "config": cfg, "objectives": [{"key": o, **OBJECTIVES[o]} for o in objs],
            "variants": [v["name"] for v in variants], "base": pack(base, True), "pareto": sols, "cloud": cloud,
            "history": history, "evals": len(cache), "simulations": len(cache) * len(seeds),
            "elapsed_s": round(time.monotonic() - t0, 1), "stopped_by": stop["why"],
            "feasible_found": any(x["viol"] == 0 for x in allv)}
