import json
import pytest
from aoe2rl.compatibility import audit, signature_matches


def test_signature_wildcards_and_literal_zero_are_distinct():
    assert signature_matches(b"\x40\x00\x53\x40\xff\x53", "40 00 53") == [0]
    assert signature_matches(b"\x40\x00\x53\x40\x0a\x53", "40 ?? 53") == [0, 3]
    assert signature_matches(b"\xaa\xaa\xaa", "aa aa") == [0, 1]


@pytest.mark.parametrize("value", ["", "?? ??", "GG 42", "4? 42"])
def test_invalid_signature_is_rejected(value):
    with pytest.raises(ValueError): signature_matches(b"\x42", value)


def test_offline_report_never_claims_runtime_compatibility(tmp_path):
    game, source, output = [tmp_path / name for name in ("game.exe", "Configuration.h", "report.json")]
    game.write_bytes(b"\x40\x00\x53\xaa\xaa\xaa")
    source.write_text('SIG_FUNC_A = "40 ?? 53";\nSIG_FUNC_B = "AA AA";\nSIG_FUNC_C = "FF FF";')
    report = audit(game, source, output)
    assert [x["status"] for x in report["signatures"]] == ["candidate", "ambiguous", "missing"]
    assert report["runtime_verified"] is False and report["safe_to_attach"] is False
    assert json.loads(output.read_text()) == report
