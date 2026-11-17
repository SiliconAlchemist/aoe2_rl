import struct
import pytest
from aoe2rl.runtime_probe import executable_sections, scan_sections


def pe_header():
    data = bytearray(4096)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<HH", data, 132, 0x8664, 1)
    struct.pack_into("<H", data, 148, 240)
    struct.pack_into("<H", data, 152, 0x20b)
    struct.pack_into("<I", data, 208, 0x3000)
    data[392:397] = b".text"
    struct.pack_into("<II", data, 400, 0x1000, 0x1000)
    struct.pack_into("<I", data, 428, 0x60000020)
    return data


def test_pe_ranges_are_bounded_and_64_bit():
    header = pe_header()
    assert executable_sections(header) == [dict(name=".text", rva=4096, size=4096)]
    struct.pack_into("<I", header, 400, 0x10000)
    with pytest.raises(ValueError, match="outside"): executable_sections(header)
    with pytest.raises(ValueError): executable_sections(header[:140])
    struct.pack_into("<H", header, 132, 0x14c)
    with pytest.raises(ValueError, match="AMD64"): executable_sections(header)


def test_scan_finds_cross_chunk_signature_and_reports_rva():
    data = b"\xff\xff\x40\x00\x53\xff\xff\xff"
    report = scan_sections(lambda address, size: data[address-0x1100:address-0x1100+size],
        0x1000, [dict(name=".text", rva=0x100, size=8)], {"function": "40 ?? 53"}, chunk_size=4)
    assert report["coverage_complete"] is True
    assert report["signatures"][0]["rvas"] == ["0x102"]
    assert report["signatures"][0]["addresses"] == ["0x1102"]


def test_partial_scan_never_claims_signature_is_missing_or_unique():
    def read(address, size):
        if address == 4: raise OSError("unreadable")
        return b"\x40" * size
    report = scan_sections(read, 0, [dict(name=".text", rva=0, size=12)],
                           {"function": "40 40", "absent": "53 53"}, chunk_size=4)
    assert report["coverage_complete"] is False
    assert report["sections"][0]["bytes_read"] == 8
    assert report["sections"][0]["sha256"] is None
    assert all(s["status"] == "incomplete" for s in report["signatures"])
    assert "0x3" not in report["signatures"][0]["rvas"]


def test_open_process_permission_error_is_saved(tmp_path, monkeypatch):
    import aoe2rl.runtime_probe as runtime
    pywintypes = pytest.importorskip("pywintypes")
    game, source, output = [tmp_path / name for name in ("AoE2DE_s.exe", "source.h", "report.json")]
    game.write_bytes(pe_header())
    source.write_text('SIG_FUNC_TEST = "40 53";')
    def denied(*args): raise pywintypes.error(5, "OpenProcess", "Access is denied")
    monkeypatch.setattr(runtime, "GameReader", denied)
    result = runtime.probe(game, source, output, pid=123)
    assert result["stage"] == "open_process" and result["windows_error"] == 5
    assert result["safe_to_attach"] is False
    assert "Access is denied" in output.read_text()
