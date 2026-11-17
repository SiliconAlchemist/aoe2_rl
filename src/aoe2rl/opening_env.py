"""Live DE opening task with explicit candidate commands and no synthetic fallback."""
import itertools
import math
import time
from pathlib import Path

import numpy as np

from .agent_bridge import AgentBridge
from .core import BridgeError
from .opening import Opening, distance, position, is_herd
from .transport import ControlPipe

TASK_VERSION = 1
MAX_ACTIONS, GLOBAL_SIZE, CANDIDATE_SIZE = 96, 24, 24
KINDS = ("wait", "build", "home", "explore", "capture")


class OpeningEnv:
    def __init__(self, horizon=180., interval=2., reset_mode="auto", trace=None):
        self.horizon, self.interval, self.reset_mode = horizon, interval, reset_mode
        self.trace = Path(trace) if trace else None
        self.bridge = AgentBridge()
        self.previous_world = None
        self.active = False

    def close(self):
        self.active = False
        if self.bridge.session:
            self.bridge.request("close")

    def observe(self, changing_world=False):
        o = self.bridge.request("observe", {"object_types": "none", "technologies": "none"})
        if o.get("information_policy") != "player_view" or o["match"]["replay"] or o["player"]["id"] != 1:
            raise BridgeError("Opening requires Player 1, player_view and a single-player non-replay match")
        if not changing_world and o["world"] != self.world:
            raise BridgeError("World changed during a rollout; discard this episode")
        return o

    def reset(self):
        self.close()
        if self.reset_mode == "manual":
            input("Start/restart a fresh unpaused single-player match, then press Enter here: ")
        status = self.bridge.request("status")
        if status.get("state") != "ready" or status.get("information_policy") != "player_view":
            raise BridgeError("Start an unpaused single-player match; enable Player 1 Agent Bridge and disable See Everything")
        self.bridge.request("open", {"client_name": "aoe2-opening-learner"})
        old = self.observe(changing_world=True)
        self.reset_info = {"mode": self.reset_mode, "previous_world": old["world"]}
        if self.reset_mode == "auto":
            helper = ControlPipe(player=1, pipe="AoE2RLOpeningReset", module="opening_reset", timeout=10)
            try:
                ping = helper.request({"op": "ping"})
                if not ping.get("ready"):
                    raise BridgeError("Reset helper is not ready for single-player training")
                helper.request({"op": "restart", "generation": ping["generation"]})
                self.reset_info.update(previous_generation=ping["generation"], previous_seed=ping.get("effective_seed"))
            finally:
                helper.close()
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    current = self.observe(changing_world=True)
                except BridgeError as exc:
                    if "observation_unavailable" not in str(exc):
                        raise
                    time.sleep(.2)
                    continue
                if current["world"] != old["world"] and 0 < current["game_time_ms"] < 15000:
                    break
                time.sleep(.2)
            else:
                raise BridgeError("Restart did not produce a new world with a fresh clock within 45 seconds")
            helper = ControlPipe(player=1, pipe="AoE2RLOpeningReset", module="opening_reset", timeout=10)
            try:
                fresh = helper.request({"op": "ping"})
                if not fresh.get("ready") or fresh["generation"] <= ping["generation"]:
                    raise BridgeError("Native world changed but reset helper did not confirm a new match")
                self.reset_info.update(generation=fresh["generation"], effective_seed=fresh.get("effective_seed"))
            finally:
                helper.close()
        else:
            current = old
            if current["world"] == self.previous_world:
                raise BridgeError("Manual reset reused the previous world")
        if current["game_time_ms"] > 15000:
            raise BridgeError("Opening must start within 15 game-seconds; restart the match")
        self.world = current["world"]
        self.previous_world = self.world
        time.sleep(.4)
        advancing = self.observe()
        if advancing["game_time_ms"] <= current["game_time_ms"]:
            raise BridgeError("Game is paused or clock is frozen; unpause before training")
        self.o = advancing
        self.origin = self.o["game_time_ms"] / 1000
        owned = self.owned()
        villagers = sorted((e for e in owned if e.get("type_id") in (83, 293) and e.get("idle")), key=lambda e: e["id"])
        tc = next((e for e in owned if e.get("type_id") == 109), None)
        scout = next((e for e in owned if e.get("type_id") == 448), None)
        if len(villagers) != 3 or tc is None or scout is None or self.o["player"]["attributes"][1] < 50:
            raise BridgeError("Expected three idle villagers, standard TC, Scout Cavalry and >=50 wood")
        self.villagers, self.tc, self.scout = [v["id"] for v in villagers], tc, scout["id"]
        self.initial_ids = {e["id"] for e in self.o["entities"]}
        self.initial_herd = {e["id"] for e in owned if is_herd(e)}
        self.houses, self.reserved, self.orders, self.start_positions = [], [], {}, {}
        self.acquired, self.explored_animals = set(), set()
        self.scout_explored = False
        self.moves, self.rejections = 0, 0
        self.reader = Opening(30, 40, "reports/unused-opening-helper.json")
        self.reader.bridge, self.reader.world, self.reader.tc = self.bridge, self.world, self.tc
        self.map = self.reader.map_data()
        self.explored_start = self.local_explored()
        self.elapsed = 0.
        self.metrics = self.measure()
        self.potential = self.score()
        self.reset_info.update(world=self.world, initial_game_time=self.origin,
                               initial_owned_livestock=sorted(self.initial_herd))
        self.active = True
        return self.encode()

    def owned(self):
        return [e for e in self.o["entities"] if e.get("owner") == 1 and e.get("access") == "full"
                and e.get("alive") and e.get("commandable")]

    def local_explored(self):
        width, height, visibility, _ = self.map
        return sum(visibility[y * width + x] > 0
                   for y in range(max(0, int(self.tc["y"])-40), min(height, int(self.tc["y"])+41))
                   for x in range(max(0, int(self.tc["x"])-40), min(width, int(self.tc["x"])+41)))

    def measure(self):
        owned = self.owned()
        by_id = {e["id"]: e for e in owned}
        herd = [e for e in owned if is_herd(e)]
        self.acquired.update(e["id"] for e in herd if e["id"] not in self.initial_herd)
        for unit in herd + [e for e in owned if e["id"] == self.scout]:
            start = self.start_positions.setdefault(unit["id"], position(unit))
            if distance(unit, start) > 5:
                if unit["id"] == self.scout:
                    self.scout_explored = True
                elif unit["id"] not in self.reserved and self.orders.get(unit["id"], {}).get("kind") == "explore":
                    self.explored_animals.add(unit["id"])
        progress = []
        for house in self.houses:
            found = next((e for e in self.o["entities"] if e["id"] not in self.initial_ids
                          and e.get("owner") == 1 and e.get("type_id") == 70
                          and distance(e, house["position"]) < 1.5), None)
            house["completed"] = bool(found and found.get("status") == 2 and found.get("alive"))
            house["id"] = found["id"] if found else None
            progress.append(min(1., found.get("hitpoints", 0) / max(1, found.get("max_hitpoints", 1))) if found else 0.)
        home = sum(uid in by_id and distance(by_id[uid], self.tc) <= 2.5 for uid in self.reserved)
        alive_explorers = [uid for uid in self.explored_animals if uid in by_id and uid not in self.reserved]
        lost = any(uid not in by_id for uid in self.villagers + [self.scout])
        return dict(houses_complete=sum(h["completed"] for h in self.houses),
                    house_progress=sum(progress), livestock_home=home, owned_livestock=len(herd),
                    acquired=len(self.acquired), explored_tiles=max(0, self.local_explored()-self.explored_start),
                    livestock_explorers=len(alive_explorers), scout_explored=self.scout_explored,
                    essential_unit_lost=lost)

    def score(self):
        m = self.metrics
        return (m["house_progress"] + .5*m["livestock_home"] + .5*min(m["acquired"], 2)
                + min(m["explored_tiles"]/500, 1) + .25*min(m["livestock_explorers"], 2)
                + .5*float(m["scout_explored"]))

    def complete(self):
        m = self.metrics
        return (m["houses_complete"] == 2 and m["livestock_home"] == 2 and m["acquired"] >= 1
                and m["explored_tiles"] >= 250 and m["livestock_explorers"] >= 2 and m["scout_explored"])

    def frontiers(self):
        # Eight directional alternatives, all on explored walkable tiles bordering fog.
        width, height, visibility, passable = self.map
        best = {}
        for y in range(max(2, int(self.tc["y"])-40), min(height-2, int(self.tc["y"])+41), 2):
            for x in range(max(2, int(self.tc["x"])-40), min(width-2, int(self.tc["x"])+41), 2):
                p = {"x": x+.5, "y": y+.5}
                d = distance(p, self.tc)
                if d > 40 or not visibility[y*width+x] or not passable[y*width+x] & 1:
                    continue
                unknown = sum(visibility[ny*width+nx] == 0
                              for dx, dy in ((-4,0),(4,0),(0,-4),(0,4),(-3,-3),(-3,3),(3,-3),(3,3))
                              if 0 <= (nx := x+dx) < width and 0 <= (ny := y+dy) < height)
                sector = int(round(math.atan2(p["y"]-self.tc["y"], p["x"]-self.tc["x"])/(math.pi/4))) % 8
                rank = unknown / (d+8)
                if unknown and (sector not in best or rank > best[sector][0]):
                    best[sector] = rank, p
        return [best[k][1] for k in sorted(best)]

    def candidates(self):
        result = [dict(kind="wait", actors=[], position=position(self.tc))]
        owned = self.owned()
        by_id = {e["id"]: e for e in owned}
        used = {uid for h in self.houses for uid in h["builders"]}
        free = [uid for uid in self.villagers if uid not in used and uid in by_id]
        if len(self.houses) < 2 and free and self.o["player"]["attributes"][1] >= 25:
            placements = []
            for i in range(16):
                angle = i*math.pi/8
                p = {"x": round(self.tc["x"]+7*math.cos(angle)), "y": round(self.tc["y"]+7*math.sin(angle))}
                if (2 <= p["x"] < self.map[0]-2 and 2 <= p["y"] < self.map[1]-2
                        and all(distance(p, h["position"]) >= 4 for h in self.houses)):
                    placements.append(p)
            if placements:
                checked = self.bridge.request("query", {"kind":"placement", "object_type":70, "positions":placements})
                legal = [p for p, r in zip(placements, checked["results"]) if r["name"] == "CAN_PLACE"]
                # Spread four choices around the TC rather than giving one fixed scripted site.
                legal = legal[::max(1, math.ceil(len(legal)/4))][:4]
                groups = ([list(c) for n in (1,2) for c in itertools.combinations(free, n)]
                          if not self.houses else [free])
                for group in groups:
                    for p in legal:
                        result.append(dict(kind="build", actors=group, position=p))
        frontier = self.frontiers()
        livestock = sorted((e for e in owned if is_herd(e)), key=lambda e: e["id"])[:8]
        actors = [by_id[self.scout]] if self.scout in by_id else []
        actors += livestock
        for unit in actors:
            uid = unit["id"]
            order = self.orders.get(uid)
            if order and self.elapsed-order["at"] < 8 and distance(unit, order["position"]) > 2:
                continue
            if uid != self.scout:
                if (uid in self.reserved or len(self.reserved) < 2) and distance(unit, self.tc) > 2.5:
                    result.append(dict(kind="home", actors=[uid], position=position(self.tc)))
                elif uid not in self.reserved and len(self.reserved) < 2:
                    result.append(dict(kind="home", actors=[uid], position=position(self.tc)))
                if uid in self.reserved:
                    continue
            targets = frontier if uid == self.scout else frontier[::2]
            for p in targets:
                if distance(unit, p) > 3:
                    result.append(dict(kind="explore", actors=[uid], position=p))
            if uid == self.scout:
                neutral = sorted((e for e in self.o["entities"] if e.get("owner") == 0 and is_herd(e)
                                  and e.get("access") == "full" and e.get("alive", True)
                                  and distance(e, self.tc) <= 40), key=lambda e: distance(e, unit))[:4]
                result.extend(dict(kind="capture", actors=[uid], position=position(e)) for e in neutral)
        if len(result) > MAX_ACTIONS:
            raise BridgeError("Candidate count exceeds the policy schema")
        return result

    def encode(self):
        self.actions = self.candidates()
        f = np.zeros(GLOBAL_SIZE, np.float32)
        m = self.metrics
        f[:12] = [min(self.elapsed/self.horizon,1), min(self.o["player"]["attributes"][1]/200,1),
                  len(self.houses)/2, m["house_progress"]/2, m["livestock_home"]/2,
                  min(m["owned_livestock"]/8,1), min(m["acquired"]/4,1),
                  min(m["explored_tiles"]/1000,1), min(m["livestock_explorers"]/4,1),
                  float(m["scout_explored"]), len(self.reserved)/2, self.score()/6]
        by_id = {e["id"]: e for e in self.owned()}
        for i, uid in enumerate(self.villagers+[self.scout]):
            e = by_id.get(uid)
            if e:
                f[12+i*3:15+i*3] = [(e["x"]-self.tc["x"])/40, (e["y"]-self.tc["y"])/40, float(e.get("idle",False))]
        c = np.zeros((MAX_ACTIONS, CANDIDATE_SIZE), np.float32)
        mask = np.zeros(MAX_ACTIONS, bool)
        for i, a in enumerate(self.actions):
            mask[i] = True
            c[i, KINDS.index(a["kind"])] = 1
            units = [by_id[uid] for uid in a["actors"]]
            center = {"x": sum(e["x"] for e in units)/len(units), "y": sum(e["y"] for e in units)/len(units)} if units else self.tc
            p = a["position"]
            c[i,5:14] = [len(units)/3, (center["x"]-self.tc["x"])/40, (center["y"]-self.tc["y"])/40,
                        (p["x"]-self.tc["x"])/40, (p["y"]-self.tc["y"])/40,
                        (p["x"]-center["x"])/80, (p["y"]-center["y"])/80,
                        distance(center,p)/100, sum(bool(e.get("idle")) for e in units)/max(1,len(units))]
            c[i,14:17] = [float(uid in a["actors"]) for uid in self.villagers]
            c[i,17] = float(self.scout in a["actors"])
            c[i,18] = float(any(uid in self.reserved for uid in a["actors"]))
            # Nearby concurrent destinations discourage redundant exploration during imitation.
            c[i,19] = min([distance(p,o["position"])/40 for uid,o in self.orders.items()
                           if uid not in a["actors"] and o["kind"] == "explore"] or [1.])
        self.last_encoded = dict(features=f, candidates=c, mask=mask)
        return self.last_encoded

    def teacher(self):
        def rank(a):
            i, action = a
            c = self.last_encoded["candidates"][i]
            if action["kind"] == "build":
                return 10 + .1*len(action["actors"])-float(c[12])
            if action["kind"] == "home":
                return 8-float(c[12])
            if action["kind"] == "capture":
                return 7-float(c[12])
            if action["kind"] == "explore":
                return 3+float(c[13])+float(c[19])-float(c[12])
            return 0
        return max(enumerate(self.actions), key=rank)[0]

    def step(self, action):
        if not self.active or not 0 <= action < len(self.actions):
            raise BridgeError("Invalid action or inactive episode")
        a = self.actions[action]
        old_time = self.o["game_time_ms"]/1000
        rejection = 0.
        if a["kind"] != "wait":
            command = "gameplay.build.v1" if a["kind"] == "build" else "gameplay.move.v1"
            args = dict(actors=a["actors"], position=a["position"])
            if a["kind"] == "build":
                args["object_type"] = 70
            response = self.bridge.request("act", {"world":self.world,"actions":[dict(command=command,args=args)]})
            result = response["results"][0]
            if result["status"] == "queued":
                raise BridgeError("Command still queued; pause or stalled simulation. Episode discarded")
            if result["status"] == "rejected":
                if result.get("stage") != "execution":
                    raise BridgeError(f"Bridge rejected command validation: {result}")
                rejection, self.rejections = -.05, self.rejections+1
            elif result["status"] == "executed":
                self.moves += 1
                if a["kind"] == "build":
                    self.houses.append(dict(position=a["position"],builders=a["actors"],completed=False))
                else:
                    uid = a["actors"][0]
                    if a["kind"] == "home" and uid not in self.reserved:
                        self.reserved.append(uid)
                    self.orders[uid] = dict(position=a["position"],at=self.elapsed,kind=a["kind"])
            else:
                raise BridgeError(f"Unexpected action result: {result}")
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            self.o = self.observe()
            if self.o["game_time_ms"]/1000-old_time >= self.interval:
                break
            time.sleep(.05)
        else:
            raise BridgeError("Game clock did not advance; no training update from this episode")
        elapsed = self.o["game_time_ms"]/1000-old_time
        self.elapsed = self.o["game_time_ms"]/1000-self.origin
        self.map = self.reader.map_data()
        self.metrics = self.measure()
        success, lost = self.complete(), self.metrics["essential_unit_lost"]
        done = success or lost or self.elapsed >= self.horizon
        potential = 0. if done else self.score()
        # Discount-consistent potential shaping, plus finite-horizon task score at termination.
        reward = (.99**(elapsed/self.interval))*potential-self.potential-.002*elapsed+rejection
        if done:
            reward += self.score()+(3 if success else 0)-(2 if lost else 0)
        self.potential = potential
        info = dict(metrics=dict(self.metrics), success=success, elapsed=elapsed,
                    game_seconds=self.elapsed, commands=self.moves, rejected=self.rejections,
                    reset=self.reset_info, houses=self.houses, reserved_livestock=self.reserved)
        if self.trace:
            import json
            self.trace.parent.mkdir(parents=True, exist_ok=True)
            with self.trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps(dict(world=self.world, action=a, reward=reward, **info))+"\n")
        self.active = not done
        return (self.encode() if not done else None), float(reward), done, info
