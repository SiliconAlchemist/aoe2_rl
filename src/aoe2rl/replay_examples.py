"""Read-only replay capture and conservative, provisional state/action pairing."""
import argparse
import base64
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
import math
from contextlib import ExitStack
import time

from .replay_data import digest, dump
from .paths import project_path, recorded_path, portable_path


def read(path):
    return json.loads(recorded_path(path).read_text(encoding="utf-8"))


def metadata_path(value):
    if value:
        return recorded_path(value)
    manifest = read("data/replays/manifest.json")
    sha = manifest["initial_conversion_candidate"]["sha256"]
    return project_path("data/replays/extracted-v1") / sha / "metadata.json"


def check_observation(o, player, world=None):
    if o.get("information_policy") != "player_view":
        raise ValueError("Expected player_view. Turn See Everything off.")
    if o.get("match", {}).get("replay") is not True:
        raise ValueError("Only replay playback is allowed; this is not a replay.")
    if o.get("player", {}).get("id") != player:
        raise ValueError("Observation is for a different player.")
    if o.get("world") is None or (world is not None and o["world"] != world):
        raise ValueError("Replay world changed; restart capture from the beginning.")
    t = o.get("game_time_ms")
    if not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
        raise ValueError("Invalid game clock.")


def check_start(o, meta):
    check_observation(o, meta["selected_player"])
    if meta["restored"]:
        raise ValueError("Restored recordings need a separately verified clock mapping.")
    if not 0 <= o["game_time_ms"] <= 5000:
        raise ValueError("Load the replay from the beginning and pause within 5 game seconds.")
    if any(o["match"].get(k) != meta["map_dimension"] for k in ("map_width", "map_height")):
        raise ValueError("Replay map dimensions differ from the selected recording.")
    owned = {e["id"]: e for e in o.get("entities", [])
             if e.get("owner") == meta["selected_player"] and e.get("access") == "full"}
    matched, tc = [], False
    for anchor in meta["anchors"]:
        e = owned.get(anchor["id"], {})
        if e.get("type_id") == anchor["type_id"]:
            matched.append(anchor["id"])
            if anchor["type_id"] == 109:
                tc = math.hypot(e.get("x", -999)-anchor["x"], e.get("y", -999)-anchor["y"]) < .1
    if len(matched) < 3 or not tc:
        expected_tc = [a for a in meta["anchors"] if a["type_id"] == 109]
        observed_tc = [{k: e.get(k) for k in ("id", "type_id", "x", "y")}
                       for e in owned.values() if e.get("type_id") == 109]
        raise ValueError(
            f"Replay identity mismatch: expected {meta['original_filename']} "
            f"(Player {meta['selected_player']}: {meta['selected_player_name']}); "
            f"observed player name {o['player'].get('name')!r}. "
            f"Matching starting IDs/types: {matched}; "
            f"expected TC {expected_tc}; observed TC {observed_tc}. "
            "Load the expected recording or use --metadata for the recording you loaded. "
            "See initial-observation.json in the capture folder. Do not bypass the identity check.")
    return matched


def capture(args):
    from .agent_bridge import AgentBridge
    from .core import BridgeError
    path = metadata_path(args.metadata)
    meta = read(path)
    if not args.confirm_replay:
        raise ValueError("Load " + meta["original_filename"] + "; then pass --confirm-replay.")
    if digest(meta["staged_path"]) != meta["replay_sha256"]:
        raise ValueError("Staged recording hash differs from metadata.")
    folder = project_path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(schema=2, replay_sha256=meta["replay_sha256"], player=meta["selected_player"],
                  metadata_path=portable_path(path), metadata_sha256=digest(path),
                  original_filename=meta["original_filename"], user_confirmed_replay=True,
                  created_at=datetime.now(timezone.utc).isoformat(), status="starting", frames=0,
                  alignment_verified=False, fog_implementation_verified=False,
                  note="Identity is user attestation plus starting-unit checks, not a game-provided replay hash.")
    report.update(mode="full_replay" if args.full_replay else "bounded",
                  map_frames=0, interval_seconds=args.interval, map_every_seconds=args.map_every,
                  observation_gaps_ms={"count": 0, "total": 0, "max": 0, "over_250": 0})
    bridge = AgentBridge(meta["selected_player"])
    error = None
    try:
        status = bridge.request("status")
        if status.get("player_id") != meta["selected_player"] or status.get("information_policy") != "player_view":
            raise ValueError("Enable the selected player's bridge and disable See Everything.")
        opened = bridge.request("open", {"client_name": "aoe2rl-replay-recorder"})
        if opened.get("information_policy") != "player_view":
            raise ValueError("Session is not player_view.")
        o = bridge.request("observe", {"object_types": "none", "technologies": "none"})
        # Retain the evidence even if the identity check fails before the first frame.
        dump(folder/"initial-observation.json", o)
        report["initial_observation_path"] = portable_path(folder/"initial-observation.json")
        report["observed_player_name"] = o.get("player", {}).get("name")
        report["expected_player_name"] = meta["selected_player_name"]
        report["initial_game_time_ms"] = o.get("game_time_ms")
        report["matched_anchor_ids"] = check_start(o, meta)
        report.update(world=o["world"], first_game_time_ms=o["game_time_ms"], status="capturing")
        endpoint = meta.get("body_end_ms", meta["duration_ms"]) + meta.get("restore_time_ms", 0)
        target = endpoint if args.full_replay else min(endpoint, o["game_time_ms"]+args.seconds*1000)
        if target <= o["game_time_ms"]:
            raise ValueError("The recording ends before the requested capture can begin.")
        wall_limit = args.wall_seconds or max(600, (target-o["game_time_ms"])/1000*3+120)
        report.update(target_game_time_ms=target, recorded_endpoint_ms=endpoint, wall_limit_seconds=wall_limit)
        dump(folder/"capture.json", report)
        print(f"Replay identity checks passed. Unpause now; recording observations only until "
              f"game time {target/1000:.1f}s. Playback will keep running when capture stops.", flush=True)
        started = last_advance = last_progress = last_status = time.monotonic()
        next_poll = started
        last_map = -math.inf
        previous = -1
        with ExitStack() as stack:
            out = stack.enter_context(gzip.open(folder/"observations.jsonl.gz", "wt", encoding="utf-8"))
            maps = stack.enter_context(gzip.open(folder/"visibility.jsonl.gz", "wt", encoding="utf-8")) if args.map_every else None
            while True:
                check_observation(o, meta["selected_player"], report["world"])
                t = o["game_time_ms"]
                if t < previous:
                    raise ValueError("Replay clock went backwards; seeking is not supported.")
                if t > previous:
                    out.write(json.dumps(o)+"\n")
                    if previous >= 0:
                        gap = t-previous
                        gaps = report["observation_gaps_ms"]
                        gaps.update(count=gaps["count"]+1, total=gaps["total"]+gap,
                                    max=max(gaps["max"], gap), over_250=gaps["over_250"]+int(gap>250))
                    report["frames"] += 1
                    report["last_game_time_ms"] = t
                    previous, last_advance = t, time.monotonic()
                if t >= target:
                    report.update(status="complete", stop_reason="recorded_endpoint_reached" if target==endpoint else "requested_duration_reached")
                    break
                now = time.monotonic()
                # Never treat a stalled clock, an expired session or a closed game as a win.
                if now-last_status >= 1:
                    current_status = bridge.request("status")
                    last_status = time.monotonic()
                    result = current_status.get("last_result")
                    if isinstance(result, dict) and result.get("world") == report["world"]:
                        report.update(status="complete", stop_reason="bridge_reported_replay_end",
                                      bridge_last_result=result, outcome_verified=False)
                        break
                if now-started > wall_limit:
                    raise TimeoutError("Wall-time limit reached; capture is partial.")
                if now-last_advance > 60:
                    raise TimeoutError("Replay clock has not advanced for 60 seconds.")
                if now-last_progress >= 10:
                    out.flush()
                    if maps: maps.flush()
                    report["elapsed_wall_seconds"] = round(now-started, 2)
                    dump(folder/"capture.json", report)
                    print(f"Captured {report['frames']} frames; game {t/1000:.1f}/{target/1000:.1f}s; "
                          f"largest frame gap {report['observation_gaps_ms']['max']}ms.", flush=True)
                    last_progress = now
                if maps and now-last_map >= args.map_every:
                    # Map has no clock. Bracket it with observations and retain it separately.
                    # Never attach this newer map to the earlier observation/model input.
                    map_data = bridge.request("map")
                    next_poll = time.monotonic()+args.interval
                    after = bridge.request("observe", {"object_types": "none", "technologies": "none"})
                    check_observation(after, meta["selected_player"], report["world"])
                    if after["game_time_ms"] < t or map_data.get("world") != report["world"]:
                        raise ValueError("World or clock changed during map capture.")
                    validate_map(map_data, meta["map_dimension"])
                    if not o["sequence"] <= map_data["sequence"] <= after["sequence"]:
                        raise ValueError("Map sequence is outside its observation brackets.")
                    maps.write(json.dumps(dict(before_time_ms=t, after_time_ms=after["game_time_ms"],
                                               before_sequence=o["sequence"], after_sequence=after["sequence"],
                                               information_policy="player_view", map=map_data))+"\n")
                    report["map_frames"] += 1
                    last_map = time.monotonic()
                    o = after
                else:
                    time.sleep(max(0, next_poll-time.monotonic()))
                    next_poll = time.monotonic()+args.interval
                    o = bridge.request("observe", {"object_types": "none", "technologies": "none"})
    except (Exception, KeyboardInterrupt) as exc:
        result = None
        if isinstance(exc, BridgeError) and report.get("world") is not None:
            try:
                result = bridge.request("status").get("last_result")
            except Exception:
                pass
        if isinstance(result, dict) and result.get("world") == report["world"]:
            report.update(status="complete", stop_reason="bridge_reported_replay_end",
                          bridge_last_result=result, outcome_verified=False, final_observe_error=str(exc))
        else:
            error = f"{type(exc).__name__}: {exc}"
            report.update(status="incomplete", error=error)
    finally:
        if bridge.session:
            try:
                bridge.request("close")
            except Exception as exc:
                report["close_error"] = str(exc)
        observations = folder/"observations.jsonl.gz"
        if observations.exists():
            report["observations_sha256"] = digest(observations)
        if (folder/"visibility.jsonl.gz").exists():
            report["visibility_sha256"] = digest(folder/"visibility.jsonl.gz")
        dump(folder/"capture.json", report)
    print(json.dumps(report, indent=2))
    if report["status"] == "complete":
        print("Capture finished. Replay playback is unchanged; you can pause or close DE now.", flush=True)
    if error:
        raise SystemExit(2)


def validate_map(data, dimension):
    if data.get("encoding") != "base64-u8" or data.get("width") != dimension or data.get("height") != dimension:
        raise ValueError("Unexpected map encoding or dimensions.")
    arrays = {k: base64.b64decode(data[k], validate=True) for k in ("terrain", "elevation", "visibility", "passable")}
    if any(len(v) != dimension*dimension for v in arrays.values()):
        raise ValueError("Map arrays do not match dimensions.")
    if any(v not in (0,1,2) for v in arrays["visibility"]):
        raise ValueError("Unknown visibility value.")
    if any(v == 0 and (arrays["terrain"][i] != 255 or arrays["elevation"][i] != 255 or arrays["passable"][i] != 0)
           for i,v in enumerate(arrays["visibility"])):
        raise ValueError("Unexplored map tiles expose terrain/elevation/passability.")
    return arrays


def visible_input(o, rich=False):
    # No header state, outcome, replay identity, or asynchronous map response is a model input.
    fields = ("id", "type_id", "owner", "access", "alive", "x", "y", "hitpoints", "max_hitpoints")
    if rich:
        own_fields = ("idle", "moving", "garrison_object_id", "carry_resource", "carry_amount",
                      "train_count", "researching", "progress_type", "progress_value", "status", "commandable")
        entities = []
        for e in o.get("entities", []):
            if e.get("access") not in ("full", "position"): continue
            allowed = ("id", "type_id", "owner", "access", "x", "y") if e["access"] == "position" else fields
            if e.get("owner") == o["player"]["id"] and e["access"] == "full": allowed += own_fields
            entities.append({k:e[k] for k in allowed if k in e})
        # Restrict resource features to the four documented balances; do not train on
        # unreviewed engine counters/facts, which contain sentinel values in this capture.
        attributes = o["player"].get("attributes", [])
        return dict(game_time_ms=o["game_time_ms"],
                    player=dict(id=o["player"]["id"], resources=dict(zip(("food","wood","stone","gold"),attributes[:4])),
                                current_age=o["player"].get("current_age"),
                                housing_headroom=o["player"].get("housing_headroom")), entities=entities)
    return dict(game_time_ms=o["game_time_ms"],
                player={"id": o["player"]["id"], "attributes": o["player"].get("attributes", {})},
                entities=[{k: e[k] for k in fields if k in e}
                          for e in o.get("entities", []) if e.get("access") in ("full", "position")])


def join(args):
    folder = recorded_path(args.capture)
    report = read(folder/"capture.json")
    if report["status"] != "complete":
        raise ValueError("Capture is incomplete. Keep it for diagnosis and capture again to a new folder.")
    path = recorded_path(report["metadata_path"])
    meta = read(path)
    if digest(path) != report["metadata_sha256"] or meta["replay_sha256"] != report["replay_sha256"]:
        raise ValueError("Capture provenance does not match replay metadata.")
    if report["player"] != meta["selected_player"] or not report.get("matched_anchor_ids"):
        raise ValueError("Missing player or starting-unit identity checks.")
    source = folder/"observations.jsonl.gz"
    if digest(source) != report["observations_sha256"]:
        raise ValueError("Observations have changed since capture.")
    with gzip.open(source, "rt", encoding="utf-8") as f:
        observations = [json.loads(line) for line in f]
    times = []
    for o in observations:
        check_observation(o, meta["selected_player"], report["world"])
        if times and o["game_time_ms"] <= times[-1]:
            raise ValueError("Observation clocks must be strictly increasing.")
        times.append(o["game_time_ms"])
    if not times:
        raise ValueError("No observation frames.")
    commands = [json.loads(line) for line in (path.parent/"commands.jsonl").read_text().splitlines()]
    if any(c["replay_sha256"] != meta["replay_sha256"] or c["player"] != meta["selected_player"] for c in commands):
        raise ValueError("Commands are for a different replay or player.")
    if any(a["timestamp_ms"] > b["timestamp_ms"] for a,b in zip(commands,commands[1:])):
        raise ValueError("Commands are not in clock order.")
    counts = Counter(c["timestamp_ms"] for c in commands)
    exclusions = Counter()
    output = project_path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    accepted = 0
    with gzip.open(output/"examples.jsonl.gz", "wt", encoding="utf-8") as out:
        for i, c in enumerate(commands):
            t, label = c["timestamp_ms"], c["label"]
            j = bisect_left(times, t)-1  # Strictly earlier; never use the command's own tick.
            reason = None
            if not label:
                reason = c["label_exclusion"]
            elif counts[t] > 1:
                reason = "simultaneous_commands"
            elif j < 0 or t > times[-1]:
                reason = "outside_capture"
            elif t-times[j] > args.max_age_ms:
                reason = "observation_too_old"
            elif i and commands[i-1]["timestamp_ms"] >= times[j]:
                reason = "intervening_or_same_tick_command"
            else:
                o = observations[j]
                entities = {e["id"]: e for e in o.get("entities", [])}
                if any(entities.get(a, {}).get("owner") != c["player"] or
                       entities.get(a, {}).get("access") != "full" or
                       not entities.get(a, {}).get("alive") for a in label["actors"]):
                    reason = "actor_not_observed_owned_alive"
                elif "target" in label and entities.get(label["target"], {}).get("access") not in ("full", "position"):
                    reason = "target_not_known"
                elif "position" in label and any(not 0 <= label["position"][k] < meta["map_dimension"] for k in ("x", "y")):
                    reason = "position_outside_map"
            if reason:
                exclusions[reason] += 1
                continue
            row = dict(schema=2, example_id=c["command_id"], split=meta["split"],
                       input=visible_input(observations[j], rich=True), target=label,
                       provenance=dict(replay_sha256=meta["replay_sha256"], player=c["player"],
                                       command_time_ms=t, observation_age_ms=t-times[j]),
                       usable_for="provisional_partial_action_supervision", alignment_verified=False,
                       label_semantics="recorded_command_attempt", execution_verified=False,
                       queue_modifier_supervised=False, executable_policy_ready=False)
            out.write(json.dumps(row)+"\n")
            accepted += 1
    grouped = write_groups(output, commands, observations, times, meta, args.max_age_ms)
    in_window = [c for c in commands if times[0] < c["timestamp_ms"] <= times[-1]]
    summary = dict(schema=2, examples=accepted, rejected=dict(exclusions), commands=len(commands),
                   commands_in_capture_window=len(in_window),
                   unresolved_in_capture_window=sum(c["label_exclusion"]=="unresolved_actor_selection" for c in in_window),
                   grouped=grouped, input_schema="player_resources_and_owned_activity_v2",
                   label_semantics="recorded_command_attempt; execution is not guaranteed",
                   replay_sha256=meta["replay_sha256"], split=meta["split"],
                   capture_report=portable_path(folder/"capture.json"), max_age_ms=args.max_age_ms,
                   commands_sha256=digest(path.parent/"commands.jsonl"),
                   alignment_verified=False, training_ready=False,
                   missing=["live clock/fog audit", "full-game policy and executor integration"],
                   limitations=["partial action labels", "unknown queue modifiers", "no terrain features",
                                "no no-op sampling", "no verified outcome labels"])
    dump(output/"summary.json", summary)
    print(json.dumps(summary, indent=2))


def write_groups(output, commands, observations, times, meta, max_age):
    """Retain ordered same-tick labels against one preceding state, with explicit masks.

    Incomplete groups must not be taught as a complete action sequence or a no-op.
    This is a separate dataset, never additional independent single-action rows.
    """
    from itertools import groupby
    report = dict(groups=0, complete_groups=0, partial_groups=0, simultaneous_groups=0,
                  supervised_commands=0, skipped={})
    skipped = Counter()
    previous_time = -1
    with gzip.open(output/"command_groups.jsonl.gz", "wt", encoding="utf-8") as out:
        for t, records in groupby(commands, key=lambda c:c["timestamp_ms"]):
            batch = list(records)
            j = bisect_left(times, t)-1
            reason = None
            if j < 0 or t > times[-1]: reason = "outside_capture"
            elif t-times[j] > max_age: reason = "observation_too_old"
            elif previous_time >= times[j]: reason = "intervening_or_same_tick_command"
            previous_time = t
            if reason:
                skipped[reason] += 1
                continue
            entities = {e["id"]:e for e in observations[j]["entities"]}
            targets = []
            for c in batch:
                label, why = c["label"], c["label_exclusion"]
                if label:
                    if any(entities.get(a,{}).get("owner") != meta["selected_player"] or
                           entities.get(a,{}).get("access") != "full" or not entities.get(a,{}).get("alive")
                           for a in label["actors"]): why = "actor_not_observed_owned_alive"
                    elif "target" in label and entities.get(label["target"],{}).get("access") not in ("full","position"):
                        why = "target_not_known"
                    elif "position" in label and any(not 0 <= label["position"][k] < meta["map_dimension"] for k in ("x","y")):
                        why = "position_outside_map"
                targets.append(dict(command_id=c["command_id"], label=label if not why else None,
                                    supervised=label is not None and why is None, exclusion=why))
            count = sum(x["supervised"] for x in targets)
            if not count:
                skipped["no_supervisable_commands"] += 1
                continue
            complete = count == len(targets)
            out.write(json.dumps(dict(schema=2, task="same_tick_command_group", split=meta["split"],
                                      input=visible_input(observations[j], rich=True), targets=targets,
                                      all_commands_labeled=complete, queue_modifiers_known=False,
                                      label_semantics="recorded_command_attempt", execution_verified=False,
                                      train_sequence_stop=False, alignment_verified=False,
                                      provenance=dict(replay_sha256=meta["replay_sha256"], player=meta["selected_player"],
                                                      command_time_ms=t, observation_age_ms=t-times[j])))+"\n")
            report["groups"] += 1
            report["complete_groups" if complete else "partial_groups"] += 1
            report["simultaneous_groups"] += int(len(batch)>1)
            report["supervised_commands"] += count
    report["skipped"] = dict(skipped)
    return report


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number")
    return number


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)
    cap = sub.add_parser("capture", help="Observe replay only; never issues game commands")
    cap.add_argument("--metadata", help="Default: intake's initial conversion candidate")
    cap.add_argument("--confirm-replay", action="store_true", help="Confirm the named replay was loaded")
    cap.add_argument("--output", default="data/replays/captures/first-v1")
    duration = cap.add_mutually_exclusive_group()
    duration.add_argument("--seconds", type=positive, default=180, help="Game seconds to collect")
    duration.add_argument("--full-replay", action="store_true", help="Collect to parsed endpoint or bridge-reported end")
    cap.add_argument("--wall-seconds", type=positive, help="Default: at least 600s, scaled for requested duration")
    cap.add_argument("--map-every", type=float, default=5, help="Wall seconds between diagnostic maps; 0 disables")
    cap.add_argument("--interval", type=positive, default=.1, help="Wall seconds between observations")
    paired = sub.add_parser("join", help="Pair commands with strictly earlier observations")
    paired.add_argument("--capture", default="data/replays/captures/first-v1")
    paired.add_argument("--output", default="data/replays/paired/first-v1")
    paired.add_argument("--max-age-ms", type=positive, default=250)
    args = p.parse_args()
    if args.operation == "capture" and (not math.isfinite(args.map_every) or args.map_every < 0):
        p.error("--map-every must be finite and nonnegative")
    try:
        (capture if args.operation == "capture" else join)(args)
    except Exception as exc:
        p.exit(2, f"{type(exc).__name__}: {exc}\n")
