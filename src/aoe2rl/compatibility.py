"""Offline signature audit for the open-source FLWL bridge, not CONTROL.

Reads source and executable files only. A match is a candidate, never proof of
the function identity, calling convention, runtime layout, or safe attachment.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def signature_matches(data, signature):
    tokens = signature.split()
    if not tokens or all(token == "??" for token in tokens):
        raise ValueError("A signature must contain at least one fixed byte")
    if any(not re.fullmatch(r"[a-fA-F0-9]{2}|\?\?", token) for token in tokens):
        raise ValueError("Signature tokens must be hex bytes or ??")
    pattern = b"".join(b"." if token == "??" else re.escape(bytes.fromhex(token))
                       for token in tokens)
    # Lookahead preserves overlapping matches; a nonunique signature is unsafe.
    return [match.start() for match in re.finditer(b"(?=" + pattern + b")", data, re.DOTALL)]


def audit(game_executable, source, output):
    game_executable, source = Path(game_executable), Path(source)
    data, source_data = game_executable.read_bytes(), source.read_bytes()
    signatures = re.findall(r'\b(SIG_FUNC_\w+)\s*=\s*"([^"]+)"', source_data.decode("utf-8"))
    if not signatures:
        raise ValueError("No SIG_FUNC definitions found in the supplied source")
    if len({name for name, _ in signatures}) != len(signatures):
        raise ValueError("Duplicate signature definitions require explicit build selection")
    results = []
    for name, signature in signatures:
        hits = signature_matches(data, signature)
        results.append(dict(name=name, signature=signature, match_count=len(hits),
                            file_offsets=[hex(hit) for hit in hits[:32]],
                            status="missing" if not hits else "candidate" if len(hits) == 1 else "ambiguous"))
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(),
                  method="offline_file_scan", executable=str(game_executable.resolve()),
                  executable_sha256=hashlib.sha256(data).hexdigest(),
                  source=str(source.resolve()), source_sha256=hashlib.sha256(source_data).hexdigest(),
                  signatures=results, runtime_verified=False, safe_to_attach=False,
                  limitation="File offsets are not runtime addresses. Runtime unpacking/relocation may change bytes. "
                             "Unique matches still require function, ABI, object-layout and live validation. "
                             "This audits FLWL source signatures, not CONTROL's private signatures.")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, help="Path to AoE2DE_s.exe")
    parser.add_argument("--source", default="vendor/aoe2-ai-module/aimodule/misc/Configuration.h")
    parser.add_argument("--output", default="reports/fallback-signatures.json")
    args = parser.parse_args()
    try:
        report = audit(args.game, args.source, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Signature audit failed: {exc}\n")
    print(json.dumps(report, indent=2))
    if any(entry["status"] != "candidate" for entry in report["signatures"]):
        parser.exit(2, "Some source signatures are missing or ambiguous; no attachment was attempted.\n")


if __name__ == "__main__":
    main()
