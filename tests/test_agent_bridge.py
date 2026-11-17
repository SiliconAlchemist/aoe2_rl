import json
import threading
import uuid
import pytest
from aoe2rl.agent_bridge import AgentBridge
from aoe2rl.core import BridgeError


@pytest.mark.parametrize("reject", [False, True])
def test_native_protocol_fragmented_response_and_error(reject, monkeypatch):
    win32pipe = pytest.importorskip("win32pipe")
    import win32file
    import aoe2rl.agent_bridge as module
    from aoe2rl.transport import ControlPipe
    name = "AoE2RL_native_test_" + uuid.uuid4().hex
    handle = win32pipe.CreateNamedPipe("\\\\.\\pipe\\"+name, win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT, 1, 65536, 65536, 1000, None)
    failures = []
    def server():
        try:
            win32pipe.ConnectNamedPipe(handle, None)
            _, raw = win32file.ReadFile(handle, 4096)
            request = json.loads(raw)
            assert request == {"contract_version": 3, "operation": "open", "payload": {"client_name": "test"}}
            response = {"ok": False, "error": {"code": "player_in_use"}} if reject else {"ok": True, "data": {"session": "test-session"}}
            raw = json.dumps(response).encode()
            win32file.WriteFile(handle, raw[:7])
            win32file.WriteFile(handle, raw[7:])
        except Exception as exc:
            failures.append(exc)
        finally:
            handle.Close()
    def connection(**kwargs):
        return ControlPipe(pipe=name, timeout=1)
    monkeypatch.setattr(module, "ControlPipe", connection)
    worker = threading.Thread(target=server, daemon=True)
    worker.start()
    client = AgentBridge()
    try:
        if reject:
            with pytest.raises(BridgeError, match="player_in_use"):
                client.request("open", {"client_name": "test"})
        else:
            assert client.request("open", {"client_name": "test"}) == {"session": "test-session"}
            assert client.session == "test-session"
    finally:
        worker.join(2)
    assert not worker.is_alive() and not failures


def test_no_session_cannot_observe():
    with pytest.raises(BridgeError, match="session first"):
        AgentBridge().request("observe")


def test_probe_rejects_omniscient_before_open(tmp_path, monkeypatch):
    import aoe2rl.agent_bridge as module
    calls = []
    def request(self, operation, payload=None):
        calls.append(operation)
        return {"information_policy": "omniscient", "player_id": 1}
    monkeypatch.setattr(module.AgentBridge, "request", request)
    result = module.probe(tmp_path/"probe.json")
    assert calls == ["status"]
    assert result["live_validated"] is False and result["error"]
