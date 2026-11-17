# Imitation examples — 31 October 2026

**Folder update — 5 November 2026:** Run from the `aoe2_rl` repository root. The package now lives under `src/aoe2rl` and is installed in both local environments; module command names are unchanged. Historical dataset paths resolve through `aoe2rl.paths` without modifying hashed metadata. See [project layout](PROJECT_LAYOUT.md).

All 10 staged recordings were converted offline. Player 1 is selected in each recording, as authorized; this includes different people and civilizations, without a skill or winner filter.

| Output | Count |
| --- | ---: |
| Parsed recordings | 10 |
| Player 1 commands | 19,629 |
| Commands with partial action labels | 8,203 |
| Command-history examples | 8,196 |
| Training / validation recordings | 8 / 2 |
| Nonempty training / validation recordings | 7 / 2 |
| Provisional state/action examples (Arena pilot) | 32 |

One training recording ends after 1.144 seconds and contributes no history examples. Whole recordings are separated into train and validation sets; repeated perspectives sharing a game GUID stay in the same split. This small collection is for establishing the pipeline, not measuring competitive strength.

## Files already generated

`data/replays/extracted-v1/summary.json` indexes the dataset. Each SHA-256 folder contains:

- `metadata.json`: player, civilization, map, provenance, starting-unit anchors and conversion counts.
- `commands.jsonl`: selected-player raw command records, parser timestamps, partial labels and explicit exclusion reasons.
- `history_examples.jsonl`: up to 16 earlier commands from that player as input, then the next partial command and delay as targets.

The history examples describe command sequences, not the game state. Their inputs exclude future commands, match outcomes, chat and other players' commands. Absolute object IDs are replay-local references, not reusable unit identities for a policy. A future learner must map them to observed entity slots. These files do not plug into the existing opening learner.

The converter uses `mgz` 1.8.51 in `.venv-replays`, separate from the training environment. Its published parser initially failed on these save-version 68.9 headers. `scripts/patch_replay_parser.py` applies two narrow header adjustments proposed in [upstream PR #147](https://github.com/happyleavesaoc/aoc-mgz/pull/147). The patched-file hash is in `reports/replay-parser-adapter.json`. All 10 bodies were consumed to EOF with zero undecoded actions reported. That does not independently verify every field's semantics.

Raw body commands are used instead of the parser's enriched action list: the latter can fill missing selections using a cache shared across players. Unresolved selections are excluded from labels here. Shift/queue modifiers remain unknown; `enqueue.additional_amount` means an increment, not the bridge's desired queue count. Winner inference from resignations is metadata only, not a verified win/loss target.

## Your next step: capture three game minutes

The user subsequently completed the Arena pilot capture: 781 observations produced 32 provisional pairs. See `reports/arena-v1-data-review.md` for offline timing evidence and remaining checks. No model training or automated tests were run. The instructions below remain the recipe for another capture; use a fresh output directory and the matching metadata.

1. Open DE through Steam and attach CONTROL as before. Enable Agent Bridge under Modules and Player 1. Turn **See Everything off**. Disable other automation modules while recording.
2. For the original local pilot, load **`MP Replay v101.103.57257.0 @2026.10.31 152644 (2).aoe2record`**: **Player 1, Varangians vs Sicilians, Glade**. This recording is not distributed. On a fresh checkout, choose your own extracted metadata and matching replay as shown in the [README](../README.md#replay-workflow). Select the chosen player's view and normal fog. Pause within the first five game seconds. Use normal or slower playback; do not seek.
3. In PowerShell, from this project folder, run:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.replay_examples capture --confirm-replay
```

4. When it prints **“Replay identity checks passed”**, unpause. It stops after three game minutes, or fails after a ten-minute wall-time limit. If paused for 60 seconds, it stops with a useful error. It only calls status/open/observe/close and never issues a game action. You can stop with Ctrl+C; incomplete captures are retained for diagnosis but excluded by the pairing tool.
5. After a complete capture, produce provisional pairs:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.replay_examples join
```

Capture results are in `data/replays/captures/first-v1/capture.json` and `observations.jsonl.gz`. Paired examples and rejection counts go to `data/replays/paired/first-v1/`. Existing output directories are never overwritten. For another attempt use `capture --confirm-replay --output data/replays/captures/first-v2`, then `join --capture data/replays/captures/first-v2 --output data/replays/paired/first-v2`.

To choose a different recording, pass its extracted `metadata.json` to `capture --metadata PATH --confirm-replay` and load that exact recording in DE. The defaults use the intake manifest's initial conversion candidate.

## Recorder improvements and sample audit

The saved Arena pilot passed source-hash, player/world, monotonically increasing clock/sequence, causal input, label-provenance and position-only entity-field checks. This is offline data validation, not independent validation of the game bridge. The detailed report is `reports/arena-v1-audit/review.md`.

The stricter effect audit looks only before the next Player 1 command and for at most 1.5 seconds. Of 32 examples, 21 have a matching observed effect. Seven of 16 production attempts show no queue increase in that window; their preceding food balances were low. Three moves and one target command also lack a matching effect in that restricted window. Absence of an effect is not proof of failure, and the audit does not silently discard them or assert successful execution. Raw recorded commands are **attempts**, not guaranteed outcomes.

The recorder now:

- Prints progress every ten wall seconds and explicitly says that replay playback continues after capture.
- Supports `--full-replay`, stopping at the parsed endpoint or a same-world end result reported by the bridge. This records a stopping reason, not a verified victory label. A stall, disconnect or game closure without that evidence remains incomplete.
- Scales its wall-time allowance with the requested capture length; `--wall-seconds` still overrides it.
- Records frame-gap statistics and uses request-start pacing to avoid adding a full interval after every bridge response.
- Saves a diagnostic map every five wall seconds by default. Maps are bracketed by observations, have their own file/hash and are never attached to an earlier model input. Unexplored terrain/elevation must be masked and passability zero. `--map-every 0` disables map collection. These extra requests can increase observation gaps.

The pairing tool additionally writes `command_groups.jsonl.gz`, retaining ordered same-tick commands against one earlier state, with masks for unresolved labels. It never interprets a partially labelled group as a complete action sequence or a no-op. Use either grouped or single-action data for a given command, not both as independent examples. The current pilot contains no retained multi-command group; it gains no extra labels from this change.

Schema 2 model inputs retain own-unit activity, cargo, production/research counts and progress. They replace the full engine resource array with named food/wood/stone/gold balances plus age and housing headroom. Unreviewed facts, diplomacy arrays and arbitrary engine counters are excluded. `access: position` entities receive only identity/type/owner/position fields. Known position-only targets are allowed, as documented by the [bridge](https://aoe2control.github.io/agent-bridge/).

Repeated unit selection remains unresolved. The installed parser drops the original selection-count marker, and its high-level helper caches selections across players. A per-player cache would still be a hypothesis about reuse across action types. We have **not** used that hypothesis to fabricate labels. In this pilot, 35 of 73 commands inside the capture interval have unresolved selections. Raw commands remain available for a later format-specific decoder.

The new capture branches have not been exercised live, and no automated tests or training were run. First collect a five-minute pilot before using full-replay capture. This also limits data size while we measure the richer recorder; offline joining/auditing currently loads the observation file into memory.

Load the same Arena recording from the beginning, pause within five seconds, keep Player 1 normal fog and See Everything off, then run:

```powershell
$meta = "data/replays/extracted-v1/e2b3751dfa489717cf1466f84cbe79cc412ea0d923617414362e5da1ea16016f/metadata.json"
.\.venv\Scripts\python.exe -m aoe2rl.replay_examples capture --metadata $meta --confirm-replay --seconds 300 --interval 0.05 --output data/replays/captures/arena-v2
.\.venv\Scripts\python.exe -m aoe2rl.replay_examples join --capture data/replays/captures/arena-v2 --output data/replays/paired/arena-next
.\.venv\Scripts\python.exe -m aoe2rl.replay_audit --capture data/replays/captures/arena-v2 --paired data/replays/paired/arena-next --output reports/arena-next-audit
```

Run the join only after capture completes, and the audit only after the join completes. Unpause when capture prompts. Use normal playback for this first run. Original captures and outputs are preserved; all new output directories must be fresh.

## What must be checked in that first run

The recorder checks replay mode, player-view policy, selected player, map size, starting-unit IDs and TC position. It rejects a changed world or a clock that goes backwards. These checks support your confirmation of the replay filename; the bridge does not expose a cryptographic recording identity.

The single-action joiner selects the most recent frame **strictly before** a command, at most 250 game milliseconds old. It excludes simultaneous commands, intervening commands, missing/dead/unowned actors, unknown targets and out-of-map coordinates. The separate grouped output preserves same-tick command groups. It does not interpolate states or guess missing selections. Faster playback or slow bridge calls may therefore yield few or zero pairs; inspect the rejection counts before expanding the capture.

The first live capture still needs a clock and fog check: compare several known opening actions with their recorded timestamps, and check that unexplored enemy units/resources do not appear in the observations. `player_view` is a runtime assertion, not independent verification of the bridge's fog implementation. No timestamp offset is guessed or silently applied. Outputs remain marked `alignment_verified: false` until that review.

The first pairs contain own-player attributes and permitted entity fields. They omit asynchronous map data, research availability and other richer features. They supervise only decoded action fields, omit queue modifiers, and do not supply legal-action masks, no-op samples or authoritative outcomes. They are a starting point for partial action supervision, not an executable full-game policy. The full-game model, action adapter and integration with reinforcement learning remain separate work.

## If something blocks capture

- **Pipe unavailable:** CONTROL must be attached and Agent Bridge enabled globally and for Player 1.
- **Access denied:** run PowerShell as the same Windows user running DE. No antivirus exception is needed for this script.
- **Observe timeout while paused:** the bridge may not service observations in that paused state. Reload at the start, use slow playback and start capture immediately; keep the five-second check intact.
- **Identity mismatch:** the original local default expects the October 31 Glade replay. To capture a different recording, pass its extracted `metadata.json` using `--metadata`. The error shows expected/observed player names and TC IDs/positions; `initial-observation.json` preserves the observation even when capture stops before its first frame. Keep these files for diagnosis rather than removing the check.
- **Zero examples:** inspect the pairing summary. Timing, unsupported actions and unresolved selections are reported separately.

## Recreate offline extraction later

The environments and converted files already exist. These commands are for recreation, not required before your first capture:

```powershell
.\.venv\Scripts\python.exe -m venv .venv-replays
.\.venv-replays\Scripts\python.exe -m pip install -r requirements-replays.txt
.\.venv-replays\Scripts\python.exe -m pip install --no-deps -e .
.\.venv-replays\Scripts\python.exe scripts/patch_replay_parser.py
.\.venv-replays\Scripts\python.exe -m aoe2rl.replay_data --output data/replays/extracted-v2
```

Original recordings remain unchanged. Local replay data and derived examples are ignored by Git. No recording contents were uploaded.
