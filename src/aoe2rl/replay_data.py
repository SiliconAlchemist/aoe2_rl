"""Offline replay commands and causal history examples; live states are separate."""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import math
from .paths import project_path, recorded_path, portable_path


def digest(path):
    h = hashlib.sha256()
    with recorded_path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path, data):
    project_path(path).write_text(json.dumps(data, indent=2, ensure_ascii=True)+"\n", encoding="utf-8")


def clean(value):
    if isinstance(value, bytes):
        return {"uninterpreted_bytes": len(value)}
    if isinstance(value, dict):
        return {str(k): clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def label_for(action_type, payload):
    """Project only explicit raw fields; no selection cache or omniscient enrichment."""
    kinds = {"BUILD":"build", "MOVE":"move", "ORDER":"target",
             "RESEARCH":"research", "DE_QUEUE":"enqueue", "QUEUE":"enqueue",
             "DE_ATTACK_MOVE":"attack_move", "STOP":"stop", "REPAIR":"repair"}
    if action_type not in kinds:
        return None, "unsupported_action"
    actors = payload.get("object_ids")
    if not actors or any(not isinstance(x, int) or x < 0 for x in actors):
        return None, "unresolved_actor_selection"
    label = dict(kind=kinds[action_type], actors=actors)
    if action_type in ("BUILD", "MOVE", "DE_ATTACK_MOVE"):
        if any(not isinstance(payload.get(k), (int,float)) or not math.isfinite(payload[k]) or payload[k]<0 for k in ("x","y")):
            return None, "invalid_position"
        label["position"] = {"x":payload["x"], "y":payload["y"]}
    for key, name in (("building_id","object_type"), ("unit_id","object_type"),
                      ("technology_id","technology"), ("target_id","target")):
        if key in payload:
            label[name] = payload[key]
    required = {"BUILD":"object_type", "ORDER":"target", "REPAIR":"target",
                "RESEARCH":"technology", "DE_QUEUE":"object_type", "QUEUE":"object_type"}.get(action_type)
    if required and (not isinstance(label.get(required), int) or not 0 <= label[required] < 2**31):
        return None, "invalid_target_or_type"
    if label["kind"] == "enqueue":
        amount = payload.get("amount")
        if not isinstance(amount, int) or amount <= 0:
            return None, "nonpositive_queue_amount"
        label["additional_amount"] = amount
    # Queue/shift flags are not reliably exposed by this parser. Supervise only these heads.
    label["queue_modifier"] = "unknown"
    return label, None


def parse_one(entry, directory, split):
    from mgz import fast
    from mgz.fast.header import decompress, parse_version
    from mgz.model import parse_match
    path = recorded_path(entry["staged_path"])
    sha = digest(path)
    if sha != entry["sha256"]:
        raise ValueError("Replay differs from its intake hash")
    with path.open("rb") as f:
        match = parse_match(f)
    selected = entry.get("selected_player") or 1
    player = next(p for p in match.players if p.number == selected)
    metadata = dict(schema=1, replay_sha256=sha, original_filename=entry["filename"],
                    staged_path=portable_path(path), selected_player=selected, split=split,
                    selected_player_name=player.name, civilization=player.civilization,
                    map_name=match.map.name, map_dimension=match.map.dimension, map_seed=match.map.seed,
                    game_guid=str(match.guid), build=match.build_version, save_version=match.save_version,
                    duration_ms=round(match.duration.total_seconds()*1000), restored=match.restored,
                    restore_time_ms=round(match.restored_at.total_seconds()*1000),
                    cheats=match.cheats, map_reveal=match.map_reveal,
                    players=[dict(slot=p.number,name=p.name,civilization=p.civilization) for p in match.players],
                    outcome_verified=False, parser_winner_inference=player.winner,
                    outcome_note="mgz infers winners from resignations; not an authoritative outcome label",
                    parser=dict(package="mgz",version=importlib.metadata.version("mgz"),
                                header_patch="PR147-two-header-fields", raw_body=True),
                    anchors=[dict(id=o.instance_id,type_id=o.object_id,x=o.position.x,y=o.position.y)
                             for o in player.objects if o.object_id in (109,83,293,448)],
                    state_action_ready=False, observations_captured=False,
                    command_semantics="partial labels; queue modifiers unknown; enqueue amount is incremental")
    directory.mkdir(parents=True, exist_ok=False)
    dump(directory/"metadata.json", metadata)
    counts, exclusions = Counter(), Counter()
    clock = 0
    events = []
    undecoded, unassigned, operation_index = 0, 0, 0
    with path.open("rb") as f:
        header = decompress(f)
        parse_version(header, f)
        fast.meta(f)
        size = path.stat().st_size
        with (directory/"commands.jsonl").open("w",encoding="utf-8") as out:
            while f.tell() < size:
                offset = f.tell()
                try:
                    op, data = fast.operation(f)
                except EOFError as exc:
                    raise ValueError(f"Incomplete operation at byte {offset}; file not certified complete") from exc
                operation_index += 1
                if op == fast.Operation.SYNC:
                    clock += data[0]
                if op != fast.Operation.ACTION:
                    continue
                kind, payload = data
                if kind == fast.Action.ERROR:
                    undecoded += 1
                if payload.get("player_id") is None and kind != fast.Action.POSTGAME:
                    unassigned += 1
                if payload.get("player_id") != selected:
                    continue
                name = kind.name
                counts[name] += 1
                label, reason = label_for(name, payload)
                if reason:
                    exclusions[reason] += 1
                event = dict(command_id=f"{sha}:{selected}:{operation_index}",
                             replay_sha256=sha, player=selected, split=split,
                             timestamp_ms=clock+metadata["restore_time_ms"], operation_index=operation_index,
                             byte_offset=offset, raw_type=name, raw_payload=clean(payload),
                             label=label, label_exclusion=reason, observation=None,
                             state_action_ready=False)
                out.write(json.dumps(event)+"\n")
                events.append(event)
    # Historical context uses only this player's earlier explicit input, never future actions,
    # enemy/header state, chat, the match result, or the target action's timestamp.
    past = []
    examples = 0
    with (directory/"history_examples.jsonl").open("w",encoding="utf-8") as out:
        for event in events:
            if event["label"] and past:
                example = dict(schema=1, task="next_command_prior", replay_sha256=sha, player=selected,
                               split=split, example_id=event["command_id"],
                               input={"past_commands":past[-16:]},
                               target={"label":event["label"],
                                       "delay_since_previous_ms":event["timestamp_ms"]-past[-1]["timestamp_ms"]},
                               reactive_policy_ready=False)
                out.write(json.dumps(example)+"\n")
                examples += 1
            if event["raw_type"] not in ("GAME", "RESIGN", "FLARE", "SPECTATE", "SAVE", "POSTGAME", "AI_ORDER"):
                past.append(dict(timestamp_ms=event["timestamp_ms"], raw_type=event["raw_type"],
                                 payload=event["raw_payload"]))
    metadata.update(command_counts=dict(counts), label_exclusions=dict(exclusions),
                    commands=len(events), partial_labels=sum(e["label"] is not None for e in events),
                    history_examples=examples, undecoded_actions_all_players=undecoded,
                    unassigned_actions_all_players=unassigned, body_end_ms=clock,
                    body_consumed_to_eof=True)
    dump(directory/"metadata.json",metadata)
    return metadata


def extract(manifest_path, output):
    manifest = json.loads(recorded_path(manifest_path).read_text(encoding="utf-8"))
    output = project_path(output)
    output.mkdir(parents=True,exist_ok=False)
    staged = {e["sha256"]:e for e in manifest["recordings"] if e.get("staged_path")}
    # Deterministic whole-file holdout, never a random split of overlapping windows.
    ids = sorted(staged)
    heldout = set(ids[-max(1,len(ids)//5):]) if len(ids)>1 else set()
    summary = dict(schema=1, status="command_examples_only", parsed=[], errors=[],
                   training_ready=False, holdout_policy="last 20 percent of sorted file hashes; whole replay",
                   missing=["player-view replay observations", "causal state/action alignment",
                            "action executor and policy feature schema for full-game imitation"])
    for sha in ids:
        entry = staged[sha]
        try:
            result = parse_one(entry,output/sha,"validation" if sha in heldout else "train")
            summary["parsed"].append({k:result[k] for k in
                       ("replay_sha256","original_filename","selected_player","selected_player_name","civilization",
                        "map_name","map_dimension","game_guid","duration_ms","split","commands","partial_labels",
                        "history_examples","undecoded_actions_all_players","unassigned_actions_all_players")})
            print(json.dumps(summary["parsed"][-1]),flush=True)
        except Exception as exc:
            # Preserve failure per file; never relabel partial data as successful.
            summary["errors"].append(dict(replay_sha256=sha,error=f"{type(exc).__name__}: {exc}"))
            print(json.dumps(summary["errors"][-1]),flush=True)
        dump(output/"summary.json",summary)
    # Group repeated perspectives of a game by GUID as well as byte-identical files.
    by_guid = {}
    for row in summary["parsed"]:
        if row["game_guid"] not in ("None", ""):
            by_guid.setdefault(row["game_guid"],[]).append(row)
    for group in by_guid.values():
        if len({r["split"] for r in group}) > 1:
            # Keep all perspectives in validation rather than leaking a match across splits.
            for row in group:
                if row["split"] != "validation":
                    row["split"] = "validation"
                    folder = output/row["replay_sha256"]
                    for name in ("commands.jsonl","history_examples.jsonl"):
                        p=folder/name
                        records=[json.loads(line) for line in p.read_text().splitlines()]
                        for record in records: record["split"]="validation"
                        p.write_text("".join(json.dumps(r)+"\n" for r in records),encoding="utf-8")
                    p=folder/"metadata.json"
                    meta=json.loads(p.read_text());meta["split"]="validation";dump(p,meta)
    summary["totals"] = {k:sum(r[k] for r in summary["parsed"]) for k in ("commands","partial_labels","history_examples")}
    summary["split_counts"] = dict(Counter(r["split"] for r in summary["parsed"]))
    summary["nonempty_history_split_counts"] = dict(Counter(r["split"] for r in summary["parsed"] if r["history_examples"]))
    dump(output/"summary.json",summary)
    return summary


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",default="data/replays/manifest.json")
    p.add_argument("--output",default="data/replays/extracted-v1")
    args=p.parse_args()
    report=extract(args.manifest,args.output)
    print(json.dumps({k:report[k] for k in ("totals","split_counts","errors","training_ready")},indent=2))
    if report["errors"]: raise SystemExit(2)
