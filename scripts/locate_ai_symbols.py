"""Offline AI-name cross-reference reconnaissance; never produces validated hooks."""
import argparse
import bisect
import hashlib
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_64


def locate(path, pid=None):
    data = Path(path).read_bytes()
    file_hash = hashlib.sha256(data).hexdigest()
    pe = struct.unpack_from("<I", data, 60)[0]
    if data[:2] != b"MZ" or data[pe:pe+4] != b"PE\0\0":
        raise ValueError("Expected PE executable")
    machine, count = struct.unpack_from("<HH", data, pe+4)
    opt_size = struct.unpack_from("<H", data, pe+20)[0]
    opt = pe+24
    if machine != 0x8664 or struct.unpack_from("<H", data, opt)[0] != 0x20b:
        raise ValueError("Expected AMD64 PE32+")
    sections = []
    for i in range(count):
        pos = opt+opt_size+i*40
        virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", data, pos+8)
        flags = struct.unpack_from("<I", data, pos+36)[0]
        if raw+raw_size > len(data): raise ValueError("Truncated section")
        sections.append((rva, virtual_size, raw, raw_size, flags))

    if pid is not None:
        from aoe2rl.runtime_probe import GameReader, executable_sections
        reader = GameReader(pid, Path(path).resolve())
        try:
            if executable_sections(reader.read(reader.base, 65536)) != executable_sections(data[:65536]):
                raise ValueError("Runtime section layout differs from executable")
            data = bytearray(data)
            for rva, virtual_size, raw, raw_size, flags in sections:
                if flags & 0x20000000:
                    length = min(raw_size, virtual_size)
                    for offset in range(0, length, 65536):
                        size = min(65536, length-offset)
                        data[raw+offset:raw+offset+size] = reader.read(reader.base+rva+offset, size)
            data = bytes(data)
        finally:
            reader.close()

    def file_offset(rva, size=1):
        for start, _, raw, length, _ in sections:
            if start <= rva and rva+size <= start+length:
                return raw+rva-start
        raise ValueError(f"RVA {rva:x} has no file bytes")

    exception_rva, exception_size = struct.unpack_from("<II", data, opt+112+3*8)
    pos = file_offset(exception_rva, exception_size)
    functions = sorted(struct.unpack_from("<III", data, at)[:2]
                       for at in range(pos, pos+exception_size, 12))
    starts = [begin for begin, _ in functions]
    names = ["game-type", "current-score", "player-number", "up-get-object-data"]
    strings = {}
    for name in names:
        needle = name.encode()+b"\0"
        for rva, _, raw, size, _ in sections:
            for match in re.finditer(re.escape(needle), data[raw:raw+size]):
                if match.start() == 0 or data[raw+match.start()-1] == 0:
                    strings[rva+match.start()] = name
    refs = []
    decoder = Cs(CS_ARCH_X86, CS_MODE_64)
    for rva, _, raw, size, flags in sections:
        if not flags & 0x20000000: continue
        code = data[raw:raw+size]
        # Candidate RIP-relative LEAs; disassemble from unwind-table function
        # start to reject byte patterns occurring inside other instructions.
        for match in re.finditer(rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....", code, re.DOTALL):
            at = rva+match.start()
            target = at+7+struct.unpack_from("<i", match.group(), 3)[0]
            if target not in strings: continue
            index = bisect.bisect_right(starts, at)-1
            if index < 0: continue
            begin, end = functions[index]
            if not begin <= at < end or end-begin > 2**20: continue
            offset = file_offset(begin, end-begin)
            instructions = list(decoder.disasm_lite(data[offset:offset+end-begin], begin))
            instruction_index = next((i for i, inst in enumerate(instructions) if inst[0] == at and inst[1] == 7 and inst[2] == "lea"), None)
            if instruction_index is None: continue
            context = instructions[max(0,instruction_index-8):instruction_index+10]
            refs.append(dict(name=strings[target], string_rva=hex(target), reference_rva=hex(at),
                             containing_function_rva=hex(begin), containing_function_end=hex(end),
                             context=[dict(rva=hex(a), instruction=m+" "+o) for a, _, m, o in context]))
    return dict(executable_sha256=file_hash, method="runtime_code_named_ai_string_xrefs" if pid is not None else "offline_named_ai_string_xrefs",
                safe_to_attach=False, functions_validated=False,
                limitation="String references may identify registration or parsing code rather than the named function. "
                           "String and unwind-table RVAs come from the on-disk executable. "
                           "Only RIP-relative LEA references covered by unwind entries are examined.",
                strings=[dict(name=n, rva=hex(r)) for r,n in strings.items()], references=refs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True)
    parser.add_argument("--output", default="reports/ai-symbol-candidates.json")
    parser.add_argument("--pid", type=int, help="Read live executable code; no dumps or writes")
    args = parser.parse_args()
    result = locate(args.game, args.pid)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
