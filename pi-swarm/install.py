#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_DIR: Final = Path(__file__).parent
CLI_DIR: Final = REPO_DIR / "cli"
EXTENSION_DIR: Final = REPO_DIR / "extension"


def install_python_tool(package_dir: Path, command_name: str, *, editable: bool) -> None:
    args = ["uv", "tool", "install", "--force", "--reinstall"]
    if editable:
        args.append("-e")
    args.append(str(package_dir))

    print(f"Installing {command_name} Python tool from {package_dir}")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to install {command_name}:", file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(1)


def install_pi_package(package_dir: Path, label: str) -> None:
    npm = shutil.which("npm")
    if not npm:
        print(f"npm not found — skipping {label} install")
        return

    print(f"Installing {label} npm dependencies...")
    result = subprocess.run(
        [npm, "install"],
        cwd=package_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"npm install failed for {label}:", file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(1)

    pi = shutil.which("pi")
    if not pi:
        print(f"pi CLI not found — skipping {label} registration")
        return

    print(f"Registering {label} with pi...")
    result = subprocess.run(
        [pi, "install", str(package_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"pi install failed for {label}:", file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(1)


def parse_editable() -> bool:
    while True:
        response = input("Install in editable mode? [Y/n]: ").strip().lower()
        if response == "" or response.startswith("y"):
            return True
        if response.startswith("n"):
            return False
        print("Please answer y or n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up pi-swarm tools")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-e", "--editable", action="store_true", help="Install in editable mode")
    group.add_argument("--no-editable", action="store_true", help="Install in non-editable mode")
    args = parser.parse_args()

    if args.editable:
        editable = True
    elif args.no_editable:
        editable = False
    else:
        editable = parse_editable()

    print("\npi-swarm setup\n")
    print("Python tool")
    install_python_tool(CLI_DIR, "bc-swarm", editable=editable)

    print("\nPi package")
    install_pi_package(EXTENSION_DIR, "pi-swarm extension")

    print("\nDone.")
    print('If bc-swarm or pi is not found, add ~/.local/bin to PATH:')
    print('  export PATH="$HOME/.local/bin:$PATH"')


if __name__ == "__main__":
    main()
