# Corvia Windows Setup Script
# Run this in PowerShell (as normal user, not Administrator)

$ErrorActionPreference = "Stop"
$INSTALL_DIR = "$env:USERPROFILE\tools\corvia"
$TARGET = "D:\repo\duanyue\ws_fw"

Write-Host "=== Corvia Setup ===" -ForegroundColor Cyan

# Check Python
try {
    $pyver = python --version 2>&1
    Write-Host "Found: $pyver" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found. Install Python 3.9+ from https://python.org" -ForegroundColor Red
    exit 1
}

# Clone or update repo
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Host "Updating existing clone..." -ForegroundColor Yellow
    git -C $INSTALL_DIR pull origin main
} else {
    Write-Host "Cloning Corvia..." -ForegroundColor Yellow
    git clone https://github.com/kevintsou/Corvia.git $INSTALL_DIR
}

# Install
Write-Host "Installing corvia..." -ForegroundColor Yellow
pip install -e $INSTALL_DIR

# Verify
Write-Host "Verifying installation..." -ForegroundColor Yellow
corvia --version

# Run analysis
Write-Host ""
Write-Host "=== Running analysis on $TARGET ===" -ForegroundColor Cyan
corvia $TARGET

Write-Host ""
Write-Host "Done." -ForegroundColor Green
