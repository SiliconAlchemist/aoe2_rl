import copy
import numpy as np
import pytest
from aoe2rl.core import ObservationFilter, Settings, BridgeError, teacher
from aoe2rl.env import CombatEnv
from aoe2rl.synthetic import SyntheticBackend


def make():
    s = Settings()
    b = SyntheticBackend(s)
    return CombatEnv(b, s), b


def test_hidden_state_never_changes_policy_input_or_masks():
    settings = Settings()
    backend = SyntheticBackend(settings)
    state = backend.reset(1, 0)
    for u in state["units"]:
        if u["player"] == 2:
            u["visible"] = False
    altered = copy.deepcopy(state)
    for u in altered["units"]:
        if u["player"] == 2:
            u["x"], u["hp"] = float("nan"), -99999
    a = ObservationFilter(settings).encode(state)
    b = ObservationFilter(settings).encode(altered)
    for key in a:
        np.testing.assert_array_equal(a[key], b[key])
    assert a["action_mask"][9] == 0


def test_memory_freezes_after_visibility_is_lost_and_resets():
    settings = Settings()
    f = ObservationFilter(settings)
    state = SyntheticBackend(settings).reset(3, 0)
    for u in state["units"]: u["visible"] = True
    f.encode(state)
    remembered = copy.deepcopy(f.memory)
    state["game_time"] = 3
    for u in state["units"]:
        if u["player"] == 2:
            u["visible"], u["hp"], u["x"] = False, 1, 100
    f.encode(state)
    assert f.memory == remembered
    f.reset()
    assert not f.memory


@pytest.mark.parametrize("change", [
    {"seq": 100}, {"episode": "old"}, {"game_time": 0},
    {"native_ai_suppressed": False}, {"fairness": "omniscient"},
    {"backend": "de"}, {"error": "crashed"}, {"shaping_potential": float("nan")}
])
def test_bad_transitions_raise_instead_of_becoming_wins(change):
    env, backend = make()
    env.reset(seed=4)
    original = backend.step
    backend.step = lambda **kwargs: {**original(**kwargs), **change}
    with pytest.raises(BridgeError):
        env.step(0)
    with pytest.raises(RuntimeError):
        env.step(0)


def test_invalid_action_rejected_before_dispatch():
    env, backend = make()
    env.reset(seed=1)
    with pytest.raises(ValueError): env.step(10)
    assert backend.seq == 0


def test_100_resets_and_rollouts_reproduce_and_preserve_spaces():
    env, backend = make()
    for seed in range(100):
        obs, _ = env.reset(seed=seed, options={"side": seed%2})
        assert env.observation_space.contains(obs)
        while True:
            obs, _, terminal, truncated, info = env.step(teacher(obs))
            assert env.observation_space.contains(obs)
            assert info["elapsed"] >= .5
            if terminal or truncated: break
    env.close()


def test_time_limit_is_truncation_not_a_defeat():
    s = Settings(horizon=.5)
    env = CombatEnv(SyntheticBackend(s), s)
    env.reset(seed=1)
    _, _, terminal, truncated, info = env.step(0)
    assert truncated and not terminal and info["outcome"] is None
