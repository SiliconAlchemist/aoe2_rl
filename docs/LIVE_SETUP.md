# Live DE integration and validation

## Current native bridge route

As of 31 October, the official 1.1.5 release works with DE 101.103.57257.0 and the native Agent Bridge handshake succeeds. Follow [AGENT_BRIDGE_SETUP.md](AGENT_BRIDGE_SETUP.md) for current connection instructions. The Lua backend below remains an unvalidated earlier candidate; the new native client has not yet been wired into CombatEnv.

## September blocker (historical)

The running game is `C:\Program Files\Steam\steamapps\common\AoE2DE`, version `101.103.54800.0` as of 26 September. A separate older installation exists on D:. Use the C: installation for subsequent work.

The previous Windows block did not recur after user-requested reinstallation. Release hashes were verified, and security settings remained unchanged. The bridge reached startup diagnostics but reported **Outdated**: missing `GameScreenContainer` (critical) and `CanAffordResearch` signatures. The pilot module was installed with `audited=false`, but no working connection was established. An antivirus exception cannot repair this incompatibility. See `reports/control-diagnostics-2026-09-26.json`.

The manifest records testing on `101.103.48987.0`, still the candidate config's target version. Do not relabel that config as compatible with the updated game. The user reports no older Steam Betas are available. Obtain an updated bridge before continuing, and restart DE cleanly before the next attachment attempt.

After compatibility is restored, run `python -m aoe2rl.cli probe --timeout 5` in the project environment. It saves a staged report and performs only `ping` and fog-filtered `inspect` requests, even while `audited=false`. It does not start, reset, or command a match, or certify a fairness audit. Requests are processed in the game's update callback; menus and paused games may not service them.

The older open-source `FLWL/aoe2-ai-module` was assessed: release history ends in March 2021; its project targets Visual Studio v142 and Windows SDK 10.0.18362.0 and depends on gRPC, Protobuf, Detours and Zydis. Visual Studio 2022 is available locally, but an up-to-date compatible build has not been produced. Its documented DE crashes/anti-tampering issues make it a separate porting task, not a validated fallback. See https://github.com/FLWL/aoe2-ai-module.

## Candidate bridge contract

`bridge/aoe2rl` implements the CONTROL Lua side. Python sends routed messages to `\\.\pipe\AoE2RL`; replies carry the documented `source` / `payload` envelope. Every operation includes a request ID. Reset creates a fresh episode ID; steps must increment sequence numbers exactly once.

Observations contain five own-unit slots and five visible/remembered enemy slots, plus time and counts. Each slot contains normalized position, HP fraction, presence, current visibility, and age of remembered information. Hidden objects are rejected before reading their dynamic fields. No enemy resource totals, technologies, global score, hidden units or unexplored terrain enter the policy.

Actions: 0 continues the existing order; 1–8 move the group two tiles along eight compass directions; 9 attacks the nearest currently visible enemy. **Action 0 is not stop or hold-position.** Commands target owned units only and are limited to one per 0.5 game-seconds. The native pathfinder can reject a geometrically valid move; that is an explicit bridge failure for this pilot, not silently relabeled experience.

The bridge is asynchronous. It issues one command, waits for at least the requested game-time interval, then reports a fresh snapshot. Game time may also advance during learner computation. Python records actual elapsed game time and uses time-adjusted discounts. There is no claim of frame-exact stepping, paused simulation, or rendering-free execution.

The candidate live bridge uses sparse terminal rewards. Damage shaping is enabled only in the synthetic fixture until live damage telemetry is validated. Enemy disappearance never means victory; only a verified game winner is accepted. Manual exit without a winner is an infrastructure error.

## Bring-up after the blocker is resolved

1. Record the game build, bridge release, and hashes. Keep the game in single-player. Back up any existing CONTROL settings before changing them.
2. Use CONTROL's documented module installation/assignment workflow to load `aoe2rl` for player 1 and `opponent` for player 2. Verify **Modules See Everything off**, **Suppress Native AI on**, and **Multithreading off**. These settings are essential; the Python audit flags do not set or read them automatically.
3. Generate scenario layouts with the `scenarios` command. Load the scenario through DE, verify two players with five Byzantine archers each, Feudal Age, no extra resources/units/upgrades, 32×32 flat grass, enemy diplomacy, and normal fog. Check that elimination triggers declare victory only at zero surviving archers. Simultaneous elimination and native scenario victory behavior still require in-game testing.
4. Prepare genuine starting `.aoe2spgame` files with the group at its intended initial state. Put their exact basenames into separate train/evaluation save banks, following `config/save-bank.example.json`. Verify each saved game can be loaded. Do not substitute a renamed scenario file. Automatic scenario-to-save-bank creation is **not implemented** because this CONTROL API does not document that capability.
5. Use training layout seeds 0–31 and held-out layout seeds 1000–1099, with both sides for each seed. `--first-seed` chooses the generated range. All learner seeds reuse the same training bank. The Python adapter selects saved layouts deterministically and rejects unverified/missing saves. Evaluation rejects training seed overlap.
6. Validate save loading from the intended in-match context. `DispatchLoadGame` requires a filename in `GetAvailableSaveFiles`; availability from this context is not yet confirmed. If it fails, implement and test a menu-state controller before attempting training. Do not fake a successful reset.

## Required evidence before enabling training

- Place enemy archers outside vision. Confirm they do not appear in observations or action masks. Reveal them, hide them, move/damage them, and confirm remembered records stay frozen.
- Leave the learner module idle and confirm the native AI sends no economic/military decisions. Built-in unit behavior such as auto-retaliation and pathfinding remains part of the game engine.
- Inspect a command trace to confirm at least 0.5 game-seconds between issued commands, including scripted actions; test rejected/stale requests.
- Complete 100 consecutive resets/rollouts with at least 99 successes. Verify unit counts, geometry/side, saved-game identity, elapsed timestamps, terminal outcomes, and recovery after a deliberate disconnect. The current candidate checks map dimensions but does not independently prove the saved game's identity or every game setting.
- Record representative early/late full-match speed and reset overhead separately from combat scenario speed. Try multiple instances only after proving isolation. The delivered runner is single-instance; multi-instance launch/isolation is not implemented.

Store logs under `runs/live-validation`, then fill `config/live-validation.json` from its example with evidence references. Set `audited=true` in the module config only after those tests pass. This is a manual evidence gate, not automatic certification of fairness.

Start the benchmark, then the bounded campaign using the README commands. Remove invalid trajectories on bridge errors; restart the episode instead of training on a fabricated terminal reward. A game/bridge update invalidates the audit and requires revalidation.

## Human evaluation

No matchmaking automation is implemented. Later human matches require consenting opponents and validation that the bridge supports the selected private-lobby setup. CONTROL documentation and older release notes differ on multiplayer support; resolve that against the exact tested release before making promises. A cheats-enabled lobby must not give the policy hidden information or extra resources. Private match scores do not automatically become ranked Elo.
