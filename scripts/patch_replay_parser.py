"""Apply the two narrowly scoped header fixes proposed in aoc-mgz PR #147.

Source: https://github.com/happyleavesaoc/aoc-mgz/pull/147
Only the isolated mgz 1.8.51 environment is supported. No game files are changed.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path

import mgz.fast.header


if importlib.metadata.version("mgz") != "1.8.51":
    raise SystemExit("This adapter is scoped to mgz 1.8.51; review before updating")
target = Path(mgz.fast.header.__file__)
original = target.read_bytes()
source = original.decode("utf-8")
marker = "# aoe2rl: upstream PR147 header fields"
if marker not in source:
    patches = [
        ("        if save >= 64.3:\n            data.read(4)\n",
         "        if save >= 64.3:\n            data.read(4)\n        if save >= 67.2:\n            de_string(data)  " + marker + "\n"),
        ('    ai = unpack(\'<I\', header)\n',
         '    if save >= 67.2:\n        header.read(8)  ' + marker + '\n    ai = unpack(\'<I\', header)\n'),
    ]
    source = source.replace("\r\n", "\n")
    for old, new in patches:
        if source.count(old) != 1:
            raise SystemExit("Parser source differs from the reviewed version; no patch written")
        source = source.replace(old, new)
    backup = target.with_suffix(".py.original")
    if not backup.exists():
        backup.write_bytes(original)
    target.write_text(source, encoding="utf-8", newline="\n")
report = {"package": "mgz", "version": "1.8.51", "patch": "PR147-two-header-fields",
          "source": "https://github.com/happyleavesaoc/aoc-mgz/pull/147",
          "patched_file": str(target), "patched_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
Path("reports").mkdir(exist_ok=True)
Path("reports/replay-parser-adapter.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
print(json.dumps(report, indent=2))
