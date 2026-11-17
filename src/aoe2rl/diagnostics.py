import hashlib
import json
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import psutil


def inspect_machine(game, output):
    game = Path(game)
    executable = game/"AoE2DE_s.exe"
    scripts = game/"resources/_common/ai/Promisory"
    entry = game/"resources/_common/drs/gamedata_x2/PromiDE.per2"
    files = []
    for path in ([entry] if entry.exists() else []) + sorted(scripts.glob("*.per")):
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        files.append(dict(path=str(path.relative_to(game)), sha256=hashlib.sha256(data).hexdigest(),
                          bytes=len(data), lines=len(text.splitlines()),
                          rule_count=len(re.findall(r"(?m)^\s*\(defrule\b", text)),
                          extreme_branches=[n for n, line in enumerate(text.splitlines(), 1)
                                            if "DIFFICULTY-EXTREME" in line and not line.lstrip().startswith(";")]))
    try:
        gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        gpu = None
    version = None
    if executable.exists() and platform.system() == "Windows":
        import win32api
        v = win32api.GetFileVersionInfo(str(executable), "\\")
        version = ".".join(str(x) for x in ((v["FileVersionMS"]>>16)&65535, v["FileVersionMS"]&65535,
                                            (v["FileVersionLS"]>>16)&65535, v["FileVersionLS"]&65535))
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), game=str(game), game_exists=executable.exists(),
                  game_version=version, logical_cpus=psutil.cpu_count(), physical_cpus=psutil.cpu_count(logical=False),
                  ram_bytes=psutil.virtual_memory().total, available_ram_bytes=psutil.virtual_memory().available,
                  workspace_free_bytes=shutil.disk_usage(Path.cwd()).free, gpu=gpu, python=platform.python_version(),
                  ai_files=files, total_rules=sum(f["rule_count"] for f in files),
                  live_bridge_verified=False)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {k: v for k, v in report.items() if k != "ai_files"}
