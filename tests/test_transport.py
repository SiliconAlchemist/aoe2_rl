import json
import threading
import time
import uuid
import pytest
from aoe2rl.transport import ControlPipe
from aoe2rl.core import BridgeError


def test_json_stream_chunking_and_concatenation():
    client = ControlPipe()
    client.buffer.extend(b'{"a":')
    assert client._pop_json() is None
    client.buffer.extend(b'1}\n{"b":2}')
    assert client._pop_json() == {"a": 1}
    assert client._pop_json() == {"b": 2}


def test_real_missing_windows_pipe_is_a_bounded_bridge_error():
    pytest.importorskip("win32pipe")
    client = ControlPipe(pipe="AoE2RL_missing_" + uuid.uuid4().hex, timeout=.1)
    started = time.monotonic()
    with pytest.raises(BridgeError, match="unavailable"):
        client.connect()
    assert time.monotonic() - started < 2
    assert client.handle is None


def test_windows_permission_error_is_actionable(monkeypatch):
    win32file = pytest.importorskip("win32file")
    import pywintypes
    def denied(*args):
        raise pywintypes.error(5, "CreateFile", "Access is denied")
    monkeypatch.setattr(win32file, "CreateFile", denied)
    with pytest.raises(BridgeError, match="Access is denied"):
        ControlPipe().connect()


@pytest.mark.parametrize("respond", [True, False])
def test_real_windows_pipe_roundtrip_and_timeout(respond):
    win32pipe = pytest.importorskip("win32pipe")
    import win32file
    name = "AoE2RL_test_"+uuid.uuid4().hex
    handle = win32pipe.CreateNamedPipe("\\\\.\\pipe\\"+name, win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT, 1, 65536, 65536, 1000, None)
    failures = []
    def server():
        try:
            win32pipe.ConnectNamedPipe(handle, None)
            _, data = win32file.ReadFile(handle, 4096)
            request = json.loads(data)
            if respond:
                envelope = {"source": {"assignedPlayerId": 1, "moduleName": "aoe2rl"},
                            "payload": {"request_id": request["payload"]["request_id"], "ok": True}}
                raw = json.dumps(envelope).encode()
                win32file.WriteFile(handle, raw[:20])
                time.sleep(.01)
                win32file.WriteFile(handle, raw[20:]) # deliberately no newline
            else:
                time.sleep(.4)
        except Exception as exc:
            failures.append(exc)
        finally:
            handle.Close()
    worker = threading.Thread(target=server, daemon=True)
    worker.start()
    client = ControlPipe(pipe=name, timeout=.2)
    try:
        if respond:
            assert client.request({"op": "ping"})["ok"] is True
        else:
            with pytest.raises(BridgeError, match="timed out"):
                client.request({"op": "ping"})
    finally:
        client.close()
        worker.join(2)
    assert not worker.is_alive()
    assert not failures
