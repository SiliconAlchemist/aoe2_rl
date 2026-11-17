"""Move one villager and build one house in an explicitly selected test world."""
import argparse
import json
import math
import time
from pathlib import Path
from aoe2rl.agent_bridge import AgentBridge
from aoe2rl.core import BridgeError


def run(world, output):
    bridge = AgentBridge()
    report = dict(world=world, movement_verified=False, house_completed=False,
                  training_validated=False, samples=[], error=None)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    def save(): target.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    def observe(types="none"):
        o = bridge.request("observe", {"object_types": types, "technologies": "none"})
        if o["world"] != world or o["information_policy"] != "player_view" or o["match"]["replay"]:
            raise BridgeError("Wrong world, replay or information policy; stopping")
        return o
    def actor(o, unit_id):
        return next(e for e in o["entities"] if e["id"] == unit_id)
    def act(command, args):
        result = bridge.request("act", {"world": world, "actions": [{"command": command, "args": args}]})
        report.setdefault("actions", []).append(dict(command=command, args=args, response=result))
        save()
        if not result.get("results") or result["results"][0]["status"] not in ("executed", "queued"):
            raise BridgeError(f"Command was not accepted: {result}")
    try:
        bridge.request("open", {"client_name": "aoe2-rl-disposable-smoke"})
        first = observe("relevant")
        if first["game_time_ms"] > 600000:
            raise BridgeError("Use a fresh disposable match under ten game-minutes old")
        report["initial_time_ms"] = first["game_time_ms"]
        own = [e for e in first["entities"] if e.get("owner") == 1 and e.get("alive") and e.get("access") == "full"]
        villager = next(e for e in own if e.get("type_id") in (83, 293) and e.get("idle") and e.get("commandable"))
        unit_id = villager["id"]
        report["villager_before"] = villager
        house = next(t for t in first["object_types"] if t.get("base_id", t["id"]) == 70 and t.get("available") and t.get("can_afford"))
        positions = [{"x": math.floor(villager["x"])+dx, "y": math.floor(villager["y"])+dy}
                     for dx, dy in [(3,0),(-3,0),(0,3),(0,-3),(4,4),(-4,4),(4,-4),(-4,-4)]]
        positions = [p for p in positions if 1 <= p["x"] < first["match"]["map_width"]-1 and 1 <= p["y"] < first["match"]["map_height"]-1]
        placement = bridge.request("query", {"kind": "placement", "object_type": house["id"], "positions": positions})
        report["placement_query"] = dict(positions=positions, response=placement)
        save()
        position = next(p for p, result in zip(positions, placement["results"]) if result["name"] == "CAN_PLACE")
        report["chosen_position"] = position
        act("gameplay.move.v1", {"actors": [unit_id], "position": position})
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            time.sleep(.5)
            o = observe()
            unit = actor(o, unit_id)
            if math.hypot(unit["x"]-villager["x"], unit["y"]-villager["y"]) > .5:
                report["movement_verified"] = True
                report["villager_after_move"] = unit
                report["move_observed_time_ms"] = o["game_time_ms"]
                break
        if not report["movement_verified"]:
            raise BridgeError("No measured villager movement within 15 seconds")
        before_ids = {e["id"] for e in o["entities"]}
        act("gameplay.build.v1", {"actors": [unit_id], "object_type": house["id"], "position": position})
        deadline = time.monotonic()+50
        while time.monotonic() < deadline:
            time.sleep(.5)
            o = observe()
            candidates = [e for e in o["entities"] if e["id"] not in before_ids and e.get("owner") == 1
                          and e.get("type_id") == house["id"] and math.hypot(e["x"]-position["x"], e["y"]-position["y"]) < 2]
            if candidates:
                building = candidates[0]
                report["samples"].append(dict(game_time_ms=o["game_time_ms"], building=building))
                if building.get("status") == 2 and building.get("hitpoints", 0) > 0:
                    report["house_completed"] = True
                    report["final_resources"] = o["player"]["attributes"][:4]
                    break
        if not report["house_completed"]:
            raise BridgeError("House completion not observed within 50 seconds")
    except (BridgeError, KeyError, StopIteration) as exc:
        report["error"] = str(exc) or "Required villager, house type or placement was unavailable"
    finally:
        if bridge.session:
            try: bridge.request("close")
            except BridgeError as exc: report["close_error"] = str(exc)
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", type=int, required=True)
    parser.add_argument("--execute", action="store_true", help="Actually command a villager in the selected disposable match")
    parser.add_argument("--output", default="reports/native-control-smoke.json")
    args = parser.parse_args()
    if not args.execute: parser.error("--execute is required: this test moves a unit and spends wood on a house")
    result = run(args.world, args.output)
    print(json.dumps({k:v for k,v in result.items() if k in ("world", "movement_verified", "house_completed", "error", "close_error")}, indent=2))
    if result["error"] or result.get("close_error"): raise SystemExit(2)
