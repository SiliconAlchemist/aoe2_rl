import argparse
import json
from pathlib import Path
from .core import BridgeError, Settings
from .env import CombatEnv


def environment(args):
    settings = Settings(player=args.player)
    if args.backend == "synthetic":
        from .synthetic import SyntheticBackend
        return CombatEnv(SyntheticBackend(settings), settings)
    from .transport import ControlPipe
    if not args.validation:
        raise BridgeError("DE training is gated until a live validation report is supplied; see docs/LIVE_SETUP.md")
    report = json.loads(Path(args.validation).read_text(encoding="utf-8"))
    for check in ("fog_test_passed", "native_ai_suppression_verified", "action_rate_verified", "reset_verified"):
        if report.get(check) is not True:
            raise BridgeError(f"Missing live validation: {check}")
    backend = ControlPipe(player=args.player, bank=args.save_bank)
    expected = "evaluation" if args.command == "evaluate" else "train"
    if not backend.bank or backend.bank["split"] != expected:
        raise BridgeError(f"This command requires a {expected} save bank")
    return CombatEnv(backend, settings)


def main(argv=None):
    p = argparse.ArgumentParser(description="AoE II RL feasibility lab; DE is never replaced by a synthetic fallback")
    sub = p.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--game", required=True)
    doctor.add_argument("--output", default="reports/machine.json")
    scenario = sub.add_parser("scenarios")
    scenario.add_argument("--output", default="artifacts/scenarios")
    scenario.add_argument("--count", type=int, default=4)
    scenario.add_argument("--first-seed", type=int, default=0)
    probe = sub.add_parser("probe", help="Read-only live connection check; does not enable training")
    probe.add_argument("--output", default="reports/connection.json")
    probe.add_argument("--player", type=int, choices=range(1, 9), default=1)
    probe.add_argument("--timeout", type=float, default=5.)
    probe.add_argument("--pipe", default="AoE2RL")
    for name in ("train", "evaluate", "benchmark"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--backend", choices=["de", "synthetic"], required=True)
        cmd.add_argument("--player", type=int, default=1)
        cmd.add_argument("--validation")
        cmd.add_argument("--save-bank")
        cmd.add_argument("--output", required=True)
        cmd.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
        if name == "train":
            cmd.add_argument("--algorithm", choices=["bc", "ppo", "bc-ppo"], default="bc-ppo")
            cmd.add_argument("--seed", type=int, default=1)
            cmd.add_argument("--seconds", type=float, default=3600)
            cmd.add_argument("--resume")
            cmd.add_argument("--max-episodes", type=int)
        else:
            cmd.add_argument("--episodes", type=int, default=200 if name == "evaluate" else 100)
            cmd.add_argument("--checkpoint")
    args = p.parse_args(argv)
    try:
        if args.command == "doctor":
            from .diagnostics import inspect_machine
            result = inspect_machine(args.game, args.output)
        elif args.command == "probe":
            import math
            if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
                p.error("--timeout must be finite and between 0 and 60 seconds")
            from .probe import probe
            result = probe(args.output, args.player, args.timeout, args.pipe)
        elif args.command == "scenarios":
            if args.count <= 0:
                p.error("--count must be positive")
            from .scenarios import generate
            result = generate(args.output, args.count, args.first_seed)
        elif args.command == "train":
            from .learning import train
            result = train(environment(args), args.output, args.algorithm, args.seed, args.seconds,
                           args.device, args.resume, args.max_episodes)
        else:
            if args.episodes <= 0:
                p.error("--episodes must be positive")
            from .evaluation import evaluate
            result = evaluate(environment(args), args.output, args.episodes, args.checkpoint, args.device)
        print(json.dumps(result, indent=2))
        if args.command == "probe" and not result["connected"]:
            p.exit(2, "Connection check failed; see the saved report for the failing stage.\n")
        if args.command in ("evaluate", "benchmark") and result["counts"]["error"]:
            p.exit(2, "Evaluation stopped on a bridge failure; the report preserves the error.\n")
    except (BridgeError, ValueError, OSError) as exc:
        p.exit(2, f"Not completed: {exc}\n")


if __name__ == "__main__":
    main()
