# Read-only bridge investigation - 27 September 2026

The read-only runtime probe completed successfully without a Windows permission change. It inspected 51,993,218 bytes across the running main executable's two executable sections. All requested bytes were readable. No DLL was injected, no debugger attached, no game commands issued, and no process memory written or dumped.

Game: `101.103.54800.0`. Executable SHA-256:
`124744bf4ae0d3856238e00d61fe321d47fcd3c0d7dfcd175c6c76aa9fb458ff`.

## Findings

The fallback's original `RUN_LIST` and `GAME_TYPE` signatures have no matches in the live code, confirming that the earlier offline misses were not sufficient to recover these old signatures at runtime either.

Live code differs from the on-disk image. Named AI string references were absent in the file-only instruction search but visible when the same search used live executable code. The probe retains only reports, hashes and small disassembly excerpts.

| Candidate | Relative virtual address | Evidence |
|---|---|---|
| AI list evaluation / RunList | `0xBE39E0` | Unique surviving fragment of the original signature at `0xBE39FA`; unwind entry at the candidate start; list-index bounds checks and list-table access in the instructions |
| game-type fact | `0xBFA0B0` | Code passes this address with the `game-type` name to the fact-registration routine; matching unwind entry and inspected instructions |

Two replacement patterns were saved under `config/experimental/native-candidates-101.103.54800.0.h`. A separate full runtime scan found **one match for each at the expected address**. These are research candidates, not installed bridge changes; no loader consumes that file. Function behavior, calling conventions, and object layouts are not fully validated.

Two further incompatibilities are visible:

- The old bridge decodes an instruction at `GAME_TYPE + 29`. The corresponding RIP-relative load is now at `+19`. Merely replacing the signature would leave the old instruction decoder reading the wrong bytes. The global pointer's type still needs validation.
- The named-fact registration helper appears to use `AIExpert` count fields at `+0x28/+0x2A` and the fact-array pointer at `+0x30`. The old source places those at `+0x18/+0x1A` and `+0x20`. This is an inference from registration code, not a complete object-layout certification.

The current blocker is engineering validation of these layouts and callbacks, not Windows access. The next milestone is a bounded single-player match inspection that proves the AI object layout and readable state, followed by a minimal bridge build. CONTROL's private engine has not been modified.

## Reproduction

Open DE and leave it at its menu. Use the project's Python environment:

```powershell
.\.venv\Scripts\python.exe -m aoe2rl.runtime_probe --game 'C:\Program Files\Steam\steamapps\common\AoE2DE\AoE2DE_s.exe' --output reports/runtime-probe.json
.\.venv\Scripts\python.exe -m aoe2rl.runtime_probe --game 'C:\Program Files\Steam\steamapps\common\AoE2DE\AoE2DE_s.exe' --source config/experimental/native-candidates-101.103.54800.0.h --output reports/runtime-candidates.json
```

The first command reports the missing original signatures with a nonzero exit. The second can find unique candidates but still reports `safe_to_attach=false`. A partial scan is labeled incomplete, never a conclusive absence. Use `--pid` only when multiple DE processes exist; the reader verifies the actual executable path before reading code.

For named-string reconnaissance, `scripts/locate_ai_symbols.py --game <executable> --pid <current-DE-pid>` uses Capstone to check instruction boundaries. Without `--pid`, it works from the file only. Install the optional `reverse-engineering` dependencies if recreating the environment. This exploratory tool examines selected RIP-relative LEAs, not every possible code or data reference.

Evidence files:

- `reports/runtime-probe-2026-09-27.json`
- `reports/ai-runtime-symbol-candidates-2026-09-27.json`
- `reports/native-candidates-2026-09-27.json`
- `reports/runtime-candidate-validation-2026-09-27.json`

Validation: 47 tests pass, including scan boundaries, incomplete reads, Windows permission-error reporting, and rejection of apparent instructions embedded inside another instruction. Existing ScenarioParser deprecation warnings remain.
