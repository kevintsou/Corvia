"""Automatic C preprocessor (cpp) installation for Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_cpp() -> str | None:
    for name in ("cpp", "gcc", "clang", "cl"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _is_cpp_available() -> bool:
    return _find_cpp() is not None


def install_cpp() -> int:
    if _is_cpp_available():
        cpp_path = _find_cpp()
        print(f"C preprocessor found: {cpp_path}")
        return 0

    print("C preprocessor (gcc/clang) not found.", file=sys.stderr)
    print(file=sys.stderr)

    if sys.platform != "win32":
        print("Please install gcc or clang using your system package manager:")
        print("  Ubuntu/Debian: sudo apt install gcc")
        print("  macOS: xcode-select --install")
        print("  Fedora: sudo dnf install gcc")
        return 1

    # On Windows, try to install MinGW via winget
    try:
        result = subprocess.run(["winget", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            try:
                answer = input("Install MinGW-w64 GCC via winget? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "y"
            if answer and answer not in ("y", "yes", ""):
                print("Skipped installation.")
                return 1

            print("Installing MinGW-w64 GCC (llvm-mingw)...")
            install_result = subprocess.run(
                ["winget", "install", "--id", "MartinStorsjo.LLVM-MinGW.MSVCRT", "--silent",
                 "--accept-package-agreements", "--accept-source-agreements"],
                capture_output=True,
                text=True,
            )
            if install_result.returncode == 0:
                print("MinGW-w64 installed successfully.")
                print("Please restart your terminal and run 'corvia --use-cpp' again.")
                return 0
            else:
                print(f"Installation failed: {install_result.stderr}", file=sys.stderr)
    except FileNotFoundError:
        pass

    print("\nwinget not available. Install manually:")
    print("  Option 1: Download llvm-mingw from https://github.com/mstorsjo/llvm-mingw/releases")
    print("  Option 2: Install MSYS2 from https://www.msys2.org/")
    print("  Option 3: Install MinGW-w64 from https://www.mingw-w64.org/")
    print("\nAfter installation, ensure 'gcc' or 'clang' is in your PATH.")
    return 1


def check_cpp_and_warn() -> None:
    if not _is_cpp_available():
        print("Warning: C preprocessor (gcc/clang) not found.", file=sys.stderr)
        print("  Run 'corvia-install-cpp' to install MinGW-w64.", file=sys.stderr)
        print("  Or install manually and ensure 'gcc' is in PATH.", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(install_cpp())
