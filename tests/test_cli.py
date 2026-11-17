import pytest
from aoe2rl import cli
from aoe2rl.core import BridgeError
from aoe2rl.env import CombatEnv
from aoe2rl.synthetic import SyntheticBackend


def test_failed_evaluation_is_nonzero_and_preserves_error_report(tmp_path, monkeypatch):
    backend = SyntheticBackend()
    def crash(**kwargs): raise BridgeError("disconnected")
    backend.reset = crash
    monkeypatch.setattr(cli, "environment", lambda args: CombatEnv(backend))
    target = tmp_path/"report.json"
    with pytest.raises(SystemExit) as exc:
        cli.main(["evaluate", "--backend", "synthetic", "--output", str(target)])
    assert exc.value.code == 2
    assert "disconnected" in target.read_text()
