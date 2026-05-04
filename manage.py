#!/usr/bin/env python3
"""Install / uninstall / reinstall myclaude into a Claude config dir.

Symlinks every item under ``installables/<category>/<name>`` to
``<claude-dir>/<category>/<name>`` using absolute paths, so edits in this
repo are visible to Claude immediately and vice versa.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = REPO_ROOT / "installables"

Item = Tuple[str, str, Path]  # (category, name, absolute source path)


def discover_items() -> List[Item]:
    """Return every installable item as (category, name, absolute_source)."""
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"{SOURCE_ROOT} not found")
    items: List[Item] = []
    for category_dir in sorted(SOURCE_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        for entry in sorted(category_dir.iterdir()):
            items.append((category_dir.name, entry.name, entry.resolve()))
    return items


def target_for(claude_dir: Path, category: str, name: str) -> Path:
    return claude_dir / category / name


def is_our_symlink(target: Path, source: Path) -> bool:
    """True iff ``target`` is a symlink whose absolute target equals ``source``."""
    if not target.is_symlink():
        return False
    link = Path(os.readlink(target))
    return link == source


def describe_existing(target: Path) -> str:
    if target.is_symlink():
        return f"symlink to {os.readlink(target)}"
    if target.is_dir():
        return "existing directory"
    if target.is_file():
        return "existing file"
    return "existing entry"


def cmd_install(claude_dir: Path, allow_partial: bool) -> int:
    items = discover_items()

    plan: List[Tuple[Path, Path]] = []
    noops: List[Tuple[Path, Path]] = []
    clashes: List[Tuple[Path, Path, str]] = []

    for category, name, source in items:
        target = target_for(claude_dir, category, name)
        if is_our_symlink(target, source):
            noops.append((target, source))
        elif target.is_symlink() or target.exists():
            clashes.append((target, source, describe_existing(target)))
        else:
            plan.append((target, source))

    if clashes and not allow_partial:
        print("ERROR: clashes detected — aborting install.")
        print("Re-run with --allow-partial-install to skip these slots.\n")
        for target, source, kind in clashes:
            print(f"  CLASH: {target}")
            print(f"         {kind}")
            print(f"         would link from: {source}")
        return 1

    if clashes:
        print("Skipping clashes (--allow-partial-install):")
        for target, _source, kind in clashes:
            print(f"  SKIP: {target} ({kind})")
        print()

    for target, source in noops:
        print(f"NOOP: {target} -> {source} (already linked)")

    for target, source in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(source, target)
        print(f"LINK: {target} -> {source}")

    print(
        f"\nDone. linked={len(plan)} already_linked={len(noops)} "
        f"clashes={len(clashes)}"
    )
    return 0


def cmd_uninstall(claude_dir: Path) -> int:
    items = discover_items()
    removed = 0
    skipped_foreign = 0
    skipped_real = 0
    not_present = 0

    for category, name, source in items:
        target = target_for(claude_dir, category, name)
        if is_our_symlink(target, source):
            target.unlink()
            print(f"UNLINK: {target}")
            removed += 1
            continue
        if target.is_symlink():
            print(f"SKIP: {target} (foreign symlink -> {os.readlink(target)})")
            skipped_foreign += 1
            continue
        if target.exists():
            print(f"SKIP: {target} ({describe_existing(target)}, not ours)")
            skipped_real += 1
            continue
        print(f"NOOP: {target} (not present)")
        not_present += 1

    print(
        f"\nDone. removed={removed} not_present={not_present} "
        f"skipped_foreign_symlink={skipped_foreign} skipped_real={skipped_real}"
    )
    return 0


def cmd_reinstall(claude_dir: Path) -> int:
    items = discover_items()
    created = 0
    already = 0
    skipped = 0

    for category, name, source in items:
        target = target_for(claude_dir, category, name)
        if is_our_symlink(target, source):
            print(f"NOOP: {target} -> {source} (already linked)")
            already += 1
            continue
        if target.is_symlink() or target.exists():
            print(f"SKIP: {target} ({describe_existing(target)})")
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(source, target)
        print(f"LINK: {target} -> {source}")
        created += 1

    print(
        f"\nDone. created={created} already_linked={already} skipped={skipped}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install / uninstall / reinstall myclaude into a Claude config dir.",
    )
    parser.add_argument(
        "--claude-dir",
        default=str(Path.home() / ".claude"),
        help="Target Claude config dir (default: ~/.claude).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Create symlinks for all items.")
    p_install.add_argument(
        "--allow-partial-install",
        action="store_true",
        help="Skip clashing slots instead of aborting.",
    )

    sub.add_parser("uninstall", help="Remove symlinks that point back to this repo.")
    sub.add_parser(
        "reinstall",
        help="Create any missing symlinks; leave existing ones untouched.",
    )

    args = parser.parse_args()
    claude_dir = Path(args.claude_dir).expanduser().resolve()

    if args.cmd == "install":
        return cmd_install(claude_dir, args.allow_partial_install)
    if args.cmd == "uninstall":
        return cmd_uninstall(claude_dir)
    if args.cmd == "reinstall":
        return cmd_reinstall(claude_dir)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
