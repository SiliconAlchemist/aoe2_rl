"""Offline data audit. Reads saved captures only; never connects to DE or trains."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import gzip
import json
import math

from .replay_data import digest, dump
from .replay_examples import read, check_observation, validate_map, visible_input
from .paths import project_path, recorded_path, portable_path


def records(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def nonfinite(value):
    if isinstance(value, float): return not math.isfinite(value)
    if isinstance(value, dict): return any(nonfinite(v) for v in value.values())
    if isinstance(value, list): return any(nonfinite(v) for v in value)
    return False


def effect(label, before, window, player):
    """Post-command evidence is diagnostic only; it never becomes a policy input."""
    actors = set(label["actors"])
    def matching(o):
        if label["kind"] == "build":
            pos = label["position"]
            return any(e.get("owner") == player and e.get("type_id") == label["object_type"]
                       and math.hypot(e.get("x",-999)-pos["x"], e.get("y",-999)-pos["y"]) < .2
                       for e in o["entities"])
        if label["kind"] == "move":
            pos = label["position"]
            return all(any(e.get("id") == actor and any(
                isinstance(e.get(k),dict) and math.hypot(e[k].get("x",-999)-pos["x"], e[k].get("y",-999)-pos["y"]) < .2
                for k in ("target_position","action_target_position")) for e in o["entities"]) for actor in actors)
        if label["kind"] in ("target", "repair"):
            return all(any(e.get("id") == actor and e.get("target_object_id") == label["target"]
                           for e in o["entities"]) for actor in actors)
        if label["kind"] == "enqueue":
            old = {e["id"]:e.get("train_count") for e in before["entities"] if e["id"] in actors}
            return any(e["id"] in actors and isinstance(old.get(e["id"]),(int,float))
                       and isinstance(e.get("train_count"),(int,float)) and e["train_count"] > old[e["id"]]
                       for e in o["entities"])
        return None
    if label["kind"] not in ("build","move","target","repair","enqueue"):
        return dict(status="effect_check_not_implemented")
    if matching(before):
        return dict(status="matching_state_already_present")
    for o in window:
        if matching(o):
            return dict(status="matching_effect_observed", first_effect_ms=o["game_time_ms"])
    return dict(status="no_matching_effect_in_window" if window else "no_unconfounded_after_frame")


def audit(capture_path, paired_path, output):
    folder, paired, output = recorded_path(capture_path), recorded_path(paired_path), project_path(output)
    report = read(folder/"capture.json")
    summary = read(paired/"summary.json")
    meta_path = recorded_path(report["metadata_path"])
    meta = read(meta_path)
    failures = []
    hashes = {"metadata": digest(meta_path) == report["metadata_sha256"],
              "recording": digest(meta["staged_path"]) == report["replay_sha256"],
              "observations": digest(folder/"observations.jsonl.gz") == report["observations_sha256"],
              "commands": digest(meta_path.parent/"commands.jsonl") == summary["commands_sha256"]}
    if not all(hashes.values()): raise ValueError(f"Source hash mismatch: {hashes}")
    obs = records(folder/"observations.jsonl.gz")
    pairs = records(paired/"examples.jsonl.gz")
    commands = [json.loads(line) for line in (meta_path.parent/"commands.jsonl").read_text().splitlines()]
    by_id = {c["command_id"]:c for c in commands}
    command_times = sorted(set(c["timestamp_ms"] for c in commands))
    if not obs: raise ValueError("Capture has no frames")
    times = [o["game_time_ms"] for o in obs]
    if len(obs) != report["frames"]: failures.append("frame_count_mismatch")
    if any(b <= a for a,b in zip(times,times[1:])): failures.append("nonmonotonic_clock")
    visibility = Counter()
    for i,o in enumerate(obs):
        check_observation(o, report["player"], report["world"])
        if i and o["sequence"] <= obs[i-1]["sequence"]: failures.append("nonmonotonic_sequence")
        if nonfinite(o): failures.append("nonfinite_raw_observation")
        enemy = False
        for e in o["entities"]:
            visibility[e.get("access", "missing")] += 1
            if e.get("owner") not in (None,0,report["player"]): enemy = True
            if e.get("access") == "position":
                extra = set(e)-{"id","type_id","class_id","owner","x","y","access"}
                if extra: failures.append("extra_fields_on_position_only_entity")
        visibility["frames_with_other_player_entities"] += int(enemy)
        if any(p.get("id") != report["player"] and "attributes" in p for p in o.get("players", [])):
            failures.append("other_player_resource_attributes_exposed")
    rows = []
    for p in pairs:
        provenance, label = p["provenance"], p["target"]
        c = by_id.get(p["example_id"])
        t = provenance["command_time_ms"]
        j = bisect_left(times,t)-1
        errors = []
        if not c or c["label"] != label or c["timestamp_ms"] != t: errors.append("command_label_mismatch")
        if provenance["replay_sha256"] != report["replay_sha256"] or provenance["player"] != report["player"]:
            errors.append("pair_identity_mismatch")
        if p["split"] != meta["split"]: errors.append("split_mismatch")
        if j < 0 or t-times[j] != provenance["observation_age_ms"] or not 0 < provenance["observation_age_ms"] <= summary["max_age_ms"]:
            errors.append("invalid_causal_alignment")
        elif p["input"] != visible_input(obs[j], rich=p.get("schema",1)>=2): errors.append("input_source_mismatch")
        if nonfinite(p["input"]): errors.append("nonfinite_model_input")
        row = dict(example_id=p["example_id"], kind=label["kind"], command_time_ms=t,
                   observation_age_ms=provenance["observation_age_ms"], structural_errors=errors)
        if j >= 0:
            next_index = bisect_right(command_times,t)
            next_command = command_times[next_index] if next_index < len(command_times) else math.inf
            end = min(t+1500, next_command)
            window = [o for o in obs[bisect_left(times,t):bisect_left(times,end)]]
            row.update(effect(label, obs[j], window, report["player"]))
            row["after_window_exclusive_end_ms"] = end
            if "first_effect_ms" in row: row["effect_delay_ms"] = row["first_effect_ms"]-t
            if label["kind"] == "enqueue":
                row["food_before"] = obs[j]["player"]["attributes"][0]
                row["producer_queues_before"] = {str(e["id"]):e.get("train_count") for e in obs[j]["entities"] if e["id"] in label["actors"]}
        failures.extend(errors)
        rows.append(row)
    map_count, exact_maps = 0, 0
    if report.get("visibility_sha256"):
        mp = folder/"visibility.jsonl.gz"
        if digest(mp) != report["visibility_sha256"]: raise ValueError("Visibility file hash mismatch")
        for row in records(mp):
            data = row["map"]
            validate_map(data, meta["map_dimension"])
            if data["world"] != report["world"] or not row["before_sequence"] <= data["sequence"] <= row["after_sequence"]:
                failures.append("map_bracket_mismatch")
            if row["before_time_ms"] > row["after_time_ms"]: failures.append("map_clock_reversed")
            map_count += 1
            exact_maps += int(row["before_time_ms"]==row["after_time_ms"])
    gaps = [b-a for a,b in zip(times,times[1:])]
    stats = dict(schema=1, capture=portable_path(folder), pairs=portable_path(paired), hashes=hashes,
                 frames=len(obs), examples=len(pairs), failures=dict(Counter(failures)),
                 structural_checks_passed=not failures, kinds=dict(Counter(p["target"]["kind"] for p in pairs)),
                 effect_results=dict(Counter(r.get("status","invalid") for r in rows)),
                 effect_results_by_kind={k:dict(Counter(r.get("status","invalid") for r in rows if r["kind"]==k)) for k in sorted({r["kind"] for r in rows})},
                 observation_gaps_ms=dict(min=min(gaps) if gaps else None,max=max(gaps) if gaps else None,
                                          mean=sum(gaps)/len(gaps) if gaps else None),
                 visibility=dict(visibility), maps=map_count, paused_map_brackets=exact_maps,
                 alignment_verified=False, fog_implementation_verified=False, training_ready=False,
                 caveats=["A recorded command can be an unsuccessful attempt.",
                          "No observed effect is not proof of failure; queue completion, delayed execution and sampling can hide it.",
                          "Effects are searched only before the next player command and for at most 1500ms.",
                          "Map masking checks are not independent verification of game visibility.",
                          "Future effects are diagnostic evidence only, never model inputs."])
    output.mkdir(parents=True, exist_ok=False)
    dump(output/"summary.json",stats)
    dump(output/"example-review.json",rows)
    text = ("# Saved replay sample audit\n\n"
            f"Frames: {len(obs)}. Examples: {len(pairs)}. Structural failures: {len(failures)}.\n\n"
            "| Kind | Effect evidence | Count |\n|---|---|---:|\n")
    for k,counts in stats["effect_results_by_kind"].items():
        for state,count in counts.items(): text += f"| {k} | {state} | {count} |\n"
    text += ("\nNo training-readiness flag was enabled. Review example-review.json for exact timestamps and queue evidence.\n\n"
             "Manual visibility check: in Player 1 normal-fog replay view, confirm the enemy base is hidden. "
             "For the Arena pilot compare the house order around 00:06.430 at (15,55) and livestock move around "
             "00:15.764 toward (13.708,46.792). A later capture must include an enemy entering and leaving sight. "
             "The original pilot contains no map visibility snapshots, so Gaia visibility cannot be certified from it.\n")
    (output/"review.md").write_text(text,encoding="utf-8")
    print(json.dumps(stats,indent=2))
    return stats


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture", required=True)
    p.add_argument("--paired", required=True)
    p.add_argument("--output", required=True)
    a=p.parse_args()
    result=audit(a.capture,a.paired,a.output)
    if result["failures"]: raise SystemExit(2)
