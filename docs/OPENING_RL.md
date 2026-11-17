# Train the two-house opening

Status, 31 October 2026: the user successfully ran the scripted opening. The new RL learner, environment and restart helper have been written but **have not been executed or tested**, at the user's request. No trained opening checkpoint exists yet. The earlier 51-test result does not cover these files.

## One-time setup

Use the existing project virtual environment; no new packages are required. In PowerShell under the same Windows account as Steam:

```powershell
# Run from the cloned repository root, beside pyproject.toml.
.\scripts\install_opening_reset.ps1
```

This copies one module to `%APPDATA%\CONTROL\AoE2Control\modules\opening_reset\`. It backs up an existing copy and does not change CONTROL settings. If this was already installed during setup, skip the command.

1. Open DE through Steam. Attach CONTROL as for the successful scripted test. If needed, run:

```powershell
& '.\vendor\AoE2Control-1.1.5\AoE2Control.exe' --headless --timeout-ms 30000 2>&1 | Tee-Object -FilePath reports/opening-training-launch.txt
```

2. Press Shift in DE. In CONTROL's **Modules** section, turn **Enabled** and **Agent Bridge** on. Keep **See Everything**, **Multithreading**, and **Tournament Mode** off. Keep **Suppress Native AI** on.
3. Under **Player 1**, enable that slot, enable **Agent Bridge**, and select **opening_reset** in the Module list. Do not assign the old `aoe2rl` combat module. Leave the module Update Interval at 1.0 game-seconds or less. Hide CONTROL with Shift.
4. Start a disposable **single-player** Arabia skirmish: Player 1 **human**, Sicilians, Dark Age, standard resources, normal fog, cheats off, Fast speed, easy opponent. Leave it unpaused. Do not run the opening script alongside the trainer. The learner alone must control Player 1.

Player 1 being human avoids a built-in AI issuing competing strategic orders. Pathfinding and normal unit behavior remain part of the game. This is a practice opening, not an Extreme evaluation.

## Short first training run

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.train_opening train --execute --episodes 4 --warmup 2 --horizon 180 --minutes 12 --output runs/opening-first
```

This requests **two imitation episodes followed by two PPO episodes**, each capped at three game-minutes. At Fast speed, four full episodes would use roughly six real minutes plus reset/processing overhead; this is an estimate, not measured throughput. The wall-clock cap is twelve minutes. The script checks its budget between steps; a blocking reset or pipe request can add its bounded timeout. A partial episode is discarded when the budget expires.

Each episode restarts the current disposable match, verifies a new world and fresh game clock, and checks the starting units/resources. A reset accepted by CONTROL is not enough: Python also waits for the new game state and the helper's new generation. **This integration has not yet been verified live.** If it fails, send `runs/opening-first/summary.json` and the reset-helper error shown in CONTROL. It stops instead of learning from a failed reset.

You do not need to manually restart between episodes when the helper works. Keep DE running and unpaused. Ctrl+C in PowerShell stops the trainer; F3 pauses the game. Stopping the trainer does not cancel the units' last orders. No background job or overnight schedule is installed.

## What learns, and what stays scripted

The model is a small recurrent actor-critic trained with PPO. During the first two episodes, a teacher supplies action labels and the model imitates them. Thereafter, sampled model actions receive game rewards and PPO updates the model after each complete episode. Two warm-up episodes are a short setup exercise, not enough to assume a reliable policy.

The model chooses among legal candidate commands: wait; build at one of several sites with one or two specific villagers; send an individual livestock home; explore a direction with a scout or livestock; approach visible neutral livestock with the scout. It receives player-view observations, relative positions, task progress, resource information and candidate features. A GRU carries memory between decisions. There is at most one command per decision, with a minimum two game-seconds between decisions by default.

Constraints intentionally narrow this first RL problem: two houses maximum, a 2+1 builder split, at most two reserved livestock, exploration within 40 tiles of the TC, and up to eight owned livestock exposed as candidates. Placement checks, frontier generation and pathfinding remain scripted/game-provided. The network learns timing, assignment and candidate selection; it does not learn arbitrary mouse control or the entire game. The teacher is defined on this same action interface, not inferred from the earlier JSON log, which lacks complete policy observations.

Reward uses progress toward houses, livestock at the TC, acquiring additional livestock, new explored tiles and explorer movement. It includes a time cost, penalties for rejected game commands and loss of essential units, and a completion bonus. Repeatedly moving livestock in and out of the TC does not accumulate a fresh one-time reward: progress is a discounted potential difference. A task deadline is terminal, with partial task score; a bridge/reset failure is an infrastructure error and never a game loss.

Success requires both houses completed, two reserved livestock within 2.5 tiles of the TC, at least one additional livestock acquired, at least 250 new nearby tiles explored, the scout moving over five tiles, and at least two surviving non-reserved livestock exploring over five tiles. Acquisition is an ownership-change measure, not proof that the scout was the first unit to see it.

## Results and continuation

Files under `runs/opening-first/`:

- `checkpoint.pt`: model, optimizer and random-generator state after each completed training episode.
- `episodes.jsonl`: imitation/PPO phase, reward, success, individual task metrics and restart evidence.
- `actions.jsonl`: selected game commands and observed progress.
- `summary.json`: completed episodes and any blocker.
- `run-config.json`: task configuration.

The first four episodes establish only that collection and updates work. Failure to achieve the opening immediately is normal for a newly initialized policy. The teacher's success and the learned policy's success are logged separately by phase. Do not interpret the combined success count as learned-policy performance.

After inspecting the short run, continue the same checkpoint for 20 **additional** episodes:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.train_opening train --execute --episodes 20 --warmup 2 --horizon 180 --minutes 45 --output runs/opening-first --resume runs/opening-first/checkpoint.pt
```

Resume preserves the task, seed, horizon, action interval, warm-up count and reset mode. Completed imitation episodes do not repeat. This tiny model defaults to CPU; `--device cuda` is available but no speed advantage has been measured.

Watch a checkpoint play without updates:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.train_opening evaluate --execute --episodes 2 --horizon 180 --minutes 8 --checkpoint runs/opening-first/checkpoint.pt --output runs/opening-evaluation
```

Automatic restart repeats the current match setup. Do not assume it generates independent maps; effective seeds are logged when CONTROL supplies them. Same-map results are diagnostics, not generalization evidence. For a genuine holdout, manually create different Arabia maps, select `--reset manual`, use a separate output folder and `--label heldout-manual-maps`, and follow the terminal's restart prompts. The label records your intent; it does not automatically enforce seed separation.

## Manual-reset fallback

If the new reset module is blocked, you can still train with the native bridge alone:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.train_opening train --execute --reset manual --episodes 4 --warmup 2 --horizon 180 --minutes 15 --output runs/opening-manual
```

At each prompt, manually restart/start a fresh match, unpause it, and press Enter in PowerShell within 15 game-seconds. The script requires a different world after each episode. Manual input time is included in reported wall time, but waiting at the input prompt itself is not automatically timed out. Use a separate run folder when changing reset modes.

The successful scripted run does not yet establish the new reset module or RL environment's correctness. No live validation flags from the old combat pipeline are changed. No synthetic environment is silently substituted. Full-game training, competitive evaluation, and unattended training across many maps remain separate work.

Official API references: [Agent Bridge](https://aoe2control.github.io/agent-bridge/), [session control](https://aoe2control.github.io/session-control/), [module lifecycle](https://aoe2control.github.io/lifecycle/).
