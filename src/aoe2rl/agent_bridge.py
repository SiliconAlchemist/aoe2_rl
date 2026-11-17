"""CONTROL 1.1.1+ native Agent Bridge v3 client and read-only connection probe."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from .core import BridgeError
from .transport import ControlPipe


class AgentBridge:
    def __init__(self, player=1, timeout=5.):
        if player not in range(1, 9):
            raise ValueError("Player must be 1 through 8")
        self.player, self.timeout, self.session = player, timeout, None

    def request(self, operation, payload=None):
        import pywintypes
        pipe = ControlPipe(player=self.player, timeout=self.timeout,
                           pipe=f"AoE2ControlAgentV3.P{self.player}")
        request = dict(contract_version=3, operation=operation, payload=payload or {})
        if operation not in ("status", "open"):
            if not self.session:
                raise BridgeError("Open an Agent Bridge session first")
            request["session"] = self.session
        encoded = json.dumps(request).encode("utf-8")
        if len(encoded) > 1024**2:
            raise BridgeError("Agent Bridge request exceeds 1 MiB")
        try:
            pipe.connect()
            deadline = time.monotonic() + self.timeout
            pipe._io(encoded, deadline)
            while time.monotonic() < deadline:
                pipe.buffer.extend(pipe._io(65536, deadline, read=True))
                if len(pipe.buffer) > 16*1024**2:
                    raise BridgeError("Agent Bridge response exceeds 16 MiB")
                response = pipe._pop_json()
                if response is None:
                    continue
                if response.get("ok") is not True:
                    error = response.get("error", {})
                    raise BridgeError(f"Agent Bridge {operation}: {error}")
                data = response.get("data")
                if not isinstance(data, dict):
                    raise BridgeError("Malformed Agent Bridge response data")
                if operation == "open":
                    self.session = data.get("session")
                    if not isinstance(self.session, str) or not self.session:
                        raise BridgeError("Agent Bridge returned no session id")
                elif operation == "close":
                    self.session = None
                return data
            raise BridgeError(f"Agent Bridge {operation} timed out")
        except (OSError, pywintypes.error) as exc:
            hint = " Run the client under the same Windows user as DE." if getattr(exc, "winerror", None) == 5 else ""
            raise BridgeError(f"Agent Bridge connection failed: {exc}.{hint}") from exc
        except BridgeError as exc:
            message = str(exc)
            if "pipe unavailable" in message:
                raise BridgeError(f"Agent Bridge pipe for player {self.player} is unavailable. "
                                  "Enable Agent Bridge in Modules and in that player's section.") from exc
            if "Access is denied" in message:
                raise BridgeError(message + " Run the client under the same Windows user as DE.") from exc
            raise
        finally:
            pipe.close()  # Protocol uses one connection per request.


def probe(output, player=1, observe=False):
    client = AgentBridge(player)
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), connected=False,
                  live_validated=False, stage="status", error=None)
    try:
        report["status"] = client.request("status")
        report["connected"] = True
        if report["status"].get("player_id") != player:
            raise BridgeError("Agent Bridge reported an unexpected player id")
        if report["status"].get("information_policy") != "player_view":
            raise BridgeError("Expected player_view; turn Modules See Everything off")
        report["stage"] = "open"
        opened = client.request("open", {"client_name": "aoe2-rl-lab-probe"})
        report["session_info"] = {k: v for k, v in opened.items() if k != "session"}
        if opened.get("information_policy") != "player_view":
            raise BridgeError("Session information policy is not player_view")
        if observe:
            report["stage"] = "observe"
            report["observation"] = client.request("observe", {"object_types": "none", "technologies": "none"})
        report["stage"] = "complete"
    except BridgeError as exc:
        report["error"] = str(exc)
    finally:
        if client.session:
            try:
                client.request("close")
            except BridgeError as exc:
                report["close_error"] = str(exc)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", type=int, default=1, choices=range(1, 9))
    parser.add_argument("--output", default="reports/agent-bridge.json")
    parser.add_argument("--observe", action="store_true")
    args = parser.parse_args()
    result = probe(args.output, args.player, args.observe)
    print(json.dumps({k: v for k, v in result.items() if k not in ("session_info", "observation")}, indent=2))
    if result["error"] or result.get("close_error"):
        parser.exit(2, "Agent Bridge probe incomplete; see the saved report.\n")
