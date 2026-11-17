import struct
import pytest

pytest.importorskip("capstone")
from scripts.locate_ai_symbols import locate


@pytest.mark.parametrize("embedded", [False, True])
def test_string_reference_requires_instruction_boundary(tmp_path, embedded):
    data = bytearray(0xa00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<HH", data, 132, 0x8664, 3)
    struct.pack_into("<H", data, 148, 240)
    struct.pack_into("<H", data, 152, 0x20b)
    struct.pack_into("<II", data, 152+112+24, 0x3000, 12)
    for i, (name, rva, raw, flags) in enumerate([
        (b".text", 0x1000, 0x400, 0x60000020),
        (b".rdata", 0x2000, 0x600, 0x40000040),
        (b".pdata", 0x3000, 0x800, 0x40000040)]):
        at = 392+i*40
        data[at:at+len(name)] = name
        struct.pack_into("<IIII", data, at+8, 0x200, rva, 0x200, raw)
        struct.pack_into("<I", data, at+36, flags)
    prefix = b"\x48\xb8" if embedded else b""  # movabs embeds fake LEA in its immediate.
    code = prefix+b"\x48\x8d\x15"+struct.pack("<i", 0x2000-(0x1000+len(prefix)+7))
    code += b"\x00\xc3" if embedded else b"\xc3"
    data[0x400:0x400+len(code)] = code
    data[0x600:0x60a] = b"game-type\0"
    struct.pack_into("<III", data, 0x800, 0x1000, 0x1000+len(code), 0)
    path = tmp_path/"fixture.exe"
    path.write_bytes(data)
    result = locate(path)
    assert len(result["references"]) == (0 if embedded else 1)
    assert result["functions_validated"] is False
