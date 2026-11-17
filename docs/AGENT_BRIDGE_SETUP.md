# Native Agent Bridge connection - 31 October 2026

## Fresh checkout

Download the compatible release from [AoE2Control releases](https://github.com/aoe2control/AoE2Control/releases). For the version documented here, extract it into `vendor/AoE2Control-1.1.5/` so `AoE2Control.exe` is directly inside that folder. The binary is not included in this repository. Open DE through Steam, run the launcher under the same Windows account, then configure the bridge toggles below. Check the release's own instructions and license before use. A different DE build may require a different release.

The `aoe2rl.agent_bridge` command uses the native bridge described here. The older `aoe2rl.cli probe` command targets the separate Lua pipe and is not a substitute for this native connection check.

AoE2Control 1.1.5 now starts successfully with the installed DE version `101.103.57257.0`. Its diagnostic report has 136 passing checks, no failures or warnings, and `hasInGamePassiveRun=true` (the engine first attached during a paused replay). The earlier native-signature repair work is no longer the preferred integration path.

The official archive SHA-256 was verified against GitHub's release asset digest:
`fed68ab7adf74b41c31ca2d76fa170f46e29167848b6c830964d8b7fc29854c3`.
The extracted executable hash matches its manifest:
`ca54e123ab1ac8f8e2fc48f23793cae18d4c0b5d4dfe69faea62551c78b2f431`.

## Working connection

The `aoe2rl.agent_bridge` client implements contract version 3, with one pipe connection per request, bounded reads/writes, session cleanup, and a 16 MiB response limit. It uses `AoE2ControlAgentV3.P1`, independently of the older Lua module's `AoE2RL` pipe.

In the CONTROL menu, enable Modules > Agent Bridge, then Player 1 > Agent Bridge. Keep Modules See Everything off. Suppress Native AI was visibly on; its gameplay effect still needs validation. No Lua module was assigned in this test.

The initial minimal INI override did not turn these toggles on. Enabling them through the overlay created the pipe. Do not assume `config/control-agent-pilot.ini` is a verified unattended setup; use the observed UI settings until the engine's saved INI format is established.

Windows rejected the client under the sandbox's separate account with error 5. Running the same client under the Windows account running DE succeeded. No antivirus exception, security-setting change, or pipe-permission change was needed.

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.agent_bridge --output reports/agent-bridge.json
```

Confirmed at the main menu: `status`, `open` (including command catalog), and `close` all succeeded. The status reports player 1, `player_view`, `waiting_for_match`, and zero accepted/executed actions. Use `--observe` only once a match is running. A successful handshake does not certify the fog policy's implementation or the training environment.

## Live movement and construction verified

After the user hid the CONTROL overlay with Shift, a fresh disposable single-player Arabia match was started: Sicilians, Dark Age, standard resources, normal fog, cheats off, Fast speed, Easiest opponent. World 1 returned live player-view observations. This was a control test, not an opponent-strength evaluation.

`scripts/smoke_native_control.py` queried legal house placements, moved villager 3723 from (109, 65) to an observed (109.808, 65), then ordered construction at (112, 65). Both commands returned `executed`. Subsequent observations independently verified a new house, entity 4590, progressing from a foundation with 1 HP to completed status 2 with 550/550 HP at game time 147636 ms. Wood fell from 200 to 175. The completed house was also visible in DE. The match was left paused using F3.

The script requires an explicitly selected world and `--execute`; it checks the world, replay state and player-view policy before acting, uses bounded waits, and closes its session. To repeat, first start a fresh disposable match and obtain its current world with the observation probe. Replace WORLD below with that observed integer; do not reuse a stale world number.

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.agent_bridge --observe --output reports/agent-bridge-live.json
.\.venv\Scripts\python.exe scripts/smoke_native_control.py --world WORLD --execute --output reports/native-control-smoke.json
```

## Remaining integration

Update: the user subsequently confirmed the scripted two-house opening works. A separate opening-specific PPO environment and restart module are now implemented; follow [OPENING_RL.md](OPENING_RL.md). These new components are untested and have not produced a trained checkpoint. The older combat-backend requirements below remain separate.

The native client is not yet a `CombatEnv` backend. Saved-game resets, observation conversion, command timing, native-AI suppression, outcome handling and fog tests remain required before connecting training. No training, performance benchmark or Extreme match has run.

## Evidence and tests

- `reports/control-launch-2026-10-31.txt`
- `reports/control-diagnostics-2026-10-31.json`
- `reports/agent-bridge-menu-2026-10-31.json`
- `reports/agent-bridge-live-2026-10-31.json`
- `reports/native-control-smoke-2026-10-31.json`
- 51 tests passed using temporary files inside the workspace. The default sandbox temporary folder caused two checkpoint rename failures; changing only the test directory resolved both.

To rerun tests, choose a **fresh directory dedicated to pytest** (pytest clears its base directory):

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .cache/pytest-new-bridge-run
```

Official documentation: https://aoe2control.github.io/agent-bridge/

Release: https://github.com/aoe2control/AoE2Control/releases/tag/1.1.5
