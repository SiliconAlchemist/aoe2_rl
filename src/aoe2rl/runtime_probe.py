"""Read-only scan of AoE2DE_s.exe executable sections in its running process.

No injection, hooks, commands, debug privileges, memory writes or memory dumps.
Only hashes, coverage and candidate addresses are saved. Candidates are not
validated game functions and must not be used automatically as hook targets.
"""
import argparse
import ctypes
import hashlib
import json
import re
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
from .compatibility import signature_matches


def executable_sections(header):
    """Parse bounded AMD64 PE headers; returns RVA/virtual-size code ranges."""
    if len(header) < 64 or header[:2] != b"MZ":
        raise ValueError("Missing DOS header")
    pe = struct.unpack_from("<I", header, 60)[0]
    if pe + 24 > len(header) or header[pe:pe+4] != b"PE\0\0":
        raise ValueError("Missing PE header")
    machine, count = struct.unpack_from("<HH", header, pe + 4)
    optional_size = struct.unpack_from("<H", header, pe + 20)[0]
    optional = pe + 24
    table = optional + optional_size
    if machine != 0x8664 or not 0 < count <= 96 or optional_size < 112 or table + count*40 > len(header):
        raise ValueError("Unsupported or truncated AMD64 PE headers")
    if struct.unpack_from("<H", header, optional)[0] != 0x20b:
        raise ValueError("Expected PE32+")
    image_size = struct.unpack_from("<I", header, optional + 56)[0]
    if not 0 < image_size <= 2**30:
        raise ValueError("Unexpected image size")
    sections = []
    for i in range(count):
        offset = table + 40*i
        size, rva = struct.unpack_from("<II", header, offset + 8)
        flags = struct.unpack_from("<I", header, offset + 36)[0]
        if flags & 0x20000000 and size:
            if rva < table + count*40 or rva + size > image_size:
                raise ValueError("Executable section lies outside the image")
            name = header[offset:offset+8].split(b"\0")[0].decode("ascii", errors="replace")
            sections.append(dict(name=name, rva=rva, size=size))
    sections.sort(key=lambda s: s["rva"])
    if not sections or sum(s["size"] for s in sections) > 512*1024**2:
        raise ValueError("No executable sections or scan exceeds 512 MiB")
    if any(a["rva"]+a["size"] > b["rva"] for a, b in zip(sections, sections[1:])):
        raise ValueError("Overlapping executable sections")
    return sections


def scan_sections(read, base, sections, signatures, chunk_size=65536, seconds=30):
    if chunk_size <= 0 or seconds <= 0 or not signatures:
        raise ValueError("Invalid scan limits or empty signatures")
    for pattern in signatures.values():
        signature_matches(b"", pattern)  # Validate before any process read.
    overlap = max(len(p.split()) for p in signatures.values()) - 1
    deadline = time.monotonic() + seconds
    hits = {name: set() for name in signatures}
    coverage = []
    for section in sections:
        tail = b""
        digest = hashlib.sha256()
        scanned = 0
        failures = []
        for offset in range(0, section["size"], chunk_size):
            if time.monotonic() >= deadline:
                raise TimeoutError("Runtime scan exceeded its time budget")
            size = min(chunk_size, section["size"] - offset)
            rva = section["rva"] + offset
            try:
                chunk = read(base + rva, size)
                if len(chunk) != size:
                    raise OSError("Incomplete process memory read")
            except OSError as exc:
                failures.append(dict(rva=hex(rva), size=size, error=str(exc)))
                tail = b""  # Never match across unreadable memory.
                continue
            scanned += size
            digest.update(chunk)
            data = tail + chunk
            for name, pattern in signatures.items():
                hits[name].update(rva - len(tail) + pos for pos in signature_matches(data, pattern))
            tail = data[-overlap:] if overlap else b""
        coverage.append(dict(**section, bytes_read=scanned, complete=not failures,
                             sha256=digest.hexdigest() if not failures else None, failures=failures))
    complete = all(s["complete"] for s in coverage)
    results = []
    for name, matches in hits.items():
        status = "incomplete" if not complete else "candidate" if len(matches) == 1 else "missing" if not matches else "ambiguous"
        results.append(dict(name=name, status=status, match_count=len(matches),
                            rvas=[hex(rva) for rva in sorted(matches)[:32]],
                            addresses=[hex(base+rva) for rva in sorted(matches)[:32]]))
    return dict(coverage_complete=complete, sections=coverage, signatures=results)


class GameReader:
    def __init__(self, pid, game):
        import win32api
        import win32process
        if Path(game).name.lower() != "aoe2de_s.exe":
            raise ValueError("This reader only targets AoE2DE_s.exe")
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise ValueError("Run with 64-bit Python")
        self.handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
        try:
            modules = win32process.EnumProcessModules(self.handle)
            # The first module is the process image; reject a reused or wrong PID.
            if not modules or not Path(win32process.GetModuleFileNameEx(self.handle, modules[0])).samefile(game):
                raise ValueError("Running process image does not match the selected game executable")
            self.base = int(modules[0])
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            self.kernel.ReadProcessMemory.restype = ctypes.c_int
        except BaseException:
            self.close()
            raise

    def read(self, address, size):
        buffer = ctypes.create_string_buffer(size)
        received = ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(int(self.handle), address, buffer, size, ctypes.byref(received)):
            raise ctypes.WinError(ctypes.get_last_error())
        if received.value != size:
            raise OSError("Incomplete process memory read")
        return buffer.raw

    def close(self):
        self.handle.Close()


def probe(game, source, output, pid=None):
    import pywintypes
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), method="read_only_runtime_code_scan",
                  stage="preflight", error=None, safe_to_attach=False, function_identity_verified=False,
                  limitation="Scans only the main executable's code sections. No heap/game-state layout is validated. "
                             "The process is not suspended, so this is not an atomic snapshot. "
                             "Scans supplied source signatures, not CONTROL's private engine.")
    reader = None
    try:
        game, source = Path(game).resolve(), Path(source).resolve()
        if game.name.lower() != "aoe2de_s.exe":
            raise ValueError("This probe only targets AoE2DE_s.exe")
        file_data, source_data = game.read_bytes(), source.read_bytes()
        sections = executable_sections(file_data[:65536])
        definitions = re.findall(r'\b(SIG_FUNC_\w+)\s*=\s*"([^"]+)"', source_data.decode("utf-8"))
        if not definitions or len(dict(definitions)) != len(definitions):
            raise ValueError("Missing or duplicate signature definitions")
        report.update(executable=str(game), executable_sha256=hashlib.sha256(file_data).hexdigest(),
                      source_sha256=hashlib.sha256(source_data).hexdigest(), source=str(source))
        report["stage"] = "find_process"
        if pid is None:
            candidates = [p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "aoe2de_s.exe"]
            if len(candidates) != 1:
                raise ValueError(f"Expected one running DE process; found {len(candidates)}. Open DE or specify --pid.")
            pid = candidates[0]
        report.update(pid=pid, stage="open_process")
        reader = GameReader(pid, game)
        report.update(module_base=hex(reader.base), stage="read_headers")
        live_sections = executable_sections(reader.read(reader.base, 65536))
        if live_sections != sections:
            raise ValueError("Runtime section layout differs from selected executable; refusing to guess ranges")
        report["stage"] = "scan"
        report.update(scan_sections(reader.read, reader.base, sections, dict(definitions)))
        report["stage"] = "complete"
    except (OSError, ValueError, pywintypes.error, psutil.Error) as exc:
        report.update(error=str(exc), windows_error=getattr(exc, "winerror", None))
    finally:
        if reader is not None:
            reader.close()
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True)
    parser.add_argument("--source", default="vendor/aoe2-ai-module/aimodule/misc/Configuration.h")
    parser.add_argument("--output", default="reports/runtime-probe.json")
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    report = probe(args.game, args.source, args.output, args.pid)
    print(json.dumps(report, indent=2))
    if report["error"] or not report.get("coverage_complete") or any(s["status"] != "candidate" for s in report.get("signatures", [])):
        parser.exit(2, "Runtime compatibility is not established; inspect the saved report.\n")


if __name__ == "__main__":
    main()
