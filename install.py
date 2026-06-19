#!/usr/bin/env python3
# /// script
# dependencies = [
#   "questionary>=2.1.1",
#   "rich>=13.0",
# ]
# requires-python = ">=3.12"
# ///
"""Bootstrap installer for basecamp.

Run this once after cloning to get the `basecamp` binary on PATH.
Subsequent reconfiguration: `basecamp install`.
"""

import argparse
import sys

from basecamp_cli.installer import run_interactive_install


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up basecamp tools")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-e", "--editable", action="store_true", help="Install in editable mode")
    group.add_argument("--no-editable", action="store_true", help="Install in non-editable mode")
    args = parser.parse_args()

    editable: bool | None
    if args.editable:
        editable = True
    elif args.no_editable:
        editable = False
    else:
        editable = None

    run_interactive_install(editable=editable)


if __name__ == "__main__":
    main()
