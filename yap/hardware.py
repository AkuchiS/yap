"""Hardware detection + adaptive model choice.

Old machines and new ones shouldn't run the same Whisper model. This picks a
size that will actually feel responsive on the box it's running on — tiny/base
on a 2019 Intel laptop, small on a modern machine, bigger only with a GPU.
"""

from __future__ import annotations

import multiprocessing
import platform
import subprocess
import sys
from typing import Optional


def _ram_gb() -> Optional[float]:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, check=True).stdout
            return int(out.strip()) / 1e9
        if sys.platform.startswith("win") or sys.platform == "cygwin":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1e9
        import os

        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:
        return None


def _has_cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def detect() -> dict:
    machine = platform.machine().lower()
    is_mac = sys.platform == "darwin"
    return {
        "platform": platform.platform(),
        "machine": machine,
        "apple_silicon": is_mac and machine in ("arm64", "aarch64"),
        "intel_mac": is_mac and machine in ("x86_64", "amd64", "x86"),
        "cores": multiprocessing.cpu_count() or 2,
        "ram_gb": _ram_gb(),
        "cuda": _has_cuda(),
    }


def recommend_model(prefer_english: bool = True, info: Optional[dict] = None) -> str:
    info = info or detect()
    ram = info["ram_gb"] or 8.0
    cores = info["cores"]

    if info["cuda"]:
        base = "small"            # a GPU can do more, but small keeps latency low
    elif ram < 4 or cores <= 2:
        base = "tiny"             # very old / very light machines
    elif info["intel_mac"] or ram < 8:
        base = "base"             # 2019 Intel MBP territory
    else:
        base = "small"           # modern laptop, Apple Silicon, etc.

    # English-only variants are smaller and more accurate for English.
    if prefer_english and base in ("tiny", "base", "small"):
        return base + ".en"
    return base


def recommend_runtime(info: Optional[dict] = None) -> tuple[str, str]:
    info = info or detect()
    if info["cuda"]:
        return "cuda", "float16"
    return "cpu", "int8"


def summary() -> str:
    info = detect()
    ram = f"{info['ram_gb']:.0f} GB" if info["ram_gb"] else "unknown"
    chip = ("Apple Silicon" if info["apple_silicon"]
            else "Intel Mac" if info["intel_mac"]
            else info["machine"])
    dev, ct = recommend_runtime(info)
    lines = [
        f"  platform : {info['platform']}",
        f"  chip     : {chip}",
        f"  cores    : {info['cores']}",
        f"  memory   : {ram}",
        f"  gpu/cuda : {'yes' if info['cuda'] else 'no'}",
        "",
        f"  recommended model   : {recommend_model(info=info)}",
        f"  recommended runtime : {dev} ({ct})",
    ]
    return "\n".join(lines)
