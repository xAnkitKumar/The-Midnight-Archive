#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap The Midnight Archive on Windows.

.DESCRIPTION
    Creates .venv (Python 3.12 via uv when available), installs requirements,
    checks FFmpeg, creates folders/schema and runs the environment doctor.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "The Midnight Archive - setup" -ForegroundColor Cyan
Write-Host "Project root: $root"

$python = Join-Path $root ".venv\Scripts\python.exe"
$uv = Get-Command uv -ErrorAction SilentlyContinue

if (-not (Test-Path $python)) {
    if ($uv) {
        Write-Host "Creating .venv with uv (Python 3.12)..."
        & uv venv --python 3.12 .venv
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Write-Host "Creating .venv with the py launcher..."
        & py -3.12 -m venv .venv
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Host "Creating .venv with python..."
        & python -m venv .venv
    }
    else {
        throw "Python 3.11+ not found. Install it with: winget install --id Python.Python.3.12 -e --scope user"
    }
}

if (-not (Test-Path $python)) {
    throw "Virtual environment was not created. Check the Python installation."
}

Write-Host "Installing Python dependencies..."
if ($uv) {
    & uv pip install -p .venv -r requirements.txt
}
else {
    # uv-created environments have no pip by default; make the fallback safe.
    & $python -m ensurepip --upgrade
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Write-Warning "FFmpeg is not on PATH. Install it with:"
    Write-Warning "  winget install --id Gyan.FFmpeg -e --scope user"
    Write-Warning "Then reopen the terminal. Phase 2 rendering needs ffmpeg and ffprobe."
}
else {
    Write-Host "FFmpeg: $($ffmpeg.Source)"
}

Write-Host "Initialising project folders and database..."
& $python -m midnight_archive init

if (-not $SkipDoctor) {
    Write-Host "Running environment doctor..."
    & $python -m midnight_archive doctor
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Doctor found missing required components. Fix them before rendering."
    }
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Activate the environment with:  .\.venv\Scripts\Activate.ps1"
Write-Host "Then try:                       python -m midnight_archive --help"
