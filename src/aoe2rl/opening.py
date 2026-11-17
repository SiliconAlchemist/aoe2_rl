"""Scripted two-house opening and local livestock scouting; not a learned policy.

Run in an unpaused, disposable single-player match with Agent Bridge enabled.
No game commands are sent unless --execute is supplied.
"""
import argparse
import base64
import json
import math
import time
from pathlib import Path

from .agent_bridge import AgentBridge
from .core import BridgeError


HERD_NAMES = {"sheep", "goat", "turkey", "goose", "pig", "cow", "llama",
              "water buffalo", "buffalo"}


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def position(entity):
    return {"x": float(entity["x"]), "y": float(entity["y"])}


def is_herd(entity):
    return entity.get("type_name", "").strip().lower() in HERD_NAMES


class Opening:
    def __init__(self, seconds, radius, output, allow_existing=False):
        self.bridge = AgentBridge()
        self.seconds, self.radius = seconds, radius
        self.output = Path(output)
        self.allow_existing = allow_existing
        self.report = {"completed": False, "error": None, "events": [],
                       "houses": [], "reserved_livestock": [],
                       "explorers": {}, "newly_captured_livestock": [],
                       "training_validated": False}
        self.world = None
        self.orders = {}
        self.reserved = []
        self.time_ms = 0

    def save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf-8")

    def event(self, kind, **details):
        self.report["events"].append(dict(game_time_ms=self.time_ms, kind=kind, **details))
        self.save()

    def observe(self):
        observation = self.bridge.request("observe", {"object_types": "none", "technologies": "none"})
        if observation.get("information_policy") != "player_view" or observation["match"]["replay"]:
            raise BridgeError("Use a single-player match with Modules See Everything off, not a replay")
        if observation["player"]["id"] != 1:
            raise BridgeError("This opening controls Player 1 only")
        if self.world is not None and observation["world"] != self.world:
            raise BridgeError("The match changed; stopping without issuing further commands")
        self.time_ms = observation["game_time_ms"]
        return observation

    def act(self, command, **args):
        result = self.bridge.request("act", {"world": self.world,
                                    "actions": [{"command": command, "args": args}]})
        self.event("command", command=command, args=args, response=result)
        statuses = [r.get("status") for r in result.get("results", [])]
        if statuses != ["executed"]:
            # A queued command can still run later. Do not retry it or duplicate a house.
            raise BridgeError(f"Command did not finish immediately: {result}. "
                              "If paused, unpause and inspect the game before restarting.")

    def map_data(self):
        data = self.bridge.request("map")
        if data["world"] != self.world or data.get("encoding") != "base64-u8":
            raise BridgeError("Unexpected map world or encoding")
        width, height = data["width"], data["height"]
        visibility = base64.b64decode(data["visibility"], validate=True)
        passable = base64.b64decode(data["passable"], validate=True)
        if len(visibility) != width * height or len(passable) != width * height:
            raise BridgeError("Map arrays do not match the reported dimensions")
        return width, height, visibility, passable

    def frontier(self, unit, map_data, occupied):
        """Choose known walkable ground near unexplored tiles, without hidden terrain."""
        width, height, visibility, passable = map_data
        best, best_score = None, -math.inf
        for y in range(max(1, int(self.tc["y"] - self.radius)),
                       min(height - 1, int(self.tc["y"] + self.radius) + 1), 2):
            for x in range(max(1, int(self.tc["x"] - self.radius)),
                           min(width - 1, int(self.tc["x"] + self.radius) + 1), 2):
                index = y * width + x
                point = {"x": x + .5, "y": y + .5}
                if not visibility[index] or not passable[index] & 1:
                    continue
                if distance(point, self.tc) > self.radius or distance(point, unit) < 3:
                    continue
                if any(distance(point, other) < 7 for other in occupied):
                    continue
                unseen = sum(visibility[ny * width + nx] == 0
                             for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4),
                                            (-3, -3), (-3, 3), (3, -3), (3, 3))
                             if 0 <= (nx := x + dx) < width and 0 <= (ny := y + dy) < height)
                if not unseen:
                    continue
                score = unseen / (distance(unit, point) + 6)
                if score > best_score:
                    best, best_score = point, score
        return best

    def move(self, unit, target, role):
        self.act("gameplay.move.v1", actors=[unit["id"]], position=target)
        self.orders[unit["id"]] = dict(position=target, time=self.time_ms, role=role)

    def build_houses(self, observation, villagers):
        existing = {e["id"] for e in observation["entities"]}
        groups = [villagers[:2], villagers[2:3]]
        for group in groups:
            center = {"x": sum(e["x"] for e in group) / len(group),
                      "y": sum(e["y"] for e in group) / len(group)}
            candidates = []
            for radius in (6, 8, 10):
                for i in range(16):
                    angle = 2 * math.pi * i / 16
                    p = {"x": round(self.tc["x"] + radius * math.cos(angle)),
                         "y": round(self.tc["y"] + radius * math.sin(angle))}
                    if (2 <= p["x"] < observation["match"]["map_width"] - 2
                            and 2 <= p["y"] < observation["match"]["map_height"] - 2
                            and all(distance(p, h["position"]) >= 4 for h in self.report["houses"])
                            and p not in candidates):
                        candidates.append(p)
            candidates.sort(key=lambda p: distance(p, center))
            self.observe()  # Recheck the world before placement and commands.
            checked = self.bridge.request("query", {"kind": "placement", "object_type": 70,
                                                     "positions": candidates})
            chosen = next((p for p, r in zip(candidates, checked["results"])
                           if r["name"] == "CAN_PLACE"), None)
            if chosen is None:
                raise BridgeError("No legal nearby house location; no placement guessed")
            builders = [v["id"] for v in group]
            self.act("gameplay.build.v1", actors=builders, object_type=70, position=chosen)
            self.report["houses"].append(dict(position=chosen, builders=builders,
                                               completed=False, builder_evidence={}))
            self.save()
        self.preexisting_ids = existing

    def update_houses(self, observation):
        entities = observation["entities"]
        for house in self.report["houses"]:
            for entity in entities:
                if (entity["id"] not in self.preexisting_ids and entity.get("owner") == 1
                        and entity.get("type_id") == 70 and distance(entity, house["position"]) < 1.5):
                    house.update(id=entity["id"], hitpoints=entity.get("hitpoints"),
                                 status=entity.get("status"),
                                 completed=entity.get("status") == 2 and entity.get("alive", False))
            for unit in entities:
                if unit["id"] in house["builders"] and not house["completed"]:
                    house["builder_evidence"][str(unit["id"])] = {
                        key: unit.get(key) for key in
                        ("action", "target_object_id", "action_target_position", "x", "y")}

    def update_livestock(self, owned, observation, map_data):
        herd = sorted((e for e in owned if is_herd(e)), key=lambda e: distance(e, self.tc))
        herd_ids = {e["id"] for e in herd}
        self.reserved = [uid for uid in self.reserved if uid in herd_ids]
        for unit in herd:
            if len(self.reserved) < 2 and unit["id"] not in self.reserved:
                self.reserved.append(unit["id"])
                self.orders.pop(unit["id"], None)
                self.event("reserve_for_tc", unit_id=unit["id"], type_name=unit["type_name"])
            if unit["id"] not in self.initial_herd and unit["id"] not in self.report["newly_captured_livestock"]:
                self.report["newly_captured_livestock"].append(unit["id"])
                self.event("livestock_captured", unit_id=unit["id"], position=position(unit))
        self.report["reserved_livestock"] = list(self.reserved)
        self.report["livestock_under_tc"] = [e["id"] for e in herd
                                              if e["id"] in self.reserved and distance(e, self.tc) <= 2.5]
        for unit in herd:
            if unit["id"] not in self.reserved:
                continue
            order = self.orders.get(unit["id"])
            if distance(unit, self.tc) > 2 and (order is None or self.time_ms - order["time"] > 20000):
                self.move(unit, position(self.tc), "under_tc")

        scouts = [e for e in owned if e["id"] == self.scout_id]
        if not scouts:
            raise BridgeError("The scout is no longer alive and controllable")
        explorers = scouts + [e for e in herd if e["id"] not in self.reserved]
        active_ids = {e["id"] for e in explorers}
        # Separate scout and livestock destinations. Never command neutral animals.
        for unit in explorers:
            info = self.report["explorers"].setdefault(str(unit["id"]),
                        dict(type_name=unit["type_name"], start=position(unit), max_displacement=0))
            info["last"] = position(unit)
            info["max_displacement"] = max(info["max_displacement"], distance(unit, info["start"]))
            order = self.orders.get(unit["id"])
            neutral = [e for e in observation["entities"] if e.get("owner") == 0 and is_herd(e)
                       and e.get("access") == "full" and e.get("alive", True)
                       and distance(e, self.tc) <= self.radius]
            capture = min(neutral, key=lambda e: distance(unit, e), default=None) if unit["id"] == self.scout_id else None
            role = "capture" if capture else "explore"
            if order and self.time_ms - order["time"] < 20000 and distance(unit, order["position"]) > 2:
                if capture is None or order["role"] == "capture":
                    continue
            occupied = [v["position"] for uid, v in self.orders.items()
                        if uid in active_ids and uid != unit["id"]]
            target = position(capture) if capture else self.frontier(unit, map_data, occupied)
            if target is not None:
                self.move(unit, target, role)

    def run(self):
        try:
            status = self.bridge.request("status")
            if status.get("state") != "ready" or status.get("information_policy") != "player_view":
                raise BridgeError("Start a single-player match and turn Modules See Everything off")
            self.bridge.request("open", {"client_name": "aoe2-rl-two-house-opening"})
            initial = self.observe()
            self.world = initial["world"]
            self.report.update(world=self.world, initial_game_time_ms=self.time_ms)
            if self.time_ms > 180000 and not self.allow_existing:
                raise BridgeError("Start within three game-minutes, or explicitly use --allow-existing-match")
            # Check that the simulation advances BEFORE any commands are queued.
            previous_time = self.time_ms
            time.sleep(1)
            initial = self.observe()
            if self.time_ms <= previous_time:
                raise BridgeError("Game is paused or not advancing. Unpause with F3, then run again")
            owned = [e for e in initial["entities"] if e.get("owner") == 1
                     and e.get("access") == "full" and e.get("alive") and e.get("commandable")]
            villagers = [e for e in owned if e.get("type_id") in (83, 293) and e.get("idle")]
            self.tc = next((e for e in owned if e.get("type_id") == 109), None)
            scout = next((e for e in owned if e.get("type_id") == 448), None)
            if len(villagers) < 3 or self.tc is None or scout is None:
                raise BridgeError("Need three idle villagers, a standard Town Center and Scout Cavalry")
            if initial["player"]["attributes"][1] < 50:
                raise BridgeError("Need at least 50 wood for two houses")
            self.scout_id = scout["id"]
            self.initial_herd = {e["id"] for e in owned if is_herd(e)}
            self.report.update(town_center=position(self.tc), scout_id=self.scout_id,
                               initial_owned_livestock=sorted(self.initial_herd))
            self.build_houses(initial, villagers)
            initial_map = self.map_data()
            self.report["initial_explored_tiles"] = sum(v > 0 for v in initial_map[2])
            deadline = time.monotonic() + self.seconds
            last_progress, last_time = time.monotonic(), self.time_ms
            while time.monotonic() < deadline:
                observation = self.observe()
                if self.time_ms > last_time:
                    last_progress, last_time = time.monotonic(), self.time_ms
                elif time.monotonic() - last_progress > 15:
                    raise BridgeError("Game stopped advancing for 15 seconds; stopping")
                owned = [e for e in observation["entities"] if e.get("owner") == 1
                         and e.get("access") == "full" and e.get("alive") and e.get("commandable")]
                self.update_houses(observation)
                map_data = self.map_data()
                self.update_livestock(owned, observation, map_data)
                self.report["final_game_time_ms"] = self.time_ms
                self.report["new_explored_tiles"] = (sum(v > 0 for v in map_data[2])
                                                       - self.report["initial_explored_tiles"])
                self.save()
                time.sleep(1)
            self.report["new_livestock_acquired"] = bool(self.report["newly_captured_livestock"])
            self.report["completed"] = (
                len(self.report["houses"]) == 2 and all(h["completed"] for h in self.report["houses"])
                and len(self.report.get("livestock_under_tc", [])) == 2
                and self.report.get("new_explored_tiles", 0) > 0
                and len(self.report["explorers"]) >= 2
                and all(e["max_displacement"] > 3 for e in self.report["explorers"].values())
                and self.report["new_livestock_acquired"])
            self.report["stop_reason"] = "Configured duration reached; last game orders remain active"
        except (BridgeError, KeyError, ValueError, OSError) as exc:
            self.report["error"] = str(exc)
        except KeyboardInterrupt:
            self.report["error"] = "Stopped by user; last issued game orders remain active"
        finally:
            if self.bridge.session:
                try:
                    self.bridge.request("close")
                except BridgeError as exc:
                    self.report["close_error"] = str(exc)
            self.save()
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Issue live game commands")
    parser.add_argument("--seconds", type=int, default=180, help="Scouting duration in real seconds (30-600)")
    parser.add_argument("--radius", type=int, default=40, help="Local scouting radius around TC (15-60 tiles)")
    parser.add_argument("--allow-existing-match", action="store_true", help="Allow a game older than three game-minutes")
    parser.add_argument("--output", default="reports/two-house-opening.json")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Add --execute to build two houses and control villagers, livestock and the scout")
    if not 30 <= args.seconds <= 600 or not 15 <= args.radius <= 60:
        parser.error("--seconds must be 30-600 and --radius must be 15-60")
    report = Opening(args.seconds, args.radius, args.output, args.allow_existing_match).run()
    print(json.dumps({key: report.get(key) for key in
                     ("completed", "new_livestock_acquired", "error", "close_error", "houses",
                      "reserved_livestock", "livestock_under_tc", "newly_captured_livestock",
                      "new_explored_tiles", "stop_reason")}, indent=2))
    print(f"Detailed report: {Path(args.output).resolve()}")
    if report["error"] or report.get("close_error"):
        raise SystemExit(2)
    if not report["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
