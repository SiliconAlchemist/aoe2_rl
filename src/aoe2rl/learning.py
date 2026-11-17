"""Compact recurrent PPO and sequence imitation, with episode-boundary checkpointing."""
import json
import os
import random
import time
import uuid
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical
from .core import ACTION_COUNT, FEATURE_COUNT, teacher


class Policy(nn.Module):
    def __init__(self, hidden=64):
        super().__init__()
        self.hidden = hidden
        self.encoder = nn.Sequential(nn.Linear(FEATURE_COUNT, hidden), nn.Tanh())
        self.memory = nn.GRUCell(hidden, hidden)
        self.actor = nn.Linear(hidden, ACTION_COUNT)
        self.critic = nn.Linear(hidden, 1)

    def forward(self, features, mask, hidden=None):
        if hidden is None:
            hidden = torch.zeros(features.shape[0], self.hidden, device=features.device)
        hidden = self.memory(self.encoder(features), hidden)
        logits = self.actor(hidden).masked_fill(~mask.bool(), -1e9)
        return Categorical(logits=logits), self.critic(hidden).squeeze(-1), hidden

    def sequence(self, features, masks):
        hidden, logits, values = None, [], []
        for x, mask in zip(features, masks):
            distribution, value, hidden = self(x.unsqueeze(0), mask.unsqueeze(0), hidden)
            logits.append(distribution.logits.squeeze(0))
            values.append(value.squeeze(0))
        return Categorical(logits=torch.stack(logits)), torch.stack(values)


def tensors(obs, device):
    return (torch.as_tensor(obs["features"], device=device).unsqueeze(0),
            torch.as_tensor(obs["action_mask"], device=device).unsqueeze(0))


def advantages(rewards, values, terminated, elapsed, interval, gamma=.99, lam=.95):
    """Time-aware GAE: time limits bootstrap, actual terminal outcomes do not."""
    result = np.zeros(len(rewards), np.float32)
    carry = 0.
    for t in reversed(range(len(rewards))):
        discount = gamma ** (elapsed[t] / interval)
        continuation = 0. if terminated[t] else 1.
        delta = rewards[t] + discount*values[t+1]*continuation-values[t]
        carry = delta + discount*(lam ** (elapsed[t]/interval))*continuation*carry
        result[t] = carry
    return result


def collect(env, model, seed, device, imitate=False, side=0):
    obs, info = env.reset(seed=seed, options={"side": side})
    features, masks, actions, logs, rewards, values, elapsed, terminals = [], [], [], [], [], [], [], []
    hidden = None
    while True:
        x, mask = tensors(obs, device)
        with torch.no_grad():
            dist, value, hidden = model(x, mask, hidden)
            action = torch.tensor([teacher(obs)], device=device) if imitate else dist.sample()
        features.append(obs["features"])
        masks.append(obs["action_mask"])
        actions.append(action.item())
        logs.append(dist.log_prob(action).item())
        values.append(value.item())
        obs, reward, terminated, truncated, info = env.step(action.item())
        rewards.append(reward)
        elapsed.append(info["elapsed"])
        terminals.append(terminated)
        if terminated or truncated:
            with torch.no_grad():
                _, last_value, _ = model(*tensors(obs, device), hidden)
            values.append(0. if terminated else last_value.item())
            break
    adv = advantages(rewards, values, terminals, elapsed, env.settings.interval)
    return dict(features=np.asarray(features), masks=np.asarray(masks), actions=np.asarray(actions),
                old_log=np.asarray(logs), advantages=adv, returns=adv+np.asarray(values[:-1]),
                outcome=info["outcome"] or "draw", reward=sum(rewards), length=len(actions))


def update(model, optimizer, episode, device, imitate=False, epochs=4):
    data = {k: torch.as_tensor(episode[k], device=device) for k in
            ("features", "masks", "actions", "old_log", "advantages", "returns")}
    adv = data["advantages"].float()
    adv = (adv-adv.mean())/(adv.std(unbiased=False)+1e-8)
    for _ in range(epochs):
        dist, values = model.sequence(data["features"], data["masks"])
        logp = dist.log_prob(data["actions"])
        if imitate:
            loss = -logp.mean()
        else:
            ratio = (logp-data["old_log"].float()).exp()
            actor = -torch.minimum(ratio*adv, ratio.clamp(.8, 1.2)*adv).mean()
            loss = actor + .5*(values-data["returns"].float()).square().mean()-.01*dist.entropy().mean()
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), .5)
        optimizer.step()
    return float(loss.item())


def save_checkpoint(path, model, optimizer, meta):
    payload = dict(model=model.state_dict(), optimizer=optimizer.state_dict(), meta=meta,
                   torch_rng=torch.get_rng_state(), numpy_rng=np.random.get_state(),
                   python_rng=random.getstate(), cuda_rng=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [])
    tmp = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    torch.save(payload, tmp)
    # OneDrive/antivirus can briefly hold the destination. Keep the previous
    # checkpoint intact and retry replacement, never truncate it in place.
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 7: raise
            time.sleep(.1*(attempt+1))


def train(env, output, algorithm="bc-ppo", seed=1, seconds=60, device="cpu", resume=None, max_episodes=None):
    if algorithm not in ("bc", "ppo", "bc-ppo") or seconds <= 0:
        raise ValueError("Choose bc, ppo or bc-ppo and positive seconds")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output/"checkpoint.pt").exists() and not resume:
        raise ValueError("Output already contains a checkpoint; use --resume or a fresh directory")
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    model = Policy().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-4)
    episode_id, cumulative, bc_spent = 0, 0., 0.
    if resume:
        # Checkpoints are local trusted artifacts, never load an untrusted downloaded pickle.
        ck = torch.load(resume, map_location=device, weights_only=False)
        meta = ck["meta"]
        if (meta["backend"], meta["algorithm"], meta["seed"], meta["settings"]) != (
                env.backend.name, algorithm, seed, vars(env.settings)):
            raise ValueError("Resume configuration/provenance does not match")
        if meta.get("total_budget_seconds") != seconds:
            raise ValueError("Resume must preserve the original total machine-time budget")
        model.load_state_dict(ck["model"])
        optimizer.load_state_dict(ck["optimizer"])
        episode_id, cumulative, bc_spent = meta["episodes"], meta["machine_seconds"], meta["bc_seconds"]
        torch.set_rng_state(ck["torch_rng"].cpu())
        np.random.set_state(ck["numpy_rng"])
        random.setstate(ck["python_rng"])
        if ck["cuda_rng"] and torch.cuda.is_available():
            torch.cuda.set_rng_state_all([x.cpu() for x in ck["cuda_rng"]])
    started = time.perf_counter()
    count = 0
    last_saved, saved_at = episode_id, started
    # --seconds is a total cumulative budget, including previous sessions and teacher collection.
    try:
        while cumulative + time.perf_counter()-started < seconds and (max_episodes is None or count < max_episodes):
            episode_start = time.perf_counter()
            imitate = algorithm == "bc" or (algorithm == "bc-ppo" and bc_spent < seconds*.2)
            episode = collect(env, model, seed*100000+episode_id, device, imitate, episode_id % 2)
            loss = update(model, optimizer, episode, device, imitate)
            duration = time.perf_counter()-episode_start
            bc_spent += duration if imitate else 0
            episode_id += 1
            count += 1
            meta = dict(backend=env.backend.name, algorithm=algorithm, seed=seed, episodes=episode_id,
                        machine_seconds=cumulative+time.perf_counter()-started, bc_seconds=bc_spent,
                        settings=vars(env.settings), torch_version=torch.__version__,
                        total_budget_seconds=seconds,
                        save_bank_seeds=sorted({e["seed"] for e in (getattr(env.backend, "bank", None) or {}).get("entries", [])}),
                        evidence="software_fixture_only" if env.backend.name == "synthetic" else "de_combat_pilot")
            with (output/"train.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({**meta, "loss": loss, "outcome": episode["outcome"],
                                   "transitions": episode["length"], "reward": episode["reward"],
                                   "stage": "imitation" if imitate else "ppo"})+"\n")
            if count == 1 or time.perf_counter()-saved_at >= 30:
                save_checkpoint(output/"checkpoint.pt", model, optimizer, meta)
                last_saved, saved_at = episode_id, time.perf_counter()
        if count and last_saved != episode_id:
            save_checkpoint(output/"checkpoint.pt", model, optimizer, meta)
    finally:
        env.close()
    return {"completed_episodes_this_run": count, "checkpoint": str(output/"checkpoint.pt"),
            "backend": env.backend.name}
