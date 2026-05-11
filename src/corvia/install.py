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
    print("Corvia: Installing C preprocessor (cpp)...")

    if _is_cpp_available():
        cpp_path = _find_cpp()
        print(f"C preprocessor found: {cpp_path}")
        return 0

    if sys.platform != "win32":
        print("Auto-install is only supported on Windows. Please install gcc/clang manually.")
        return 1

    try:
        result = subprocess.run(
            ["winget", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("Using winget to install MinGW...")
            install_result = subprocess.run(
                ["winget", "install", "--id", "LLVM.LLVM", "--silent", "--accept-package-agreements", "--accept-source-agreements"],
                capture_output=True,
                text=True,
            )
            if install_result.returncode == 0:
                print("LLVM/Clang installed successfully.")
                print("Please restart your terminal and run 'corvia --version' to verify.")
                return 0
            else:
                print(f"winget install failed: {install_result.stderr}")

    except FileNotFoundError:
        pass

    print("\nwinget not available. Please install manually:")
    print("  Option 1: Download LLVM from https://clang.llvm.org/")
    print("  Option 2: Install MinGW-w64 from https://www.mingw-w64.org/")
    print("  Option 3: Install MSYS2 from https://www.msys2.org/")
    print("\nAfter installation, ensure 'cpp' or 'clang' is in your PATH.")
    return 1


def check_cpp_and_warn() -> None:
    if not _is_cpp_available():
        print("Warning: C preprocessor (cpp) not found. Use --use-cpp requires cpp installed.", file=sys.stderr)
        print("Run 'corvia-install-cpp' or 'pip install corvia[cpp]' to install.", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(install_cpp())