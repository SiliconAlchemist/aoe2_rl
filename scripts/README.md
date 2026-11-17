# Operational scripts

Run from the repository root after environment setup. These scripts have different effects; only run the one for the intended task.

| Script | Purpose |
| --- | --- |
| `setup_environment.ps1` | Install environments and register `src/aoe2rl`; `-ReuseInstalled` repairs the local folder move |
| `repair_environment.py` | Refresh activation and entry-point paths using the selected environment's Python |
| `import_recordings.py` | Catalogue and stage local recordings; preserves originals |
| `patch_replay_parser.py` | Apply the scoped mgz header adapter in the isolated replay environment |
| `install_opening_reset.ps1` | Install the CONTROL Lua helper into the user's application-data directory |
| `smoke_native_control.py` | Explicit live movement/building probe; sends game commands when authorized through its CLI |
| `run_campaign.py` | Run or resume the configured training/evaluation campaign |
| `summarize_campaign.py` | Summarize saved campaign results |
| `locate_ai_symbols.py` | Earlier offline/native compatibility investigation |

Replay capture, pairing and audit are package commands: `python -m aoe2rl.replay_examples` and `python -m aoe2rl.replay_audit`. They retain their existing names after the source-layout move.
