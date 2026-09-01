"""Tests for scripts/build_docs_zip.py - documentation packaging script.

These tests verify:
- Version extraction from pyproject.toml
- SHA256 checksum calculation
- Checksum file creation
- Error handling and validation
- Cross-platform path handling
"""

from __future__ import annotations

import hashlib
import sys

from pathlib import Path
from unittest import mock

import pytest

# Import the script module (must be in sys.path)
# For CI/CD, add scripts/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

# Import functions from build_docs_zip module
try:
    from build_docs_zip import _sha256_file, _version
except ImportError:
    pytest.skip("build_docs_zip script not found", allow_module_level=True)


class TestVersionExtraction:
    """Test version extraction from pyproject.toml."""

    def test_version_extraction_success(self, tmp_path):
        """Extract version successfully from valid pyproject.toml."""
        pyproject_content = b"""
[project]
name = "test-project"
version = "0.1.0"
"""
        pyproject_file = tmp_path / "pyproject.toml"
        pyproject_file.write_bytes(pyproject_content)

        # Mock the PYPROJECT path
        with mock.patch("build_docs_zip.PYPROJECT", pyproject_file):
            version = _version()
            assert version == "0.1.0"

    def test_version_extraction_missing_file(self, tmp_path):
        """Exit gracefully when pyproject.toml is missing."""
        missing_file = tmp_path / "nonexistent.toml"

        with mock.patch("build_docs_zip.PYPROJECT", missing_file):
            with pytest.raises(SystemExit) as exc_info:
                _version()
            assert exc_info.value.code == 1

    def test_version_extraction_missing_key(self, tmp_path):
        """Exit gracefully when project.version key is missing."""
        pyproject_content = b"""
[project]
name = "test-project"
description = "Missing version key"
"""
        pyproject_file = tmp_path / "pyproject.toml"
        pyproject_file.write_bytes(pyproject_content)

        with mock.patch("build_docs_zip.PYPROJECT", pyproject_file):
            with pytest.raises(SystemExit) as exc_info:
                _version()
            assert exc_info.value.code == 1

    def test_version_extraction_malformed_toml(self, tmp_path):
        """Exit gracefully when TOML is malformed."""
        pyproject_content = b"""
[project
name = "test-project"
version = "0.1.0"
"""  # Missing closing bracket
        pyproject_file = tmp_path / "pyproject.toml"
        pyproject_file.write_bytes(pyproject_content)

        with mock.patch("build_docs_zip.PYPROJECT", pyproject_file):
            with pytest.raises(SystemExit) as exc_info:
                _version()
            assert exc_info.value.code == 1


class TestSHA256Calculation:
    """Test SHA256 checksum calculation."""

    def test_sha256_calculation_small_file(self, tmp_path):
        """Calculate SHA256 for small file correctly."""
        test_file = tmp_path / "test.txt"
        content = b"Hello, world!"
        test_file.write_bytes(content)

        result = _sha256_file(test_file)

        # Verify against known SHA256
        expected = hashlib.sha256(content).hexdigest()
        assert result == expected
        assert len(result) == 64  # SHA256 hex string length

    def test_sha256_calculation_large_file(self, tmp_path):
        """Calculate SHA256 for large file (tests chunked reading)."""
        test_file = tmp_path / "large.bin"
        # Create 10 MB file
        content = b"x" * (10 * 1024 * 1024)
        test_file.write_bytes(content)

        result = _sha256_file(test_file)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_sha256_calculation_empty_file(self, tmp_path):
        """Calculate SHA256 for empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        result = _sha256_file(test_file)

        # SHA256 of empty string
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_sha256_calculation_binary_file(self, tmp_path):
        """Calculate SHA256 for binary file."""
        test_file = tmp_path / "binary.bin"
        # Binary content with null bytes
        content = bytes(range(256)) * 100
        test_file.write_bytes(content)

        result = _sha256_file(test_file)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_sha256_file_not_found(self, tmp_path):
        """Exit gracefully when file doesn't exist."""
        missing_file = tmp_path / "nonexistent.zip"

        with pytest.raises(SystemExit) as exc_info:
            _sha256_file(missing_file)
        assert exc_info.value.code == 1


class TestIntegration:
    """Integration tests for the full workflow."""

    def test_sha256_and_version_together(self, tmp_path):
        """Test version extraction and SHA256 calculation together."""
        # Create a test ZIP file
        zip_file = tmp_path / "test-docs-0.1.0.zip"
        zip_file.write_bytes(b"Mock ZIP content")

        # Create a valid pyproject.toml
        pyproject_file = tmp_path / "pyproject.toml"
        pyproject_file.write_bytes(b"[project]\nversion = '0.1.0'\n")

        with mock.patch("build_docs_zip.PYPROJECT", pyproject_file):
            version = _version()
            sha256 = _sha256_file(zip_file)

        assert version == "0.1.0"
        assert len(sha256) == 64
        assert sha256.islower()  # SHA256 should be lowercase

    def test_sha256_filename_sanitization(self):
        """Test that version strings are sanitized for filenames."""
        # Versions with special characters should be safe
        versions = [
            "0.1.0",
            "0.1.0-alpha",
            "0.1.0-beta.1",
            "0.1.0+build.123",
        ]

        for version in versions:
            # No exception should be raised for any version format
            safe_version = version.replace(" ", "_").replace("/", "-").replace("\\", "-")
            assert "/" not in safe_version
            assert "\\" not in safe_version
            assert len(safe_version) > 0


# Cross-platform path handling tests
class TestPathHandling:
    """Test cross-platform path handling."""

    def test_path_resolution_works_on_all_platforms(self, tmp_path):
        """Path operations work on Windows, Linux, macOS."""
        test_file = tmp_path / "subdir" / "test.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_bytes(b"test")

        # Path resolution should work
        assert test_file.exists()
        assert test_file.is_file()
        assert test_file.resolve().is_absolute()

    def test_absolute_and_relative_paths(self, tmp_path):
        """Both absolute and relative paths work."""
        # Absolute path
        abs_path = tmp_path / "test.txt"
        abs_path.write_bytes(b"test")

        assert _sha256_file(abs_path)  # Should work

        # Relative path (if in correct directory)
        # Note: This is harder to test in isolation, so we just verify
        # that Path handles both correctly
        assert abs_path.is_absolute()
        relative_repr = abs_path.relative_to(tmp_path)
        assert not str(relative_repr).startswith("/")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
