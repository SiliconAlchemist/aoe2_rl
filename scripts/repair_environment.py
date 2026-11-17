"""Refresh an existing local environment's activation and launchers after a move.

Run with that environment's python.exe. Does not download packages or replace
installed libraries; reinstall this project in editable mode separately.
"""
from datetime import datetime, timezone
from importlib.metadata import distributions
import json
from pathlib import Path
import shutil
import sys
import venv


def main():
    root = Path(__file__).resolve().parents[1]
    environment = Path(sys.prefix).resolve()
    allowed = {root/".venv", root/".venv-replays"}
    if environment not in allowed or sys.prefix == sys.base_prefix:
        raise SystemExit("Use this checkout's .venv or .venv-replays python.exe")
    from pip._vendor.distlib.scripts import ScriptMaker
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root/".cache"/"environment-move-backups"/environment.name/stamp
    backup.mkdir(parents=True)
    for path in (environment/"pyvenv.cfg", environment/"Scripts"/"activate",
                 environment/"Scripts"/"activate.bat", environment/"Scripts"/"Activate.ps1"):
        if path.exists(): shutil.copy2(path, backup/path.name)
    builder = venv.EnvBuilder(with_pip=False)
    context = builder.ensure_directories(str(environment))
    builder.create_configuration(context)
    builder.setup_scripts(context)
    maker = ScriptMaker(None, str(environment/"Scripts"))
    maker.executable = str(environment/"Scripts"/"python.exe")
    maker.clobber = True
    maker.variants = {""}
    refreshed = []
    for distribution in distributions():
        for entry in distribution.entry_points:
            if entry.group not in ("console_scripts", "gui_scripts"): continue
            if Path(entry.name).name != entry.name: raise ValueError("Invalid entry-point filename")
            maker.make(f"{entry.name} = {entry.value}", {"gui": entry.group == "gui_scripts"})
            refreshed.append(entry.name)
            if entry.name == "pip":
                for alias in (f"pip{sys.version_info.major}", f"pip{sys.version_info.major}.{sys.version_info.minor}"):
                    maker.make(f"{alias} = {entry.value}")
    report = dict(environment=str(environment), activation_backup=str(backup),
                  refreshed_entry_points=sorted(set(refreshed)), packages_reinstalled=False)
    (backup/"repair.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(f"Refreshed activation and {len(set(refreshed))} entry points in {environment.name}.")
    print(f"Previous activation files saved in {backup}")


if __name__ == "__main__":
    main()
