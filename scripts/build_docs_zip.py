#!/usr/bin/env python3
"""Build the documentation site and package it as a ZIP for offline distribution.

This script:
1. Builds documentation using MkDocs (or alternative builder)
2. Creates a ZIP archive of the site/ directory
3. Generates SHA256 checksums for integrity validation
4. Maintains a CHECKSUMS.txt log for version tracking

Usage:
    python scripts/build_docs_zip.py
    python scripts/build_docs_zip.py --builder zensical
    python scripts/build_docs_zip.py --no-build          # only zip an existing site/
    python scripts/build_docs_zip.py --output-dir /tmp

Output:
    dist/doc_organize-docs-{version}.zip
    dist/doc_organize-docs-{version}.zip.sha256
    dist/CHECKSUMS.txt (appended)

Examples:
    >>> # Full workflow: build docs + zip + checksums
    >>> python scripts/build_docs_zip.py
    [build_docs_zip] Building with: /usr/bin/python -m mkdocs build --strict
    [build_docs_zip] Building documentation...
    [build_docs_zip] Creating ZIP archive from site/...
    [build_docs_zip] ZIP created: doc_organize-docs-0.3.0.zip (2.45 MB)
    [build_docs_zip] SHA256: a1b2c3d4e5f6...
    [build_docs_zip] Checksum saved to: doc_organize-docs-0.3.0.zip.sha256
    [build_docs_zip] All checksums in: CHECKSUMS.txt

    >>> # Skip build, only zip existing site/
    >>> python scripts/build_docs_zip.py --no-build
    [build_docs_zip] Skipping build step, using existing site/
    [build_docs_zip] Creating ZIP archive from site/...
    [build_docs_zip] ZIP created: doc_organize-docs-0.3.0.zip (2.45 MB)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys

from datetime import datetime
from pathlib import Path

import tomllib

# Root directory: scripts/ -> root/
# If script is in scripts/build_docs_zip.py:
#   Path(__file__).resolve() = /path/to/scripts/build_docs_zip.py
#   .parent = /path/to/scripts/
#   .parent.parent = /path/to/ (root)
ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
PYPROJECT = ROOT / "pyproject.toml"
ZIP_PREFIX = "doc_organize-docs"


def _version() -> str:
    """Extract project version from pyproject.toml.

    Returns:
        str: Version string (e.g., '0.3.0')

    Raises:
        SystemExit: If pyproject.toml cannot be read or parsed
    """
    try:
        with PYPROJECT.open("rb") as fh:
            data = tomllib.load(fh)
        version = data.get("project", {}).get("version")
        if not isinstance(version, str):
            raise TypeError(f"Expected str version, got {type(version).__name__}")
        if not version:
            raise ValueError("Empty version string in pyproject.toml")
        return version
    except FileNotFoundError:
        print(
            f"[build_docs_zip] ERROR: {PYPROJECT} not found. Must run from project root.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"[build_docs_zip] ERROR: Cannot read version from {PYPROJECT}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def _build(builder: str, strict: bool) -> None:
    """Build documentation using specified builder.

    Args:
        builder: Builder name ('mkdocs' or 'zensical')
        strict: Whether to pass --strict flag to builder

    Raises:
        SystemExit: If build fails or builder not found
    """
    # Whitelist allowed builders (security: prevent shell injection)
    allowed_builders = {"mkdocs", "zensical"}
    if builder not in allowed_builders:
        print(
            f"[build_docs_zip] ERROR: Unknown builder '{builder}'. Allowed: {', '.join(sorted(allowed_builders))}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Construct command
    if builder == "mkdocs":
        cmd = [sys.executable, "-m", "mkdocs", "build"]
    else:
        cmd = [builder, "build"]

    if strict:
        cmd.append("--strict")

    print(f"[build_docs_zip] Building with: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=str(ROOT.resolve()), check=False)
        if result.returncode != 0:
            print(
                f"[build_docs_zip] ERROR: Build failed with exit code {result.returncode}",
                file=sys.stderr,
            )
            sys.exit(result.returncode)
    except FileNotFoundError:
        print(
            f"[build_docs_zip] ERROR: Builder '{builder}' not found. Install it first.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"[build_docs_zip] ERROR: Build failed: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def _zip(output_dir: Path, version: str) -> Path:
    """Create ZIP archive of site/ directory.

    Args:
        output_dir: Directory where ZIP will be saved
        version: Version string for filename

    Returns:
        Path: Path to created ZIP file

    Raises:
        SystemExit: If site/ not found or ZIP creation fails
    """
    # Verify site/ exists
    if not SITE_DIR.exists():
        print(
            f"[build_docs_zip] ERROR: Site directory {SITE_DIR} not found. Run build first (without --no-build).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not any(SITE_DIR.iterdir()):
        print(
            f"[build_docs_zip] ERROR: Site directory {SITE_DIR} is empty.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize version for safe filename (whitelist alphanumeric + valid chars)
    safe_version = re.sub(r"[^a-zA-Z0-9._\-+]", "_", version)

    # Warn if overwriting
    zip_stem = output_dir / f"{ZIP_PREFIX}-{safe_version}"
    zip_path = zip_stem.with_suffix(".zip")
    if zip_path.exists():
        print(
            f"[build_docs_zip] WARNING: Overwriting existing {zip_path.name}",
        )

    # Create ZIP
    try:
        print(f"[build_docs_zip] Creating ZIP archive from {SITE_DIR}...")
        archive = Path(shutil.make_archive(str(zip_stem), "zip", SITE_DIR))
        return archive
    except Exception as e:
        print(
            f"[build_docs_zip] ERROR: Failed to create ZIP: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def _sha256_file(file_path: Path) -> str:
    """Calculate SHA256 hash of a file.

    Args:
        file_path: Path to file

    Returns:
        str: Lowercase hex digest of SHA256 hash
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
    except Exception as e:
        print(
            f"[build_docs_zip] ERROR: Cannot read {file_path} for hashing: {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    return sha256_hash.hexdigest()


def _create_checksum_files(archive: Path) -> str:
    """Create .sha256 and CHECKSUMS.txt files for integrity validation.

    Creates:
    - {archive}.sha256: Single-line SHA256 file for direct verification
    - CHECKSUMS.txt: Appended log of all builds with timestamps

    Args:
        archive: Path to ZIP file

    Returns:
        str: SHA256 hash string
    """
    sha256_hash = _sha256_file(archive)
    file_size_mb = archive.stat().st_size / (1024 * 1024)

    # Create .sha256 file (single checksum for verification)
    sha256_file = archive.with_suffix(".zip.sha256")
    sha256_file.unlink(missing_ok=True)  # Clean up old checksum file
    try:
        with open(sha256_file, "w", encoding="utf-8") as f:
            f.write(f"{sha256_hash}  {archive.name}\n")
        # Make readable by GitHub Actions and other processes
        try:
            os.chmod(sha256_file, 0o644)
        except OSError:
            pass  # chmod may not be supported on all platforms (e.g., Windows)
    except Exception as e:
        print(
            f"[build_docs_zip] ERROR: Cannot write {sha256_file}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create/append to CHECKSUMS.txt (historical log)
    checksums_file = archive.parent / "CHECKSUMS.txt"
    timestamp = datetime.now().isoformat()
    try:
        with open(checksums_file, "a", encoding="utf-8") as f:
            f.write(f"{sha256_hash}  {archive.name}  ({timestamp})\n")
        try:
            os.chmod(checksums_file, 0o644)
        except OSError:
            pass  # chmod may not be supported on all platforms (e.g., Windows)
    except Exception as e:
        print(
            f"[build_docs_zip] ERROR: Cannot write {checksums_file}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Print summary
    print(f"\n[build_docs_zip] ZIP created: {archive.name} ({file_size_mb:.2f} MB)")
    print(f"[build_docs_zip] SHA256: {sha256_hash}")
    print(f"[build_docs_zip] Checksum saved to: {sha256_file.name}")
    print(f"[build_docs_zip] All checksums in: {checksums_file.name}")

    return sha256_hash


def main() -> None:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Build documentation and package as offline ZIP.",
        epilog="Examples:\n"
        "  python scripts/build_docs_zip.py\n"
        "  python scripts/build_docs_zip.py --no-build\n"
        "  python scripts/build_docs_zip.py --output-dir /tmp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--builder",
        choices=["mkdocs", "zensical"],
        default="mkdocs",
        help="Doc builder to use (default: mkdocs)",
    )
    parser.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        default=True,
        help="Skip --strict flag when building",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        default=False,
        help="Skip the build step; zip whatever is already in site/",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        metavar="DIR",
        help="Directory for the output ZIP (default: dist/)",
    )
    args = parser.parse_args()

    # Build phase (unless --no-build)
    if not args.no_build:
        _build(args.builder, args.strict)
    elif not SITE_DIR.exists():
        print(
            f"[build_docs_zip] ERROR: {SITE_DIR} does not exist. Run without --no-build first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ZIP phase
    output_dir = Path(args.output_dir) if Path(args.output_dir).is_absolute() else ROOT / args.output_dir
    archive = _zip(output_dir, _version())

    # Checksum phase
    _create_checksum_files(archive)


if __name__ == "__main__":
    main()
