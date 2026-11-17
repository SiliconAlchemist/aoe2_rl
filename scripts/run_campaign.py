"""One bounded local session. Run again to resume; never installs a scheduler."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/campaign.json")
    p.add_argument("--output", default="runs/campaign")
    args = p.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out/"campaign-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"machine_seconds": 0, "completed": [], "config": cfg}
    if state["config"] != cfg:
        raise SystemExit("Campaign configuration changed; use a new output directory")
    if cfg["backend"] == "de":
        for key in ("validation", "train_bank", "evaluation_bank"):
            if not Path(cfg[key]).is_file():
                raise SystemExit(f"Live campaign blocked: missing {cfg[key]}. See docs/LIVE_SETUP.md")
    start = time.perf_counter()
    prior = state["machine_seconds"]
    def remaining():
        elapsed = time.perf_counter()-start
        return min(cfg["nightly_seconds"]-elapsed, cfg["total_machine_seconds"]-prior-elapsed)
    def persist():
        state["machine_seconds"] = prior+time.perf_counter()-start
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2))
        temp.replace(state_path)
    def execute(job, command):
        if job in state["completed"]: return True
        if remaining() <= 1: return False
        print(f"Starting {job}; {remaining()/3600:.2f} session hours left", flush=True)
        try:
            result = subprocess.run([sys.executable, "-m", "aoe2rl.cli", *command], timeout=remaining())
        except subprocess.TimeoutExpired:
            print("Session budget reached. Last completed episode checkpoint is preserved.", flush=True)
            persist()
            return False
        if result.returncode:
            persist()
            raise SystemExit(f"{job} failed. Campaign stopped; failure is not a game result.")
        state["completed"].append(job)
        persist()
        return True
    def common(split):
        options = ["--backend", cfg["backend"], "--device", cfg["device"]]
        if cfg["backend"] == "de":
            options += ["--validation", cfg["validation"], "--save-bank", cfg[f"{split}_bank"]]
        return options
    try:
        if not execute("scripted-evaluation", ["evaluate", *common("evaluation"), "--episodes",
                str(cfg["evaluation_episodes"]), "--output", str(out/"scripted-evaluation.json")]): return
        for algorithm in cfg["algorithms"]:
            for seed in cfg["seeds"]:
                run = out/f"{algorithm}-{seed}"
                command = ["train", *common("train"), "--algorithm", algorithm, "--seed", str(seed),
                           "--seconds", str(cfg["seconds_per_run"]), "--output", str(run)]
                if (run/"checkpoint.pt").exists(): command += ["--resume", str(run/"checkpoint.pt")]
                if not execute(f"train-{algorithm}-{seed}", command): return
                if not execute(f"evaluate-{algorithm}-{seed}", ["evaluate", *common("evaluation"),
                        "--episodes", str(cfg["evaluation_episodes"]), "--checkpoint", str(run/"checkpoint.pt"),
                        "--output", str(run/"evaluation.json")]): return
    finally:
        persist()


if __name__ == "__main__":
    main()
