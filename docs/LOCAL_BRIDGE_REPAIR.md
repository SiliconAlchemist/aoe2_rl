# Local compatibility investigation - 26 September 2026

**27 September update:** the read-only runtime scan now works without permission changes. Both original signatures are missing in live code; two replacement candidates were located and each matches once. The old game-pointer instruction offset and apparent AI fact layout also changed. See `docs/RUNTIME_PROBE_RESULTS.md`; no bridge patch is yet enabled.

A recent release can fail after one game update: signatures identify sequences of native machine instructions. Recompilation can change those sequences while the game's visible behavior stays the same. The two failed CONTROL checks are direct evidence of unresolved signatures, not a judgment based on the release date. The 61 passed checks do not establish that the remaining gameplay API is compatible.

## CONTROL findings

- Release 1.0.0's manifest records runtime validation against DE `101.103.48987.0`; the installed game is `101.103.54800.0`.
- Current startup diagnostics report `GameScreenContainer` missing (critical) and `CanAffordResearch` missing (noncritical). Raw evidence: `reports/control-diagnostics-2026-09-26.json`.
- The public repository supplies examples and documentation, not native engine sources. The local release has a packed launcher, embedded engine and release metadata. The manifest names VMProtect. No documented external signature override was found in the headless/configuration/API documentation; this is not proof that none exists privately.
- Lua adapter edits cannot directly replace native signatures that the engine must resolve before serving those Lua APIs.
- The documented Shift overlay toggle was tested at the game menu and no overlay appeared. Module assignment and in-game passive diagnostics have not been completed; absence of a module pipe alone is not proof of every native API failing.
- The bundled EULA explicitly restricts modification/reverse engineering. No changes were made to CONTROL's binary. A maintainer-provided signature override, engine source, or development build would substantially shorten the repair path.

## Open-source fallback findings

Downloaded `FLWL/aoe2-ai-module`, commit `a6a550d148deafb63d67f0fe22ae1edd522b4729`, into the ignored vendor directory. Its LGPL-2.1 source exposes the native bridge implementation.

The new offline audit reads its `SIG_FUNC_RUN_LIST` and `SIG_FUNC_GAME_TYPE` definitions and scans the installed game file. Both have **zero file matches**. This does not inspect runtime memory: unpacking or relocation may make runtime bytes different. No fallback DLL was loaded.

Reproduce the result:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.compatibility --game 'C:\Program Files\Steam\steamapps\common\AoE2DE\AoE2DE_s.exe' --output reports/fallback-signatures-2026-09-26.json
```

The report records hashes, signatures and match counts. Ambiguous or missing matches produce a nonzero exit. Even a unique match never marks a build safe to attach. Literal zero bytes and overlapping matches are tested explicitly; the old bridge's scanner treats zero as a wildcard, which would also need review for future signatures containing literal zero.

The source also depends on assumptions beyond those two signatures: a `+29` instruction location in `SetGamePointer`, a `Game.programMode` layout at `0x2C0`, native AI object layouts, and the calling convention for `RunList`. Updating two byte patterns alone would not validate these assumptions.

Build prerequisites: the project requests MSVC v142 and Windows SDK 10.0.18362.0. This machine has MSVC 14.38/14.44 and SDK 10.0.22621.0. Its expected vendored vcpkg/dependencies are absent. Its old Zydis API calls require a compatible dependency version or a source port. Compilation was not attempted, and no global toolchain settings were changed.

## Concrete path to an owned bridge

1. Establish a read-only runtime probe for the current DE build and identify the AI callback and game-state entry points. Validate unique executable addresses and object layouts. Keep signatures tied to the executable hash; fail closed on a different build.
2. Build a minimal x64 bridge with a localhost-only transport and explicit startup errors. The fallback currently binds gRPC to `0.0.0.0`; restrict it before use. Start with time, assigned player and visible-unit observations. Retain the existing Python observation filter as an additional check.
3. Verify read-only observations in a disposable single-player scenario before implementing owned-unit move/attack commands and the command-rate limit. Validate native AI suppression and fog restrictions with actual evidence.
4. Add save loading/reset, verified outcomes and recovery, then connect the existing learner through a backend adapter. The current CONTROL Lua backend is not interchangeable with the fallback's gRPC fact/action API.

The first unresolved engineering milestone is current-build native entry points and layouts. This work is feasible to investigate locally, but its duration and success are unmeasured. It consumes the same two-week feasibility budget as learning experiments; it should not be described as a small completed compatibility fix.

Sources:

- https://github.com/aoe2control/AoE2Control
- https://aoe2control.github.io/headless-mode/
- https://aoe2control.github.io/config-location/
- https://aoe2control.github.io/interface-options/
- https://github.com/FLWL/aoe2-ai-module
