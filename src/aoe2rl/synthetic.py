"""Tiny deterministic software-test fixture. NOT an AoE II simulator or strength benchmark."""
import copy
import math
import numpy as np
from .core import DIRECTIONS, Settings


class SyntheticBackend:
    name = "synthetic"

    def __init__(self, settings=None):
        self.settings = settings or Settings()

    def reset(self, seed, side):
        self.rng = np.random.default_rng(seed)
        self.episode = f"synthetic-{seed}-{side}"
        self.time, self.seq, self.commands = 0., 0, 0
        self.order = 0
        self.units = []
        for p in (1, 2):
            x = (9 if (p == 1) != bool(side) else 19)
            for i in range(5):
                self.units.append(dict(id=p*100+i, player=p, x=x + float(self.rng.uniform(-1, 1)),
                    y=14+i*.6+float(self.rng.uniform(-.3, .3)), hp=30., max_hp=30.))
        return self._snapshot()

    def _snapshot(self):
        own = [u for u in self.units if u["player"] == self.settings.player and u["hp"] > 0]
        enemy = [u for u in self.units if u["player"] != self.settings.player and u["hp"] > 0]
        units = copy.deepcopy(self.units)
        for u in units:
            u["visible"] = u["player"] == self.settings.player or any(
                math.hypot(u["x"]-a["x"], u["y"]-a["y"]) <= 10 for a in own)
        outcome = None if own and enemy else ("draw" if not own and not enemy else "win" if own else "loss")
        return dict(schema=1, backend=self.name, episode=self.episode, seq=self.seq,
                    game_time=self.time, units=units, outcome=outcome, commands=self.commands,
                    fairness="fog_limited", native_ai_suppressed=True,
                    shaping_potential=(sum(u["hp"] for u in own)-sum(u["hp"] for u in enemy))/150)

    def step(self, episode, seq, action, interval):
        if episode != self.episode or seq != self.seq + 1:
            raise RuntimeError("Synthetic protocol mismatch")
        self.seq = seq
        self.commands += action != 0
        if action:
            self.order = action
        alive = [u for u in self.units if u["hp"] > 0]
        damage = {}
        for u in alive:
            enemies = [v for v in alive if v["player"] != u["player"]]
            if not enemies:
                continue
            target = min(enemies, key=lambda v: math.hypot(v["x"]-u["x"], v["y"]-u["y"]))
            dx, dy = target["x"]-u["x"], target["y"]-u["y"]
            distance = math.hypot(dx, dy)
            order = self.order if u["player"] == self.settings.player else 9
            if order == 9 and distance <= 4:
                damage[target["id"]] = damage.get(target["id"], 0) + 3*interval
            else:
                if 1 <= order <= 8:
                    dx, dy = DIRECTIONS[order-1]
                elif order == 9:
                    dx, dy = dx/max(distance, .01), dy/max(distance, .01)
                else:
                    continue
                u["x"] = float(np.clip(u["x"]+dx*interval, 0, self.settings.map_size-.01))
                u["y"] = float(np.clip(u["y"]+dy*interval, 0, self.settings.map_size-.01))
        for u in alive:
            u["hp"] = max(0, u["hp"]-damage.get(u["id"], 0))
        self.time += interval
        return self._snapshot()

    def close(self):
        pass
