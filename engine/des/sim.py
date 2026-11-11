"""Simulateur à événements discrets (SimPy) d'une ligne de confection, façon FlexSim.

Objets : Source (lancement des paquets selon l'ordre de coupe), File (chariot d'encours devant chaque
poste, capacité en paquets, retouches prioritaires), Poste (1..n serveurs, temps = SAM / efficience
selon une loi de variabilité, mise en route au changement de modèle/taille, pannes MTBF/MTTR,
défauts → retouche), Opérateur (ressource mobile : marche jusqu'au poste qui l'appelle, porte les
paquets quand le poste suivant est loin), Transporteur (agent de liaison : ramasse jusqu'à `capacity`
paquets et les dépose), Sortie. Pauses de l'équipe : tout s'arrête.

Déterministe pour une graine donnée. Sortie : statistiques + trace horodatée pour l'animation.

Trace (`trace.events`, triés par temps) :
  [t, 0, station, état]                         état d'un poste (indices de model.STATION_STATES)
  [t, 1, paquet, lieu, réf]                     lieu (model.LOC_KINDS) : 0 file(poste) 1 poste 2 sortie
                                                poste 3 porté par opérateur 4 transporteur 5 terminé 6 source
  [t, 2, acteur, t_fin, chemin]                 déplacement le long de trace.paths[chemin]
  [t, 3, acteur, état]                          état d'un acteur (opérateurs puis transporteurs)
  [t, 4, cintre, t_fin, s0, s1]                 cintre qui roule sur la boucle du convoyeur de l'abscisse s0 à
                                                s1 (m, s1 peut dépasser la longueur : modulo)
  [t, 5, cintre, lieu, réf]                     cintre arrêté : 0 stock de cintres vides (chargement) 1 dérivation
                                                du poste réf 2 au poste réf 3 attente d'insertion après le poste réf
                                                4 chargement 5 déchargement
Avec un convoyeur, un paquet porté par un cintre a le lieu 7 (réf = cintre).
"""
from __future__ import annotations

import math
import random
import statistics
from collections import deque
from typing import Optional

import simpy

from engine.des import distributions as D
from engine.des.conveyor_sim import ConveyorMixin
from engine.des.model import normalize_model
from engine.des.paths import PathTable

# états des postes
S_WORK, S_STARVED, S_BLOCKED, S_DOWN, S_SETUP, S_WAIT_OP, S_BREAK, S_TRANSFER = range(8)
# priorité d'affichage d'un poste à plusieurs serveurs
_STATION_PRIORITY = [S_DOWN, S_BREAK, S_WORK, S_SETUP, S_TRANSFER, S_WAIT_OP, S_BLOCKED, S_STARVED]
# états des opérateurs
O_IDLE, O_WALK, O_WORK, O_SETUP, O_CARRY, O_BREAK, O_WAIT = range(7)
# états des transporteurs
T_IDLE, T_EMPTY, T_LOADED, T_LOADING, T_WAIT, T_BREAK = range(6)
# lieux des paquets
L_QUEUE, L_PROCESS, L_OUT, L_OPERATOR, L_TRANSPORTER, L_DONE, L_SOURCE, L_CARRIER = range(8)
# cintres arrêtés
C_EMPTY, C_SPUR, C_STATION, C_MERGE, C_LOAD, C_UNLOAD = range(6)


class Tracker:
    """Temps passé dans chaque état ; une pause (ou panne) force l'état affiché."""

    def __init__(self, sim: "Simulator", n_states: int, initial: int, on_change=None):
        self.sim, self.acc = sim, [0.0] * n_states
        self.base, self.override = initial, None
        self.state, self.since = initial, 0.0
        self.on_change = on_change
        self.log: list[list] = []       # [t0, t1, état] pour le Gantt

    def _apply(self):
        new = self.override if self.override is not None else self.base
        if new == self.state:
            return
        now = self.sim.env.now
        self.acc[self.state] += now - self.since
        if now > self.since and self.log is not None and len(self.log) < 4000:
            self.log.append([round(self.since, 2), round(now, 2), self.state])
        self.state, self.since = new, now
        if self.on_change:
            self.on_change(new)

    def set(self, state: int):
        self.base = state
        self._apply()

    def force(self, state: Optional[int]):
        self.override = state
        self._apply()

    def close(self, T: float):
        self.acc[self.state] += max(0.0, T - self.since)
        if T > self.since and len(self.log) < 4000:
            self.log.append([round(self.since, 2), round(T, 2), self.state])
        self.since = T


class BQueue:
    """File de paquets à capacité finie (FIFO, retouches en tête) avec statistiques pondérées par le temps."""

    def __init__(self, env: simpy.Environment, cap: int):
        self.env, self.cap = env, cap
        self.items: deque = deque()
        self.getters: deque = deque()
        self.putters: deque = deque()
        self.pieces = 0
        self.area_b = self.area_p = 0.0
        self.last = 0.0
        self.max_b = self.max_p = 0

    def _acc(self):
        now = self.env.now
        self.area_b += len(self.items) * (now - self.last)
        self.area_p += self.pieces * (now - self.last)
        self.last = now

    def _add(self, b, front=False):
        self._acc()
        (self.items.appendleft if front else self.items.append)(b)
        self.pieces += b.qty
        self.max_b, self.max_p = max(self.max_b, len(self.items)), max(self.max_p, self.pieces)
        while self.getters and self.items:
            self._pop_to(self.getters.popleft())

    def _pop_to(self, ev):
        self._acc()
        b = self.items.popleft()
        self.pieces -= b.qty
        ev.succeed(b)
        while self.putters and len(self.items) < self.cap:
            pev, pb, front = self.putters.popleft()
            self._add(pb, front)
            pev.succeed()

    def put(self, b, force: bool = False):
        ev = self.env.event()
        if force or len(self.items) < self.cap:
            self._add(b, front=force)
            ev.succeed()
        else:
            self.putters.append((ev, b, False))
        return ev

    def get(self):
        ev = self.env.event()
        if self.items:
            self._pop_to(ev)
        else:
            self.getters.append(ev)
        return ev

    def free(self) -> int:
        return self.cap - len(self.items) - len(self.putters)


class Bundle:
    __slots__ = ("idx", "lot", "qty", "fresh", "rework", "t0", "loc", "carrier", "step", "rail_t")

    def __init__(self, idx, lot, qty, fresh, rework, t0):
        self.idx, self.lot, self.qty, self.fresh, self.rework, self.t0 = idx, lot, qty, fresh, rework, t0
        self.loc = None
        self.carrier: Optional[int] = None     # cintre du convoyeur
        self.step = 0                           # rang de la gamme à faire ensuite (convoyeur)
        self.rail_t = 0.0                       # minutes passées sur le rail


class Simulator(ConveyorMixin):
    def __init__(self, model: dict, seed: Optional[int] = None, trace: Optional[bool] = None):
        self.m = normalize_model(model)
        S = self.m["settings"]
        self.seed = S["seed"] if seed is None else int(seed)
        self.trace_on = S["trace"] if trace is None else bool(trace)
        self.rng = random.Random(self.seed)
        self.env = simpy.Environment()
        self.T = self.m["shift"]["minutes"]
        self.speed = S["walk_speed_m_per_min"]
        self.eff = S["efficiency"]
        self.route = self.m["route"]
        self.st = {s["id"]: s for s in self.m["stations"]}
        self.sidx = {sid: i for i, sid in enumerate(self.st)}
        pts = {k: (float(v[0]), float(v[1])) for k, v in self.m["points"].items()}
        self.paths = PathTable.from_json(pts, self.m.get("paths"))
        self.breaks = [(b["start_min"], b["start_min"] + b["minutes"]) for b in self.m["shift"]["breaks"]]
        # trace
        self.events: list[list] = []
        self.max_ev = S["max_trace_events"]
        self.truncated, self.trace_until = False, self.T
        self.path_ids: dict[tuple, int] = {}
        self.path_list: list[list] = []
        self.bundle_table: list[list] = []
        # files, serveurs, opérateurs, transporteurs
        self.q = {sid: BQueue(self.env, s["queue_capacity"]) for sid, s in self.st.items()}
        self.out_slots = {sid: simpy.Container(self.env, capacity=s["out_capacity"], init=s["out_capacity"])
                          for sid, s in self.st.items()}
        self.st_state = {sid: S_STARVED for sid in self.st}
        self.servers: dict[str, list[Tracker]] = {}
        self.down = {sid: False for sid in self.st}
        self.down_iv: dict[str, list[tuple[float, float]]] = {sid: [] for sid in self.st}
        self.last_lot = {sid: None for sid in self.st}
        self.done_st = {sid: 0 for sid in self.st}
        self.defects = {sid: 0 for sid in self.st}
        self.ops = {o["id"]: o for o in self.m["operators"]}
        self.actor_ids = list(self.ops) + [t["id"] for t in self.m["transporters"]]
        self.aidx = {a: i for i, a in enumerate(self.actor_ids)}
        self.op_res = {oid: simpy.Resource(self.env, capacity=1) for oid in self.ops}
        self.op_loc: dict[str, str] = {}
        self.op_walk = {oid: 0.0 for oid in self.ops}
        self.op_carry = {oid: 0.0 for oid in self.ops}
        self.op_tr: dict[str, Tracker] = {}
        self.trs = {t["id"]: t for t in self.m["transporters"]}
        self.tr_loc = {tid: "src" for tid in self.trs}
        self.tr_dist = {tid: 0.0 for tid in self.trs}
        self.tr_loads = {tid: 0 for tid in self.trs}
        self.tr_tr: dict[str, Tracker] = {}
        self.pickups = simpy.Store(self.env)
        # flux
        self.live: dict[int, Bundle] = {}
        self.launched = self.initial = self.done = 0
        self.lead: list[float] = []
        self.completions: list[tuple[float, int]] = []
        self.wip_series: list[list] = []
        self.transport_m = 0.0
        self.capacity_event = self.env.event()
        self.notes: list[str] = []
        self._init_conveyor()

    # ------------------------------------------------------------------ trace
    def ev(self, *row):
        if not self.trace_on or self.truncated:
            return
        if len(self.events) >= self.max_ev:
            self.truncated, self.trace_until = True, self.env.now
            return
        self.events.append([round(self.env.now, 3), *row])

    def _path_id(self, a: str, b: str) -> tuple[float, int]:
        m, pts = self.paths.get(a, b)
        key = (a, b)
        if key not in self.path_ids:
            self.path_ids[key] = len(self.path_list)
            self.path_list.append(pts)
        return m, self.path_ids[key]

    def _loc(self, b: Bundle, kind: int, ref: int = 0):
        b.loc = (kind, ref)
        self.ev(1, b.idx, kind, ref)

    def _new_bundle(self, lot: int, qty: int, fresh: bool, rework: bool = False) -> Bundle:
        b = Bundle(len(self.bundle_table), lot, qty, fresh, rework, self.env.now)
        self.bundle_table.append([lot, qty, 1 if rework else 0])
        self.live[b.idx] = b
        return b

    # ------------------------------------------------------------------ états
    def _station_changed(self, sid: str):
        servers = self.servers.get(sid) or []
        states = {t.state for t in servers}
        new = next((s for s in _STATION_PRIORITY if s in states), S_STARVED)
        if new != self.st_state[sid]:
            self.st_state[sid] = new
            self.ev(0, self.sidx[sid], new)

    def _override_station(self, sid: str):
        o = S_BREAK if self._on_break() else (S_DOWN if self.down[sid] else None)
        for t in self.servers[sid]:
            t.force(o)

    def _on_break(self, t: Optional[float] = None) -> bool:
        t = self.env.now if t is None else t
        return any(a <= t < b for a, b in self.breaks)

    def _blocked_intervals(self, sid: str) -> list[tuple[float, float]]:
        return sorted(self.down_iv[sid] + self.breaks)

    # ------------------------------------------------------------------ travail interrompu par pannes / pauses
    def _work(self, sid: str, duration: float, busy_cb=None):
        remaining = duration
        ivs = self._blocked_intervals(sid)
        while remaining > 1e-9:
            now = self.env.now
            cur = next(((a, b) for a, b in ivs if a <= now < b), None)
            if cur:
                yield self.env.timeout(cur[1] - now)
                continue
            nxt = min((a for a, b in ivs if a > now), default=math.inf)
            step = min(remaining, nxt - now)
            yield self.env.timeout(step)
            remaining -= step
            if busy_cb:
                busy_cb(step)

    def _wait_up(self, sid: str):
        ivs = self._blocked_intervals(sid)
        while True:
            now = self.env.now
            cur = next(((a, b) for a, b in ivs if a <= now < b), None)
            if not cur:
                return
            yield self.env.timeout(cur[1] - now)

    # ------------------------------------------------------------------ déplacements
    def _walk_op(self, oid: str, to: str, carrying: bool = False):
        frm = self.op_loc[oid]
        if frm == to:
            return
        m, pid = self._path_id(frm, to)
        dt = m / self.speed
        tr = self.op_tr[oid]
        tr.set(O_CARRY if carrying else O_WALK)
        self.ev(2, self.aidx[oid], round(self.env.now + dt, 3), pid)
        self.ev(3, self.aidx[oid], O_CARRY if carrying else O_WALK)
        yield self.env.timeout(dt)
        self.op_walk[oid] += m
        if carrying:
            self.op_carry[oid] += m
        self.op_loc[oid] = to

    def _op_state(self, oid: str, s: int):
        self.op_tr[oid].set(s)
        self.ev(3, self.aidx[oid], s)

    def _walk_tr(self, tid: str, to: str, loaded: bool):
        frm = self.tr_loc[tid]
        if frm == to:
            return
        m, pid = self._path_id(frm, to)
        dt = m / self.trs[tid]["speed_m_per_min"]
        s = T_LOADED if loaded else T_EMPTY
        self.tr_tr[tid].set(s)
        self.ev(2, self.aidx[tid], round(self.env.now + dt, 3), pid)
        self.ev(3, self.aidx[tid], s)
        yield self.env.timeout(dt)
        self.tr_dist[tid] += m
        if loaded:
            self.transport_m += m
        self.tr_loc[tid] = to

    def _tr_state(self, tid: str, s: int):
        self.tr_tr[tid].set(s)
        self.ev(3, self.aidx[tid], s)

    # ------------------------------------------------------------------ processus
    def _server(self, sid: str, k: int):
        st = self.st[sid]
        tr = self.servers[sid][k]
        pos = self.route.index(sid) if sid in self.route else -1
        while True:
            tr.set(S_STARVED)
            b = yield self.q[sid].get()
            if not st["operators"]:
                tr.set(S_WAIT_OP)
                yield self.env.event()       # jamais déclenché : poste sans opérateur
            tr.set(S_WAIT_OP)
            oid, req = yield from self._acquire(st)
            yield from self._walk_op(oid, sid)
            yield from self._wait_up(sid)
            o = self.ops[oid]
            # mise en route au changement de lot (modèle / taille)
            lot = self.m["source"]["lots"][b.lot]
            key = (lot["style"], lot["size"])
            if st["setup_min"] > 0 and self.last_lot[sid] not in (None, key):
                tr.set(S_SETUP)
                self._op_state(oid, O_SETUP)
                yield from self._work(sid, st["setup_min"])
            self.last_lot[sid] = key
            tr.set(S_WORK)
            self._op_state(oid, O_WORK)
            self._loc(b, L_PROCESS, self.sidx[sid])
            if b.carrier is not None:
                self._cv_park(b.carrier, 2, self.sidx[sid])
            per_piece = st["minutes"] / max(1e-6, self.eff * o["efficiency"])
            dur = st["handling_min"] + D.sample_total(self.rng, st["dist"], per_piece, b.qty)
            yield from self._work(sid, dur)
            self.done_st[sid] += b.qty
            # contrôle : pièces défectueuses renvoyées en retouche
            if st["defect_pct"] > 0 and st["rework_to"]:
                p = st["defect_pct"] / 100.0
                n_def = sum(1 for _ in range(b.qty) if self.rng.random() < p)
                if n_def:
                    self.defects[sid] += n_def
                    if n_def >= b.qty and self.cv and b.carrier is not None:
                        # cintre entier défectueux : il repart par le convoyeur vers le poste de retouche
                        b.rework = True
                        self.bundle_table[b.idx][2] = 1
                        b.step = self.route.index(st["rework_to"]) - 1 if st["rework_to"] in self.route else b.step
                        n_def = 0
                if n_def:
                    if n_def >= b.qty:
                        rb = b
                        rb.rework = True
                        self.bundle_table[rb.idx][2] = 1
                        b = None
                    else:
                        b.qty -= n_def
                        self.bundle_table[b.idx][1] = b.qty
                        rb = self._new_bundle(b.lot, n_def, False, True)
                    self.q[st["rework_to"]].put(rb, force=True)
                    self._loc(rb, L_QUEUE, self.sidx[st["rework_to"]])
            released = False
            if b is not None:
                released = yield from self._output(sid, tr, b, oid, pos, req)
            if not released:
                self._op_state(oid, O_IDLE)
                self.op_res[oid].release(req)

    def _acquire(self, st: dict):
        ops = st["operators"]
        if len(ops) == 1:
            req = self.op_res[ops[0]].request()
            yield req
            return ops[0], req
        # opérateur libre le plus proche, sinon le premier qui se libère
        free = [o for o in ops if self.op_res[o].count == 0 and not self.op_res[o].queue]
        if free:
            oid = min(free, key=lambda o: (self.paths.get(self.op_loc[o], st["id"])[0], o))
            req = self.op_res[oid].request()
            yield req
            return oid, req
        reqs = [(o, self.op_res[o].request()) for o in ops]
        yield self.env.any_of([r for _, r in reqs])
        chosen = None
        for o, r in reqs:
            if r.triggered and chosen is None:
                chosen = (o, r)
            elif r.triggered:
                self.op_res[o].release(r)
            else:
                r.cancel()
        return chosen

    def _release(self, oid: str, req):
        self._op_state(oid, O_IDLE)
        self.op_res[oid].release(req)

    def _output(self, sid: str, tr: Tracker, b: Bundle, oid: str, pos: int, req):
        """Sortie du paquet ; renvoie True si l'opérateur a déjà été libéré (poste bloqué sans lui)."""
        if self.cv and b.carrier is not None:
            return (yield from self._cv_output(sid, tr, b, oid, req))
        S = self.m["settings"]
        nxt = self.route[pos + 1] if 0 <= pos < len(self.route) - 1 else None
        if nxt is None:
            self._complete(b)
            return False
        meters = self.paths.get(sid, nxt)[0]
        mode = S["transfer"]
        if mode == "auto":
            mode = "handoff" if meters <= S["carry_threshold_m"] else ("transporter" if self.trs else "operator")
        if mode == "transporter" and not self.trs:
            mode = "operator"
        if mode == "transporter":
            self._release(oid, req)
            tr.set(S_BLOCKED)
            yield self.out_slots[sid].get(1)
            self._loc(b, L_OUT, self.sidx[sid])
            yield self.pickups.put((self.env.now, sid, nxt, b))
            return True
        if mode == "operator":
            tr.set(S_TRANSFER)
            self._loc(b, L_OPERATOR, self.aidx[oid])
            yield from self._walk_op(oid, nxt, carrying=True)
            self.transport_m += meters
            self._op_state(oid, O_WAIT)
            tr.set(S_BLOCKED)
            yield self.q[nxt].put(b)
            self._loc(b, L_QUEUE, self.sidx[nxt])
            return False
        self._release(oid, req)
        tr.set(S_BLOCKED)
        yield self.q[nxt].put(b)
        self.transport_m += meters
        self._loc(b, L_QUEUE, self.sidx[nxt])
        return True

    def _transporter(self, tid: str):
        t = self.trs[tid]
        while True:
            self._tr_state(tid, T_IDLE)
            first = yield self.pickups.get()
            loads = [first]
            for it in list(self.pickups.items):        # même poste : on prend jusqu'à la capacité
                if len(loads) >= t["capacity"]:
                    break
                if it[1] == first[1]:
                    self.pickups.items.remove(it)
                    loads.append(it)
            sid = first[1]
            yield from self._walk_tr(tid, sid, loaded=False)
            self._tr_state(tid, T_LOADING)
            yield self.env.timeout(t["load_min"])
            for _, s, _, b in loads:
                self.out_slots[s].put(1)
                self._loc(b, L_TRANSPORTER, self.aidx[tid])
            self.tr_loads[tid] += len(loads)
            loads.sort(key=lambda it: self.route.index(it[2]))
            for _, _, dest, b in loads:
                yield from self._walk_tr(tid, dest, loaded=True)
                self._tr_state(tid, T_WAIT)
                yield self.q[dest].put(b)
                self._loc(b, L_QUEUE, self.sidx[dest])

    def _complete(self, b: Bundle):
        self._loc(b, L_DONE, 0)
        self.done += b.qty
        self.completions.append((self.env.now, b.qty))
        if b.fresh and not b.rework:
            self.lead.append(self.env.now - b.t0)
        self.live.pop(b.idx, None)
        ev, self.capacity_event = self.capacity_event, self.env.event()
        ev.succeed()

    def _source(self):
        src = self.m["source"]
        size = src["bundle_size"]
        first = self.route[0]
        cap = src["wip_cap_bundles"]
        for li, lot in enumerate(src["lots"]):
            left = lot["qty"] if lot["qty"] > 0 else math.inf
            while left > 0:
                n = int(min(size, left))
                while cap and sum(1 for b in self.live.values() if b.fresh) >= cap:
                    yield self.capacity_event
                b = self._new_bundle(li, n, True)
                b.t0 = self.env.now
                self.launched += n
                self._loc(b, L_SOURCE, 0)
                yield self.q[first].put(b)
                b.t0 = self.env.now
                self._loc(b, L_QUEUE, self.sidx[first])
                left -= n
                if src["interval_min"] > 0:
                    yield self.env.timeout(src["interval_min"])

    def _failures(self, sid: str):
        for a, b in self.down_iv[sid]:
            if a > self.env.now:
                yield self.env.timeout(a - self.env.now)
            self.down[sid] = True
            self._override_station(sid)
            yield self.env.timeout(max(0.0, b - self.env.now))
            self.down[sid] = False
            self._override_station(sid)

    def _breaks(self):
        for a, b in self.breaks:
            if a > self.env.now:
                yield self.env.timeout(a - self.env.now)
            for sid in self.st:
                self._override_station(sid)
            for oid, t in self.op_tr.items():
                t.force(O_BREAK)
            for tid, t in self.tr_tr.items():
                t.force(T_BREAK)
            yield self.env.timeout(max(0.0, b - self.env.now))
            for sid in self.st:
                self._override_station(sid)
            for t in list(self.op_tr.values()) + list(self.tr_tr.values()):
                t.force(None)

    def _snapshots(self):
        every = self.m["settings"]["snapshot_every_min"]
        while True:
            self.wip_series.append([round(self.env.now, 2), sum(b.qty for b in self.live.values()),
                                    [self.q[s].pieces for s in self.st]])
            yield self.env.timeout(every)

    def _gen_failures(self):
        rng = random.Random(self.seed * 7919 + 13)
        for sid, st in self.st.items():
            ivs = []
            if st["mtbf_min"] > 0 and st["mttr_min"] > 0:
                t = rng.expovariate(1.0 / st["mtbf_min"])
                while t < self.T:
                    d = max(0.5, rng.expovariate(1.0 / st["mttr_min"]))
                    ivs.append((t, min(self.T, t + d)))
                    t += d + rng.expovariate(1.0 / st["mtbf_min"])
            for b in self.m["breakdowns"]:
                if b["station"] == sid and b["duration_min"] > 0:
                    ivs.append((b["start_min"], min(self.T, b["start_min"] + b["duration_min"])))
            ivs.sort()
            merged: list[tuple[float, float]] = []
            for a, b in ivs:
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            self.down_iv[sid] = merged

    # ------------------------------------------------------------------ exécution
    def run(self) -> dict:
        m = self.m
        self._gen_failures()
        for sid, st in self.st.items():
            self.servers[sid] = [Tracker(self, 8, S_STARVED, on_change=lambda _s, sid=sid: self._station_changed(sid))
                                 for _ in range(st["servers"])]
        for oid, o in self.ops.items():
            self.op_loc[oid] = o["stations"][0] if o["stations"] else "src"
            self.op_tr[oid] = Tracker(self, 7, O_IDLE)
        for tid in self.trs:
            self.tr_tr[tid] = Tracker(self, 6, T_IDLE)
        # encours de départ : paquets déjà devant les postes (hors 1er poste)
        size = m["source"]["bundle_size"]
        wip0 = []
        for pos, sid in enumerate(self.route):
            if pos == 0:
                continue
            for _ in range(min(m["source"]["start_wip_bundles"], self.st[sid]["queue_capacity"])):
                if self.cv:
                    wip0.append((sid, pos))
                    continue
                b = self._new_bundle(0, size, False)
                self.initial += size
                self.q[sid].put(b)
                self._loc(b, L_QUEUE, self.sidx[sid])
        if self.cv:
            self._cv_start(wip0)
        for sid, st in self.st.items():
            if not st["operators"]:
                self.notes.append(f"Poste {sid} sans opérateur : les paquets s'y accumulent.")
            for k in range(st["servers"]):
                self.env.process(self._server(sid, k))
            if self.down_iv[sid]:
                self.env.process(self._failures(sid))
        for tid in self.trs:
            self.env.process(self._transporter(tid))
        self.env.process(self._cv_source() if self.cv else self._source())
        self.env.process(self._breaks())
        self.env.process(self._snapshots())
        self.env.run(until=self.T)
        return self._result()

    def _home(self, a: str) -> str:
        if a in self.ops:
            return (self.ops[a]["stations"] or ["src"])[0]
        return "src"

    # ------------------------------------------------------------------ résultats
    def _result(self) -> dict:
        T, m = self.T, self.m
        for trs in self.servers.values():
            for t in trs:
                t.close(T)
        for t in list(self.op_tr.values()) + list(self.tr_tr.values()):
            t.close(T)
        for q in self.q.values():
            q._acc()
        pct = lambda v, tot: round(100.0 * v / tot, 1) if tot > 0 else 0.0  # noqa: E731
        stations = []
        for sid, st in self.st.items():
            acc = [sum(t.acc[i] for t in self.servers[sid]) for i in range(8)]
            tot = T * st["servers"]
            states = {name: pct(acc[i], tot) for i, name in enumerate(
                ["work", "starved", "blocked", "down", "setup", "wait_operator", "break", "transfer"])}
            q = self.q[sid]
            stations.append({
                "id": sid, "label": st["label"], "servers": st["servers"], "operators": list(st["operators"]),
                "minutes": st["minutes"], "pieces": self.done_st[sid], "defects": self.defects[sid],
                "states": states, "utilization_pct": round(states["work"] + states["setup"], 1),
                "queue_avg": round(q.area_b / T, 2), "queue_max": q.max_b,
                "queue_avg_pieces": round(q.area_p / T, 1), "queue_max_pieces": q.max_p,
                "down_min": round(acc[S_DOWN], 1),
            })
        active = lambda s: s["states"]["work"] + s["states"]["setup"] + s["states"]["down"] + s["states"]["wait_operator"]  # noqa: E731
        # goulot : poste le plus actif ; à ±1 point près, celui dont la charge par serveur est la plus forte
        # (le 1er poste, toujours alimenté en flux tiré, ne doit pas masquer le vrai goulot)
        bott = None
        if stations:
            top = max(active(s) for s in stations)
            cands = [s for s in stations if active(s) >= top - 1.0]
            bott = max(cands, key=lambda s: (s["minutes"] / max(1, s["servers"]), active(s)))["id"]
        ops = []
        for oid, o in self.ops.items():
            acc = self.op_tr[oid].acc
            states = {n: pct(acc[i], T) for i, n in enumerate(["idle", "walk", "work", "setup", "carry", "break", "wait"])}
            ops.append({"id": oid, "name": o["name"], "stations": o["stations"], "states": states,
                        "utilization_pct": round(states["work"] + states["setup"], 1),
                        "walk_m": round(self.op_walk[oid], 1), "carry_m": round(self.op_carry[oid], 1),
                        "gantt": self.op_tr[oid].log[:1500]})
        trs = []
        for tid, t in self.trs.items():
            acc = self.tr_tr[tid].acc
            states = {n: pct(acc[i], T) for i, n in enumerate(["idle", "empty", "loaded", "loading", "wait", "break"])}
            trs.append({"id": tid, "name": t["name"], "capacity": t["capacity"], "states": states,
                        "utilization_pct": round(100 - states["idle"] - states["break"], 1),
                        "distance_m": round(self.tr_dist[tid], 1), "loads": self.tr_loads[tid],
                        "gantt": self.tr_tr[tid].log[:1500]})
        hours = max(1, math.ceil(T / 60))
        hourly = [0] * hours
        cum, run = [[0.0, 0]], 0
        for t, n in self.completions:
            hourly[min(hours - 1, int(t // 60))] += n
            run += n
            cum.append([round(t, 2), run])
        if len(cum) > 1500:
            step = len(cum) / 1500
            cum = [cum[int(i * step)] for i in range(1500)] + [cum[-1]]
        in_sys = sum(b.qty for b in self.live.values())
        lead = sorted(self.lead)
        hist = _histogram(lead)
        prod_minutes = T - sum(b - a for a, b in self.breaks)
        target = m["settings"]["target_per_hour"]
        wip_vals = [w[1] for w in self.wip_series]
        kpis = {
            "pieces": self.done, "per_hour": round(self.done / T * 60, 1),
            "per_hour_worked": round(self.done / max(1e-6, prod_minutes) * 60, 1),
            "lead_time_avg": round(statistics.mean(lead), 1) if lead else None,
            "lead_time_p90": round(lead[int(0.9 * (len(lead) - 1))], 1) if lead else None,
            "wip_avg": round(statistics.mean(wip_vals), 1) if wip_vals else 0,
            "wip_max": max(wip_vals) if wip_vals else 0,
            "bottleneck": bott, "operators": len(ops),
            "operator_util_avg": round(statistics.mean([o["utilization_pct"] for o in ops]), 1) if ops else 0,
            "walk_m": round(sum(self.op_walk.values()), 1), "transport_m": round(self.transport_m, 1),
            "defects": sum(self.defects.values()), "launched": self.launched,
            "target_per_hour": target,
        }
        cv_k, cv_det = self._cv_result(T)
        kpis.update(cv_k)
        res = {
            "success": True, "seed": self.seed, "shift_minutes": T, "breaks": m["shift"]["breaks"],
            "kpis": kpis, "stations": stations, "operators": ops, "transporters": trs,
            "throughput": {"hourly": hourly, "cumulative": cum, "target_per_hour": target},
            "wip_series": [[w[0], w[1]] for w in self.wip_series],
            "queue_series": {"stations": list(self.st), "rows": [[w[0], w[2]] for w in self.wip_series]},
            "lead_time": {"hist": hist, "count": len(lead), "sample": [round(x, 1) for x in lead[:: max(1, len(lead) // 400)]]},
            "conservation": {"initial": self.initial, "launched": self.launched, "done": self.done,
                             "in_system": in_sys, "ok": self.initial + self.launched == self.done + in_sys},
            "notes": self.notes, "conveyor": cv_det or None,
        }
        if self.trace_on:
            res["trace"] = {
                "events": self.events, "paths": self.path_list, "bundles": self.bundle_table,
                "truncated": self.truncated, "until": round(self.trace_until, 2),
                "actors": [{"id": a, "kind": "operator" if a in self.ops else "transporter",
                            "name": (self.ops.get(a) or self.trs.get(a) or {}).get("name", a),
                            "start": list(self.m["points"].get(self._home(a), [0, 0]))} for a in self.actor_ids],
                "stations": list(self.st), "lots": m["source"]["lots"],
                "station_states": ["work", "starved", "blocked", "down", "setup", "wait_operator", "break", "transfer"],
                "operator_states": ["idle", "walk", "work", "setup", "carry", "break", "wait"],
                "transporter_states": ["idle", "empty", "loaded", "loading", "wait", "break"],
                "loc_kinds": ["queue", "process", "out", "operator", "transporter", "done", "source", "carrier"],
                "carriers": self.cv_ids if self.cv else [],
                "carrier_parks": ["empty", "spur", "station", "merge", "load", "unload"],
            }
        return res


def _histogram(values: list[float], bins: int = 12) -> dict:
    if not values:
        return {"edges": [], "counts": []}
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return {"edges": [round(lo, 1), round(lo + 1, 1)], "counts": [len(values)]}
    w = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int((v - lo) / w))] += 1
    return {"edges": [round(lo + i * w, 1) for i in range(bins + 1)], "counts": counts}


def simulate(model: dict, seed: Optional[int] = None, trace: Optional[bool] = None) -> dict:
    """Une réplication du modèle."""
    return Simulator(model, seed, trace).run()
