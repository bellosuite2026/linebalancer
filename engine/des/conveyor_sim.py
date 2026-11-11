"""Convoyeur suspendu dans le simulateur (mixin de engine.des.sim.Simulator).

Fonctionnement (type UPS Eton / INA) :
- Chargement : la source pose `carrier_capacity` pièces sur un cintre vide (stock de cintres vides à
  la station de chargement), puis l'insère sur la boucle principale s'il reste de la place sur le rail
  (une réserve de places est gardée pour les postes qui renvoient leurs cintres : pas d'interblocage).
- Routage selon la gamme : à chaque étape, le cintre va vers le poste de l'opération ; avec la
  réaffectation dynamique, vers le poste le moins chargé parmi ceux qui ont la compétence (postes
  interchangeables `alternates`, dont les postes d'une même opération partagée par l'équilibrage).
- Aiguillage d'entrée (temps d'aiguillage + longueur de la dérivation) seulement si la dérivation a de
  la place (limite d'encours de la station) ; sinon le cintre fait un tour de plus (recirculation).
  Les cintres qui attendent un aiguillage occupé s'accumulent sur le rail.
- Après l'opération, le cintre attend une place sur la boucle et l'aiguillage de sortie (le poste est
  « bloqué aval » pendant ce temps), puis repart vers l'étape suivante.
- Déchargement : pièces terminées, le cintre vide revient au chargement par la boucle.
"""
from __future__ import annotations

import simpy

C_EMPTY, C_SPUR, C_STATION, C_MERGE, C_LOAD, C_UNLOAD = range(6)
L_QUEUE, L_PROCESS, L_OUT, L_CARRIER, L_SOURCE = 0, 1, 2, 7, 6
S_STARVED, S_BLOCKED = 1, 2


class ConveyorMixin:
    def _init_conveyor(self):
        c = self.m.get("conveyor") or {}
        self.cv = c if c.get("enabled") else None
        if not self.cv:
            return
        self.cv_L = float(c["length_m"])
        self.cv_v = float(c["speed_m_per_min"])
        self.cv_sw = float(c["switch_sec"]) / 60.0
        self.cv_ids = [f"C{k + 1:03d}" for k in range(int(c["carriers"]))]
        self.empty = simpy.Store(self.env)
        cap = int(c["capacity"])
        self.rail = simpy.Container(self.env, capacity=cap, init=cap)     # places libres sur la boucle
        self.cv_reserve = min(len(self.st), max(1, cap // 4))
        self.sw_in = {sid: simpy.Resource(self.env, capacity=1) for sid in self.st}
        self.sw_out = {sid: simpy.Resource(self.env, capacity=1) for sid in self.st}
        self.unloader = simpy.Resource(self.env, capacity=1)
        self.inbound = {sid: 0 for sid in self.st}
        self.reserved = {sid: 0 for sid in self.st}
        self.on_rail = self.circ = 0
        self.rail_area = self.circ_area = 0.0
        self.rail_last = self.circ_last = 0.0
        self.rail_max = self.circ_max = 0
        self.recirc = self.reassigned = 0
        self.cv_rail_times: list[float] = []
        self.cv_station_times: list[float] = []
        self.cv_trips = [0] * len(self.cv_ids)
        self.cv_dist = [0.0] * len(self.cv_ids)
        self.cv_recirc_st = {sid: 0 for sid in self.st}
        self.cv_assigned = {sid: 0 for sid in self.st}

    # ------------------------------------------------------------------ compteurs pondérés par le temps
    def _rail_delta(self, d: int):
        now = self.env.now
        self.rail_area += self.on_rail * (now - self.rail_last)
        self.rail_last = now
        self.on_rail += d
        self.rail_max = max(self.rail_max, self.on_rail)

    def _circ_delta(self, d: int):
        now = self.env.now
        self.circ_area += self.circ * (now - self.circ_last)
        self.circ_last = now
        self.circ += d
        self.circ_max = max(self.circ_max, self.circ)

    def _cv_park(self, c: int, kind: int, ref: int = 0):
        self.ev(5, c, kind, ref)

    def _rail_move(self, c: int, b, s0: float, d: float):
        if d <= 1e-9:
            return
        dt = d / self.cv_v
        self.ev(4, c, round(self.env.now + dt, 3), round(s0, 3), round(s0 + d, 3))
        yield self.env.timeout(dt)
        self.cv_dist[c] += d
        if b is not None:
            b.rail_t += dt

    def _wait_break(self):
        while True:
            now = self.env.now
            cur = next(((a, b) for a, b in self.breaks if a <= now < b), None)
            if not cur:
                return
            yield self.env.timeout(cur[1] - now)

    # ------------------------------------------------------------------ routage
    def _station_load(self, sid: str) -> float:
        q = self.q[sid]
        busy = sum(1 for t in self.servers.get(sid) or [] if t.base != S_STARVED)
        return (len(q.items) + len(q.putters) + self.inbound[sid] + self.reserved[sid] + busy) / max(1, self.st[sid]["servers"])

    def _choose(self, step: int) -> str:
        base = self.route[step]
        cands = [base]
        if self.cv["dynamic_routing"]:
            cands += [s for s in self.cv["alternates"].get(base, []) if self.st[s]["operators"]]
        best = min(cands, key=lambda s: (self._station_load(s), cands.index(s)))
        if best != base:
            self.reassigned += 1
        return best

    def _trip(self, c: int, b, s_from: float):
        cv, L = self.cv, self.cv_L
        last_target = None
        while True:
            if b.step >= len(self.route):
                yield from self._rail_move(c, b, s_from, (cv["s_unload"] - s_from) % L)
                s_from = cv["s_unload"]
                req = self.unloader.request()
                yield req
                self._cv_park(c, C_UNLOAD, 0)
                yield self.env.timeout(cv["unload_min"])
                self.unloader.release(req)
                if b.fresh and not b.rework:
                    self.cv_rail_times.append(b.rail_t)
                    self.cv_station_times.append(max(0.0, self.env.now - b.t0 - b.rail_t))
                self.cv_trips[c] += 1
                self._complete(b)
                # cintre vide : retour au chargement par la boucle
                yield from self._rail_move(c, None, s_from, (cv["s_load"] - s_from) % L)
                self.rail.put(1)
                self._rail_delta(-1)
                self._circ_delta(-1)
                self._cv_park(c, C_EMPTY, 0)
                self.empty.put(c)
                return
            target = self._choose(b.step)
            sp = cv["spurs"][target]
            d = (sp["s"] - s_from) % L
            if d < 1e-6 and last_target is not None:
                d = L                              # même poste encore plein : un tour complet
            self.inbound[target] += 1
            yield from self._rail_move(c, b, s_from, d)
            self.inbound[target] -= 1
            s_from = sp["s"]
            q = self.q[target]
            if q.free() - self.reserved[target] > 0:
                self.reserved[target] += 1
                req = self.sw_in[target].request()
                t0 = self.env.now
                yield req                            # accumulation devant l'aiguillage
                yield self.env.timeout(self.cv_sw + sp["len"] / self.cv_v)
                self.sw_in[target].release(req)
                b.rail_t += self.env.now - t0
                self.rail.put(1)
                self._rail_delta(-1)
                self.reserved[target] -= 1
                self.cv_assigned[target] += 1
                yield q.put(b)
                self._cv_park(c, C_SPUR, self.sidx[target])
                self._loc(b, L_QUEUE, self.sidx[target])
                return
            self.recirc += 1                       # dérivation pleine : tour supplémentaire
            self.cv_recirc_st[target] += 1
            last_target = target

    def _cv_output(self, sid: str, tr, b, oid: str, req):
        """Le poste renvoie le cintre sur la boucle ; l'opérateur est libéré tout de suite."""
        self._release(oid, req)
        tr.set(S_BLOCKED)
        self._cv_park(b.carrier, C_MERGE, self.sidx[sid])
        self._loc(b, L_OUT, self.sidx[sid])
        yield self.rail.get(1)                       # place sur la boucle
        r2 = self.sw_out[sid].request()
        yield r2
        t0 = self.env.now
        yield self.env.timeout(self.cv_sw)
        self.sw_out[sid].release(r2)
        b.rail_t += self.env.now - t0
        self._rail_delta(1)
        b.step += 1
        self._loc(b, L_CARRIER, b.carrier)
        self.env.process(self._trip(b.carrier, b, self.cv["spurs"][sid]["s"]))
        return True

    def _cv_source(self):
        src, cv = self.m["source"], self.cv
        size = cv["carrier_capacity"]
        cap = src["wip_cap_bundles"]
        for li, lot in enumerate(src["lots"]):
            left = lot["qty"] if lot["qty"] > 0 else float("inf")
            while left > 0:
                n = int(min(size, left))
                while cap and sum(1 for b in self.live.values() if b.fresh) >= cap:
                    yield self.capacity_event
                c = yield self.empty.get()
                yield from self._wait_break()
                b = self._new_bundle(li, n, True)
                b.carrier, b.step = c, 0
                self.launched += n
                self._circ_delta(1)
                self._loc(b, L_SOURCE, 0)
                self._cv_park(c, C_LOAD, 0)
                yield self.env.timeout(cv["load_min"])
                # garde des places pour les sorties de postes ; pilotage du lancement (cintres sur la boucle)
                while self.rail.level <= self.cv_reserve or self.on_rail >= cv["max_on_rail"]:
                    yield self.env.timeout(0.1)
                yield self.rail.get(1)
                self._rail_delta(1)
                b.t0 = self.env.now
                self._loc(b, L_CARRIER, c)
                self.env.process(self._trip(c, b, cv["s_load"]))
                left -= n
                if src["interval_min"] > 0:
                    yield self.env.timeout(src["interval_min"])

    def _cv_start(self, initial_wip: list[tuple[str, int]]):
        """Cintres : encours de départ dans les dérivations, le reste au stock de cintres vides."""
        free = list(range(len(self.cv_ids)))
        size = self.cv["carrier_capacity"]
        for sid, pos in initial_wip:
            if not free:
                break
            c = free.pop(0)
            b = self._new_bundle(0, size, False)
            b.carrier, b.step = c, pos
            self.initial += size
            self.q[sid].put(b)
            self._circ_delta(1)
            self._cv_park(c, C_SPUR, self.sidx[sid])
            self._loc(b, L_QUEUE, self.sidx[sid])
        for c in free:
            self.empty.items.append(c)
            self._cv_park(c, C_EMPTY, 0)

    def _cv_result(self, T: float) -> tuple[dict, dict]:
        if not self.cv:
            return ({k: None for k in ("rail_util_pct", "carriers_in_circulation", "rail_time_avg", "station_time_avg",
                                       "rail_share_pct", "recirculations", "reassigned")}, {})
        self._rail_delta(0)
        self._circ_delta(0)
        cv = self.cv
        rt, stt = self.cv_rail_times, self.cv_station_times
        ra = sum(rt) / len(rt) if rt else None
        sa = sum(stt) / len(stt) if stt else None
        k = {
            "rail_util_pct": round(100.0 * self.rail_area / T / cv["capacity"], 1),
            "carriers_in_circulation": round(self.circ_area / T, 1),
            "rail_time_avg": round(ra, 2) if ra is not None else None,
            "station_time_avg": round(sa, 2) if sa is not None else None,
            "rail_share_pct": round(100.0 * ra / (ra + sa), 1) if ra is not None and sa is not None and ra + sa > 0 else None,
            "recirculations": self.recirc, "reassigned": self.reassigned,
        }
        det = {
            "name": cv["name"], "length_m": cv["length_m"], "capacity": cv["capacity"], "carriers": len(self.cv_ids),
            "carrier_capacity": cv["carrier_capacity"], "station_wip": cv["station_wip"],
            "speed_m_per_min": cv["speed_m_per_min"], "switch_sec": cv["switch_sec"],
            "rail_max": self.rail_max, "circulation_max": self.circ_max,
            "rail_util_max_pct": round(100.0 * self.rail_max / cv["capacity"], 1),
            "trips": sum(self.cv_trips), "distance_m": round(sum(self.cv_dist), 1),
            "stations": [{"id": sid, "assigned": self.cv_assigned[sid], "recirculations": self.cv_recirc_st[sid]}
                         for sid in self.st],
            "carriers_ids": self.cv_ids,
        }
        return k, det
