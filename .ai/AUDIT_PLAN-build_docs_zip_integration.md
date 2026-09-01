# AUDIT_PLAN: `build_docs_zip.py` Integration

## 1. Auditoría de Código

### 1.1 Análisis de Dependencias

```python
import argparse          # ✅ stdlib, available Python 3.0+
import hashlib           # ✅ stdlib, available Python 3.0+
import shutil            # ✅ stdlib, available Python 3.0+
import subprocess        # ✅ stdlib, available Python 3.0+
import sys               # ✅ stdlib, available Python 3.0+
import tomllib           # ⚠️ Python 3.11+ ONLY
from datetime import datetime    # ✅ stdlib
from pathlib import Path         # ✅ stdlib
```

**ISSUE #1: `tomllib` requires Python 3.11+**
- **Current Project Support:** Python 3.11+
- **Status:** ✅ Compatible
- **Note:** `tomllib` read-only; fallback to `toml` package not needed for CI/CD

**Validation:** OK ✅

---

### 1.2 Path Logic & Cross-Platform

```python
ROOT = Path(__file__).resolve().parent.parent  # .github/scripts/ → .github/ → root/
SITE_DIR = ROOT / "site"
PYPROJECT = ROOT / "pyproject.toml"
```

**Analysis:**
- ✅ `.resolve()` — handles symlinks, works on Windows/Linux/macOS
- ✅ `.parent.parent` — correct relative navigation
- ✅ Path concatenation (`/`) — cross-platform

**Issue #2: Circular Path Dependency if script moved to `scripts/`**
```python
# CURRENT (script in .github/scripts/)
ROOT = Path(__file__).resolve().parent.parent  # ✅ Correct: .github/scripts/.. = .github/.. = root/

# IF MOVED to scripts/
ROOT = Path(__file__).resolve().parent.parent  # ✅ Still correct: scripts/.. = root/.. = ERROR!
# FIX NEEDED:
ROOT = Path(__file__).resolve().parent  # ✅ scripts/. = root/
```

**Recommendation:** If moving to `scripts/`, update ROOT calculation to `.parent` only.

**Validation:** ⚠️ CONDITIONAL — depends on Tarea 2 decision

---

### 1.3 Version Extraction

```python
def _version() -> str:
    with PYPROJECT.open("rb") as fh:
        version: str = tomllib.load(fh)["project"]["version"]
    return version
```

**Risks:**
- ⚠️ **No error handling** — fails if `pyproject.toml` missing or malformed
- ⚠️ **KeyError risk** — if `["project"]["version"]` missing
- ⚠️ **Type hint incorrect** — `tomllib.load()` returns `dict[str, Any]`, not strongly typed

**Fix Recommendation:**
```python
def _version() -> str:
    """Extract version from pyproject.toml."""
    try:
        with PYPROJECT.open("rb") as fh:
            data = tomllib.load(fh)
        return data.get("project", {}).get("version", "0.0.0")
    except (FileNotFoundError, OSError) as e:
        print(f"[build_docs_zip] ERROR: Cannot read {PYPROJECT}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[build_docs_zip] ERROR: Invalid TOML in {PYPROJECT}: {e}", file=sys.stderr)
        sys.exit(1)
```

**Severity:** ⚠️ Medium (CI/CD context — pyproject.toml always exists)

---

### 1.4 Builder Command Construction

```python
def _build(builder: str, strict: bool) -> None:
    if builder == "mkdocs":
        cmd = [sys.executable, "-m", "mkdocs", "build"]
    else:
        cmd = [builder, "build"]  # ⚠️ Assumes builder is executable name
    if strict:
        cmd.append("--strict")
    print(f"[build_docs_zip] Building with: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)
```

**Issues:**
- ⚠️ **Security: Shell Injection Risk** — `builder` argument not validated, could be arbitrary command
  - **Current:** `--builder zensical` → executes `zensical build`
  - **Attack:** `--builder 'rm -rf /'` → would execute `rm -rf /`
  - **Mitigation:** Whitelist allowed builders or quote arguments

- ⚠️ **No check if mkdocs/builder installed** — subprocess fails if not available
  - **Current:** `subprocess.run()` without `capture_output=True`
  - **Better:** Check if command exists before running, or catch subprocess exception

- ⚠️ **cwd=ROOT not absolute** — if called from different CWD, may fail
  - **Better:** Use absolute path `cwd=str(ROOT.resolve())`

**Fixes Recommended:**
```python
def _build(builder: str, strict: bool) -> None:
    """Build documentation using specified builder."""
    # Whitelist allowed builders
    allowed_builders = {"mkdocs", "zensical"}
    if builder not in allowed_builders:
        print(f"[build_docs_zip] ERROR: Unknown builder '{builder}'. Allowed: {allowed_builders}", 
              file=sys.stderr)
        sys.exit(1)
    
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
            sys.exit(result.returncode)
    except FileNotFoundError:
        print(f"[build_docs_zip] ERROR: Builder '{builder}' not found. Install it first.", 
              file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[build_docs_zip] ERROR: Build failed: {e}", file=sys.stderr)
        sys.exit(1)
```

**Severity:** ⚠️ High (security + reliability)

---

### 1.5 ZIP Creation

```python
def _zip(output_dir: Path, version: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_stem = output_dir / f"{ZIP_PREFIX}-{version}"
    archive = Path(shutil.make_archive(str(zip_stem), "zip", SITE_DIR))
    print(f"[build_docs_zip] Created: {archive}")
    return archive
```

**Issues:**
- ⚠️ **SITE_DIR existence not verified** — `shutil.make_archive()` fails silently or exits with unclear error
- ⚠️ **Filename with special characters** — version could contain spaces or invalid chars
- ⚠️ **File overwrite without warning** — if ZIP exists, `make_archive()` silently overwrites

**Fix Recommended:**
```python
def _zip(output_dir: Path, version: str) -> Path:
    """Create ZIP archive of site/ directory."""
    if not SITE_DIR.exists():
        print(f"[build_docs_zip] ERROR: Site directory {SITE_DIR} not found. Run build first.",
              file=sys.stderr)
        sys.exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitize version for filename
    safe_version = version.replace(" ", "_").replace("/", "_")
    zip_stem = output_dir / f"{ZIP_PREFIX}-{safe_version}"
    
    # Warn if overwriting
    if zip_stem.with_suffix(".zip").exists():
        print(f"[build_docs_zip] WARNING: Overwriting {zip_stem.with_suffix('.zip').name}")
    
    archive = Path(shutil.make_archive(str(zip_stem), "zip", SITE_DIR))
    print(f"[build_docs_zip] Created: {archive}")
    return archive
```

**Severity:** ⚠️ Medium (UX + reliability)

---

### 1.6 SHA256 Calculation

```python
def _sha256_file(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()
```

**Analysis:**
- ✅ Correct chunked reading (memory-safe for large files)
- ✅ Binary mode (`"rb"`)
- ✅ `hexdigest()` returns lowercase hex string

**No Issues** ✅

---

### 1.7 Checksum File Creation

```python
def _create_checksum_files(archive: Path) -> str:
    """Create .sha256 and CHECKSUMS.txt files for integrity validation."""
    sha256_hash = _sha256_file(archive)

    sha256_file = archive.with_suffix(".zip.sha256")
    with open(sha256_file, "w") as f:
        f.write(f"{sha256_hash}  {archive.name}\n")

    checksums_file = archive.parent / "CHECKSUMS.txt"
    timestamp = datetime.now().isoformat()
    with open(checksums_file, "a") as f:
        f.write(f"{sha256_hash}  {archive.name}  ({timestamp})\n")
    ...
```

**Issues:**
- ⚠️ **CHECKSUMS.txt append mode** — file grows indefinitely, no rotation/cleanup
- ⚠️ **Encoding not explicit** — uses default (UTF-8 on Linux, CP1252 on Windows)
- ⚠️ **File permissions not set** — checksum files might not be readable by GitHub Actions

**Fix Recommendation:**
```python
def _create_checksum_files(archive: Path) -> str:
    """Create .sha256 and CHECKSUMS.txt files for integrity validation."""
    sha256_hash = _sha256_file(archive)

    # SHA256 file
    sha256_file = archive.with_suffix(".zip.sha256")
    with open(sha256_file, "w", encoding="utf-8") as f:
        f.write(f"{sha256_hash}  {archive.name}\n")
    sha256_file.chmod(0o644)  # Ensure readable

    # Checksums log (keep last 10 entries)
    checksums_file = archive.parent / "CHECKSUMS.txt"
    timestamp = datetime.now().isoformat()
    
    # Read existing entries
    entries = []
    if checksums_file.exists():
        with open(checksums_file, "r", encoding="utf-8") as f:
            entries = f.readlines()
    
    # Keep last 9 + add new
    entries = entries[-9:] if len(entries) >= 10 else entries
    entries.append(f"{sha256_hash}  {archive.name}  ({timestamp})\n")
    
    # Write back
    with open(checksums_file, "w", encoding="utf-8") as f:
        f.writelines(entries)
    checksums_file.chmod(0o644)
    ...
```

**Severity:** ⚠️ Medium (file management + cross-platform)

---

### 1.8 Argparse Configuration

```python
parser.add_argument(
    "--builder",
    choices=["mkdocs", "zensical"],
    default="mkdocs",
    help="Doc builder to use (default: mkdocs)",
)
```

**Analysis:**
- ✅ Whitelist via `choices=` — prevents shell injection (good!)
- ✅ Default is sensible
- ✅ Help text clear

**No Issues** ✅ (Whitelist mitigates builder security risk)

---

## 2. Integration Risks

### 2.1 Workflow Integration Risk

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| YAML syntax error | Low | 🔴 Blocks CI | Validate YAML before commit |
| `dist/` path wrong in workflow | Medium | 🔴 Blocks CI | Test artifact upload locally |
| ZIP too large (timeout) | Low | 🟡 Timeout | Set timeout limit in workflow |
| GitHub Release fails | Low | 🟡 Partial failure | Add `--continue-on-error` if needed |
| Disk space exhausted | Low | 🔴 Blocks CI | Clean up old artifacts periodically |

### 2.2 Script Execution Risk

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| `site/` directory missing | Low | 🔴 Fail | Script checks and exits gracefully |
| `mkdocs build` fails | Medium | 🔴 Fail | Stop before ZIP step (correct flow) |
| Version extraction fails | Low | 🔴 Fail | Add error handling to `_version()` |
| ZIP creation fails | Low | 🔴 Fail | Verify disk space, SITE_DIR not empty |
| SHA256 calculation takes too long | Very Low | 🟡 Timeout | Chunked read mitigates (8KB chunks) |

---

## 3. Gaps & Missing Features

### 3.1 Documentation

- ❌ No docstring for `main()` function
- ❌ No examples in module docstring of expected output
- ❌ No troubleshooting guide (e.g., "if script fails, check X")

**Recommendation:** Add comprehensive module docstring with examples.

---

### 3.2 Logging & Observability

- ⚠️ Print statements only (no logging framework)
- ✅ Sufficient for CI/CD context (stdout captured by GitHub Actions)

**Recommendation:** Keep simple print-based logging for CI/CD.

---

### 3.3 Testing

- ❌ No unit tests for `_sha256_file()`, `_version()`, etc.
- ❌ No integration test (e.g., `pytest -v` on script)

**Recommendation:** Add tests in `tests/unit/test_build_docs_zip.py` (optional for v0.3.0, but good practice).

---

### 3.4 GitHub Actions Specific

**Missing from script:**
- No environment variable injection (e.g., `GH_TOKEN` for Release creation)
- No GitHub API calls (delegated to `ncipollo/release-action@v1` — correct)

**Sufficient** ✅

---

## 4. Compatibility Matrix

| OS | Python 3.11 | Python 3.12 | Python 3.14 | Notes |
|----|------------|------------|------------|-------|
| Windows | ✅ | ✅ | ✅ | Path() works, tomllib available |
| Linux | ✅ | ✅ | ✅ | Same as Windows |
| macOS | ✅ | ✅ | ✅ | Same as Windows |

**GitHub Actions Environment:** Ubuntu 22.04 (Python 3.12+) ✅

---

## 5. Blocking Issues (Must Fix Before IMPLEMENT)

| Issue | Severity | Fix |
|-------|----------|-----|
| **ZIP_PREFIX = "doc_calidad-docs"** | 🔴 High | Change to `"doc_organize-docs"` |
| **Path inconsistency (.github/scripts/ vs scripts/)** | 🔴 High | Move to `scripts/` + update ROOT calc |
| **No error handling in _version()** | 🟡 Medium | Add try/except + fallback |
| **Shell injection risk in _build()** | 🟡 Medium | Already mitigated by argparse choices |
| **SITE_DIR not verified** | 🟡 Medium | Add existence check before ZIP |

---

## 6. Non-Blocking Issues (Nice-to-Have)

| Issue | Severity | Fix |
|-------|----------|-----|
| **CHECKSUMS.txt unbounded growth** | 🟢 Low | Rotate/trim old entries |
| **File permissions** | 🟢 Low | Set 0o644 on output files |
| **Encoding not explicit** | 🟢 Low | Add `encoding="utf-8"` to `open()` |
| **No unit tests** | 🟢 Low | Add tests (optional) |

---

## 7. Pre-Integration Validation Checklist

Before proceeding to IMPLEMENT, validate:

- [ ] **Decisión #1:** ¿Mover script a `scripts/` (Opción A) o dejar en `.github/scripts/` (Opción B)?
- [ ] **Decisión #2:** ¿Corregir ZIP_PREFIX a `doc_organize-docs`?
- [ ] **Decisión #3:** ¿Full workflow restore (all 5 steps) o gradual?
- [ ] **Testing:** ¿Ejecutar script localmente antes de commit?
  - Test command: `python .github/scripts/build_docs_zip.py --no-build` (ZIPs existing site/)
  - Expected output: `dist/doc_organize-docs-0.3.0.zip`, `.sha256`, `CHECKSUMS.txt`
- [ ] **YAML Validation:** ¿Validar workflow YAML antes de push?
  - Test command: `python -m yaml < .github/workflows/docs-zip-release.yml`
- [ ] **Documentation:** ¿Actualizar README + CHANGELOG antes de release?

---

## 8. Summary & Recommendation

| Dimension | Status | Note |
|-----------|--------|------|
| **Code Quality** | ⚠️ Medium | Needs error handling + validation |
| **Security** | ✅ Good | Whitelist in argparse mitigates shell injection |
| **Reliability** | ⚠️ Medium | Missing edge case handling |
| **CI/CD Readiness** | 🟡 Ready* | *With fixes: ZIP_PREFIX, path consistency |
| **Cross-Platform** | ✅ Good | Python + Path() handle Windows/Linux/macOS |

### Recommendation

**🚀 PROCEED TO IMPLEMENT** with the following conditions:

1. ✅ Apply blocking fixes (ZIP_PREFIX, path consistency)
2. ✅ Apply medium-severity improvements (error handling, validation)
3. ✅ Restore workflow steps (uncomment 5 steps)
4. ✅ Validate YAML + test locally
5. ✅ Update documentation (README, CHANGELOG)
6. ⏸️ Optional: Add unit tests (can defer to v0.3.1)

**Estimated effort:** ~35 minutes
**Risk level:** Low (with fixes)
**Go/No-Go:** ✅ **GO** (pending user confirmation of decisions)

---

## 9. Next Steps

**Status:** 🔴 AWAITING USER INPUT

**User must confirm:**
1. **Decisions** (see § 6 "Matriz de Decisiones")
2. **Testing strategy** (local dry-run? immediate push?)
3. **Documentation updates** (which files to update?)

**Then:** → IMPLEMENT phase (apply all fixes + restore workflow + test + commit + push)
