import importlib
import json
import pytest
from aoe2rl.core import BridgeError

probe_module = importlib.import_module("aoe2rl.probe")


@pytest.mark.parametrize("failure", [None, "connect", "ping", "inspect"])
def test_probe_stages_close_and_never_validate(tmp_path, monkeypatch, failure):
    operations = []
    class Pipe:
        def __init__(self, **kwargs): pass
        def connect(self):
            if failure == "connect": raise BridgeError("pipe missing")
        def request(self, payload):
            operations.append(payload["op"])
            if failure == payload["op"]: raise BridgeError("not responding")
            return {"op": "pong" if payload["op"] == "ping" else "inspection", "schema": 1}
        def close(self): operations.append("close")
    monkeypatch.setattr(probe_module, "ControlPipe", Pipe)
    target = tmp_path / "probe.json"
    result = probe_module.probe(target)
    assert result["stage"] == (failure or "complete")
    assert result["connected"] is (failure is None)
    assert result["live_validated"] is False
    assert operations[-1] == "close"
    assert set(operations) <= {"ping", "inspect", "close"}
    assert json.loads(target.read_text()) == result
