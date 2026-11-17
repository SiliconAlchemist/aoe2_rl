# AoE2Control 1.0.0 reports Outdated on DE 101.103.54800.0

Prepared 26 September 2026 for manual maintainer support. Not posted or sent.

With Steam AoE II: Definitive Edition running at its main menu on Windows, the official AoE2Control 1.0.0 launcher reached startup diagnostics. Health was `Outdated`, with 61 passes, two failures, and `hasCriticalFailure=true`.

| Diagnostic | Severity | Result |
|---|---|---|
| offset.GameScreenContainer | Critical | Signature not found |
| offset.CanAffordResearch | Noncritical | Signature not found |

Game version: `101.103.54800.0`. The release manifest records testing against `101.103.48987.0`.

Archive SHA-256 verified against GitHub's asset digest:
`d428fa1e25d5e6f26a126e1c104bb7cd1ca73f42d6e23c28d84ecd0c684da224`

Launcher SHA-256 verified against the included manifest:
`0aa66133aa15173fc287d8eccffc096ee1c52a2089204ace568bbbbe26617c29`

Invocation: `AoE2Control.exe --headless --override-module <pilot-module-folder>`. The module copy completed. The launcher invocation returned exit code 0 with no console output; this did not indicate compatible startup. No in-game passive diagnostics or bot commands completed, and the module-specific named pipe remained unavailable. No security settings were changed. Steam offers no older Betas for this installation.

Raw evidence is saved in `reports/control-diagnostics-2026-09-26.json` in the local project.

Is an updated engine build available for `101.103.54800.0`, or is there another supported way to use a matching game version with 1.0.0?

Official release: https://github.com/aoe2control/AoE2Control/releases/tag/1.0.0
