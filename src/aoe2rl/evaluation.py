import json
import math
import time
from pathlib import Path
import numpy as np
import psutil
from .core import BridgeError, teacher


def wilson(wins, games):
    if not games:
        return [None, None]
    p, z = wins/games, 1.959963984540054
    denominator = 1 + z*z/games
    centre = (p+z*z/(2*games))/denominator
    radius = z*math.sqrt(p*(1-p)/games+z*z/(4*games*games))/denominator
    return [max(0., centre-radius), min(1., centre+radius)]


def evaluate(env, output, episodes=200, checkpoint=None, device="cpu", first_seed=900000000):
    model = None
    if checkpoint:
        import torch
        from .learning import Policy
        ck = torch.load(checkpoint, map_location=device, weights_only=False)
        if ck["meta"]["backend"] != env.backend.name or ck["meta"]["settings"] != vars(env.settings):
            raise ValueError("Checkpoint backend/settings differ from evaluation environment")
        bank = getattr(env.backend, "bank", None)
        if bank and set(ck["meta"].get("save_bank_seeds", [])) & {e["seed"] for e in bank["entries"]}:
            raise ValueError("Evaluation save-bank seeds overlap training")
        model = Policy().to(device)
        model.load_state_dict(ck["model"])
        model.eval()
    counts = dict(win=0, loss=0, draw=0, error=0)
    records, durations, latencies = [], [], []
    transitions, sim_seconds, resets, peak_ram = 0, 0., [], 0
    begin = time.perf_counter()
    try:
        for i in range(episodes):
            start = time.perf_counter()
            record = dict(seed=first_seed+i//2, side=i%2)
            try:
                reset_start = time.perf_counter()
                obs, info = env.reset(seed=record["seed"], options={"side": record["side"]})
                resets.append(time.perf_counter()-reset_start)
                hidden = None
                reward_total = 0.
                while True:
                    decision_start = time.perf_counter()
                    if model is None:
                        action = teacher(obs)
                    else:
                        import torch
                        from .learning import tensors
                        with torch.no_grad():
                            dist, _, hidden = model(*tensors(obs, device), hidden)
                            action = dist.probs.argmax(-1).item()
                    latencies.append(time.perf_counter()-decision_start)
                    obs, reward, terminated, truncated, info = env.step(action)
                    transitions += 1
                    sim_seconds += info["elapsed"]
                    reward_total += reward
                    if terminated or truncated:
                        outcome = info["outcome"] or "draw"
                        counts[outcome] += 1
                        record.update(outcome=outcome, reward=reward_total,
                                      time_limit=truncated, commands=info.get("commands"))
                        break
                durations.append(time.perf_counter()-start)
            except BridgeError as exc:
                counts["error"] += 1
                record.update(outcome="error", error=str(exc))
                env.close()
                # A missing/broken live bridge needs intervention; do not hammer it 200 times.
                records.append(record)
                break
            peak_ram = max(peak_ram, psutil.Process().memory_info().rss)
            records.append(record)
    finally:
        env.close()
    wall = time.perf_counter()-begin
    completed = counts["win"]+counts["loss"]+counts["draw"]
    rate = transitions/wall if wall else 0
    report = dict(backend=env.backend.name, evidence="software_fixture_only" if env.backend.name == "synthetic" else "de_combat_pilot",
                  policy="scripted" if checkpoint is None else str(checkpoint), requested_episodes=episodes,
                  completed_episodes=completed, counts=counts, records=records, wall_seconds=wall,
                  transitions=transitions, transitions_per_second=rate, simulated_seconds=sim_seconds,
                  reset_mean_seconds=float(np.mean(resets)) if resets else None,
                  episode_mean_seconds=float(np.mean(durations)) if durations else None,
                  inference_p95_seconds=float(np.quantile(latencies, .95)) if latencies else None,
                  peak_python_rss_bytes=peak_ram, win_rate=counts["win"]/completed if completed else None,
                  win_rate_95_ci=wilson(counts["win"], completed),
                  valid_strength_result=env.backend.name == "de" and completed == episodes and counts["error"] == 0,
                  nights_per_million_transitions=1e6/(rate*8*3600) if rate else None,
                  forecast_caveat="Measured collection only; excludes learner updates. Synthetic rates cannot forecast DE.")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {k: v for k, v in report.items() if k != "records"}
