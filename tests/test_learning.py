import numpy as np
import torch
from aoe2rl.core import ACTION_COUNT, FEATURE_COUNT, Settings
from aoe2rl.env import CombatEnv
from aoe2rl.synthetic import SyntheticBackend
from aoe2rl.learning import Policy, advantages, train
from aoe2rl.evaluation import evaluate, wilson


def test_masked_actions_have_zero_probability():
    model = Policy()
    mask = torch.zeros(1, ACTION_COUNT)
    mask[0, 0] = 1
    dist, _, _ = model(torch.zeros(1, FEATURE_COUNT), mask)
    assert dist.probs[0, 0] == 1
    assert all(dist.sample().item() == 0 for _ in range(100))


def test_gae_bootstraps_truncations_but_not_terminal_wins():
    np.testing.assert_allclose(advantages([1], [.5, .8], [True], [.5], .5), [.5])
    np.testing.assert_allclose(advantages([1], [.5, .8], [False], [1.], .5), [1+.99**2*.8-.5])


def test_recurrent_sequence_matches_stepwise_inference():
    model = Policy()
    x = torch.randn(7, FEATURE_COUNT)
    masks = torch.ones(7, ACTION_COUNT)
    dist, values = model.sequence(x, masks)
    h = None
    for i in range(7):
        d, v, h = model(x[i:i+1], masks[i:i+1], h)
        torch.testing.assert_close(d.probs[0], dist.probs[i])
        torch.testing.assert_close(v[0], values[i])


def test_checkpoint_resume_and_evaluation_provenance(tmp_path):
    def env(): return CombatEnv(SyntheticBackend())
    train(env(), tmp_path, algorithm="ppo", seconds=60, max_episodes=1)
    ck = torch.load(tmp_path/"checkpoint.pt", weights_only=False)
    assert ck["meta"]["episodes"] == 1
    train(env(), tmp_path, algorithm="ppo", seconds=60, max_episodes=1, resume=tmp_path/"checkpoint.pt")
    ck = torch.load(tmp_path/"checkpoint.pt", weights_only=False)
    assert ck["meta"]["episodes"] == 2
    report = evaluate(env(), tmp_path/"eval.json", episodes=4, checkpoint=tmp_path/"checkpoint.pt")
    assert report["completed_episodes"] == 4
    assert report["valid_strength_result"] is False
    assert report["counts"]["error"] == 0


def test_confidence_interval_and_errors(tmp_path):
    assert wilson(0, 0) == [None, None]
    assert wilson(80, 100)[0] < .8 < wilson(80, 100)[1]
    from aoe2rl.core import BridgeError
    backend = SyntheticBackend()
    def crash(**kwargs): raise BridgeError("test crash")
    backend.reset = crash
    report = evaluate(CombatEnv(backend), tmp_path/"error.json", episodes=5)
    assert report["counts"] == {"win": 0, "loss": 0, "draw": 0, "error": 1}
    assert report["completed_episodes"] == 0


def test_checkpoint_survives_temporary_windows_file_lock(tmp_path, monkeypatch):
    from aoe2rl import learning
    model = Policy()
    optimizer = torch.optim.Adam(model.parameters())
    original = learning.os.replace
    attempts = []
    def locked(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("simulated file lock")
        return original(source, destination)
    monkeypatch.setattr(learning.os, "replace", locked)
    monkeypatch.setattr(learning.time, "sleep", lambda _: None)
    learning.save_checkpoint(tmp_path/"checkpoint.pt", model, optimizer, {"verified": True})
    assert len(attempts) == 3
    assert torch.load(tmp_path/"checkpoint.pt", weights_only=False)["meta"]["verified"]
