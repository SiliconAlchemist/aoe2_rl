"""Read-only bring-up check; never enables training or changes a match."""
import json
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .core import BridgeError
from .transport import ControlPipe


def probe(output, player=1, timeout=5., pipe="AoE2RL"):
    processes = []
    for process in psutil.process_iter(["name", "pid"]):
        if (process.info["name"] or "").lower() in ("aoe2de_s.exe", "aoe2control.exe"):
            processes.append(process.info)
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), processes=processes,
                  connected=False, live_validated=False, stage="connect", error=None)
    backend = ControlPipe(player=player, timeout=timeout, pipe=pipe)
    try:
        backend.connect()
        report["stage"] = "ping"
        pong = backend.request({"op": "ping"})
        if pong.get("op") != "pong":
            raise BridgeError("Unexpected ping response; confirm the installed module version")
        report["ping"] = pong
        report["stage"] = "inspect"
        state = backend.request({"op": "inspect"})
        if state.get("op") != "inspection" or state.get("schema") != 1:
            raise BridgeError("Unexpected inspection response; update the candidate Lua module")
        report.update(connected=True, stage="complete", inspection=state)
    except (BridgeError, OSError) as exc:
        report["error"] = str(exc)
    finally:
        backend.close()
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
