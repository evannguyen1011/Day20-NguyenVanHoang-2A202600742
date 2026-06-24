#!/usr/bin/env python3
"""Probe the laptop and print which lab paths are open.

Cross-platform: Windows / macOS / Linux. Uses only stdlib so it runs
before any pip installs. Output is both a human-readable summary and
a JSON blob (`hardware.json`) the rest of the lab consumes.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def detect_cpu() -> dict:
    info = {"arch": platform.machine(), "cores_logical": os.cpu_count() or 1}
    sys_plat = sys.platform
    if sys_plat == "darwin":
        rc, out = run(["sysctl", "-n", "machdep.cpu.brand_string"])
        info["model"] = out.strip() if rc == 0 else "unknown"
        rc, out = run(["sysctl", "-n", "hw.physicalcpu"])
        info["cores_physical"] = int(out.strip()) if rc == 0 and out.strip().isdigit() else None
        info["apple_silicon"] = info["arch"] in ("arm64", "aarch64")
    elif sys_plat.startswith("linux"):
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            for line in cpuinfo.splitlines():
                if line.startswith("model name"):
                    info["model"] = line.split(":", 1)[1].strip()
                    break
            flags_line = next(
                (l for l in cpuinfo.splitlines() if l.startswith("flags") or l.startswith("Features")),
                "",
            )
            flags = flags_line.split(":", 1)[1].split() if ":" in flags_line else []
            info["avx2"] = "avx2" in flags
            info["avx512"] = any(f.startswith("avx512") for f in flags)
            info["neon"] = "neon" in flags or "asimd" in flags
        except OSError:
            info["model"] = "unknown"
    elif sys_plat == "win32":
        rc, out = run(["wmic", "cpu", "get", "Name,NumberOfCores", "/format:value"])
        if rc == 0 and "Name=" in out:
            for line in out.splitlines():
                if line.startswith("Name="):
                    info["model"] = line.split("=", 1)[1].strip()
                elif line.startswith("NumberOfCores="):
                    val = line.split("=", 1)[1].strip()
                    info["cores_physical"] = int(val) if val.isdigit() else None
        else:
            # wmic was removed in recent Windows 11 builds — fall back to PowerShell CIM.
            rc, out = run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "$c=Get-CimInstance Win32_Processor;"
                    "Write-Output ('Name=' + $c.Name);"
                    "Write-Output ('NumberOfCores=' + $c.NumberOfCores)",
                ],
                timeout=15,
            )
            for line in out.splitlines():
                if line.startswith("Name="):
                    info["model"] = line.split("=", 1)[1].strip()
                elif line.startswith("NumberOfCores="):
                    val = line.split("=", 1)[1].strip()
                    info["cores_physical"] = int(val) if val.isdigit() else None
    info.setdefault("model", "unknown")
    info.setdefault("cores_physical", info["cores_logical"])
    return info


def detect_ram_gb() -> float:
    sys_plat = sys.platform
    if sys_plat == "darwin":
        rc, out = run(["sysctl", "-n", "hw.memsize"])
        return round(int(out.strip()) / 1024**3, 1) if rc == 0 and out.strip().isdigit() else 0.0
    if sys_plat.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024**2, 1)
        except OSError:
            return 0.0
    if sys_plat == "win32":
        rc, out = run(["wmic", "computersystem", "get", "TotalPhysicalMemory", "/format:value"])
        for line in out.splitlines():
            if line.startswith("TotalPhysicalMemory="):
                val = line.split("=", 1)[1].strip()
                if val.isdigit():
                    return round(int(val) / 1024**3, 1)
        # wmic absent on recent Windows 11 — use the Win32 API via ctypes (stdlib).
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / 1024**3, 1)
        except Exception:
            pass
    return 0.0


def detect_gpu() -> dict:
    """Returns a dict listing which accelerator backends are available."""
    backends = {
        "nvidia_cuda": False,
        "amd_rocm": False,
        "apple_metal": False,
        "vulkan": False,
        "cpu_only": False,
    }
    details: dict[str, str] = {}

    if shutil.which("nvidia-smi"):
        rc, out = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
        if rc == 0 and out.strip():
            backends["nvidia_cuda"] = True
            details["nvidia"] = out.strip().splitlines()[0]

    if shutil.which("rocminfo"):
        rc, out = run(["rocminfo"])
        if rc == 0 and "AMD" in out:
            backends["amd_rocm"] = True
            details["amd_rocm"] = "available"

    if sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64"):
        backends["apple_metal"] = True
        details["apple_metal"] = "Apple Silicon"

    for tool in ("vulkaninfo", "vulkaninfoSDK"):
        if shutil.which(tool):
            rc, out = run([tool, "--summary"], timeout=8)
            if rc == 0 and "deviceName" in out.lower():
                backends["vulkan"] = True
                details["vulkan"] = "device present"
                break

    if not any(v for k, v in backends.items() if k != "cpu_only"):
        backends["cpu_only"] = True

    return {"backends": backends, "details": details}


def detect_docker() -> dict:
    info = {"docker": False, "compose": False}
    if shutil.which("docker"):
        rc, _ = run(["docker", "info"], timeout=8)
        info["docker"] = rc == 0
    if shutil.which("docker-compose") or info["docker"]:
        rc, _ = run(["docker", "compose", "version"], timeout=5)
        info["compose"] = rc == 0
    return info


def recommend(cpu: dict, ram: float, gpu: dict, docker: dict) -> dict:
    backends = gpu["backends"]

    # Pick the llama.cpp build backend with the best speed-vs-setup ratio.
    if backends["nvidia_cuda"]:
        primary_backend = "CUDA"
        cmake_flag = "-DGGML_CUDA=on"
    elif backends["apple_metal"]:
        primary_backend = "Metal"
        cmake_flag = "-DGGML_METAL=on"
    elif backends["amd_rocm"]:
        primary_backend = "ROCm/HIP"
        cmake_flag = "-DGGML_HIPBLAS=on"
    elif backends["vulkan"]:
        primary_backend = "Vulkan"
        cmake_flag = "-DGGML_VULKAN=on"
    else:
        primary_backend = "CPU (AVX/NEON tuning)"
        cmake_flag = ""  # default CPU build

    paths = [
        "01-llama-cpp-quickstart",
        "02-llama-cpp-server",
        "03-milestone-integration",
        "BONUS-llama-cpp-optimization",
    ]
    if backends["apple_metal"]:
        paths.append("BONUS-mlx-macos")

    if ram >= 32:
        model = "Qwen2.5-7B-Instruct (Q4_K_M)"
    elif ram >= 16:
        model = "Llama-3.2-3B-Instruct (Q4_K_M)"
    elif ram >= 8:
        model = "Qwen2.5-1.5B-Instruct (Q4_K_M)"
    else:
        model = "TinyLlama-1.1B (Q4_K_M)"

    return {
        "recommended_paths": paths,
        "recommended_model": model,
        "llama_cpp_backend": primary_backend,
        "llama_cpp_cmake_flag": cmake_flag,
    }


def main() -> int:
    cpu = detect_cpu()
    ram = detect_ram_gb()
    gpu = detect_gpu()
    docker = detect_docker()
    rec = recommend(cpu, ram, gpu, docker)

    print("─" * 60)
    print(f"  Platform : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  CPU      : {cpu['model']}")
    print(f"             {cpu.get('cores_physical', '?')} physical · {cpu['cores_logical']} logical cores")
    if cpu.get("avx512"):
        print("             AVX-512 available")
    elif cpu.get("avx2"):
        print("             AVX2 available")
    if cpu.get("neon"):
        print("             ARM NEON available")
    print(f"  RAM      : {ram} GB")
    print(f"  GPU      : ", end="")
    active = [k for k, v in gpu["backends"].items() if v and k != "cpu_only"]
    if active:
        print(", ".join(active))
        for k, v in gpu["details"].items():
            print(f"             - {k}: {v}")
    else:
        print("CPU only (no discrete accelerator)")
    print(f"  Docker   : {'yes' if docker['docker'] else 'no'} (compose: {'yes' if docker['compose'] else 'no'})")
    print("─" * 60)
    print("\nRecommended paths for your hardware:")
    for p in rec["recommended_paths"]:
        print(f"  • {p}")
    print(f"\nRecommended model: {rec['recommended_model']}")
    print(f"llama.cpp backend: {rec['llama_cpp_backend']}")
    if rec["llama_cpp_cmake_flag"]:
        print(f"  cmake flag:      {rec['llama_cpp_cmake_flag']}")
    print("─" * 60)

    out = {
        "cpu": cpu,
        "ram_gb": ram,
        "gpu": gpu,
        "docker": docker,
        "recommendation": rec,
    }
    Path("hardware.json").write_text(json.dumps(out, indent=2))
    print("\nSaved hardware.json — other lab scripts will read this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
