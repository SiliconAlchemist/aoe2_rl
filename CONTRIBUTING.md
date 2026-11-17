# Contributing

This is an early research project. Useful contributions make game interaction, replay data or evaluation more reliable and explain the evidence behind a change.

## Set up

Use Python 3.12 and the setup steps in the [README](README.md). Work from the root containing `pyproject.toml`. The Python source lives under `src/aoe2rl` and is installed in editable mode.

Start with a small, focused change. For a new learning algorithm, action interface or dataset format, describe the intended experiment and compatibility implications in an issue first.

## Describe validation accurately

- Distinguish offline analysis, synthetic software runs, replay capture and live game behavior.
- Report what you ran and what remains unverified. Tests that were not run should be stated as such.
- Do not present a synthetic score or opening completion as a full-game win rate.
- Preserve the difference between attempted commands, accepted commands and observed effects.
- Keep future actions, outcomes and hidden game information out of policy inputs.
- Preserve raw recordings and hashed capture metadata. Generate revised datasets in new directories.

Run relevant existing tests when appropriate:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Game integration needs separate manual validation. Use a disposable local single-player session or a replay as appropriate; document the game build, bridge version, player slot and information policy. No test suite can replace those checks.

## Report a problem

Include the command, expected behavior, actual result, package/game/bridge versions and a minimal relevant error excerpt. Indicate whether the issue came from extraction, capture, pairing, audit or training. Remove private paths, chat and unrelated player information before posting logs. You do not need to upload a complete recording to report an initial connection failure.

## Before opening a pull request

Keep the change scoped, update affected run instructions and state the validation performed. Avoid committing `data/replays`, `reports`, `runs`, environments, game files or downloaded tools. Explain schema changes and how existing captures/checkpoints are handled.

Contribute only material you have the right to share. Project contributions are made under the repository's [MIT License](LICENSE); third-party components retain their own terms.
