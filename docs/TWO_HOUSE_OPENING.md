# Two houses and livestock scouting

This is a scripted controller, not an RL policy. The user subsequently ran it successfully. The saved report shows both houses complete, two livestock under the TC, two more acquired, and 1,248 newly explored tiles; it lacks a finalized completion flag. To train a policy for the same task, see [OPENING_RL.md](OPENING_RL.md). That new learner has not yet been run or tested.

## Start it

1. Open AoE II DE from Steam and leave it at the main menu.
2. Open PowerShell in the project folder. Attach the installed bridge:

```powershell
# Run from the cloned repository root, beside pyproject.toml.
& '.\vendor\AoE2Control-1.1.5\AoE2Control.exe' --headless --timeout-ms 30000 2>&1 | Tee-Object -FilePath reports/opening-launch.txt
```

3. In DE, press Shift to open CONTROL. Enable **Modules > Agent Bridge** and **Player 1 > Agent Bridge**. Keep **See Everything off**. Press Shift to hide CONTROL again. The saved INI override was not reliable in the prior setup, so check these toggles manually.
4. Start a fresh **single-player Skirmish**, with Player 1 human, Sicilians (the previously verified civilization), Arabia, Dark Age, standard resources, normal fog and cheats off. Any easy opponent is fine for this control demonstration. Use a standard start with three villagers, a Town Center and Scout Cavalry. Leave the game **unpaused**.
5. Within the first three game-minutes, run this in the same PowerShell window:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.opening --execute --seconds 180
```

Use the same Windows account that runs Steam and DE. No Windows security exception or administrator mode is expected to be necessary. If you already attached CONTROL successfully, skip the launcher step.

## Behavior

- Two idle villagers build one house together; a third idle villager builds a separate house. The script queries legal positions near the TC. Houses already on the map do not count: it builds **two additional houses**.
- The first two available owned sheep (or geese, goats and equivalent livestock) go under the TC and are excluded from exploration. It does not slaughter them or order villagers to gather food.
- The scout explores nearby unexplored areas and approaches visible neutral livestock to acquire them. Other owned livestock explore separate nearby targets. Newly acquired animals join exploration once two are reserved at the TC.
- Exploration uses only player-view observations and known walkable ground near unexplored tiles, within 40 tiles of the TC. It is a simple local search, not a full-map exploration planner or an optimal build order.
- After three real minutes it disconnects. Existing game orders remain active. It does not pause DE or keep controlling units afterward. Press **F3** yourself to pause and inspect; **Ctrl+C** in PowerShell stops the controller early.

The game must stay unpaused and advancing. If it is paused before startup, the script refuses to issue orders. If a command is queued instead of executed, it stops rather than retrying and potentially placing duplicate buildings. Inspect the game before rerunning after any partial failure.

## Check it manually

Watch the two villagers work on the same foundation and the third work on the other. Confirm two completed houses, exactly two reserved livestock beneath the TC, and the scout plus remaining livestock revealing different nearby areas. Initial livestock may already belong to you; additional discoveries depend on the map and allotted duration.

The terminal prints the outcome. Detailed commands, assigned villager IDs, builder observations, house completion, reserved livestock IDs, newly acquired animals and explored-tile count are saved in `reports/two-house-opening.json`.

`completed: true` requires both houses completed, two livestock observed within 2.5 tiles of the TC, movement by the assigned explorers, new explored tiles, and at least one additional livestock acquired. Acquisition is recorded from ownership changes; it does not prove which unit first saw the animal. Inspect the scout visually for that check. `completed: false` without an error means the duration ended before all these checks were met; inspect individual fields. Exit codes: 0 all checks met, 1 partial result, 2 error or interruption.

Optional longer local search:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.opening --execute --seconds 300 --radius 50 --output reports/opening-longer.json
```

For an existing disposable match older than three game-minutes, add `--allow-existing-match`. It still needs three idle villagers and at least 50 wood, and will build two additional houses. Prefer a fresh match for each test. The current controller expects standard Scout Cavalry and TC type IDs, so Eagle Scout or unusual scenario starts are not supported.

If the pipe is unavailable, confirm that DE is open, CONTROL is attached and both Agent Bridge toggles are enabled. If access is denied, run PowerShell as the same Windows user as DE. If DE has updated since the successful bridge smoke test, check CONTROL's compatibility diagnostics before proceeding.

Protocol reference: https://aoe2control.github.io/agent-bridge/
