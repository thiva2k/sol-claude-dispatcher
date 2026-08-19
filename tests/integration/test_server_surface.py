"""The MCP surface itself: registration, startup refusal, locking, restart.

Most lifecycle tests call the tool bodies directly for determinism. This module
covers the parts that only exist at the server boundary: the registered tool
list, the §6 instructions, the §22 layer-4 startup refusal, and one real stdio
``initialize`` / ``tools/list`` handshake against a live server process.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from sol_claude_dispatcher import __version__
from sol_claude_dispatcher.errors import RecursionDetected
from sol_claude_dispatcher.locks import RepositoryLock
from sol_claude_dispatcher.models import TaskState
from sol_claude_dispatcher.server import (
    SERVER_INSTRUCTIONS,
    TOOL_NAMES,
    Dispatcher,
    build_dispatcher,
    build_server,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


async def test_server_registers_exactly_four_tools_with_the_section_6_instructions(
    integration_config_file,
):
    server = build_server(integration_config_file)

    assert server.name == "sol-claude-dispatcher"
    assert server.version == __version__
    assert set(TOOL_NAMES) == {
        "dispatch_claude_task",
        "resume_claude_task",
        "review_task_with_fable",
        "get_task",
    }

    tools = await server.list_tools()
    assert sorted(t.name for t in tools) == sorted(TOOL_NAMES)
    for tool in tools:
        assert tool.description
        assert tool.input_schema["type"] == "object"

    by_name = {t.name: t for t in tools}
    assert by_name["dispatch_claude_task"].input_schema["required"] == ["request"]
    assert set(by_name["resume_claude_task"].input_schema["required"]) == {
        "task_id",
        "instruction",
    }
    assert by_name["get_task"].input_schema["required"] == ["task_id"]
    # A caller cannot hand Fable a session or a worktree.
    assert set(by_name["review_task_with_fable"].input_schema["properties"]) == {
        "task_id",
        "focus",
    }

    # §6: the hierarchy statement leads the instructions, verbatim.
    assert server.instructions == SERVER_INSTRUCTIONS
    assert server.instructions.startswith(
        "Sol is the sole orchestrator and final reviewer.\n"
        "Use dispatch_claude_task for new implementation work.\n"
        "Use resume_claude_task only to continue an existing implementation.\n"
        "Use review_task_with_fable only for independent review.\n"
        "Worker completion is evidence, never approval.\n"
        "Workers must never delegate recursively.\n"
    )


async def test_tool_bodies_reach_the_dispatcher_through_the_server(
    integration_config_file, request_payload, fake_env
):
    """The MCP adapters are thin: calling through the server does real work."""
    server = build_server(integration_config_file)

    payload = await server.call_tool("get_task", {"task_id": "no-such-task"})

    # An unknown task is reported as a concise structured refusal, not a raise.
    rendered = json.dumps(payload, default=str)
    assert "TaskNotFound" in rendered
    assert "Traceback" not in rendered


# ---------------------------------------------------------------------------
# §22 layer 4 — startup refusal
# ---------------------------------------------------------------------------


def test_server_refuses_to_initialise_inside_a_worker(
    integration_config_file, monkeypatch
):
    monkeypatch.setenv("SOL_WORKER", "1")
    monkeypatch.delenv("SOL_DISPATCHER_TEST_OVERRIDE", raising=False)

    with pytest.raises(RecursionDetected):
        build_server(integration_config_file)
    with pytest.raises(RecursionDetected):
        build_dispatcher(integration_config_file)


async def test_dispatch_refuses_inside_a_worker_even_on_a_built_dispatcher(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """The check is re-run per tool call, not only at startup (§22 layer 4)."""
    monkeypatch.setenv("SOL_WORKER", "1")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "RecursionDetected"
    assert dispatcher.store.list_tasks() == []


async def test_dispatch_refuses_beyond_the_configured_depth(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§22 layer 5: depth greater than the configured maximum is refused."""
    monkeypatch.setenv("SOL_DISPATCH_DEPTH", "2")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "RecursionDetected"
    assert result["details"] == {"depth": 2, "max": 1}


# ---------------------------------------------------------------------------
# §25 — one mutating worker per repository
# ---------------------------------------------------------------------------


async def test_second_concurrent_dispatch_to_the_same_repository_is_busy(
    dispatcher, request_payload, fake_env, monkeypatch, integration_config
):
    """Two dispatches, one repository: the second is refused, not queued."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    request_payload["execution"]["timeout_seconds"] = 2

    other = Dispatcher(integration_config)
    first, second = await asyncio.gather(
        dispatcher.dispatch_claude_task(dict(request_payload)),
        other.dispatch_claude_task(dict(request_payload)),
    )

    busy = [r for r in (first, second) if r.get("error") == "RepositoryBusy"]
    assert len(busy) == 1, (first, second)
    assert busy[0]["retryable"] is True
    assert "lock_path" in busy[0]["details"]
    # The refused dispatch never created a task directory.
    assert len(dispatcher.store.list_tasks()) == 1


async def test_dispatch_is_refused_while_the_repository_lock_is_held(
    dispatcher, request_payload, fake_env, seeded_repo
):
    with RepositoryLock(seeded_repo, dispatcher.config.locks_path):
        result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "RepositoryBusy"
    assert result["details"]["repository"] == str(seeded_repo)


async def test_the_lock_is_released_after_a_failed_dispatch(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """The lock lives in a ``finally``; a failed run must not wedge the repo."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "malformed-json")
    failed = await dispatcher.dispatch_claude_task(request_payload)
    assert failed["status"] == TaskState.FAILED.value

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    again = await dispatcher.dispatch_claude_task(request_payload)
    assert "error" not in again


# ---------------------------------------------------------------------------
# §27 — restart recovery
# ---------------------------------------------------------------------------


async def test_a_restarted_server_sees_every_prior_task(
    dispatcher, request_payload, fake_env, integration_config, integration_config_file
):
    first = await dispatcher.dispatch_claude_task(request_payload)
    second = await dispatcher.dispatch_claude_task(request_payload)

    reborn = build_dispatcher(integration_config_file)

    assert sorted(reborn.store.list_tasks()) == sorted(
        [first["task_id"], second["task_id"]]
    )
    view = await reborn.get_task(first["task_id"])
    assert view["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert view["session_id"] == first["session_id"]
    assert view["worktree"] == first["worktree"]
    assert len(view["runs"]) == 1


# ---------------------------------------------------------------------------
# stdio smoke test — a real server process, a real handshake
# ---------------------------------------------------------------------------


async def test_stdio_handshake_lists_the_four_tools(integration_config_file):
    """Start the server over stdio, initialize, list tools, exit."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["SOL_DISPATCHER_CONFIG"] = str(integration_config_file)
    env.pop("SOL_WORKER", None)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from sol_claude_dispatcher.server import main; main()"],
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), timeout=30)
            assert init.server_info.name == "sol-claude-dispatcher"
            assert init.instructions == SERVER_INSTRUCTIONS

            listed = await asyncio.wait_for(session.list_tools(), timeout=30)
            assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
