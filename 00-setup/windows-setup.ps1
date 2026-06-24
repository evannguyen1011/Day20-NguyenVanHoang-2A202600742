# Day 20 lab setup (Windows). Requires PowerShell 7+ (`pwsh`).
# Two supported paths:
#   1. Native Windows (CPU only, prebuilt llama-cpp-python wheel)
#   2. WSL2 — recommended if you have an NVIDIA GPU; run linux-setup.sh inside WSL.
#
# Run as: pwsh -ExecutionPolicy Bypass -File 00-setup\windows-setup.ps1
$ErrorActionPreference = 'Stop'

Set-Location (Join-Path $PSScriptRoot '..')
$LabRoot = (Get-Location).Path

Write-Host "==> Day 20 lab setup (Windows)" -ForegroundColor Cyan
Write-Host "    repo: $LabRoot"

# 1. Python check (3.10–3.12 supported)
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python 3.10+ not found. Install from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
$pyVer = (& python --version) 2>&1
Write-Host "    Python: $pyVer"

# 2. virtualenv
if (-not (Test-Path '.venv')) {
    Write-Host "==> Creating .venv"
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

Write-Host "==> Upgrading pip"
python -m pip install --upgrade pip wheel | Out-Null

Write-Host "==> Installing Python deps from requirements.txt"
pip install -r requirements.txt

# 3. llama-cpp-python — prebuilt CPU wheel works on Windows out of the box.
#    For CUDA, set $env:LLAMA_CUDA=1 and ensure CUDA Toolkit + cmake are installed.
if ($env:LLAMA_CUDA -eq '1') {
    Write-Host "==> Building llama-cpp-python with CUDA (requires CUDA Toolkit + cmake)"
    $env:CMAKE_ARGS = '-DGGML_CUDA=on'
    pip install --upgrade --force-reinstall --no-cache-dir "llama-cpp-python[server]"
} else {
    # Pin 0.3.19 (last proper cp312 AVX2 build on the CPU wheel index). The newer
    # generic win_amd64 wheels (0.3.24+) are compiled with AVX-512 and crash with
    # STATUS_ILLEGAL_INSTRUCTION (0xc000001d) on AVX2-only CPUs (e.g. AMD Zen 2).
    Write-Host "==> Installing prebuilt llama-cpp-python 0.3.19 (CPU / AVX2)"
    pip install "llama-cpp-python[server]==0.3.19" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
}

# 4. Probe + download model
#    Force UTF-8 so the Unicode box-drawing output doesn't crash on the
#    legacy cp1252 Windows console.
$env:PYTHONUTF8 = '1'
python .\00-setup\detect-hardware.py
python .\00-setup\download-model.py

Write-Host ""
Write-Host "==> Setup complete. Activate the venv next time with:" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "==> If you have an NVIDIA GPU, consider WSL2 path instead:"
Write-Host "    wsl --install -d Ubuntu-22.04"
Write-Host "    Then inside WSL: bash 00-setup/linux-setup.sh"
Write-Host ""
Write-Host "==> Next: 01-llama-cpp-quickstart\README.md"
