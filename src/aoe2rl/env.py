import math
import time
import gymnasium as gym
import numpy as np
from .core import ACTION_COUNT, FEATURE_COUNT, SCHEMA, BridgeError, ObservationFilter, Settings


class CombatEnv(gym.Env):
    """Single learner, opponent controlled by the backend. No fallback on bridge failure."""
    metadata = {"render_modes": []}

    def __init__(self, backend, settings=None):
        self.settings = settings or Settings()
        self.backend = backend
        self.filter = ObservationFilter(self.settings)
        self.action_space = gym.spaces.Discrete(ACTION_COUNT)
        self.observation_space = gym.spaces.Dict({
            "features": gym.spaces.Box(0, 1, (FEATURE_COUNT,), np.float32),
            "action_mask": gym.spaces.MultiBinary(ACTION_COUNT),
        })
        self.episode = None
        self.done = True
        self.seq = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.done = True
        self.filter.reset()
        self.seq = 0
        state = self.backend.reset(seed=int(seed if seed is not None else self.np_random.integers(2**31)),
                                   side=int((options or {}).get("side", 0)))
        self._validate(state)
        self.episode = state["episode"]
        self.time = float(state["game_time"])
        self.shaping = float(state.get("shaping_potential", 0))
        self.obs = self.filter.encode(state)
        self.done = False
        return self.obs, self._info(state)

    def _validate(self, state):
        if state.get("schema") != SCHEMA or not state.get("episode"):
            raise BridgeError("Bridge schema/episode mismatch")
        if state.get("error"):
            raise BridgeError(state["error"])
        if state.get("fairness") != "fog_limited" or state.get("native_ai_suppressed") is not True:
            raise BridgeError("Bridge has not established fog filtering and native AI suppression")
        if state.get("backend") != self.backend.name:
            raise BridgeError("Backend provenance mismatch")
        if state.get("outcome") not in (None, "win", "loss", "draw"):
            raise BridgeError("Invalid outcome")

    def step(self, action):
        if self.done:
            raise RuntimeError("reset() is required before step()")
        if not self.action_space.contains(action) or not self.obs["action_mask"][int(action)]:
            raise ValueError("Invalid or masked action")
        self.seq += 1
        try:
            state = self.backend.step(episode=self.episode, seq=self.seq, action=int(action),
                                      interval=self.settings.interval)
            self._validate(state)
            if state["episode"] != self.episode or state.get("seq") != self.seq:
                raise BridgeError("Stale or out-of-order transition")
            elapsed = float(state["game_time"]) - self.time
            outcome = state.get("outcome")
            if not math.isfinite(elapsed) or elapsed < 0 or (not outcome and elapsed < self.settings.interval - 1e-5):
                raise BridgeError("Game clock failed to advance by the action interval")
            self.time = float(state["game_time"])
            potential = float(state.get("shaping_potential", 0))
            if not math.isfinite(potential) or abs(potential) > 1:
                raise BridgeError("Invalid shaping potential")
            # Telescoping shaping stays in [-0.1, 0.1] over an episode; terminal reward dominates.
            reward = 0.05 * (potential - self.shaping)
            self.shaping = potential
            reward += {None: 0, "win": 1, "loss": -1, "draw": 0}[outcome]
            terminated = outcome is not None
            truncated = not terminated and self.time >= self.settings.horizon
            self.done = terminated or truncated
            self.obs = self.filter.encode(state)
            return self.obs, float(reward), terminated, truncated, {**self._info(state), "elapsed": elapsed}
        except Exception:
            self.done = True
            raise

    def _info(self, state):
        return {k: state.get(k) for k in ("backend", "episode", "game_time", "outcome", "seq", "commands", "build")}

    def close(self):
        self.done = True
        self.backend.close()
