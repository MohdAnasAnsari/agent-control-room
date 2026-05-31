"""
Agent Executor
════════════════════════════════════════════════════════════════════════════════
Implements the full agent execution lifecycle and wires together:
  registry   → load/update AgentState
  llm_factory → call the appropriate LLM
  tool_registry → execute tool calls

Execution steps
───────────────
1.  Load agent config + memory from AgentRegistry
2.  Build message array: strip timestamps from history, prune to context budget
3.  Call LLM (primary model, with triple fallback: Claude → GPT → Groq)
4.  Execute any tool calls in parallel (mock implementations)
5.  If tools were called: send results back for a final LLM answer
6.  Update agent memory (user message + assistant response)
7.  Persist state changes (via registry batch sync)
8.  Return structured output dict

Context window management
──────────────────────────
For each agent call, token counts are estimated for system + history + next
message.  If the running total exceeds 80% of the model's context limit, the
oldest history messages are evicted one pair at a time until we are safely
under threshold.  A warning is logged when pruning occurs.

Tool result formatting
──────────────────────
Claude expects tool results as 'user'-role messages with tool_result content
blocks.  OpenAI/Groq use a 'tool'-role message.  The executor detects which
format to use based on the active model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.config import settings
from app.services.agent_registry import registry as _registry
from app.services.agent_state_manager import AgentState, AgentStatus
from app.services.llm_provider import LLMResponse, ToolCall, llm_factory
from app.services.tool_registry import (
    execute_tools_parallel,
    get_tool_definitions,
)

logger = logging.getLogger(__name__)

# ── Context window limits per model (tokens) ─────────────────────────────────
_CONTEXT_LIMITS: Dict[str, int] = {
    "claude-opus-4-8":           200_000,
    "claude-sonnet-4-6":         200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "gpt-4o":                    128_000,
    "gpt-4o-mini":               128_000,
    "llama-3.3-70b-versatile":    32_768,
    "mixtral-8x7b-32768":         32_768,
    "llama2-70b-4096":             4_096,
}

_CONTEXT_WARN_AT = 0.80   # prune history when we exceed this fraction
_CALL_TIMEOUT_S  = 30.0   # hard timeout per LLM call (enforced in llm_provider)


# ══════════════════════════════════════════════════════════════════════════════
# AgentExecutor
# ══════════════════════════════════════════════════════════════════════════════


class AgentExecutor:
    """
    Stateless class — a single instance serves all concurrent executions.
    All state is held in AgentState / registry, not here.
    """

    # ── Public entrypoint ─────────────────────────────────────────────────────

    async def execute(
        self,
        agent_id: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        *,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run a single agent invocation end-to-end.

        Parameters
        ──────────
        agent_id   UUID string of the agent to run.
        input_data Dict passed by the orchestrator node; contains at minimum
                   'input' (the upstream output) and 'workflow_input'.
        context    Orchestrator context: execution_id, workflow_id, node_id, …
        user_id    Optional authenticated user UUID for cost attribution.

        Returns
        ───────
        Structured dict::
            {
                "agent_id": str,
                "agent_name": str,
                "output": str,           # final LLM text
                "tool_calls": [...],     # raw tool calls (may be empty)
                "tool_results": [...],   # tool outputs (may be empty)
                "tokens": {"input": int, "output": int, "total": int},
                "model": str,
                "cost_usd": float,
                "duration_ms": int,
            }
        """
        agent = await _registry.get_or_load(agent_id)
        if not agent:
            raise ValueError(f"Agent '{agent_id}' not found in registry or database")

        start = time.monotonic()

        # Transition to RUNNING
        async with agent._lock:
            agent.set_status(AgentStatus.RUNNING)
            agent.set_task(context.get("current_node_id", "executing"))
            agent.increment_execution()

        try:
            result = await self._run(agent, input_data, context, user_id=user_id)
        except Exception as exc:
            # Mark agent as errored and immediately persist
            async with agent._lock:
                agent.set_status(AgentStatus.ERROR)
                agent.set_task(None)
                agent.update_metadata("last_error", str(exc))
            await _registry.mark_critical(agent_id)
            raise

        # Transition to IDLE
        async with agent._lock:
            agent.set_status(AgentStatus.IDLE)
            agent.set_task(None)

        await _registry.mark_dirty(agent_id)
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result

    async def stream(
        self,
        agent_id: str,
        user_message: str,
        *,
        user_id: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream LLM token chunks for a single agent invocation.
        Does NOT execute tools — streaming calls are text-only.

        Usage::
            async for chunk in executor.stream(agent_id, "Hello"):
                print(chunk, end="", flush=True)
        """
        agent = await _registry.get_or_load(agent_id)
        if not agent:
            raise ValueError(f"Agent '{agent_id}' not found")

        model = model_override or agent.model
        history = self._prepare_history(agent, model, user_message)

        messages = history + [{"role": "user", "content": user_message}]

        async for chunk in llm_factory.stream(
            agent.system_prompt, messages, model=model
        ):
            yield chunk

    # ── Internal execution logic ──────────────────────────────────────────────

    async def _run(
        self,
        agent: AgentState,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        *,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        model = agent.model or settings.DEFAULT_MODEL

        # 1. Extract the human-readable user message
        user_message = self._extract_user_message(input_data)

        # 2. Prepare pruned history and log user turn in memory
        history = self._prepare_history(agent, model, user_message)

        async with agent._lock:
            agent.update_memory(user_message, "user")

        messages = history + [{"role": "user", "content": user_message}]

        # 3. Resolve tool specs from agent's tool name list
        tool_defs = (
            get_tool_definitions(agent.tools) if agent.tools else []
        )

        # 4. First LLM call (may yield tool_calls)
        first_resp: LLMResponse = await llm_factory.call(
            agent.system_prompt,
            messages,
            model=model,
            tools=tool_defs or None,
            user_id=user_id,
        )

        tool_results: List[Dict[str, Any]] = []
        final_resp = first_resp

        # 5. Execute tool calls if any
        if first_resp.tool_calls:
            logger.info(
                "Agent %s: executing %d tool call(s): %s",
                agent.agent_id,
                len(first_resp.tool_calls),
                [tc.name for tc in first_resp.tool_calls],
            )
            tool_results = await execute_tools_parallel(first_resp.tool_calls)

            # 6. Follow-up call with tool results for the final answer
            follow_up_msgs = (
                messages
                + [{"role": "assistant", "content": first_resp.content or ""}]
                + self._format_tool_results(first_resp.tool_calls, tool_results, model)
            )

            final_resp = await llm_factory.call(
                agent.system_prompt,
                follow_up_msgs,
                model=model,
                user_id=user_id,
            )

        # 7. Persist assistant reply to memory
        async with agent._lock:
            agent.update_memory(final_resp.content, "assistant")

        return {
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "output": final_resp.content,
            "tool_calls": [tc.to_dict() for tc in first_resp.tool_calls],
            "tool_results": tool_results,
            "tokens": {
                "input": first_resp.input_tokens + final_resp.input_tokens,
                "output": first_resp.output_tokens + final_resp.output_tokens,
                "total": first_resp.total_tokens + final_resp.total_tokens,
            },
            "model": model,
            "cost_usd": first_resp.cost_usd + final_resp.cost_usd,
        }

    # ── Message preparation helpers ───────────────────────────────────────────

    def _extract_user_message(self, input_data: Dict[str, Any]) -> str:
        """
        Convert orchestrator node input to a plain text user message.
        Priority: input → workflow_input.query/message → str(input_data)
        """
        if "input" in input_data:
            v = input_data["input"]
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return v.get("query") or v.get("message") or v.get("text") or json.dumps(v)
            return str(v)

        wi = input_data.get("workflow_input", {})
        if isinstance(wi, dict):
            return (
                wi.get("query")
                or wi.get("message")
                or wi.get("text")
                or json.dumps(wi)
            )
        return str(wi) if wi else str(input_data)

    def _prepare_history(
        self,
        agent: AgentState,
        model: str,
        next_message: str,
    ) -> List[Dict[str, Any]]:
        """
        Return agent's conversation history ready for the messages array,
        evicting the oldest pairs when approaching the context limit.
        """
        provider = llm_factory.get_provider(model)
        limit = _CONTEXT_LIMITS.get(model, 32_768)
        budget = int(limit * _CONTEXT_WARN_AT)

        # Strip internal timestamp field from stored messages
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in agent.memory
            if m.get("role") in ("user", "assistant")
        ]

        # Count fixed overhead: system prompt + next message
        used = provider.count_tokens(agent.system_prompt) + provider.count_tokens(next_message)

        # Walk history in reverse, keeping as many recent messages as fit
        kept: List[Dict[str, Any]] = []
        evicted = 0
        for msg in reversed(history):
            t = provider.count_tokens(msg["content"])
            if used + t > budget:
                evicted += 1
                continue
            used += t
            kept.insert(0, msg)

        if evicted:
            logger.warning(
                "Agent %s (%s): context at %.0f%% of %d-token limit — "
                "evicted %d oldest message(s)",
                agent.agent_id, model,
                (used / limit) * 100, limit, evicted,
            )

        return kept

    def _format_tool_results(
        self,
        calls: List[ToolCall],
        results: List[Dict[str, Any]],
        model: str,
    ) -> List[Dict[str, Any]]:
        """
        Format tool results as follow-up messages appropriate for the provider.

        Claude:    user-role message with tool_result content blocks
        GPT/Groq:  one tool-role message per result
        """
        is_claude = model.startswith("claude")

        if is_claude:
            blocks = []
            for call, res in zip(calls, results):
                raw = res.get("result", res)
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(raw),
                    }
                )
            return [{"role": "user", "content": blocks}]
        else:
            msgs = []
            for call, res in zip(calls, results):
                raw = res.get("result", res)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(raw),
                        "name": call.name,
                    }
                )
            return msgs


# ── Module-level singleton (import and use this everywhere) ──────────────────
agent_executor = AgentExecutor()
