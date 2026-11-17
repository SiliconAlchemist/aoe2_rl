# Implementation status - 5 November 2026

## Latest update

The repository root is now `aoe2_rl`, with installable source in `src/aoe2rl`. Both existing environments have been re-registered and their activation scripts/launchers refreshed. Replay path resolution preserves historical capture metadata hashes after the folder move. No tests, live capture or training were run for this restructure.

Replay work: 10 recordings yielded 19,629 selected-player commands and 8,196 command-history examples. The user's Arena capture yielded 781 observations and 32 provisional pairs. Offline structural checks passed; 21 commands had a matching effect before the next command, with 11 unconfirmed. The user confirmed initially hidden enemy bases and the opening movements. Visibility transitions, unresolved selections and full-game learner integration remain open. The improved five-minute recorder has not yet been exercised. See [imitation data](IMITATION_DATA.md) and [project layout](PROJECT_LAYOUT.md).

## Current update

The user confirmed the scripted two-house opening works. Its report records both houses completed with the 2+1 builder assignment, two livestock under the TC, two newly acquired and 1,248 newly explored tiles. The report did not finalize its aggregate completion flag; this is not an RL result.

New: `src/aoe2rl/opening_env.py` provides live observations, candidate actions, task rewards, bounded steps and restart verification; `src/aoe2rl/train_opening.py` adds recurrent PPO, imitation warm-up, checkpoint/resume and evaluation. `opening_reset` is installed in the user's CONTROL modules folder and must be selected for Player 1. **None of the new training code or reset helper has been run or tested**, per the user's instruction. No trained opening checkpoint exists. See `OPENING_RL.md`. The short first run is four episodes, two imitation then two PPO; all testing is left to the user.

## Earlier bridge bring-up

AoE2Control 1.1.5 passes all 136 engine checks on DE 101.103.57257.0. The native Agent Bridge works under the same Windows user as DE. A fresh single-player match supplied player-view observations; a villager moved, and a house progressed from foundation to completed status with 550/550 HP. Both commands were accepted, and their actual effects were independently observed. Wood decreased by 25; the completed house was visible in the game. The match is paused. Evidence: `reports/native-control-smoke-2026-10-31.json`.

The earlier 51 tests passed with workspace-local temporary files; that result does not cover the new opening training code. See `docs/AGENT_BRIDGE_SETUP.md`. The old combat pipeline still requires native observation/action conversion, saved-game resets and its live validation checks. The separate opening learner uses match restart, not that unverified save bank. Neither control smoke tests nor the scripted opening establish learned performance or competitive strength.

## September history (superseded compatibility blocker)

## Outcome

The initial training lab is implemented and tested. **The two-week live DE feasibility study is not complete.** No live match data, Extreme win rate, full-game agent, or expert-strength result exists yet.

The current blocker is **AoE2Control/game incompatibility**. At the user's request, the official 1.0.0 release was re-extracted on 26 September. The archive hash matched GitHub's release digest, and the executable matched the included manifest. The unsigned launcher ran without changing security settings. The prior Windows block did not recur.

DE is running from C:, now build `101.103.54800.0`. Bridge startup diagnostics report **Outdated**, with 61 passes and two failures: critical `GameScreenContainer` and noncritical `CanAffordResearch`, both missing signatures. Its release manifest records testing on `101.103.48987.0`. The pilot module was installed with `audited=false`; no working pipe or bot actions were observed.

The user reports Steam offers no older Betas. No newer official bridge release was found. The public repository contains examples rather than the engine source, so a local rebuild is not available from that repository. No game downgrade or binary patch was performed.

Evidence: `reports/control-diagnostics-2026-09-26.json`, `reports/connection-2026-09-26.json`, and `reports/machine-2026-09-26.json`. The updated AI inventory contains 7,864 rule declarations. A maintainer-ready report is in `docs/BRIDGE_COMPATIBILITY_REPORT.md`; it has not been sent.

## Delivered and exercised

- 47 automated tests passed, including Windows pipe integration, missing-pipe and permission-error handling, read-only diagnostic stages, pre-audit Lua inspection, and checkpoint file-lock recovery. ScenarioParser emits deprecation warnings from its own reconstruction code; scenario round-trip checks pass.
- Isolated Python 3.12 environment with CUDA-enabled PyTorch; successful RTX 5060 Ti computation and a two-episode GPU PPO smoke run.
- Recurrent PPO, imitation, and imitation-then-PPO; three training seeds for each completed in the synthetic smoke campaign.
- Scripted baseline and all nine checkpoints evaluated on 20 held-out synthetic episodes each. These runs only exercise software. They are too short and the synthetic dynamics are too simplified to compare AoE algorithm quality.
- Environment observation filtering, memory, action masks, timing/sequence checks, crash handling, and time-limit bootstrapping.
- Actual Windows pipe round-trip with fragmented JSON and a bounded nonresponsive-server test; Lua bridge logic tested under a mocked engine.
- OneDrive checkpoint failure reproduced during a campaign, fixed with fewer writes and bounded atomic-replacement retries, then campaign successfully resumed.
- Four real DE scenario files generated and parsed back: two randomized layouts, each mirrored. They have not been loaded or played in DE.
- Current game script inventory with hashes, source-backed feasibility notes, CLI documentation, and a bounded/resumable campaign runner.

Reports: `reports/machine.json`, `reports/blockers.json`, `reports/campaign-summary.json`, and `reports/synthetic-benchmark.json`. Checkpoints and detailed experiment logs are under `runs/`. The dependency lockfile and package metadata allow environment recreation.

## Runtime investigation update

Read-only access succeeded with full executable-section coverage and no permission changes. Two new entry-point patterns match uniquely in live code, but game-pointer decoding and AI object layouts also changed. No bridge is enabled from these candidates. See `docs/RUNTIME_PROBE_RESULTS.md`.

## Remaining work

The local repair investigation is recorded in `docs/LOCAL_BRIDGE_REPAIR.md`. The open-source fallback is now downloaded and its two source signatures were scanned against the current game file; both have zero offline matches. This is not a runtime-memory test. `aoe2rl.compatibility` makes that audit reproducible, and no fallback DLL has been built or loaded.

1. Obtain an updated bridge for DE `101.103.54800.0`. The older open-source module was assessed but not built or validated; porting it would be a separate engineering effort.
2. Verify generated scenarios in DE, prepare separate genuine saved-game banks, and prove that the API can reset them from the intended context. Automatic scenario-to-save conversion is not implemented.
3. Run live fog, native AI suppression, action-rate, outcome, and 100-reset tests. Candidate Lua modules and audit templates are deliberately disabled by default.
4. Measure early/late full-game and pilot throughput. Multi-instance process isolation/launching is not implemented.
5. Run the agreed overnight live campaign only after those checks pass. No unattended nightly schedule has been installed.
6. Use measured learning curves and throughput to decide whether to add macroeconomy, full games, opponent leagues, Extreme evaluation, and eventually human matches.

The current implementation is a useful foundation and a tested small learning pipeline. Live feasibility and expert-level performance remain unresolved.
