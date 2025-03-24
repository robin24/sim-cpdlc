#!/usr/bin/env python3
"""
Version Updater Script

This script updates all version numbers in the version_info.txt file.
It can be used manually or as part of a GitHub Actions workflow.
"""

import re
import sys
import argparse
from pathlib import Path


def parse_version(version_str):
    """
    Parse a version string into a tuple of integers.
    Supports formats like '1.2.3' or '1.2.3.4'.
    """
    parts = version_str.split(".")
    # Convert all parts to integers
    version_tuple = tuple(int(part) for part in parts)

    # Ensure we have at least 3 components
    if len(version_tuple) < 3:
        version_tuple = version_tuple + (0,) * (3 - len(version_tuple))

    # For file version, ensure we have exactly 4 components
    if len(version_tuple) < 4:
        version_tuple = version_tuple + (0,) * (4 - len(version_tuple))

    return version_tuple


def format_version_string(version_tuple):
    """
    Format a version tuple as a string with 3 components (e.g., '1.2.3').
    """
    # Use only the first 3 components for string representation
    return ".".join(str(part) for part in version_tuple[:3])


def update_version_info(file_path, new_version):
    """
    Update all version numbers in the version_info.txt file.

    Args:
        file_path: Path to the version_info.txt file
        new_version: New version string (e.g., '1.2.3')

    Returns:
        bool: True if file was updated, False otherwise
    """
    try:
        # Read the current content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse the new version
        version_tuple = parse_version(new_version)
        version_string = format_version_string(version_tuple)

        # Update filevers and prodvers tuples (all 4 components)
        content = re.sub(
            r"filevers=\(\d+,\s*\d+,\s*\d+,\s*\d+\)",
            f"filevers={version_tuple}",
            content,
        )
        content = re.sub(
            r"prodvers=\(\d+,\s*\d+,\s*\d+,\s*\d+\)",
            f"prodvers={version_tuple}",
            content,
        )

        # Update FileVersion and ProductVersion strings (3 components)
        content = re.sub(
            r"StringStruct\(u\'FileVersion\',\s*u\'[\d\.]+\'\)",
            f"StringStruct(u'FileVersion', u'{version_string}')",
            content,
        )
        content = re.sub(
            r"StringStruct\(u\'ProductVersion\',\s*u\'[\d\.]+\'\)",
            f"StringStruct(u'ProductVersion', u'{version_string}')",
            content,
        )

        # Write the updated content back to the file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True

    except Exception as e:
        print(f"Error updating version: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Update version numbers in version_info.txt"
    )
    parser.add_argument("version", help="New version number (e.g., 1.2.3)")
    parser.add_argument(
        "--file",
        default="version_info.txt",
        help="Path to version_info.txt (default: version_info.txt)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        return 1

    if args.dry_run:
        # Read the current content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse the new version
        version_tuple = parse_version(args.version)
        version_string = format_version_string(version_tuple)

        print(f"Would update version to: {args.version}")
        print(f"  - File version tuple: {version_tuple}")
        print(f"  - Version string: {version_string}")
        return 0

    success = update_version_info(file_path, args.version)
    if success:
        print(f"Successfully updated version to {args.version}")
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
