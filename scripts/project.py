#!/usr/bin/env python3
"""Cross-platform development entry point for the MilkChan repositories."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

MILKCHAN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SENTIENT_ROOT = MILKCHAN_ROOT.parent / "SentientMilk"


def _display_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    dry_run: bool,
    extra_env: Mapping[str, str] | None = None,
) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    env_text = " ".join(f"{key}={value}" for key, value in (extra_env or {}).items())
    prefix = f"{env_text} " if env_text else ""
    print(f"[{cwd}] {prefix}{_display_command(command)}", flush=True)
    if not dry_run:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Develop, test, lint, and build MilkChan with SentientMilk.",
    )
    parser.add_argument(
        "--sentient-root",
        type=Path,
        default=DEFAULT_SENTIENT_ROOT,
        help="Path to the SentientMilk checkout (default: sibling repository).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )
    parser.add_argument(
        "command",
        choices=("setup", "dev", "test", "lint", "format", "build"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sentient_root = args.sentient_root.expanduser().resolve()
    if not (sentient_root / "sentientmilk_framework").is_dir():
        raise SystemExit(f"SentientMilk checkout not found: {sentient_root}")

    python = sys.executable
    if args.command == "setup":
        run(
            [python, "-m", "pip", "install", "-e", f"{sentient_root}[dev]"],
            cwd=MILKCHAN_ROOT,
            dry_run=args.dry_run,
        )
        run(
            [python, "-m", "pip", "install", "-e", ".[dev,build]"],
            cwd=MILKCHAN_ROOT,
            dry_run=args.dry_run,
        )
    elif args.command == "dev":
        run(
            [python, "-m", "milkchan.main"],
            cwd=MILKCHAN_ROOT,
            dry_run=args.dry_run,
            extra_env={"PYTHONPATH": str(sentient_root)},
        )
    elif args.command == "test":
        run(
            [python, "-m", "pytest", "-q"],
            cwd=sentient_root,
            dry_run=args.dry_run,
        )
        run(
            [python, "-m", "pytest", "-q"],
            cwd=MILKCHAN_ROOT,
            dry_run=args.dry_run,
            extra_env={"PYTHONPATH": str(sentient_root)},
        )
    elif args.command in {"lint", "format"}:
        ruff_action = "format" if args.command == "format" else "check"
        run(
            [python, "-m", "ruff", ruff_action, "."],
            cwd=sentient_root,
            dry_run=args.dry_run,
        )
        run(
            [python, "-m", "ruff", ruff_action, "."],
            cwd=MILKCHAN_ROOT,
            dry_run=args.dry_run,
        )
    elif args.command == "build":
        run(
            [python, "-m", "PyInstaller", "--noconfirm", "--clean", "MilkChan.spec"],
            cwd=MILKCHAN_ROOT,
            dry_run=args.dry_run,
            extra_env={"SENTIENTMILK_FRAMEWORK_PARENT": str(sentient_root)},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
