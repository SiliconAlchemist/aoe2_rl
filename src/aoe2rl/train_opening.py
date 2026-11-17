"""Small recurrent candidate-action PPO learner for the live DE opening task."""
import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from .core import BridgeError
from .learning import advantages, save_checkpoint
from .opening_env import OpeningEnv, TASK_VERSION, GLOBAL_SIZE, CANDIDATE_SIZE, MAX_ACTIONS


class OpeningPolicy(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(GLOBAL_SIZE, 64), nn.Tanh())
        self.memory = nn.GRUCell(64, 64)
        self.actor = nn.Sequential(nn.Linear(64+CANDIDATE_SIZE, 64), nn.Tanh(), nn.Linear(64, 1))
        self.critic = nn.Linear(64, 1)

    def forward(self, features, candidates, mask, hidden=None):
        if hidden is None:
            hidden = torch.zeros(features.shape[0], 64, device=features.device)
        hidden = self.memory(self.encoder(features), hidden)
        context = hidden.unsqueeze(1).expand(-1, candidates.shape[1], -1)
        logits = self.actor(torch.cat((context, candidates), -1)).squeeze(-1)
        dist = Categorical(logits=logits.masked_fill(~mask.bool(), -1e9))
        return dist, self.critic(hidden).squeeze(-1), hidden

    def sequence(self, data):
        hidden, logits, values = None, [], []
        for f, c, m in zip(data["features"], data["candidates"], data["mask"]):
            dist, value, hidden = self(f[None], c[None], m[None], hidden)
            logits.append(dist.logits.squeeze(0))
            values.append(value.squeeze(0))
        return Categorical(logits=torch.stack(logits)), torch.stack(values)


def collect(env, model, device, imitate=False, greedy=False, deadline=None):
    obs = env.reset()
    trajectory = {k: [] for k in ("features", "candidates", "mask", "actions", "old_log",
                                  "rewards", "values", "elapsed")}
    hidden = None
    started = time.monotonic()
    while True:
        if time.monotonic()-started > 600 or (deadline and time.monotonic() >= deadline):
            raise BridgeError("Run time budget reached during episode; partial rollout was not used for learning")
        with torch.no_grad():
            args = [torch.as_tensor(obs[k], device=device).unsqueeze(0)
                    for k in ("features", "candidates", "mask")]
            dist, value, hidden = model(*args, hidden)
            action = env.teacher() if imitate else (dist.probs.argmax(-1).item() if greedy else dist.sample().item())
            logp = dist.log_prob(torch.tensor([action], device=device)).item()
        for k in ("features", "candidates", "mask"):
            trajectory[k].append(obs[k])
        trajectory["actions"].append(action)
        trajectory["old_log"].append(logp)
        trajectory["values"].append(value.item())
        obs, reward, done, info = env.step(action)
        trajectory["rewards"].append(reward)
        trajectory["elapsed"].append(info["elapsed"])
        if done:
            break
    # The task is explicitly finite-horizon: deadline is terminal, not a continuing-task time limit.
    values = trajectory["values"] + [0.]
    terminals = [False]*(len(values)-2)+[True]
    adv = advantages(trajectory["rewards"], values, terminals, trajectory["elapsed"], env.interval)
    trajectory = {k: np.asarray(v) for k, v in trajectory.items()}
    trajectory["advantages"] = adv
    trajectory["returns"] = adv + trajectory["values"]
    env.close()  # Release the session during CPU updates; no 30-second session-expiry race.
    return trajectory, info


def update(model, optimizer, trajectory, device, imitate):
    data = {k: torch.as_tensor(v, device=device) for k, v in trajectory.items()}
    advantage = data["advantages"].float()
    advantage = (advantage-advantage.mean())/(advantage.std(unbiased=False)+1e-8)
    loss_value = 0.
    for _ in range(4):
        dist, values = model.sequence(data)
        logp = dist.log_prob(data["actions"])
        if imitate:
            loss = -logp.mean() + .5*(values-data["returns"].float()).square().mean()
        else:
            ratio = (logp-data["old_log"].float()).exp()
            actor_loss = -torch.minimum(ratio*advantage, ratio.clamp(.8,1.2)*advantage).mean()
            loss = actor_loss + .5*(values-data["returns"].float()).square().mean() - .01*dist.entropy().mean()
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), .5)
        optimizer.step()
        loss_value = float(loss.item())
    return loss_value


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output/"checkpoint.pt"
    if checkpoint.exists() and args.command == "train" and not args.resume:
        raise ValueError("Checkpoint already exists; use --resume or a new output folder")
    config = dict(task="de_two_house_opening", task_version=TASK_VERSION, horizon=args.horizon,
                  interval=args.interval, seed=args.seed, warmup=args.warmup, reset=args.reset,
                  global_size=GLOBAL_SIZE, candidate_size=CANDIDATE_SIZE, max_actions=MAX_ACTIONS)
    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    if args.device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA is unavailable; use --device cpu")
    model = OpeningPolicy().to(args.device)
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-4)
    completed = 0
    load_path = args.checkpoint if args.command == "evaluate" else args.resume
    if load_path:
        # Only load checkpoints created locally by this project.
        saved = torch.load(load_path, map_location=args.device, weights_only=False)
        meta = saved["meta"]
        if meta.get("config", {}).get("task_version") != TASK_VERSION or meta.get("config", {}).get("task") != config["task"]:
            raise ValueError("Checkpoint belongs to another task or schema")
        if args.command == "train" and meta["config"] != config:
            raise ValueError("Resume must preserve task, seed, horizon, interval, warmup and reset mode")
        model.load_state_dict(saved["model"])
        if args.command == "train":
            optimizer.load_state_dict(saved["optimizer"])
            completed = meta["episodes"]
            torch.set_rng_state(saved["torch_rng"].cpu())
            np.random.set_state(saved["numpy_rng"])
            random.setstate(saved["python_rng"])
            if saved["cuda_rng"] and torch.cuda.is_available():
                torch.cuda.set_rng_state_all([s.cpu() for s in saved["cuda_rng"]])
    if args.command == "evaluate" and not load_path:
        raise ValueError("Evaluation requires --checkpoint")
    config["evaluation_label"] = args.label if args.command == "evaluate" else None
    (output/"run-config.json").write_text(json.dumps(config, indent=2)+"\n", encoding="utf-8")
    # Keep checkpoint configuration stable: evaluation labels are not training hyperparameters.
    config.pop("evaluation_label")
    env = OpeningEnv(args.horizon, args.interval, args.reset, output/"actions.jsonl")
    started = time.monotonic()
    deadline = started+args.minutes*60
    summary = dict(task=config["task"], command=args.command, episodes_this_run=0,
                   successful_episodes=0, imitation_episodes=0, ppo_episodes=0,
                   error=None, trained=False, evaluation_label=args.label, config=config)
    try:
        while summary["episodes_this_run"] < args.episodes and time.monotonic() < deadline:
            imitation = args.command == "train" and completed < args.warmup
            phase = "imitation" if imitation else ("ppo" if args.command == "train" else "evaluation")
            print(f"Episode {completed+1}: {phase}; resetting the game...", flush=True)
            trajectory, info = collect(env, model, args.device, imitate=imitation,
                                       greedy=args.command == "evaluate", deadline=deadline)
            loss = update(model, optimizer, trajectory, args.device, imitation) if args.command == "train" else None
            completed += 1
            summary["episodes_this_run"] += 1
            summary["successful_episodes"] += int(info["success"])
            if phase in ("imitation", "ppo"):
                summary[phase+"_episodes"] += 1
                summary["trained"] = True
            record = dict(episode=completed, phase=phase, reward=float(trajectory["rewards"].sum()),
                          transitions=len(trajectory["actions"]), loss=loss, **info)
            with (output/"episodes.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record)+"\n")
            if args.command == "train":
                save_checkpoint(checkpoint, model, optimizer,
                                dict(config=config, episodes=completed, evidence="live_de_opening_only"))
            print(json.dumps({k: record[k] for k in ("episode", "phase", "success", "reward", "metrics")}), flush=True)
            summary["episodes_total"] = completed
            summary["wall_seconds"] = time.monotonic()-started
            (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    except (BridgeError, ValueError, OSError, RuntimeError, KeyError) as exc:
        summary["error"] = str(exc)
    except KeyboardInterrupt:
        summary["error"] = "Interrupted; partial episode discarded, previous checkpoint retained"
    finally:
        try:
            env.close()
        except (BridgeError, OSError) as exc:
            summary["close_error"] = str(exc)
        summary["wall_seconds"] = time.monotonic()-started
        (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("train", "evaluate"))
    parser.add_argument("--execute", action="store_true", help="Authorize unit commands and restarting this disposable game")
    parser.add_argument("--episodes", type=int, default=4, help="Additional episodes in this invocation")
    parser.add_argument("--warmup", type=int, default=2, help="Total imitation episodes before PPO")
    parser.add_argument("--horizon", type=float, default=180, help="Task deadline in game seconds")
    parser.add_argument("--interval", type=float, default=2, help="Minimum game seconds between decisions")
    parser.add_argument("--minutes", type=float, default=12, help="Wall-clock budget including resets")
    parser.add_argument("--reset", choices=("auto", "manual"), default="auto")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", default="runs/opening-first")
    parser.add_argument("--resume")
    parser.add_argument("--checkpoint")
    parser.add_argument("--label", default="same_setup_diagnostic")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required: training commands units and restarts the disposable match")
    if (not 1 <= args.episodes <= 10000 or not 0 <= args.warmup <= 1000
            or not 30 <= args.horizon <= 600 or not .5 <= args.interval <= 10
            or not 1 <= args.minutes <= 480):
        parser.error("Use episodes 1-10000, warmup 0-1000, horizon 30-600, interval .5-10, minutes 1-480")
    try:
        summary = run(args)
    except (BridgeError, ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Setup blocked: {exc}\n")
    print(json.dumps(summary, indent=2))
    if summary["error"] or summary.get("close_error"):
        parser.exit(2, "Run stopped; see summary.json. No fabricated game outcome was used.\n")


if __name__ == "__main__":
    main()
