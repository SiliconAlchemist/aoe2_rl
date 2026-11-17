# Project structure and relocation

The `aoe2_rl` folder is the repository root. Python code lives in `src/aoe2rl`; its import name remains `aoe2rl` for command and checkpoint compatibility. Source installation uses the `src` layout configured in `pyproject.toml`. Operational scripts and game modules are outside the Python package.

## Python responsibilities

| Area | Modules under `src/aoe2rl/` |
| --- | --- |
| Native game connection | `agent_bridge.py`, `transport.py` |
| Replay conversion and validation | `replay_data.py`, `replay_examples.py`, `replay_audit.py` |
| Project and dataset paths | `paths.py` |
| Scripted opening and its learner | `opening.py`, `opening_env.py`, `train_opening.py` |
| Earlier combat/synthetic learning | `core.py`, `env.py`, `synthetic.py`, `learning.py`, `evaluation.py` |
| Experiment CLI and scenario generation | `cli.py`, `scenarios.py` |
| Diagnostics and compatibility investigation | `diagnostics.py`, `probe.py`, `compatibility.py`, `runtime_probe.py` |

Modules remain at their existing import paths. This move does not rename Lua modules, named pipes, checkpoint classes, saved replay IDs or CLI commands. Further domain-package splitting can happen when those interfaces need a functional redesign.

## Setup and execution

Run commands from the root containing `pyproject.toml`, not its parent and not `src/`. Both local environments use editable installation, so source changes are immediately available without reinstalling. A fresh checkout must install the package before running module commands or scripts that import it.

`scripts/setup_environment.ps1 -Environment both` creates Python 3.12 environments, installs requirements, registers this package, refreshes activation/launchers and patches the isolated replay parser. The main environment uses the CUDA wheel source in the existing lockfile workflow. Replay setup uses `--no-deps` when installing this project to avoid pulling training dependencies into the small parser environment.

After moving the checkout, `scripts/setup_environment.ps1 -Environment both -ReuseInstalled` re-registers the source and refreshes activation and installed entry-point launchers. It preserves installed libraries and the existing parser patch; activation/configuration backups go under `.cache/environment-move-backups/`. Packaging build dependencies may still be downloaded. This helper addresses this checkout's same-machine path move, not migration to another Python installation or operating system; recreate environments for those changes.

Temporary packaging files live under `.cache/package-install/` to avoid the Windows temporary-directory rename failure encountered during the move. No administrator launch or security-setting change was needed.

## Dataset path compatibility

New in-project replay references are relative to the repository root. `paths.py` finds the root from the source checkout. Set `AOE2RL_PROJECT_ROOT` only when running an installed package against a separate checkout.

Historical capture reports contain metadata hashes. Rewriting those metadata files just to replace a directory would invalidate that evidence. The replay tools instead resolve historical absolute `data/replays/...` references to the same subtree in the current checkout when it exists. Their hash checks remain in force. External original recordings under the game's savegame directory are not relocated or substituted by filename.

Historical reports may still display the previous absolute path. This is expected: generated evidence is preserved. New outputs use portable references where the referenced file is in the project. CLI output directories are relative to the repository root for replay commands; other experiment tools should continue to be invoked from the root.

## What is source-controlled

Keep source, scripts, tests, Lua modules, shared configs, dependency requirements and documentation in Git. Local data under `data/replays`, reports, runs, downloaded vendor files, virtual environments and caches are ignored. No existing data was deleted or reparsed as part of the restructure. The subsequent GitHub preparation initialized a local repository on `main`; see [publication steps](PUBLISHING.md). No remote has been published by that preparation.

The November 5 restructure installed the source package into both existing environments and repaired their activation and launchers. Tests, replay capture, game commands and model training were not run.
