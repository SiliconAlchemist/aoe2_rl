# Local datasets

`replays/` contains the local manifest, SHA-256-named original copies, extracted commands, observation captures and derived pairs. It is ignored by Git and is not part of the installed Python package.

Use the replay tools to generate new outputs in fresh directories. Do not rewrite historical metadata to fix a moved directory: capture reports hash that metadata. The path resolver handles the legacy absolute dataset references while preserving the bytes and hashes.

See [replay intake](../docs/REPLAY_DATASET.md) and [imitation workflow](../docs/IMITATION_DATA.md).
