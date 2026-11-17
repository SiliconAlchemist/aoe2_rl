"""Catalogue local AoE II recordings and copy a build-matched starter set.

This imports files only: it does not parse game state, launch DE or train a model.
Build labels are read from filenames and are not a playback compatibility check.
"""
import argparse
import hashlib
import json
import re
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from aoe2rl.paths import project_path, portable_path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest(source, output, build, player=None):
    source, output = Path(source).resolve(), project_path(output).resolve()
    if not source.is_dir():
        raise ValueError(f"Recording folder does not exist: {source}")
    if output == source or source in output.parents:
        raise ValueError("Keep the imported dataset outside the original game folder")
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(source.rglob("*.aoe2record")):
        before = path.stat()
        match = re.search(r"Replay v([\d.]+) @", path.name)
        label = match.group(1) if match else None
        entry = dict(source_path=str(path), filename=path.name, size_bytes=before.st_size,
                     modified_utc=datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat(),
                     filename_build=label, playback_verified=False, parsed=False,
                     training_ready=False, selected_player=player,
                     status="catalogued_only", staged_path=None, sha256=None)
        if label == build:
            temporary = raw / (uuid.uuid4().hex + ".partial")
            try:
                shutil.copyfile(path, temporary)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Source changed during copy; import again after recording finishes")
                digest = sha256(temporary)
                if sha256(path) != digest:
                    raise ValueError("Copied bytes differ from source; import again")
                target = raw / (digest + ".aoe2record")
                if target.exists():
                    if sha256(target) != digest:
                        raise ValueError("Existing staged file has an unexpected hash")
                else:
                    temporary.replace(target)
                entry.update(status="staged_filename_build_match", staged_path=portable_path(target), sha256=digest)
            except (OSError, ValueError) as exc:
                entry.update(status="import_error", error=str(exc))
            finally:
                if temporary.exists():
                    temporary.unlink()
        entries.append(entry)
    staged = [e for e in entries if e["staged_path"]]
    summary = dict(total_recordings=len(entries), total_bytes=sum(e["size_bytes"] for e in entries),
                   filename_build_counts=dict(Counter(e["filename_build"] or "unknown" for e in entries)),
                   staged_recordings=len(staged), unique_staged_recordings=len({e["sha256"] for e in staged}),
                   staged_source_bytes=sum(e["size_bytes"] for e in staged),
                   import_errors=sum(e["status"] == "import_error" for e in entries))
    manifest = dict(schema=1, imported_at=datetime.now(timezone.utc).isoformat(),
                    source_root=str(source), selected_filename_build=build,
                    selected_player=player,
                    selected_player_status="provisional_slot; identity_and_quality_unassessed" if player else "awaiting_selection",
                    compatibility="filename_match_only; replay playback not checked",
                    parsed=False, training_ready=False, summary=summary, recordings=entries)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        backup = output / ("manifest.previous." + uuid.uuid4().hex + ".json")
        shutil.copyfile(manifest_path, backup)
    manifest_path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--output", default="data/replays")
    parser.add_argument("--player", type=int, choices=range(1, 9), help="Provisional in-game player slot")
    args = parser.parse_args()
    result = ingest(args.source, args.output, args.build, args.player)
    print(json.dumps(result, indent=2))
    if result["import_errors"]:
        raise SystemExit(2)
