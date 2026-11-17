import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign")
    parser.add_argument("--output", default="reports/campaign-summary.json")
    args = parser.parse_args()
    root = Path(args.campaign)
    state = json.loads((root/"campaign-state.json").read_text())
    groups = {}
    for path in sorted(root.glob("*/evaluation.json")):
        result = json.loads(path.read_text())
        algorithm, seed = path.parent.name.rsplit("-", 1)
        groups.setdefault(algorithm, []).append(dict(seed=int(seed), counts=result["counts"],
            win_rate=result["win_rate"], complete=result["completed_episodes"] == result["requested_episodes"],
            valid_strength_result=result["valid_strength_result"], report=str(path)))
    summary = dict(backend=state["config"]["backend"],
        evidence="software_fixture_only" if state["config"]["backend"] == "synthetic" else "de_combat_pilot",
        machine_seconds=state["machine_seconds"], completed_jobs=len(state["completed"]),
        algorithms={name: {"runs": runs, "mean_win_rate": statistics.mean(
            r["win_rate"] for r in runs if r["win_rate"] is not None)} for name, runs in groups.items()})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2))
    print(json.dumps({"backend": summary["backend"], "completed_jobs": summary["completed_jobs"],
                      "summary": str(output)}, indent=2))


if __name__ == "__main__":
    main()
