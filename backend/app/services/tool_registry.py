"""
Tool Registry
════════════════════════════════════════════════════════════════════════════════
Defines the catalogue of tools available to agents and provides:
  • Provider-agnostic ToolDefinition specs (consumed by llm_provider formatters)
  • Mock async implementations for each tool (real integrations in production)
  • execute_tool() dispatcher
  • get_tool_definitions() filtered-lookup helper

Mock strategy
─────────────
All implementations return realistic-looking data so the LLM can reason about
the results without requiring external services.  They are marked as MOCK in
their docstrings; swap for real implementations without changing any callers.

Tool result format
──────────────────
Each implementation returns a plain dict.  Callers (agent_executor) JSON-encode
these and pass them back to the LLM in the follow-up conversation turn.
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.llm_provider import ToolCall, ToolDefinition

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Mock tool implementations
# ══════════════════════════════════════════════════════════════════════════════


async def _web_search(query: str, num_results: int = 3) -> Dict[str, Any]:
    """MOCK: Simulate a web search and return top results."""
    await asyncio.sleep(0.02)  # Simulate network latency
    results = [
        {
            "title": f"{query.title()} — Overview and Key Facts",
            "url": f"https://example.com/search?q={query.replace(' ', '+')}",
            "snippet": (
                f"Comprehensive information about {query}. "
                "This article covers background, recent developments, and expert analysis."
            ),
            "published_date": "2026-05-28",
        },
        {
            "title": f"Latest News: {query}",
            "url": f"https://news.example.com/{query.replace(' ', '-').lower()}",
            "snippet": (
                f"Breaking: New findings on {query} have emerged. "
                "Researchers report significant progress in this area."
            ),
            "published_date": "2026-05-30",
        },
        {
            "title": f"{query} — In-depth Analysis",
            "url": f"https://analysis.example.com/{query.replace(' ', '-').lower()}",
            "snippet": (
                f"Expert analysis of {query}. Detailed breakdown of causes, "
                "effects and actionable recommendations."
            ),
            "published_date": "2026-05-25",
        },
    ]
    return {
        "query": query,
        "total_results": len(results),
        "results": results[:num_results],
        "search_time_ms": random.randint(80, 350),
    }


async def _file_read(path: str) -> Dict[str, Any]:
    """MOCK: Simulate reading a file from the filesystem."""
    await asyncio.sleep(0.005)
    # Generate plausible mock content based on file extension
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "txt"
    mock_contents: Dict[str, str] = {
        "txt":  f"This is the content of {path}.\nLine 2 of the file.\nLine 3: some data.",
        "json": f'{{"file": "{path}", "data": [1, 2, 3], "status": "ok"}}',
        "csv":  "id,name,value\n1,alpha,100\n2,beta,200\n3,gamma,300",
        "md":   f"# {path}\n\nThis document contains important information.\n\n## Section 1\n\nContent here.",
        "py":   f'# {path}\n\ndef main():\n    print("Hello from {path}")\n\nif __name__ == "__main__":\n    main()',
    }
    content = mock_contents.get(ext, f"[Binary or unknown file: {path}]")
    return {
        "path": path,
        "content": content,
        "size_bytes": len(content),
        "encoding": "utf-8",
        "exists": True,
    }


async def _file_write(path: str, content: str) -> Dict[str, Any]:
    """MOCK: Simulate writing content to a file."""
    await asyncio.sleep(0.005)
    return {
        "path": path,
        "bytes_written": len(content.encode("utf-8")),
        "success": True,
        "message": f"Successfully wrote {len(content)} characters to {path}",
    }


async def _email_send(to: str, subject: str, body: str) -> Dict[str, Any]:
    """MOCK: Simulate sending an email via SMTP."""
    await asyncio.sleep(0.01)
    msg_id = "".join(random.choices(string.hexdigits, k=16)).lower()
    return {
        "sent": True,
        "message_id": f"<{msg_id}@mail.example.com>",
        "to": to,
        "subject": subject,
        "body_preview": body[:100] + ("..." if len(body) > 100 else ""),
        "timestamp": "2026-05-30T12:00:00Z",
    }


async def _database_query(sql: str, limit: int = 10) -> Dict[str, Any]:
    """MOCK: Simulate executing a SQL query against a database."""
    await asyncio.sleep(0.008)
    sql_upper = sql.strip().upper()

    # Minimal SQL introspection to produce useful mock output
    if sql_upper.startswith("SELECT"):
        rows = [{"id": i + 1, "value": f"row_{i + 1}", "score": round(0.5 + i * 0.1, 2)} for i in range(3)]
        return {
            "rows": rows[:limit],
            "row_count": len(rows),
            "columns": ["id", "value", "score"],
            "query": sql,
            "execution_ms": random.randint(2, 25),
        }
    elif sql_upper.startswith(("INSERT", "UPDATE", "DELETE")):
        return {
            "affected_rows": random.randint(1, 5),
            "query": sql,
            "execution_ms": random.randint(3, 15),
            "success": True,
        }
    else:
        return {
            "rows": [],
            "row_count": 0,
            "query": sql,
            "execution_ms": 1,
            "message": "Query executed",
        }


# ══════════════════════════════════════════════════════════════════════════════
# Tool definitions  (provider-agnostic JSON Schema specs)
# ══════════════════════════════════════════════════════════════════════════════

TOOL_DEFINITIONS: List[ToolDefinition] = [
    ToolDefinition(
        name="web_search",
        description="Search the web for current information, news, or general knowledge on any topic.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 3, max 10)",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="file_read",
        description="Read and return the contents of a file at the given path.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative file path to read",
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="file_write",
        description="Write content to a file, creating it if it does not exist.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write to",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    ),
    ToolDefinition(
        name="email_send",
        description="Send an email to a recipient with a subject and body.",
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or HTML)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    ),
    ToolDefinition(
        name="database_query",
        description="Execute a SQL query against the application database and return results.",
        parameters={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL query to execute (SELECT, INSERT, UPDATE, DELETE)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return for SELECT queries (default 10)",
                    "default": 10,
                },
            },
            "required": ["sql"],
        },
    ),
]

# ── Registry: name → (definition, async_executor) ────────────────────────────

_ToolEntry = Tuple[ToolDefinition, Callable[..., Any]]

_REGISTRY: Dict[str, _ToolEntry] = {
    "web_search":      (TOOL_DEFINITIONS[0], _web_search),
    "file_read":       (TOOL_DEFINITIONS[1], _file_read),
    "file_write":      (TOOL_DEFINITIONS[2], _file_write),
    "email_send":      (TOOL_DEFINITIONS[3], _email_send),
    "database_query":  (TOOL_DEFINITIONS[4], _database_query),
}


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def get_tool_definitions(names: Optional[List[str]] = None) -> List[ToolDefinition]:
    """
    Return ToolDefinition objects for the requested tool *names*.
    If *names* is None or empty, return all registered tools.
    Unknown names are silently skipped.
    """
    if not names:
        return list(TOOL_DEFINITIONS)
    result = []
    for name in names:
        entry = _REGISTRY.get(name)
        if entry:
            result.append(entry[0])
        else:
            logger.debug("get_tool_definitions: unknown tool '%s' — skipped", name)
    return result


def list_tool_names() -> List[str]:
    """Return the names of all registered tools."""
    return list(_REGISTRY.keys())


async def execute_tool(call: ToolCall) -> Dict[str, Any]:
    """
    Dispatch a single ToolCall to its mock implementation.

    Returns a dict that can be JSON-serialised and passed back to the LLM.
    Never raises — errors are returned as {"error": "...", "tool": "..."}.
    """
    entry = _REGISTRY.get(call.name)
    if not entry:
        logger.warning("execute_tool: unknown tool '%s'", call.name)
        return {
            "error": f"Unknown tool: '{call.name}'. Available: {list_tool_names()}",
            "tool": call.name,
        }

    _, fn = entry
    try:
        result = await fn(**call.arguments)
        logger.debug("execute_tool: '%s' succeeded", call.name)
        return result
    except TypeError as exc:
        # Argument mismatch (e.g., unexpected keyword)
        logger.warning("execute_tool: '%s' bad arguments: %s", call.name, exc)
        return {"error": f"Invalid arguments for tool '{call.name}': {exc}", "tool": call.name}
    except Exception as exc:
        logger.warning("execute_tool: '%s' raised: %s", call.name, exc)
        return {"error": str(exc), "tool": call.name}


async def execute_tools_parallel(calls: List[ToolCall]) -> List[Dict[str, Any]]:
    """
    Execute multiple tool calls concurrently and return results in order.
    Each result dict carries 'tool_call_id' for correlation with the model.
    """
    raw = await asyncio.gather(*(execute_tool(c) for c in calls), return_exceptions=True)
    results = []
    for call, res in zip(calls, raw):
        if isinstance(res, Exception):
            results.append({"tool_call_id": call.id, "tool": call.name, "error": str(res)})
        else:
            results.append({"tool_call_id": call.id, "tool": call.name, "result": res})
    return results
