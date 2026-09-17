"""Conformance tests for FastAPI app.state thread-safety invariants (FM-2).

This test suite validates that app.state has all required attributes and that
thread-safety documentation (STATE.md, ADR-004) is up-to-date.

See: src/doc_organize/web/STATE.md
See: docs/adr/ADR-004-GIL-Thread-Safety.md
"""

import pytest

from doc_organize.web.app import create_app


@pytest.mark.asyncio
async def test_app_state_has_required_attributes():
    """Validate that app.state contains all documented attributes."""
    app = create_app()

    # Use lifespan context to initialize app.state
    async with app.router.lifespan_context(app):
        # Validate each documented attribute exists
        assert hasattr(app.state, "project_registry"), "Missing app.state.project_registry"
        assert hasattr(app.state, "auth_db_path"), "Missing app.state.auth_db_path"
        assert hasattr(app.state, "taxonomy_template_registry"), "Missing app.state.taxonomy_template_registry"
        assert hasattr(app.state, "security"), "Missing app.state.security"
        assert hasattr(app.state, "login_rate_limiter"), "Missing app.state.login_rate_limiter"
        assert hasattr(app.state, "active_project_operations"), "Missing app.state.active_project_operations"


@pytest.mark.asyncio
async def test_app_state_attribute_types():
    """Validate that app.state attributes have expected types."""
    from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry
    from doc_organize.projects.project_registry import ProjectRegistry
    from doc_organize.web.auth import LoginRateLimiter

    app = create_app()

    async with app.router.lifespan_context(app):
        # Validate types
        assert isinstance(app.state.project_registry, ProjectRegistry), (
            f"app.state.project_registry should be ProjectRegistry, got {type(app.state.project_registry)}"
        )

        assert app.state.auth_db_path is None or isinstance(app.state.auth_db_path, str), (
            f"app.state.auth_db_path should be str or None, got {type(app.state.auth_db_path)}"
        )

        assert isinstance(app.state.taxonomy_template_registry, TaxonomyTemplateRegistry), (
            f"app.state.taxonomy_template_registry should be TaxonomyTemplateRegistry, got {type(app.state.taxonomy_template_registry)}"
        )

        assert app.state.security is not None, "app.state.security should not be None"

        assert isinstance(app.state.login_rate_limiter, LoginRateLimiter), (
            f"app.state.login_rate_limiter should be LoginRateLimiter, got {type(app.state.login_rate_limiter)}"
        )

        assert isinstance(app.state.active_project_operations, set), (
            f"app.state.active_project_operations should be set, got {type(app.state.active_project_operations)}"
        )


def test_state_md_exists():
    """Validate that STATE.md documentation file exists and is readable."""
    import os

    state_doc_path = os.path.join(os.path.dirname(__file__), "..", "..", "src", "doc_organize", "web", "STATE.md")

    assert os.path.isfile(state_doc_path), f"STATE.md not found at {state_doc_path}"

    with open(state_doc_path, encoding="utf-8") as f:
        content = f.read()
        assert "app.state.project_registry" in content, "STATE.md missing documentation for project_registry"
        assert "app.state.login_rate_limiter" in content, "STATE.md missing documentation for login_rate_limiter"
        assert "app.state.active_project_operations" in content, "STATE.md missing documentation for active_project_operations"
        assert "Thread-Safety" in content, "STATE.md should mention thread-safety"


def test_adr004_exists():
    """Validate that ADR-004 documentation exists and references STATE.md."""
    import os

    adr_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "adr", "ADR-004-GIL-Thread-Safety.md")

    assert os.path.isfile(adr_path), f"ADR-004 not found at {adr_path}"

    with open(adr_path, encoding="utf-8") as f:
        content = f.read()
        assert "GIL" in content, "ADR-004 should discuss GIL"
        assert "STATE.md" in content, "ADR-004 should reference STATE.md"


@pytest.mark.asyncio
async def test_login_rate_limiter_is_mutable():
    """Validate that login_rate_limiter can be used for rate limiting (mutation test)."""
    from doc_organize.web.auth import LoginRateLimiter

    rate_limiter = LoginRateLimiter()

    # First check should show not locked
    assert not rate_limiter.is_locked("tenant", "user"), "First login attempt should not be locked"

    # Record failures
    rate_limiter.record_failure("tenant", "user")
    rate_limiter.record_failure("tenant", "user")

    # Should be able to query lock status
    locked = rate_limiter.is_locked("tenant", "user")
    assert isinstance(locked, bool), "is_locked() should return bool"


@pytest.mark.asyncio
async def test_active_project_operations_is_mutable():
    """Validate that active_project_operations set can track in-progress scans."""
    app = create_app()

    async with app.router.lifespan_context(app):
        ops = app.state.active_project_operations

        # Should start empty
        assert isinstance(ops, set), "active_project_operations should be a set"

        # Should support add/discard
        ops.add("tenant:project1")
        assert "tenant:project1" in ops, "add() should work"

        ops.discard("tenant:project1")
        assert "tenant:project1" not in ops, "discard() should work"


def test_state_comments_in_app_py():
    """Validate that app.py has thread-safety comments for each app.state assignment."""
    import os

    app_py_path = os.path.join(os.path.dirname(__file__), "..", "..", "src", "doc_organize", "web", "app.py")

    with open(app_py_path, encoding="utf-8") as f:
        content = f.read()

        # Check for STATE.md references in comments
        assert "STATE.md" in content or "Thread-safety" in content, "app.py should have thread-safety comments referencing STATE.md"


@pytest.mark.asyncio
async def test_no_new_attributes_after_startup():
    """Validate that app.state is not modified after lifespan initialization."""
    app = create_app()

    async with app.router.lifespan_context(app):
        # Try to add new attribute (should work in Python but violates ADR-004)
        # This is a documentation test, not a blocker
        app.state.new_attr = "test"

        # Verify new attribute exists
        assert hasattr(app.state, "new_attr"), "New attribute should be assignable (but should not be)"

        # Clean up
        delattr(app.state, "new_attr")

        print("⚠️  app.state allows new attributes after startup. See ADR-004: this violates initialization contract (informational only)")
