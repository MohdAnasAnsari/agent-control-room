"""
Unit tests for tool_registry.py
Covers: mock implementations, execute_tool dispatcher, get_tool_definitions,
        execute_tools_parallel, and error handling.
"""

import pytest

from app.services.llm_provider import ToolCall
from app.services.tool_registry import (
    TOOL_DEFINITIONS,
    execute_tool,
    execute_tools_parallel,
    get_tool_definitions,
    list_tool_names,
    _web_search,
    _file_read,
    _file_write,
    _email_send,
    _database_query,
)


# ─── web_search ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_web_search_returns_results():
    result = await _web_search("artificial intelligence")
    assert "results" in result
    assert len(result["results"]) > 0
    assert result["query"] == "artificial intelligence"
    assert isinstance(result["total_results"], int)


@pytest.mark.asyncio
async def test_web_search_num_results_respected():
    result = await _web_search("python", num_results=2)
    assert len(result["results"]) <= 2


@pytest.mark.asyncio
async def test_web_search_result_shape():
    result = await _web_search("test query")
    for r in result["results"]:
        assert "title" in r
        assert "url" in r
        assert "snippet" in r


# ─── file_read ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_read_returns_content():
    result = await _file_read("/data/report.json")
    assert result["path"] == "/data/report.json"
    assert "content" in result
    assert result["exists"] is True
    assert isinstance(result["size_bytes"], int)


@pytest.mark.asyncio
async def test_file_read_json_extension():
    result = await _file_read("config.json")
    assert result["content"].startswith("{")


@pytest.mark.asyncio
async def test_file_read_py_extension():
    result = await _file_read("app.py")
    assert "def" in result["content"] or "#" in result["content"]


# ─── file_write ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_write_reports_bytes():
    content = "Hello, World!"
    result = await _file_write("/output/test.txt", content)
    assert result["success"] is True
    assert result["bytes_written"] == len(content.encode())
    assert result["path"] == "/output/test.txt"


@pytest.mark.asyncio
async def test_file_write_empty_content():
    result = await _file_write("/tmp/empty.txt", "")
    assert result["bytes_written"] == 0
    assert result["success"] is True


# ─── email_send ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_send_returns_sent_true():
    result = await _email_send(
        to="user@example.com",
        subject="Test Email",
        body="This is a test.",
    )
    assert result["sent"] is True
    assert result["to"] == "user@example.com"
    assert result["subject"] == "Test Email"
    assert "message_id" in result


@pytest.mark.asyncio
async def test_email_body_preview_truncation():
    long_body = "x" * 200
    result = await _email_send("a@b.com", "Subject", long_body)
    assert len(result["body_preview"]) <= 103  # 100 chars + "..."


# ─── database_query ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_database_query_select():
    result = await _database_query("SELECT * FROM agents LIMIT 5")
    assert "rows" in result
    assert isinstance(result["rows"], list)
    assert "row_count" in result
    assert "columns" in result


@pytest.mark.asyncio
async def test_database_query_insert():
    result = await _database_query("INSERT INTO logs (msg) VALUES ('test')")
    assert result["success"] is True
    assert "affected_rows" in result


@pytest.mark.asyncio
async def test_database_query_has_execution_ms():
    result = await _database_query("SELECT 1")
    assert result["execution_ms"] >= 0


# ─── execute_tool dispatcher ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tool_web_search():
    call = ToolCall(id="tc1", name="web_search", arguments={"query": "machine learning"})
    result = await execute_tool(call)
    assert "results" in result


@pytest.mark.asyncio
async def test_execute_tool_file_read():
    call = ToolCall(id="tc2", name="file_read", arguments={"path": "/tmp/data.csv"})
    result = await execute_tool(call)
    assert result["path"] == "/tmp/data.csv"


@pytest.mark.asyncio
async def test_execute_tool_file_write():
    call = ToolCall(id="tc3", name="file_write", arguments={"path": "/out.txt", "content": "hello"})
    result = await execute_tool(call)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_tool_email_send():
    call = ToolCall(
        id="tc4",
        name="email_send",
        arguments={"to": "a@b.com", "subject": "Hi", "body": "Body text"},
    )
    result = await execute_tool(call)
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_execute_tool_database_query():
    call = ToolCall(id="tc5", name="database_query", arguments={"sql": "SELECT 1"})
    result = await execute_tool(call)
    assert "rows" in result


@pytest.mark.asyncio
async def test_execute_tool_unknown_returns_error():
    call = ToolCall(id="tc6", name="nonexistent_tool", arguments={})
    result = await execute_tool(call)
    assert "error" in result
    assert "nonexistent_tool" in result["error"]


@pytest.mark.asyncio
async def test_execute_tool_bad_arguments_returns_error():
    # file_read requires 'path'; pass a wrong arg
    call = ToolCall(id="tc7", name="file_read", arguments={"wrong_param": "x"})
    result = await execute_tool(call)
    assert "error" in result


# ─── execute_tools_parallel ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_tools_parallel_two_calls():
    calls = [
        ToolCall(id="p1", name="web_search", arguments={"query": "test"}),
        ToolCall(id="p2", name="file_read",  arguments={"path": "data.txt"}),
    ]
    results = await execute_tools_parallel(calls)
    assert len(results) == 2
    # Each result carries its tool_call_id for correlation
    assert results[0]["tool_call_id"] == "p1"
    assert results[1]["tool_call_id"] == "p2"


@pytest.mark.asyncio
async def test_execute_tools_parallel_preserves_order():
    calls = [
        ToolCall(id=f"id{i}", name="file_read", arguments={"path": f"file{i}.txt"})
        for i in range(5)
    ]
    results = await execute_tools_parallel(calls)
    for i, res in enumerate(results):
        assert res["tool_call_id"] == f"id{i}"


@pytest.mark.asyncio
async def test_execute_tools_parallel_handles_exception():
    from unittest.mock import AsyncMock, patch

    async def boom(call):
        raise RuntimeError("tool exploded")

    with patch("app.services.tool_registry.execute_tool", side_effect=boom):
        calls = [ToolCall(id="e1", name="web_search", arguments={"query": "q"})]
        results = await execute_tools_parallel(calls)

    assert "error" in results[0]


# ─── get_tool_definitions ─────────────────────────────────────────────────────

def test_get_tool_definitions_all():
    defs = get_tool_definitions()
    assert len(defs) == len(TOOL_DEFINITIONS)


def test_get_tool_definitions_subset():
    defs = get_tool_definitions(["web_search", "file_read"])
    assert len(defs) == 2
    names = [d.name for d in defs]
    assert "web_search" in names
    assert "file_read" in names


def test_get_tool_definitions_empty_names_returns_all():
    defs = get_tool_definitions([])
    assert len(defs) == len(TOOL_DEFINITIONS)


def test_get_tool_definitions_unknown_skipped():
    defs = get_tool_definitions(["web_search", "does_not_exist"])
    assert len(defs) == 1
    assert defs[0].name == "web_search"


def test_list_tool_names():
    names = list_tool_names()
    assert "web_search" in names
    assert "file_read" in names
    assert "file_write" in names
    assert "email_send" in names
    assert "database_query" in names


def test_all_tools_have_required_fields():
    for td in TOOL_DEFINITIONS:
        assert td.name
        assert td.description
        assert isinstance(td.parameters, dict)
        assert td.parameters.get("type") == "object"
        assert "properties" in td.parameters
        assert "required" in td.parameters
