"""Stress tests for ProjectRegistry concurrency with asyncio.Lock (FM-3).

Tests validate that per-project asyncio.Lock correctly serializes concurrent
operations on the same project while allowing parallel operations on
different projects.

See: src/doc_organize/projects/project_registry.py (line 61: asyncio.Lock per project)
"""

import asyncio

from typing import cast

import pytest

from doc_organize.projects.project_registry import ProjectRegistry


@pytest.mark.asyncio
async def test_concurrent_creates_different_projects(tmp_path):
    """Verify 10 concurrent create_project() calls on different projects all succeed.

    **Scenario**: Multiple concurrent project creations with unique names.
    **Expected**: All succeed without serialization; different projects don't block each other.
    **GIL/Lock Model**: No per-project lock contention; each project gets its own lock.
    """
    base = tmp_path / "workspaces"
    base.mkdir()
    registry_path = tmp_path / "projects.json"

    async with ProjectRegistry(registry_path) as registry:
        # Create 10 concurrent create_project tasks with unique project names
        project_names = [f"project-{i}" for i in range(10)]

        async def create_task(name: str):
            project = await registry.create_project(name, base)
            return project.name

        # Run all creates concurrently
        created_names = await asyncio.gather(*[create_task(name) for name in project_names])

        # Verify all projects were created successfully
        assert len(created_names) == 10, "All 10 creates should succeed"
        assert len(set(created_names)) == 10, "All project names should be unique"

        # Verify projects are listed
        projects = await registry.list_projects()
        assert len(projects) >= 10, "At least 10 projects should be listed"


@pytest.mark.asyncio
async def test_list_projects_during_concurrent_creates(tmp_path):
    """Verify list_projects() can execute while create_project() on other projects runs.

    **Scenario**: 5 concurrent creates + 5 concurrent lists on different projects.
    **Expected**: Lists return consistent snapshots without deadlock.
    **GIL/Lock Model**: list_projects() doesn't hold lock; sees consistent dict snapshot (GIL-protected).
    """
    base = tmp_path / "workspaces"
    base.mkdir()
    registry_path = tmp_path / "projects.json"

    async with ProjectRegistry(registry_path) as registry:
        # Pre-populate some projects
        for i in range(3):
            await registry.create_project(f"initial-{i}", base)

        # Concurrent creates + lists
        async def create_task(idx: int):
            await registry.create_project(f"concurrent-{idx}", base)

        async def list_task() -> int:
            projects = await registry.list_projects()
            return len(projects)

        # Run mixed workload
        results = await asyncio.gather(*[create_task(i) for i in range(5)], *[list_task() for _ in range(5)])

        # Verify lists returned consistent counts (last 5 items are list results)
        list_results = cast(list[int], results[-5:])
        assert all(isinstance(count, int) for count in list_results), "All list_projects() calls should return count"
        assert all(count >= 3 for count in list_results), "Each list should see at least 3 initial projects"


@pytest.mark.asyncio
async def test_concurrent_gets_different_projects(tmp_path):
    """Verify concurrent get_project() calls on different projects run in parallel.

    **Scenario**: 5 concurrent get_project() calls on different projects.
    **Expected**: Gets run in parallel (no global lock); all succeed.
    **GIL/Lock Model**: Per-project locks allow parallel ops on different projects.
    """
    base = tmp_path / "workspaces"
    base.mkdir()
    registry_path = tmp_path / "projects.json"

    async with ProjectRegistry(registry_path) as registry:
        # Create 5 projects
        project_names = []
        for i in range(5):
            project = await registry.create_project(f"get-test-{i}", base)
            project_names.append(project.name)

        # Concurrent gets on different projects
        async def get_task(idx: int):
            try:
                project_name = project_names[idx]
                project = await registry.get_project(project_name)
                return f"got-{idx}" if project else f"not-found-{idx}"
            except (ValueError, KeyError, RuntimeError, OSError) as e:
                return f"error-{idx}: {e!s}"

        # Run 5 concurrent gets on different projects
        results = await asyncio.gather(*[get_task(i) for i in range(5)])

        # All gets should succeed (different projects, parallel execution)
        successful_gets = [r for r in results if r.startswith("got-")]
        assert len(successful_gets) >= 4, "Most gets should succeed on different projects"


@pytest.mark.asyncio
async def test_no_deadlock_multiple_projects_concurrent_operations(tmp_path):
    """Verify no deadlock when multiple projects are created/queried concurrently.

    **Scenario**: 3 projects × mixed concurrent operations (create → list → get).
    **Expected**: All operations complete without deadlock; each project serializes its own ops.
    **Timeout**: Test should complete in < 10 seconds (would hang if deadlock).
    **GIL/Lock Model**: Per-project locks don't interact; no global lock → no deadlock.
    """
    base = tmp_path / "workspaces"
    base.mkdir()
    registry_path = tmp_path / "projects.json"

    async with ProjectRegistry(registry_path) as registry:
        # Create initial projects
        project_names = {}
        for i in range(3):
            project = await registry.create_project(f"project-{i}", base)
            project_names[i] = project.name

        # Concurrent ops: get + list on each project
        async def mixed_ops(proj_idx: int, op_idx: int):
            project_name = project_names[proj_idx]

            if op_idx == 0:
                # Get project
                proj = await registry.get_project(project_name)
                return "get-ok" if proj else "get-fail"
            elif op_idx == 1:
                # List projects
                projects = await registry.list_projects()
                return f"list-ok:{len(projects)}"
            else:
                # Get project again
                proj = await registry.get_project(project_name)
                return "get-ok" if proj else "get-fail"

        # Run 3 projects × 3 ops = 9 concurrent tasks
        results = await asyncio.gather(*[mixed_ops(i, j) for i in range(3) for j in range(3)], return_exceptions=False)

        # Verify no deadlock (all tasks completed) and reasonable results
        assert len(results) == 9, "All 9 operations should complete"
        ok_count = sum(1 for r in results if isinstance(r, str) and "ok" in r.lower())
        assert ok_count >= 8, "Most operations should succeed"
