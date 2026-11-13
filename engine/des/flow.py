"""Logique personnalisée par blocs (type « Process Flow » de FlexSim) exécutée par un moteur à événements
discrets (SimPy). Module séparé des solveurs d'équilibrage.

Un graphe (JSON commun moteur / API / interface) :

    {"name": "...", "shift": {"minutes": 480, "breaks": [...]}, "settings": {"seed": 42, "dist": {...}},
     "resources": [{"name": "Opératrices", "kind": "operator|machine|chariot", "capacity": 6}],
     "blocks": [{"id": "b1", "type": "source", "label": "Coupe", "params": {...}, "x": 0, "y": 0}],
     "edges": [{"from": "b1", "port": 0, "to": "b2"}]}

Blocs (« jetons » = paquets ou pièces, porteurs d'attributs : modèle, taille, couleur, lot…) :
  source     lots [{style, size, color, qty}], bundle_size, interval_min (0 = tiré), wip_cap (produits en cours)
  queue      file FIFO, capacity (0 = illimitée)
  operation  minutes/pièce, servers, dist, setup_min, efficiency, resource (pool pris pendant l'opération),
             queue_capacity, station (lien vers un poste du plan pour l'animation)
  delay      minutes (par jeton, sans capacité : séchage, attente…)
  decision   mode prob (probs par sortie) | attr (routes [[valeurs]] par sortie, sinon la dernière) |
             cond (attr, op, value : sortie 0 si vrai, 1 sinon)
  split      sépare en sous-composants, un par sortie (components : devant / dos / manches…)
  join       assemblage : attend un jeton sur chaque entrée avec la même clé (match : product | lot | size |
             attribut) puis en sort un seul
  inspect    contrôle : comme une opération ; defect_pct → sortie 1 (retouche), sinon sortie 0
  batch      groupage de `size` jetons de même clé (key : attribut ou rien) ; unbatch : dégroupage
  acquire    prend `qty` d'une ressource (opérateur, machine, chariot) ; release : la rend
  attribute  fixe des attributs (set {k: v}) ou en tire un au hasard (attr, values [[valeur, poids]])
  sink       sortie (comptage, temps de traversée)

Conservation : chaque jeton porte `pp` = pièces de produit qu'il représente (une séparation en k
sous-composants donne pp/k à chacun, un assemblage additionne) : lancé = terminé + en cours.
"""
from __future__ import annotations

import copy
import math
import random
import statistics
from collections import deque
from typing import Any, Optional

import simpy

from engine.des import distributions as D

BLOCK_TYPES = ["source", "queue", "operation", "delay", "decision", "split", "join", "inspect", "batch", "unbatch",
               "acquire", "release", "attribute", "sink"]
BLOCK_LABELS = {"source": "Source", "queue": "File", "operation": "Opération", "delay": "Retard", "decision": "Décision",
                "split": "Séparation", "join": "Assemblage", "inspect": "Contrôle", "batch": "Groupage",
                "unbatch": "Dégroupage", "acquire": "Prendre ressource", "release": "Libérer ressource",
                "attribute": "Attribut", "sink": "Sortie"}
# sorties attendues : nombre exact, ou (min, None)
OUTS: dict[str, Any] = {"source": 1, "queue": 1, "operation": 1, "delay": 1, "decision": (2, None), "split": (2, None),
                        "join": 1, "inspect": 2, "batch": 1, "unbatch": 1, "acquire": 1, "release": 1, "attribute": 1,
                        "sink": 0}
LIMITS = {"blocks": 300, "edges": 600, "tokens": 200_000, "trace_events": 80_000, "replications": 20}


class FlowError(ValueError):
    pass


def _f(v, d=0.0, lo=None, hi=None) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = float(d)
    if x != x:
        x = float(d)
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


# ====================================================================== validation
def _graph_index(g: dict):
    blocks = [b for b in g.get("blocks") or [] if isinstance(b, dict)]
    ids = [str(b.get("id")) for b in blocks]
    by = {str(b.get("id")): b for b in blocks}
    outs: dict[str, list[tuple[int, str]]] = {i: [] for i in ids}
    ins: dict[str, list[tuple[str, int]]] = {i: [] for i in ids}
    for e in g.get("edges") or []:
        a, b = str(e.get("from")), str(e.get("to"))
        if a in by and b in by:
            p = int(_f(e.get("port"), 0, 0, 50))
            outs[a].append((p, b))
            ins[b].append((a, p))
    for a in outs:
        outs[a].sort()
    return blocks, ids, by, outs, ins


def _sccs(ids: list[str], succ: dict[str, list[str]]) -> list[list[str]]:
    """Composantes fortement connexes (Tarjan itératif)."""
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = [0]
    for root in ids:
        if root in index:
            continue
        work = [(root, iter(succ.get(root, [])))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(succ.get(nxt, []))))
                elif nxt in on:
                    low[v] = min(low[v], index[nxt])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    out.append(comp)
    return out


def validate(g: dict) -> dict:
    """Erreurs bloquantes et avertissements ; chaque message cite les blocs concernés."""
    errors: list[dict] = []
    warnings: list[dict] = []
    blocks, ids, by, outs, ins = _graph_index(g)

    def err(msg, ids_=()):
        errors.append({"msg": msg, "blocks": list(ids_)})

    def warn(msg, ids_=()):
        warnings.append({"msg": msg, "blocks": list(ids_)})

    if not blocks:
        err("Le graphe est vide.")
        return {"ok": False, "errors": errors, "warnings": warnings}
    if len(blocks) > LIMITS["blocks"]:
        err(f"Trop de blocs ({len(blocks)} > {LIMITS['blocks']}).")
    if len(set(ids)) != len(ids):
        err("Deux blocs ont le même identifiant.")
    for e in g.get("edges") or []:
        if str(e.get("from")) not in by or str(e.get("to")) not in by:
            err("Lien vers un bloc inexistant.", [str(e.get("from")), str(e.get("to"))])
    res_names = {str(r.get("name")) for r in g.get("resources") or []}
    lab = lambda b: f"« {b.get('label') or BLOCK_LABELS.get(b.get('type'), b.get('type'))} »"  # noqa: E731
    for b in blocks:
        t, bid = b.get("type"), str(b.get("id"))
        if t not in BLOCK_TYPES:
            err(f"Type de bloc inconnu : {t}.", [bid])
            continue
        n_out = len(outs[bid])
        want = OUTS[t]
        if isinstance(want, int) and n_out != want:
            if want == 0:
                err(f"{lab(b)} : une sortie ne doit pas avoir de lien sortant.", [bid])
            elif n_out < want:
                err(f"{lab(b)} : {want - n_out} sortie(s) non reliée(s).", [bid])
            else:
                err(f"{lab(b)} : trop de liens sortants ({n_out} au lieu de {want}).", [bid])
        elif isinstance(want, tuple) and n_out < want[0]:
            err(f"{lab(b)} : il faut au moins {want[0]} sorties reliées.", [bid])
        ports = [p for p, _ in outs[bid]]
        if len(set(ports)) != len(ports):
            err(f"{lab(b)} : deux liens partent de la même sortie.", [bid])
        if t == "join" and len(ins[bid]) < 2:
            err(f"{lab(b)} : un assemblage attend au moins 2 branches en entrée.", [bid])
        if t == "source" and ins[bid]:
            err(f"{lab(b)} : une source ne reçoit pas de lien entrant.", [bid])
        if t != "source" and not ins[bid]:
            err(f"{lab(b)} : branche orpheline (aucun lien entrant).", [bid])
        p = b.get("params") or {}
        if t in ("acquire", "release") and str(p.get("resource") or "") not in res_names:
            err(f"{lab(b)} : ressource « {p.get('resource') or '?'} » non déclarée.", [bid])
        if t == "operation" and p.get("resource") and str(p["resource"]) not in res_names:
            err(f"{lab(b)} : ressource « {p['resource']} » non déclarée.", [bid])
        if t == "decision" and (p.get("mode") or "prob") == "prob":
            probs = [_f(x, 0, 0) for x in p.get("probs") or []]
            if probs and abs(sum(probs[: n_out]) - 1) > 0.02 and abs(sum(probs[: n_out]) - 100) > 2:
                warn(f"{lab(b)} : les probabilités ne font pas 100 % (elles seront normalisées).", [bid])
    srcs = [i for i in ids if by[i].get("type") == "source"]
    sinks = [i for i in ids if by[i].get("type") == "sink"]
    if not srcs:
        err("Il faut au moins une source.")
    if not sinks:
        err("Il faut au moins une sortie.")
    succ = {i: [b for _, b in outs[i]] for i in ids}
    pred = {i: [a for a, _ in ins[i]] for i in ids}

    def reach(starts, nb):
        seen, st = set(starts), list(starts)
        while st:
            v = st.pop()
            for w in nb.get(v, []):
                if w not in seen:
                    seen.add(w)
                    st.append(w)
        return seen

    fwd, bwd = reach(srcs, succ), reach(sinks, pred)
    orph = [i for i in ids if i not in fwd]
    dead = [i for i in ids if i not in bwd]
    if srcs and orph:
        err("Branche orpheline : bloc(s) qu'aucune source n'alimente.", orph)
    if sinks and dead:
        err("Branche sans issue : bloc(s) qui n'atteignent aucune sortie.", dead)
    for comp in _sccs(ids, succ):
        cyc = len(comp) > 1 or comp[0] in succ.get(comp[0], [])
        if not cyc:
            continue
        if any(by[c].get("type") in ("decision", "inspect") for c in comp):
            warn("Boucle (retouche) contrôlée par une décision / un contrôle.", comp)
        else:
            err("Cycle sans décision ni contrôle : les jetons tourneraient sans fin.", comp)
    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ====================================================================== simulation
class Token:
    __slots__ = ("id", "root", "qty", "pp", "attrs", "t0", "comp", "held", "children", "block", "lot")

    def __init__(self, tid, root, qty, pp, attrs, t0, lot=0):
        self.id, self.root, self.qty, self.pp, self.attrs, self.t0 = tid, root, qty, pp, attrs, t0
        self.comp = ""
        self.held: list = []
        self.children: list = []
        self.block = None
        self.lot = lot


class BlockStats:
    __slots__ = ("entered", "exited", "wip", "area", "last", "max", "busy", "servers", "waits", "defects")

    def __init__(self):
        self.entered = self.exited = self.wip = self.max = self.defects = 0
        self.area = self.last = self.busy = 0.0
        self.servers = 0
        self.waits: list[float] = []


class FlowSim:
    def __init__(self, graph: dict, seed: Optional[int] = None, trace: bool = True, station_ids: Optional[list] = None):
        chk = validate(graph)
        if not chk["ok"]:
            raise FlowError(chk["errors"][0]["msg"])
        self.g = graph
        S = graph.get("settings") or {}
        self.seed = int(_f(S.get("seed"), 42) if seed is None else seed)
        self.rng = random.Random(self.seed)
        self.dist = D.normalize(S.get("dist") or {"kind": "normal", "cv": 0.1})
        self.eff = _f(S.get("efficiency"), 1, 0.1, 3)
        sh = graph.get("shift") or {}
        self.T = _f(sh.get("minutes"), 480, 10, 960)
        self.breaks = sorted((_f(b.get("start_min"), 0), _f(b.get("start_min"), 0) + _f(b.get("minutes"), 0))
                             for b in sh.get("breaks") or [] if _f(b.get("minutes"), 0) > 0)
        self.env = simpy.Environment()
        self.blocks, self.ids, self.by, self.outs, self.ins = _graph_index(graph)
        self.bidx = {bid: k for k, bid in enumerate(self.ids)}
        # port d'entrée d'un lien (bloc amont, port amont) → rang parmi les entrées du bloc aval
        self.inport = {bid: {(a, p): k for k, (a, p) in enumerate(self.ins[bid])} for bid in self.ids}
        self.stats = {bid: BlockStats() for bid in self.ids}
        self.pools = {str(r.get("name")): simpy.Resource(self.env, capacity=int(_f(r.get("capacity"), 1, 1, 500)))
                      for r in graph.get("resources") or []}
        self.pool_busy = {k: 0.0 for k in self.pools}
        self.stores: dict[str, simpy.Store] = {}
        self.join_buf: dict[str, dict] = {}
        self.batch_buf: dict[str, dict] = {}
        self.live: dict[int, Token] = {}
        self.next_id = 0
        self.launched_pp = self.done_pp = 0.0
        self.done_tokens = 0
        self.lead: list[float] = []
        self.completions: list[tuple[float, float]] = []
        self.wip_series: list[list] = []
        self.capacity_event = self.env.event()
        self.trace_on = trace
        self.events: list[list] = []
        self.truncated = False
        self.max_ev = int(_f(S.get("max_trace_events"), 60000, 0, LIMITS["trace_events"]))
        self.station_ids = [str(s) for s in station_ids or []]
        self.st_link = {bid: str((self.by[bid].get("params") or {}).get("station") or "") for bid in self.ids}
        self.last_key: dict[str, Any] = {}
        self.cur_busy: dict[tuple, float] = {}

    # ------------------------------------------------------------------ utilitaires
    def ev(self, *row):
        if not self.trace_on or self.truncated:
            return
        if len(self.events) >= self.max_ev:
            self.truncated = True
            return
        self.events.append([round(self.env.now, 3), *row])

    def P(self, bid: str) -> dict:
        return self.by[bid].get("params") or {}

    def _live_pp(self) -> float:
        return sum(t.pp for t in self.live.values())

    def _new(self, root, qty, pp, attrs, lot=0) -> Token:
        if self.next_id >= LIMITS["tokens"]:
            raise FlowError("Trop de jetons : réduisez la durée ou augmentez la taille des paquets.")
        t = Token(self.next_id, root, qty, pp, dict(attrs), self.env.now, lot)
        self.next_id += 1
        self.live[t.id] = t
        return t

    def _kill(self, t: Token):
        self.live.pop(t.id, None)
        self.ev(7, t.id)

    def _st_in(self, bid: str, t: Token):
        s = self.stats[bid]
        self._acc(bid)
        s.entered += 1
        s.wip += 1
        s.max = max(s.max, s.wip)
        t.block = bid
        self.ev(6, t.id, self.bidx[bid], t.lot, 1 if t.attrs.get("_rework") else 0)

    def _st_out(self, bid: str):
        s = self.stats[bid]
        self._acc(bid)
        s.exited += 1
        s.wip -= 1

    def _acc(self, bid: str):
        s = self.stats[bid]
        now = self.env.now
        s.area += s.wip * (now - s.last)
        s.last = now

    def _on_break(self) -> Optional[float]:
        now = self.env.now
        return next((b for a, b in self.breaks if a <= now < b), None)

    def _work(self, duration: float):
        remaining = duration
        while remaining > 1e-9:
            end = self._on_break()
            if end is not None:
                yield self.env.timeout(end - self.env.now)
                continue
            nxt = min((a for a, _ in self.breaks if a > self.env.now), default=math.inf)
            step = min(remaining, nxt - self.env.now)
            yield self.env.timeout(step)
            remaining -= step

    def _key(self, t: Token, how: str):
        if how in ("", None, "product"):
            return ("p", t.root, t.qty)
        if how == "lot":
            return ("l", t.lot, t.qty)
        if how == "size":
            return ("s", t.attrs.get("taille", ""), t.qty)
        return ("a", t.attrs.get(how, ""), t.qty)

    # ------------------------------------------------------------------ circulation des jetons
    def send(self, t: Token, frm: str, port: int):
        outs = self.outs[frm]
        to = next((b for p, b in outs if p == port), None)
        if to is None:            # sortie non reliée (validation l'interdit) : jeton perdu = compté en cours
            return
        k = self.inport[to].get((frm, port), 0)
        yield from self.enter(to, t, k)

    def enter(self, bid: str, t: Token, inport: int = 0):
        typ = self.by[bid]["type"]
        p = self.P(bid)
        self._st_in(bid, t)
        if typ in ("queue", "operation", "inspect"):
            yield self.stores[bid].put(t)
        elif typ == "delay":
            self.env.process(self._delay(bid, t))
        elif typ == "decision":
            self._st_out(bid)
            yield from self.send(t, bid, self._decide(bid, t))
        elif typ == "attribute":
            self._set_attrs(p, t)
            self._st_out(bid)
            yield from self.send(t, bid, 0)
        elif typ == "split":
            self._st_out(bid)
            ports = [pt for pt, _ in self.outs[bid]]
            comps = [str(c) for c in p.get("components") or []]
            k = max(1, len(ports))
            self._kill(t)
            for i, pt in enumerate(ports):
                c = self._new(t.root, t.qty, t.pp / k, t.attrs, t.lot)
                c.t0, c.comp = t.t0, comps[i] if i < len(comps) else f"composant {i + 1}"
                c.attrs["composant"] = c.comp
                c.held = list(t.held) if i == 0 else []
                self.env.process(self.send(c, bid, pt))
        elif typ == "join":
            self._join(bid, t, inport)
        elif typ == "batch":
            self._batch(bid, t)
        elif typ == "unbatch":
            self._st_out(bid)
            self._kill(t)
            for c in t.children or [t]:
                self.live[c.id] = c
                self.env.process(self.send(c, bid, 0))
        elif typ == "acquire":
            self.env.process(self._acquire(bid, t))
        elif typ == "release":
            name, qty = str(p.get("resource") or ""), int(_f(p.get("qty"), 1, 1, 100))
            for _ in range(qty):
                h = next((h for h in t.held if h[0] == name), None)
                if h:
                    t.held.remove(h)
                    self.pools[name].release(h[1])
                    self.pool_busy[name] += self.env.now - h[2]
            self._st_out(bid)
            yield from self.send(t, bid, 0)
        elif typ == "sink":
            self._st_out(bid)
            for h in t.held:
                self.pools[h[0]].release(h[1])
                self.pool_busy[h[0]] += self.env.now - h[2]
            t.held = []
            self.done_pp += t.pp
            self.done_tokens += 1
            self.completions.append((self.env.now, t.pp))
            if not t.attrs.get("_rework") and not t.attrs.get("_initial"):
                self.lead.append(self.env.now - t.t0)
            self.stats[bid].waits.append(self.env.now - t.t0)
            self._kill(t)
            ev, self.capacity_event = self.capacity_event, self.env.event()
            ev.succeed()

    def _decide(self, bid: str, t: Token) -> int:
        p = self.P(bid)
        ports = [pt for pt, _ in self.outs[bid]]
        mode = p.get("mode") or "prob"
        if mode == "attr":
            v = str(t.attrs.get(str(p.get("attr") or ""), ""))
            for i, vals in enumerate(p.get("routes") or []):
                if i < len(ports) and v in [str(x) for x in vals or []]:
                    return ports[i]
            return ports[-1]
        if mode == "cond":
            a = t.attrs.get(str(p.get("attr") or ""), "")
            b = p.get("value")
            op = p.get("op") or "=="
            try:
                x, y = float(a), float(b)
            except (TypeError, ValueError):
                x, y = str(a), str(b)
            ok = {"==": x == y, "!=": x != y, ">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y}.get(op, False)
            return ports[0] if ok else ports[min(1, len(ports) - 1)]
        probs = [_f(x, 0, 0) for x in p.get("probs") or []][: len(ports)]
        probs += [0.0] * (len(ports) - len(probs))
        if sum(probs) <= 0:
            probs = [1.0] * len(ports)
        r = self.rng.random() * sum(probs)
        acc = 0.0
        for i, w in enumerate(probs):
            acc += w
            if r < acc:
                return ports[i]
        return ports[-1]

    def _set_attrs(self, p: dict, t: Token):
        for k, v in (p.get("set") or {}).items():
            t.attrs[str(k)] = v
        if p.get("attr") and p.get("values"):
            vals = [(v[0], _f(v[1], 1, 0)) if isinstance(v, (list, tuple)) and len(v) > 1 else (v, 1.0)
                    for v in p["values"]]
            tot = sum(w for _, w in vals) or 1
            r, acc = self.rng.random() * tot, 0.0
            for v, w in vals:
                acc += w
                if r < acc:
                    t.attrs[str(p["attr"])] = v
                    break

    def _delay(self, bid: str, t: Token):
        yield self.env.timeout(_f(self.P(bid).get("minutes"), 0, 0, 10000))
        self._st_out(bid)
        yield from self.send(t, bid, 0)

    def _acquire(self, bid: str, t: Token):
        p = self.P(bid)
        name, qty = str(p.get("resource") or ""), int(_f(p.get("qty"), 1, 1, 100))
        for _ in range(qty):
            req = self.pools[name].request()
            yield req
            t.held.append((name, req, self.env.now))
        self._st_out(bid)
        yield from self.send(t, bid, 0)

    def _join(self, bid: str, t: Token, inport: int):
        p = self.P(bid)
        n_in = len(self.ins[bid])
        buf = self.join_buf.setdefault(bid, {})
        key = self._key(t, str(p.get("match") or "product"))
        slots = buf.setdefault(key, [deque() for _ in range(n_in)])
        slots[min(inport, n_in - 1)].append(t)
        if all(slots):
            parts = [s.popleft() for s in slots]
            if not any(slots):
                buf.pop(key, None)
            for _ in parts:
                self._st_out(bid)
            first = parts[0]
            out = self._new(first.root, first.qty, sum(x.pp for x in parts), first.attrs, first.lot)
            out.t0 = min(x.t0 for x in parts)
            out.attrs.pop("composant", None)
            out.attrs["_rework"] = any(x.attrs.get("_rework") for x in parts)
            out.attrs["_initial"] = any(x.attrs.get("_initial") for x in parts)
            for x in parts:
                out.held += x.held
                self._kill(x)
            out.block = bid
            self.ev(6, out.id, self.bidx[bid], out.lot, 1 if out.attrs.get("_rework") else 0)
            self.env.process(self.send(out, bid, 0))

    def _batch(self, bid: str, t: Token):
        p = self.P(bid)
        size = int(_f(p.get("size"), 2, 1, 1000))
        key = t.attrs.get(str(p.get("key"))) if p.get("key") else ""
        buf = self.batch_buf.setdefault(bid, {}).setdefault(key, [])
        buf.append(t)
        if len(buf) >= size:
            parts = buf[:size]
            del buf[:size]
            for _ in parts:
                self._st_out(bid)
            first = parts[0]
            b = self._new(first.root, sum(x.qty for x in parts), sum(x.pp for x in parts), first.attrs, first.lot)
            b.t0 = min(x.t0 for x in parts)
            b.children = parts
            for x in parts:
                self.live.pop(x.id, None)
                self.ev(7, x.id)
            b.block = bid
            self.ev(6, b.id, self.bidx[bid], b.lot, 0)
            self.env.process(self.send(b, bid, 0))

    # ------------------------------------------------------------------ processus de blocs à capacité
    def _queue_fwd(self, bid: str):
        while True:
            t = yield self.stores[bid].get()
            self._st_out(bid)
            yield from self.send(t, bid, 0)

    def _server(self, bid: str, k: int):
        p = self.P(bid)
        typ = self.by[bid]["type"]
        st = self.stats[bid]
        per_piece = _f(p.get("minutes"), 0, 0, 1000) / max(0.05, self.eff * _f(p.get("efficiency"), 1, 0.05, 3))
        dist = D.normalize(p["dist"]) if p.get("dist") else self.dist
        setup = _f(p.get("setup_min"), 0, 0, 1000)
        res = str(p.get("resource") or "")
        link = self.st_link.get(bid)
        sidx = self.station_ids.index(link) if link in self.station_ids else -1
        while True:
            if sidx >= 0:
                self.ev(0, sidx, 1)
            t = yield self.stores[bid].get()
            req = None
            if res and res in self.pools:
                req = self.pools[res].request()
                yield req
                t0r = self.env.now
            if sidx >= 0:
                self.ev(0, sidx, 0)
            t_start = self.env.now
            self.cur_busy[(bid, k)] = t_start
            key = (t.lot, t.attrs.get("taille"))
            if setup > 0 and self.last_key.get(bid) not in (None, key):
                yield from self._work(setup)
            self.last_key[bid] = key
            yield from self._work(D.sample_total(self.rng, dist, per_piece, t.qty) if per_piece > 0 else 0.0)
            st.busy += self.env.now - t_start
            self.cur_busy.pop((bid, k), None)
            if req is not None:
                self.pools[res].release(req)
                self.pool_busy[res] += self.env.now - t0r
            port = 0
            if typ == "inspect":
                pdef = _f(p.get("defect_pct"), 0, 0, 100) / 100.0
                if pdef > 0 and self.rng.random() < 1 - (1 - pdef) ** max(1, t.qty):
                    st.defects += 1
                    t.attrs["_rework"] = True
                    port = 1
            if sidx >= 0:
                self.ev(0, sidx, 2)
            self._st_out(bid)
            yield from self.send(t, bid, port)

    def _source(self, bid: str):
        p = self.P(bid)
        size = int(_f(p.get("bundle_size"), 10, 1, 500))
        interval = _f(p.get("interval_min"), 0, 0, 1000)
        cap = int(_f(p.get("wip_cap"), 30, 0, 100000))
        if cap == 0 and interval <= 0:      # flux tiré sans plafond : 1 paquet par opération (évite l'infini)
            cap = max(2, sum(1 for b in self.blocks if b.get("type") in ("operation", "inspect")))
        lots = [lot for lot in p.get("lots") or [] if isinstance(lot, dict)] or [{"style": "Modèle", "qty": 0}]
        for li, lot in enumerate(lots):
            left = int(_f(lot.get("qty"), 0, 0)) or math.inf
            attrs = {"modele": str(lot.get("style") or "Modèle"), "taille": str(lot.get("size") or ""),
                     "couleur": str(lot.get("color") or "")}
            while left > 0:
                n = int(min(size, left))
                while cap and len({x.root for x in self.live.values()}) >= cap:
                    yield self.capacity_event
                t = self._new(None, n, float(n), attrs, li)
                t.root = t.id
                self.launched_pp += n
                yield from self.send(t, bid, 0)
                left -= n
                if interval > 0:
                    yield self.env.timeout(interval)

    def _snapshots(self):
        while True:
            self.wip_series.append([round(self.env.now, 2), round(self._live_pp(), 1)])
            yield self.env.timeout(5.0)

    # ------------------------------------------------------------------ exécution
    def run(self) -> dict:
        for bid in self.ids:
            typ = self.by[bid]["type"]
            p = self.P(bid)
            if typ == "queue":
                cap = int(_f(p.get("capacity"), 0, 0, 100000))
                self.stores[bid] = simpy.Store(self.env, capacity=cap or math.inf)
                self.env.process(self._queue_fwd(bid))
            elif typ in ("operation", "inspect"):
                cap = int(_f(p.get("queue_capacity"), 0, 0, 100000))
                self.stores[bid] = simpy.Store(self.env, capacity=cap or math.inf)
                n = int(_f(p.get("servers"), 1, 1, 50))
                self.stats[bid].servers = n
                for k in range(n):
                    self.env.process(self._server(bid, k))
        for bid in self.ids:
            if self.by[bid]["type"] == "source":
                self.env.process(self._source(bid))
        self.env.process(self._snapshots())
        self.env.run(until=self.T)
        return self._result()

    def _result(self) -> dict:
        T = self.T
        for bid in self.ids:
            self._acc(bid)
        for (bid, _k), t0 in self.cur_busy.items():     # opérations en cours à la fin du poste
            self.stats[bid].busy += T - t0
        blocks = []
        for bid in self.ids:
            b, s = self.by[bid], self.stats[bid]
            row = {"id": bid, "type": b["type"], "label": b.get("label") or BLOCK_LABELS[b["type"]],
                   "entered": s.entered, "exited": s.exited, "wip_avg": round(s.area / T, 2), "wip_max": s.max,
                   "wip_now": s.wip}
            if b["type"] in ("operation", "inspect"):
                row["servers"] = s.servers
                row["utilization_pct"] = round(100.0 * s.busy / (T * max(1, s.servers)), 1)
                row["queue_now"] = len(self.stores[bid].items)
            if b["type"] == "inspect":
                row["defects"] = s.defects
            if b["type"] == "sink":
                row["lead_avg"] = round(statistics.mean(s.waits), 1) if s.waits else None
            if b["type"] == "join":
                row["waiting"] = sum(len(q) for slots in (self.join_buf.get(bid) or {}).values() for q in slots)
            blocks.append(row)
        ops = [r for r in blocks if "utilization_pct" in r]
        bott = max(ops, key=lambda r: r["utilization_pct"])["id"] if ops else None
        hours = max(1, math.ceil(T / 60))
        hourly = [0.0] * hours
        cum, run = [[0.0, 0.0]], 0.0
        for t, n in self.completions:
            hourly[min(hours - 1, int(t // 60))] += n
            run += n
            cum.append([round(t, 2), round(run, 2)])
        in_sys = self._live_pp()
        lead = sorted(self.lead)
        wips = [w[1] for w in self.wip_series]
        pools = [{"name": k, "capacity": r.capacity, "utilization_pct": round(100.0 * self.pool_busy[k] / (T * r.capacity), 1)}
                 for k, r in self.pools.items()]
        kpis = {"pieces": round(self.done_pp, 1), "per_hour": round(self.done_pp / T * 60, 1),
                "lead_time_avg": (round(statistics.mean(lead), 1) if lead else
                                  (round(statistics.mean(wips) / (self.done_pp / T), 1) if wips and self.done_pp > 0 and statistics.mean(wips) > 0 else None)),
                "lead_time_basis": "measured" if lead else ("little" if self.done_pp > 0 and wips else None),
                "lead_time_p90": round(lead[int(0.9 * (len(lead) - 1))], 1) if lead else None,
                "wip_avg": round(statistics.mean(wips), 1) if wips else 0, "wip_max": max(wips) if wips else 0,
                "bottleneck": bott, "tokens": self.next_id, "done_tokens": self.done_tokens,
                "launched": round(self.launched_pp, 1)}
        res = {"success": True, "seed": self.seed, "shift_minutes": T, "kpis": kpis, "blocks": blocks, "resources": pools,
               "throughput": {"hourly": [round(h, 1) for h in hourly], "cumulative": cum[:: max(1, len(cum) // 1500)] + [cum[-1]]},
               "wip_series": self.wip_series,
               "conservation": {"launched": round(self.launched_pp, 3), "done": round(self.done_pp, 3),
                                "in_system": round(in_sys, 3),
                                "ok": abs(self.launched_pp - self.done_pp - in_sys) < 1e-6}}
        if self.trace_on:
            res["trace"] = {"events": self.events, "truncated": self.truncated, "blocks": self.ids,
                            "stations": self.station_ids, "until": round(self.env.now if not self.truncated else self.events[-1][0], 2)}
        return res


def simulate_flow(graph: dict, seed: Optional[int] = None, trace: bool = True, station_ids: Optional[list] = None) -> dict:
    return FlowSim(graph, seed, trace, station_ids).run()


def run_flow_experiment(graph: dict, replications: int = 1, station_ids: Optional[list] = None, progress=None) -> dict:
    from engine.des.experiment import ci
    n = max(1, min(LIMITS["replications"], int(replications)))
    base = int(_f((graph.get("settings") or {}).get("seed"), 42))
    first = simulate_flow(graph, base, True, station_ids)
    if progress:
        progress(1, n)
    kp = [first["kpis"]]
    for r in range(1, n):
        kp.append(simulate_flow(graph, base + r, False, station_ids)["kpis"])
        if progress:
            progress(r + 1, n)
    keys = ["pieces", "per_hour", "lead_time_avg", "wip_avg", "wip_max"]
    first["replications"] = {"n": n, "kpis": {k: ci([x.get(k) for x in kp]) for k in keys}}
    return first


# ====================================================================== génération depuis la gamme
def _transitive_reduction(nodes: list, edges: set) -> set:
    succ = {n: {b for a, b in edges if a == n} for n in nodes}

    def reach(a, skip):
        seen, st = set(), [x for x in succ[a] if (a, x) != skip]
        while st:
            v = st.pop()
            if v in seen:
                continue
            seen.add(v)
            st.extend(succ[v])
        return seen

    return {(a, b) for a, b in edges if b not in reach(a, (a, b))}


def from_plan(plan: dict, problem: Optional[dict] = None, name: str = "") -> dict:
    """Graphe généré depuis un calcul (stations + opérations) et la gamme (précédences) : branches parallèles
    (séparation en sous-composants) puis assemblages là où plusieurs branches se rejoignent."""
    stations = plan.get("stations") or []
    if not stations:
        raise FlowError("Le calcul ne contient aucune station.")
    sid = [str(s["station"]) for s in stations]
    op_st: dict[str, str] = {}
    op_name: dict[str, str] = {}
    for s in stations:
        for o in s.get("operations") or []:
            oid = str(o.get("id") or o.get("name"))
            op_st.setdefault(oid, str(s["station"]))
            op_name[oid] = str(o.get("name") or oid)
    preds: dict[str, list[str]] = {}
    for o in (problem or {}).get("operations") or []:
        preds[str(o.get("id"))] = [str(x) for x in o.get("predecessors") or []]
    edges = set()
    for oid, st in op_st.items():
        for pr in preds.get(oid, []):
            a = op_st.get(pr)
            if a and a != st:
                edges.add((a, st))
    order = {s: i for i, s in enumerate(sid)}
    # pas de précédences exploitables (ou cycle entre stations) : ligne en série dans l'ordre des stations
    if not edges or any(order[a] >= order[b] for a, b in edges):
        edges = {(a, b) for a, b in zip(sid, sid[1:])}
    edges = _transitive_reduction(sid, edges)
    indeg = {s: sum(1 for a, b in edges if b == s) for s in sid}
    outdeg = {s: sum(1 for a, b in edges if a == s) for s in sid}
    blocks, links = [], []
    workers = plan.get("workers") or {}
    n_ops = sum(int(s.get("operators") or len(s.get("worker_ids") or []) or 1) for s in stations)
    col = {}

    def depth(s, memo={}):  # noqa: B006
        if s in memo:
            return memo[s]
        ps = [a for a, b in edges if b == s]
        memo[s] = 0 if not ps else 1 + max(depth(p) for p in ps)
        return memo[s]

    for s in sid:
        col[s] = depth(s)
    rows: dict[int, int] = {}
    pos = {}
    for s in sid:
        c = col[s]
        pos[s] = (c, rows.get(c, 0))
        rows[c] = rows.get(c, 0) + 1
    X = lambda c: 260 + c * 300  # noqa: E731
    Y = lambda r: 60 + r * 150  # noqa: E731
    blocks.append({"id": "src", "type": "source", "label": "Coupe (paquets)", "x": 0, "y": 60,
                   "params": {"lots": [{"style": plan.get("problem_name") or "Modèle", "size": "", "color": "", "qty": 0}],
                              "bundle_size": 10, "interval_min": 0, "wip_cap": max(4, round(0.6 * len(sid)))}})

    def comp_name(s):
        st = next(x for x in stations if str(x["station"]) == s)
        ops = [str(o.get("name") or "") for o in st.get("operations") or []]
        return (ops[0] if ops else f"Poste {s}")[:30]

    roots = [s for s in sid if indeg[s] == 0]
    entry: dict[str, str] = {}
    for s in sid:
        st = next(x for x in stations if str(x["station"]) == s)
        c, r = pos[s]
        if indeg[s] > 1:
            jid = f"join_{s}"
            blocks.append({"id": jid, "type": "join", "label": f"Assemblage avant poste {s}", "x": X(c) - 150, "y": Y(r),
                           "params": {"match": "product"}})
            links.append({"from": jid, "port": 0, "to": f"op_{s}"})
            entry[s] = jid
        else:
            entry[s] = f"op_{s}"
        nw = int(st.get("operators") or len(st.get("worker_ids") or []) or 1)
        blocks.append({"id": f"op_{s}", "type": "operation", "label": f"Poste {s} · {comp_name(s)}", "x": X(c), "y": Y(r),
                       "params": {"minutes": round(float(st.get("minutes") or 0), 4), "servers": max(1, nw),
                                  "queue_capacity": 0, "station": s,
                                  "operations": [str(o.get("name") or "") for o in st.get("operations") or []],
                                  "operators": [str((workers.get(w) or {}).get("name") or w) for w in st.get("worker_ids") or []]}})
    # sorties des postes : séparation si plusieurs successeurs
    succ = {s: sorted((b for a, b in edges if a == s), key=lambda x: order[x]) for s in sid}
    in_count: dict[str, int] = {}

    def link_to(frm, port, s):
        links.append({"from": frm, "port": port, "to": entry[s]})
        in_count[s] = in_count.get(s, 0) + 1

    if len(roots) > 1:
        blocks.append({"id": "split_src", "type": "split", "label": "Séparation des composants", "x": 130, "y": 60,
                       "params": {"components": [comp_name(r) for r in roots]}})
        links.append({"from": "src", "port": 0, "to": "split_src"})
        for i, r in enumerate(roots):
            link_to("split_src", i, r)
    else:
        link_to("src", 0, roots[0])
    leaves = [s for s in sid if outdeg[s] == 0]
    for s in sid:
        c, r = pos[s]
        if len(succ[s]) > 1:
            spid = f"split_{s}"
            blocks.append({"id": spid, "type": "split", "label": f"Séparation après poste {s}", "x": X(c) + 150, "y": Y(r),
                           "params": {"components": [comp_name(x) for x in succ[s]]}})
            links.append({"from": f"op_{s}", "port": 0, "to": spid})
            for i, nx in enumerate(succ[s]):
                link_to(spid, i, nx)
        elif succ[s]:
            link_to(f"op_{s}", 0, succ[s][0])
    maxc = max(col.values()) if col else 0
    if len(leaves) > 1:
        blocks.append({"id": "join_end", "type": "join", "label": "Assemblage final", "x": X(maxc + 1) - 150, "y": 60,
                       "params": {"match": "product"}})
        for s in leaves:
            links.append({"from": f"op_{s}", "port": 0, "to": "join_end"})
        links.append({"from": "join_end", "port": 0, "to": "sink"})
    else:
        links.append({"from": f"op_{leaves[0]}", "port": 0, "to": "sink"})
    blocks.append({"id": "sink", "type": "sink", "label": "Produits finis", "x": X(maxc + 1), "y": 60, "params": {}})
    return {"name": name or f"Flux · {plan.get('problem_name') or 'gamme'}", "version": 1,
            "shift": {"minutes": 480, "breaks": [{"start_min": 120, "minutes": 15, "label": "Pause"},
                                                  {"start_min": 240, "minutes": 30, "label": "Déjeuner"}]},
            "settings": {"seed": 42, "dist": {"kind": "normal", "cv": 0.10}, "efficiency": 1.0},
            "resources": [{"name": "Opératrices", "kind": "operator", "capacity": n_ops}],
            "blocks": blocks, "edges": links,
            "generated": {"stations": len(sid), "branches": len(roots), "joins": sum(1 for b in blocks if b["type"] == "join")}}


def normalize_graph(g: dict) -> dict:
    """Copie bornée (types, tailles) pour stockage / exécution."""
    out = copy.deepcopy(g or {})
    out["blocks"] = [b for b in out.get("blocks") or [] if isinstance(b, dict)][: LIMITS["blocks"]]
    out["edges"] = [e for e in out.get("edges") or [] if isinstance(e, dict)][: LIMITS["edges"]]
    out["resources"] = [r for r in out.get("resources") or [] if isinstance(r, dict)][:30]
    for b in out["blocks"]:
        b["id"] = str(b.get("id"))[:40]
        b["label"] = str(b.get("label") or BLOCK_LABELS.get(b.get("type"), ""))[:80]
        b["params"] = b.get("params") if isinstance(b.get("params"), dict) else {}
    out["name"] = str(out.get("name") or "Flux")[:120]
    return out
