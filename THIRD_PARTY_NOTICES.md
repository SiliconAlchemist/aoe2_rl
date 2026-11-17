# Third-party components

The root MIT license applies to project-authored code and documentation. It does not relicense dependencies, downloaded binaries, game assets or recordings supplied by users.

| Component | Use in this project | Source |
| --- | --- | --- |
| AoE2Control | External Agent Bridge and Lua runtime for local DE integration | [Repository and releases](https://github.com/aoe2control/AoE2Control), [bridge protocol](https://aoe2control.github.io/agent-bridge/) |
| aoc-mgz | Isolated `.aoe2record` parser | [Repository](https://github.com/happyleavesaoc/aoc-mgz) |
| PyTorch | Neural-network and optimization tools | [Project](https://pytorch.org/) |
| Gymnasium | Environment interface | [Project](https://gymnasium.farama.org/) |
| AoE2ScenarioParser | Earlier scenario-generation workflow | [Repository](https://github.com/KSneijders/AoE2ScenarioParser) |

AoE2Control is downloaded separately into an ignored `vendor/` directory. Its own EULA and third-party notices govern that software; a copy of this project's MIT license does not replace them. The game is also a separate installation and is not distributed here.

`scripts/patch_replay_parser.py` documents two header-format adjustments proposed in [aoc-mgz PR #147](https://github.com/happyleavesaoc/aoc-mgz/pull/147). It modifies the user's isolated parser installation and retains a backup there. Neither the installed parser package nor its patched copy is committed to this repository. See that upstream project for its license and contribution history.

Dependency versions are listed in `requirements-lock.txt` and `requirements-replays.txt`; their distributed packages carry their own license notices. Research papers linked from the documentation are references, not bundled publications. Local recordings, model checkpoints and downloaded tools are excluded by `.gitignore`.
