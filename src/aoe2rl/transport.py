"""Bounded Windows named-pipe JSON transport for CONTROL's documented routing envelope."""
import json
import time
import uuid
from pathlib import Path
from .core import BridgeError


class ControlPipe:
    name = "de"

    def __init__(self, player=1, timeout=15., pipe="AoE2RL", module="aoe2rl", bank=None):
        self.player, self.timeout, self.pipe, self.module = player, timeout, pipe, module
        self.handle = None
        self.buffer = bytearray()
        self.bank = None
        if bank:
            self.bank = json.loads(Path(bank).read_text(encoding="utf-8"))
            if self.bank.get("split") not in ("train", "evaluation") or not self.bank.get("entries"):
                raise ValueError("Save bank needs a split and nonempty entries")
            for item in self.bank["entries"]:
                if item.get("live_verified") is not True or not str(item.get("save_game", "")).endswith(".aoe2spgame"):
                    raise ValueError("Every save-bank entry must reference a verified DE saved game")
                if Path(item["save_game"]).name != item["save_game"] or item.get("side") not in (0, 1):
                    raise ValueError("Save-bank names must be basenames, with side 0 or 1")

    def connect(self):
        import win32file
        import win32pipe
        import pywintypes
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                self.handle = win32file.CreateFile("\\\\.\\pipe\\" + self.pipe,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                    win32file.OPEN_EXISTING, win32file.FILE_FLAG_OVERLAPPED, None)
                # Byte mode gives consistent newline buffering across message chunks.
                win32pipe.SetNamedPipeHandleState(self.handle, win32pipe.PIPE_READMODE_BYTE, None, None)
                return
            except (OSError, pywintypes.error) as exc:
                if self.handle is not None:
                    self.handle.Close()
                    self.handle = None
                if exc.winerror not in (2, 231):
                    raise BridgeError(f"Cannot connect to CONTROL: {exc}") from exc
                time.sleep(.05)
        raise BridgeError("CONTROL pipe unavailable. Start a compatible game and load the aoe2rl module.")

    def _io(self, data, deadline, read=False):
        import win32file
        import win32event
        import pywintypes
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        try:
            status, buffer = (win32file.ReadFile(self.handle, data, overlapped) if read
                              else win32file.WriteFile(self.handle, data, overlapped))
            if status == 997:
                wait = win32event.WaitForSingleObject(overlapped.hEvent, max(0, int((deadline-time.monotonic())*1000)))
                if wait != win32event.WAIT_OBJECT_0:
                    win32file.CancelIoEx(self.handle, overlapped)
                    # Retain the buffer until the cancellation completes.
                    try: win32file.GetOverlappedResult(self.handle, overlapped, True)
                    except (OSError, pywintypes.error): pass
                    raise BridgeError("CONTROL I/O timed out")
            size = win32file.GetOverlappedResult(self.handle, overlapped, False)
            return bytes(buffer[:size]) if read else None
        finally:
            overlapped.hEvent.Close()

    def _pop_json(self):
        # Accept newline-delimited, concatenated, and bare JSON messages. Never assume
        # one pipe read equals one complete message, including at UTF-8 boundaries.
        try:
            text = self.buffer.decode("utf-8").lstrip()
            if not text:
                self.buffer.clear()
                return None
            value, end = json.JSONDecoder().raw_decode(text)
        except (ValueError, UnicodeDecodeError):
            return None
        remaining = text[end:].encode("utf-8")
        self.buffer = bytearray(remaining)
        if not isinstance(value, dict):
            raise BridgeError("CONTROL envelope must be a JSON object")
        return value

    def request(self, payload):
        import win32file
        import win32pipe
        import pywintypes
        if self.handle is None:
            self.connect()
        request_id = uuid.uuid4().hex
        envelope = {"target": {"assignedPlayerId": self.player, "moduleName": self.module},
                    "payload": {**payload, "request_id": request_id}}
        deadline = time.monotonic() + self.timeout
        try:
            self._io((json.dumps(envelope) + "\n").encode(), deadline)
            while time.monotonic() < deadline:
                while self.buffer:
                    reply = self._pop_json()
                    if reply is None:
                        break
                    source = reply.get("source", {})
                    data = reply.get("payload", {})
                    if not isinstance(source, dict) or not isinstance(data, dict):
                        raise BridgeError("Malformed CONTROL routing envelope")
                    if source.get("assignedPlayerId") != self.player or source.get("moduleName") != self.module:
                        continue
                    if data.get("request_id") == request_id:
                        if data.get("error"):
                            raise BridgeError(data["error"])
                        return data
                _, available, _ = win32pipe.PeekNamedPipe(self.handle, 0)
                if available:
                    data = self._io(min(available, 65536), deadline, read=True)
                    self.buffer.extend(data)
                    if len(self.buffer) > 2**20:
                        raise BridgeError("CONTROL message exceeds 1 MiB")
                else:
                    time.sleep(.001)
        except (OSError, pywintypes.error, ValueError) as exc:
            self.close()
            raise BridgeError(f"CONTROL communication failed: {exc}") from exc
        except BridgeError:
            self.close()
            raise
        self.close()
        raise BridgeError(f"CONTROL timed out during {payload['op']}; no outcome inferred")

    def reset(self, seed, side):
        if not self.bank:
            raise BridgeError("A verified DE save bank is required; scenario files are not saved games")
        candidates = sorted((e for e in self.bank["entries"] if e["side"] == side), key=lambda e: e["seed"])
        if not candidates:
            raise BridgeError(f"No saved scenarios for side {side}")
        selected = candidates[seed % len(candidates)]
        return self.request({"op": "reset", "seed": selected["seed"], "side": side,
                             "save_game": selected["save_game"]})

    def step(self, **kwargs):
        return self.request({"op": "step", **kwargs})

    def close(self):
        if self.handle is not None:
            self.handle.Close()
            self.handle = None
        self.buffer.clear()
