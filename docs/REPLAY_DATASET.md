# Local imitation recording intake — 31 October 2026

The user authorized using local `.aoe2record` files and said any player is acceptable initially. Player 1 is selected provisionally; this does not imply the player is the user, the winner or an expert.

Source: the local `Games\Age of Empires 2 DE` directory under the Windows user profile. This document records the initial local intake; recordings are not included in the repository.

- 831 recordings catalogued across two profile folders, totaling 4,164,435,246 bytes.
- 10 distinct recordings with filename build `101.103.57257.0`, matching the installed executable version, copied into `data/replays/raw/` (56,298,727 bytes).
- Copies named by their SHA-256 hashes; copied bytes verified against originals.
- Other 821 recordings indexed by source path without duplicating the remaining approximately 4.11 GB.
- Originals unchanged. No replay playback, training or tests were run.

`data/replays/manifest.json` maps original names and paths to staged copies, file sizes, modification times, filename build labels, hashes and the provisional player slot. The raw data and manifest are excluded from Git through `.gitignore`.

Initial conversion candidate: `MP Replay v101.103.57257.0 @2026.10.31 152644 (2).aoe2record`, the newest staged recording. The `(2)` in its filename is not treated as player-count metadata.

The subsequent [imitation-data preparation](IMITATION_DATA.md) parsed all 10 staged recordings, identified players/maps/civilizations, and produced 19,629 selected-player commands and 8,196 command-history examples. Two whole recordings are held out for validation. Player-view observation reconstruction, live replay compatibility and timing checks remain outstanding. This is not yet a dataset for a reactive policy. Older filename builds are not assumed to be playable by the installed game. No replay has been certified a win or a high-quality demonstration.

To refresh the inventory and copy additional current-build files:

```powershell
$recordings = Join-Path $env:USERPROFILE 'Games\Age of Empires 2 DE'
.\.venv\Scripts\python.exe scripts/import_recordings.py --source $recordings --build 101.103.57257.0 --player 1 --output data/replays
```

The importer preserves a prior manifest when refreshing. Build matching is based on filenames only. No upload or external transmission was performed by the importer.
