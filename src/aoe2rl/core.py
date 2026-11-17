"""Shared, deliberately small combat interface. No raw engine state enters a policy."""
from dataclasses import dataclass
import math
import numpy as np

SCHEMA = 1
# 0 = continue current order; 1..8 = compass moves; 9 = attack nearest visible enemy.
DIRECTIONS = [(math.cos(i * math.pi / 4), math.sin(i * math.pi / 4)) for i in range(8)]
ACTION_COUNT = 10
FEATURE_COUNT = 64  # time + own count + visible count + enemy memory count + 10 x 6


class BridgeError(RuntimeError):
    """Infrastructure failure; must never be converted into a game outcome."""


@dataclass(frozen=True)
class Settings:
    interval: float = 0.5
    horizon: float = 120.0
    map_size: int = 32
    player: int = 1
    timeout: float = 15.0

    def __post_init__(self):
        if self.interval < 0.5 or self.horizon <= 0 or self.map_size < 8:
            raise ValueError("Require interval >= 0.5, positive horizon, map >= 8")
        if self.player not in (1, 2) or self.timeout <= 0:
            raise ValueError("Pilot supports players 1/2 and positive timeout")


class ObservationFilter:
    def __init__(self, settings):
        self.settings = settings
        self.memory = {}

    def reset(self):
        self.memory.clear()

    def encode(self, state):
        s = self.settings
        now = float(state["game_time"])
        if not math.isfinite(now) or now < 0:
            raise BridgeError("Invalid game timestamp")
        own, visible = [], []
        for unit in state["units"]:
            owner = int(unit["player"])
            # Fail closed: absent visibility never means visible. Do not even read hidden fields.
            if owner != s.player and unit.get("visible") is not True:
                continue
            if owner not in (1, 2):
                continue
            data = {k: unit[k] for k in ("id", "player", "x", "y", "hp", "max_hp")}
            if not all(math.isfinite(float(data[k])) for k in ("x", "y", "hp", "max_hp")):
                raise BridgeError("Non-finite visible unit state")
            if data["max_hp"] <= 0:
                raise BridgeError("Invalid maximum HP")
            if owner == s.player:
                if data["hp"] > 0:
                    own.append(data)
            else:
                if data["hp"] > 0:
                    visible.append(data)
                    self.memory[data["id"]] = (dict(data), now)
                else:
                    self.memory.pop(data["id"], None)
        own.sort(key=lambda u: u["id"])
        visible.sort(key=lambda u: u["id"])
        visible_ids = {u["id"] for u in visible}
        remembered = [(u, t) for uid, (u, t) in sorted(self.memory.items()) if uid not in visible_ids]
        units = [(u, now, 1.0) for u in own[:5]]
        units += [(None, now, 0)] * (5 - len(units))
        enemy = [(u, now, 1.0) for u in visible]
        enemy += [(u, t, 0.0) for u, t in remembered]
        units += enemy[:5] + [(None, now, 0)] * max(0, 5 - len(enemy))
        features = [min(now / s.horizon, 1), min(len(own) / 5, 1),
                    min(len(visible) / 5, 1), min(len(remembered) / 5, 1)]
        for u, seen_at, current in units:
            if u is None:
                features.extend([0.] * 6)
            else:
                features.extend([np.clip(u["x"] / s.map_size, 0, 1),
                                 np.clip(u["y"] / s.map_size, 0, 1),
                                 np.clip(u["hp"] / u["max_hp"], 0, 1), 1., current,
                                 min(max(now - seen_at, 0) / s.horizon, 1)])
        mask = np.zeros(ACTION_COUNT, dtype=np.int8)
        mask[0] = 1
        if own:
            x = sum(u["x"] for u in own) / len(own)
            y = sum(u["y"] for u in own) / len(own)
            for i, (dx, dy) in enumerate(DIRECTIONS, 1):
                mask[i] = 0 <= x + 2 * dx < s.map_size and 0 <= y + 2 * dy < s.map_size
            mask[9] = bool(visible)
        return {"features": np.asarray(features, dtype=np.float32), "action_mask": mask}


def teacher(obs):
    """Small transparent teacher, using only the exact policy observation."""
    f, mask = obs["features"], obs["action_mask"]
    if mask[9]:
        return 9
    own = f[4:34].reshape(5, 6)
    remembered = f[34:].reshape(5, 6)
    own = own[own[:, 3] > 0]
    remembered = remembered[remembered[:, 3] > 0]
    if len(own) and len(remembered):
        delta = remembered[0, :2] - own[:, :2].mean(0)
        preferred = 1 + int(round(math.atan2(delta[1], delta[0]) / (math.pi / 4))) % 8
        return preferred if mask[preferred] else 0
    # Initial exploration towards the map centre, without knowing the enemy spawn.
    if len(own):
        delta = np.array([0.5, 0.5]) - own[:, :2].mean(0)
        preferred = 1 + int(round(math.atan2(delta[1], delta[0]) / (math.pi / 4))) % 8
        return preferred if mask[preferred] else 0
    return 0
