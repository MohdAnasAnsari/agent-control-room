"""
Model-agnostic LLM provider layer
════════════════════════════════════════════════════════════════════════════════
Provides a unified async interface over three LLM backends:
  • Claude  (Anthropic)  — production default
  • GPT-4o  (OpenAI)     — secondary production option
  • Groq    (Groq)       — free-tier for testing / fallback

Design principles
─────────────────
  Unified response  — LLMResponse carries content, token counts, tool calls
                      and a cost figure regardless of which backend was used.
  Pluggable tools   — Pass List[ToolDefinition]; each provider converts to its
                      own wire format internally.
  Rate limiting     — Sliding-window semaphore per provider (calls_per_minute).
  Retry / fallback  — Transient API errors get exponential back-off; if the
                      primary provider is exhausted, LLMFactory retries with
                      the configured fallback (default: Groq).
  Cost tracking     — Every call writes a row to api_usage via UsageTracker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid as _uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from uuid import UUID

from app.core.config import settings
from app.models.database import ApiUsage
from app.models.db_session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ── Optional provider SDK imports (graceful degradation if not installed) ─────
try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic = None  # type: ignore
    _ANTHROPIC_AVAILABLE = False

try:
    import openai as _openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _openai = None  # type: ignore
    _OPENAI_AVAILABLE = False

try:
    import groq as _groq
    _GROQ_AVAILABLE = True
except ImportError:
    _groq = None  # type: ignore
    _GROQ_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# Custom exceptions
# ══════════════════════════════════════════════════════════════════════════════


class LLMError(Exception):
    """Base exception for all LLM layer errors."""


class RateLimitError(LLMError):
    """Provider rate-limit reached; caller should back off and retry."""


class InvalidAPIKeyError(LLMError):
    """API key is missing, malformed, or revoked."""


class ModelUnavailableError(LLMError):
    """The requested model is temporarily or permanently unavailable."""


class LLMTimeoutError(LLMError):
    """The LLM call exceeded the configured timeout."""


# ══════════════════════════════════════════════════════════════════════════════
# Shared data classes
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolDefinition:
    """Provider-agnostic tool / function specification."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema object (type + properties)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolCall:
    """A single tool invocation returned by the model."""
    id: str
    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class LLMResponse:
    """Unified response container returned by every provider."""
    content: str
    model: str
    provider: str                              # "claude" | "openai" | "groq"
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    cost_usd: float = 0.0
    raw: Any = field(default=None, repr=False)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "finish_reason": self.finish_reason,
            "cost_usd": self.cost_usd,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Pricing registry  (USD per million tokens: input, output)
# ══════════════════════════════════════════════════════════════════════════════

_PRICING: Dict[str, Tuple[float, float]] = {
    # Claude (Anthropic)
    "claude-opus-4-8":           (15.00, 75.00),
    "claude-sonnet-4-6":         (3.00,  15.00),
    "claude-haiku-4-5-20251001": (0.80,   4.00),
    # OpenAI
    "gpt-4o":                    (5.00,  15.00),
    "gpt-4o-mini":               (0.15,   0.60),
    "gpt-4-turbo":               (10.00, 30.00),
    # Groq (free tier)
    "llama-3.3-70b-versatile":   (0.00,   0.00),
    "mixtral-8x7b-32768":        (0.00,   0.00),
    "llama2-70b-4096":           (0.00,   0.00),
}


def cost_for_model(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Return total cost in USD for the given token counts."""
    in_price, out_price = _PRICING.get(model, (0.0, 0.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


# ══════════════════════════════════════════════════════════════════════════════
# Rate limiter  — sliding window, one Semaphore per provider instance
# ══════════════════════════════════════════════════════════════════════════════


class RateLimiter:
    """
    Sliding-window rate limiter implemented as an asyncio.Semaphore.

    Each slot acquired is released after *period* seconds, enforcing at most
    *calls_per_minute* concurrent + queued requests within the rolling window.
    """

    def __init__(self, calls_per_minute: int, period: float = 60.0) -> None:
        self._calls = calls_per_minute
        self._period = period
        self._sem: Optional[asyncio.Semaphore] = None

    def _get_sem(self) -> asyncio.Semaphore:
        # Lazily created so it belongs to the running event loop
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._calls)
        return self._sem

    async def __aenter__(self) -> "RateLimiter":
        await self._get_sem().acquire()
        return self

    async def __aexit__(self, *_: Any) -> None:
        sem = self._get_sem()
        loop = asyncio.get_running_loop()
        loop.call_later(self._period, sem.release)


# ══════════════════════════════════════════════════════════════════════════════
# Abstract base class
# ══════════════════════════════════════════════════════════════════════════════


class LLMProvider(ABC):
    """
    Abstract interface that every concrete provider must implement.

    Subclasses handle all provider-specific formatting, authentication,
    and SDK calls.  The orchestrator and agents interact only with this class.
    """

    provider_name: str = "abstract"

    def __init__(
        self,
        model_name: str,
        api_key: str,
        *,
        calls_per_minute: int = 60,
        timeout_s: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._rate_limiter = RateLimiter(calls_per_minute)

    # ── Required implementations ──────────────────────────────────────────────

    @abstractmethod
    async def call(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
    ) -> LLMResponse:
        """
        Send a single (non-streaming) chat completion request.

        *messages* must follow the OpenAI format:
            [{"role": "user", "content": "..."}, ...]

        Returns a unified LLMResponse.  Raises LLMError subclasses on failure.
        """

    @abstractmethod
    async def stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        Yield response text incrementally as tokens arrive.

        Usage::
            async for chunk in provider.stream(system, messages):
                print(chunk, end="", flush=True)
        """

    # ── Default implementation (override for precision) ───────────────────────

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for *text*.
        Default: ~4 characters per token (reasonable for English text).
        Override in subclasses for provider-accurate counts.
        """
        return max(1, len(text) // 4)

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _calc_cost(self, input_tokens: int, output_tokens: int) -> float:
        return cost_for_model(self.model_name, input_tokens, output_tokens)

    async def _retry(
        self,
        coro_fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Call *coro_fn* with exponential back-off on transient errors.
        Raises the last exception when all retries are exhausted.
        """
        last_exc: Exception = RuntimeError("no attempts made")
        for attempt in range(self.max_retries):
            try:
                async with self._rate_limiter:
                    return await asyncio.wait_for(
                        coro_fn(*args, **kwargs), timeout=self.timeout_s
                    )
            except asyncio.TimeoutError as exc:
                last_exc = LLMTimeoutError(
                    f"{self.provider_name} call timed out after {self.timeout_s}s"
                )
                logger.warning("%s timeout (attempt %d/%d)", self.provider_name, attempt + 1, self.max_retries)
            except RateLimitError as exc:
                last_exc = exc
                delay = 2.0 ** attempt
                logger.warning(
                    "%s rate limit hit (attempt %d/%d) — retrying in %.0fs",
                    self.provider_name, attempt + 1, self.max_retries, delay,
                )
                await asyncio.sleep(delay)
            except (InvalidAPIKeyError, ModelUnavailableError):
                raise   # non-retryable
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    delay = 2.0 ** attempt
                    logger.warning(
                        "%s transient error (attempt %d/%d): %s — retrying in %.0fs",
                        self.provider_name, attempt + 1, self.max_retries, exc, delay,
                    )
                    await asyncio.sleep(delay)
        raise last_exc

    @staticmethod
    def _messages_to_str(messages: List[Dict[str, Any]]) -> str:
        """Concatenate messages into a plain string for token estimation."""
        return " ".join(m.get("content", "") for m in messages if isinstance(m.get("content"), str))

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model_name!r})"


# ══════════════════════════════════════════════════════════════════════════════
# Tool format converters
# ══════════════════════════════════════════════════════════════════════════════


def _tools_to_claude(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def _tools_to_openai(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _parse_openai_tool_calls(raw_calls: Any) -> List[ToolCall]:
    result = []
    for tc in raw_calls or []:
        try:
            args = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            args = {}
        result.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Claude (Anthropic)
# ══════════════════════════════════════════════════════════════════════════════


class ClaudeLLM(LLMProvider):
    """
    Anthropic Claude provider.

    Supported models: claude-opus-4-8, claude-sonnet-4-6,
                      claude-haiku-4-5-20251001
    Rate limit: 50 req/min (adjust per tier in settings).
    """

    provider_name = "claude"

    def __init__(
        self,
        model_name: str = "claude-sonnet-4-6",
        api_key: str = "",
        *,
        calls_per_minute: int = 50,
        timeout_s: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            model_name, api_key,
            calls_per_minute=calls_per_minute,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package is not installed. Run: pip install anthropic"
            )
        self._client = _anthropic.AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)

    # ── call ──────────────────────────────────────────────────────────────────

    async def call(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
    ) -> LLMResponse:
        return await self._retry(
            self._call_once,
            system_prompt, messages, tools,
            max_tokens=max_tokens,
            temperature=temperature,
            user_id=user_id,
        )

    async def _call_once(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]],
        *,
        max_tokens: int,
        temperature: float,
        user_id: Optional[str],
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = _tools_to_claude(tools)

        try:
            raw = await self._client.messages.create(**kwargs)
        except _anthropic.RateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
        except _anthropic.AuthenticationError as exc:
            raise InvalidAPIKeyError(str(exc)) from exc
        except _anthropic.APIStatusError as exc:
            if exc.status_code in (529, 503):
                raise ModelUnavailableError(str(exc)) from exc
            raise LLMError(str(exc)) from exc

        # Parse content blocks
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        for block in raw.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        in_tok = raw.usage.input_tokens
        out_tok = raw.usage.output_tokens
        cost = self._calc_cost(in_tok, out_tok)

        response = LLMResponse(
            content="\n".join(text_parts),
            model=self.model_name,
            provider=self.provider_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            tool_calls=tool_calls,
            finish_reason=raw.stop_reason or "stop",
            cost_usd=cost,
            raw=raw,
        )

        await UsageTracker.record(
            user_id=user_id,
            model=self.model_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost=cost,
        )
        return response

    # ── stream ────────────────────────────────────────────────────────────────

    async def stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        async with self._rate_limiter:
            async with self._client.messages.stream(
                model=self.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text

    # ── count_tokens ──────────────────────────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        # Claude tokenises BPE; ~3.5–4 chars/token for English
        return max(1, len(text) // 4)


# ══════════════════════════════════════════════════════════════════════════════
# GPT (OpenAI)
# ══════════════════════════════════════════════════════════════════════════════


class GPTProvider(LLMProvider):
    """
    OpenAI GPT provider.

    Supported models: gpt-4o, gpt-4o-mini, gpt-4-turbo
    Rate limit: 100 req/min (RPM; adjust per tier).
    """

    provider_name = "openai"

    def __init__(
        self,
        model_name: str = "gpt-4o",
        api_key: str = "",
        *,
        calls_per_minute: int = 100,
        timeout_s: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            model_name, api_key,
            calls_per_minute=calls_per_minute,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
        if not _OPENAI_AVAILABLE:
            raise ImportError(
                "openai package is not installed. Run: pip install openai"
            )
        self._client = _openai.AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    # ── call ──────────────────────────────────────────────────────────────────

    async def call(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
    ) -> LLMResponse:
        return await self._retry(
            self._call_once,
            system_prompt, messages, tools,
            max_tokens=max_tokens,
            temperature=temperature,
            user_id=user_id,
        )

    async def _call_once(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]],
        *,
        max_tokens: int,
        temperature: float,
        user_id: Optional[str],
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = _tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        try:
            raw = await self._client.chat.completions.create(**kwargs)
        except _openai.RateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
        except _openai.AuthenticationError as exc:
            raise InvalidAPIKeyError(str(exc)) from exc
        except _openai.APIStatusError as exc:
            if exc.status_code in (503, 529):
                raise ModelUnavailableError(str(exc)) from exc
            raise LLMError(str(exc)) from exc

        choice = raw.choices[0]
        content = choice.message.content or ""
        tool_calls = _parse_openai_tool_calls(choice.message.tool_calls)

        in_tok = raw.usage.prompt_tokens if raw.usage else 0
        out_tok = raw.usage.completion_tokens if raw.usage else 0
        cost = self._calc_cost(in_tok, out_tok)

        response = LLMResponse(
            content=content,
            model=self.model_name,
            provider=self.provider_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            cost_usd=cost,
            raw=raw,
        )

        await UsageTracker.record(
            user_id=user_id,
            model=self.model_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost=cost,
        )
        return response

    # ── stream ────────────────────────────────────────────────────────────────

    async def stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        async with self._rate_limiter:
            stream = await self._client.chat.completions.create(
                model=self.model_name,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    # ── count_tokens ──────────────────────────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        # Try tiktoken for precision; fall back to character estimate
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self.model_name)
            return len(enc.encode(text))
        except Exception:
            return max(1, len(text) // 4)


# ══════════════════════════════════════════════════════════════════════════════
# Groq  (free-tier, testing)
# ══════════════════════════════════════════════════════════════════════════════


class GroqProvider(LLMProvider):
    """
    Groq provider — uses the Groq Python SDK.

    Supported models: llama-3.3-70b-versatile, mixtral-8x7b-32768,
                      llama2-70b-4096
    Rate limit: 30 req/min (free tier).  Free to use for testing.
    """

    provider_name = "groq"

    def __init__(
        self,
        model_name: str = "llama-3.3-70b-versatile",
        api_key: str = "",
        *,
        calls_per_minute: int = 30,
        timeout_s: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            model_name, api_key,
            calls_per_minute=calls_per_minute,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
        if not _GROQ_AVAILABLE:
            raise ImportError(
                "groq package is not installed. Run: pip install groq"
            )
        self._client = _groq.AsyncGroq(api_key=api_key or settings.GROQ_API_KEY)

    # ── call ──────────────────────────────────────────────────────────────────

    async def call(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]] = None,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
    ) -> LLMResponse:
        return await self._retry(
            self._call_once,
            system_prompt, messages, tools,
            max_tokens=max_tokens,
            temperature=temperature,
            user_id=user_id,
        )

    async def _call_once(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]],
        *,
        max_tokens: int,
        temperature: float,
        user_id: Optional[str],
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = _tools_to_openai(tools)  # Groq uses OpenAI format
            kwargs["tool_choice"] = "auto"

        try:
            raw = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            exc_str = str(exc).lower()
            if "rate limit" in exc_str or "429" in exc_str:
                raise RateLimitError(str(exc)) from exc
            if "401" in exc_str or "authentication" in exc_str or "api key" in exc_str:
                raise InvalidAPIKeyError(str(exc)) from exc
            if "503" in exc_str or "unavailable" in exc_str:
                raise ModelUnavailableError(str(exc)) from exc
            raise LLMError(str(exc)) from exc

        choice = raw.choices[0]
        content = choice.message.content or ""
        tool_calls = _parse_openai_tool_calls(
            getattr(choice.message, "tool_calls", None)
        )

        in_tok = getattr(raw.usage, "prompt_tokens", 0) or 0
        out_tok = getattr(raw.usage, "completion_tokens", 0) or 0
        cost = self._calc_cost(in_tok, out_tok)  # always 0.0 for free-tier models

        response = LLMResponse(
            content=content,
            model=self.model_name,
            provider=self.provider_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            cost_usd=cost,
            raw=raw,
        )

        await UsageTracker.record(
            user_id=user_id,
            model=self.model_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost=cost,
        )
        return response

    # ── stream ────────────────────────────────────────────────────────────────

    async def stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        async with self._rate_limiter:
            stream = await self._client.chat.completions.create(
                model=self.model_name,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta


# ══════════════════════════════════════════════════════════════════════════════
# Usage tracker — writes api_usage rows (fire-and-forget, never blocks)
# ══════════════════════════════════════════════════════════════════════════════

# Sentinel UUID used for system-initiated calls (no authenticated user)
_SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class UsageTracker:
    """Write api_usage rows without blocking the calling coroutine."""

    @staticmethod
    async def record(
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        user_id: Optional[str] = None,
    ) -> None:
        resolved_user = (
            UUID(user_id) if user_id else _SYSTEM_USER_ID
        )
        try:
            async with AsyncSessionLocal() as session:
                session.add(
                    ApiUsage(
                        user_id=resolved_user,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.debug("UsageTracker: failed to write api_usage row: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# LLM Factory
# ══════════════════════════════════════════════════════════════════════════════

# Maps model name prefix/exact to (ProviderClass, rpm)
_MODEL_REGISTRY: Dict[str, Tuple[type, int]] = {
    # Claude
    "claude-opus-4-8":           (ClaudeLLM,   50),
    "claude-sonnet-4-6":         (ClaudeLLM,   50),
    "claude-haiku-4-5-20251001": (ClaudeLLM,   50),
    # OpenAI
    "gpt-4o":                    (GPTProvider, 100),
    "gpt-4o-mini":               (GPTProvider, 100),
    "gpt-4-turbo":               (GPTProvider, 100),
    # Groq
    "llama-3.3-70b-versatile":   (GroqProvider, 30),
    "mixtral-8x7b-32768":        (GroqProvider, 30),
    "llama2-70b-4096":           (GroqProvider, 30),
}

# API key lookup per provider class
_API_KEY_MAP: Dict[type, str] = {
    ClaudeLLM:    settings.ANTHROPIC_API_KEY,
    GPTProvider:  settings.OPENAI_API_KEY,
    GroqProvider: settings.GROQ_API_KEY,
}


class LLMFactory:
    """
    Central factory for creating and caching provider instances.

    Usage::
        from app.services.llm_provider import llm_factory

        response = await llm_factory.call(
            model="claude-sonnet-4-6",
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "Hello"}],
        )
    """

    def __init__(self) -> None:
        self._cache: Dict[str, LLMProvider] = {}

    def get_provider(self, model_name: str) -> LLMProvider:
        """
        Return a (cached) provider instance for *model_name*.
        Raises ValueError for unknown models.
        """
        if model_name in self._cache:
            return self._cache[model_name]

        entry = _MODEL_REGISTRY.get(model_name)
        if not entry:
            raise ValueError(
                f"Unknown model '{model_name}'. "
                f"Available: {sorted(_MODEL_REGISTRY.keys())}"
            )

        provider_cls, rpm = entry
        api_key = _API_KEY_MAP.get(provider_cls, "")
        instance = provider_cls(
            model_name=model_name,
            api_key=api_key,
            calls_per_minute=rpm,
            timeout_s=settings.LLM_TIMEOUT_S,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self._cache[model_name] = instance
        return instance

    def available_models(self) -> List[str]:
        """Return a sorted list of all registered model names."""
        return sorted(_MODEL_REGISTRY.keys())

    def models_by_provider(self) -> Dict[str, List[str]]:
        """Return models grouped by provider name."""
        out: Dict[str, List[str]] = {}
        for model, (cls, _) in _MODEL_REGISTRY.items():
            name = cls.provider_name
            out.setdefault(name, []).append(model)
        return {k: sorted(v) for k, v in out.items()}

    # ── High-level convenience call with triple fallback ─────────────────────

    # Ordered fallback chain: if the requested model fails, try each in turn.
    # GPT-4o-mini is used as intermediate to avoid full GPT-4o cost on fallback.
    _FALLBACK_CHAIN: List[str] = ["gpt-4o-mini", "llama-3.3-70b-versatile"]

    async def call(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        tools: Optional[List[ToolDefinition]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
        enable_fallback: Optional[bool] = None,
    ) -> LLMResponse:
        """
        Call the LLM with triple-level automatic fallback.

        Fallback order (when use_fallback=True):
            1. Requested model
            2. gpt-4o-mini
            3. llama-3.3-70b-versatile (Groq — free, always available)

        Only RateLimitError and ModelUnavailableError trigger fallback;
        InvalidAPIKeyError and LLMTimeoutError are re-raised immediately.
        If the requested model IS already a fallback candidate, that candidate
        is skipped (no infinite loop).
        """
        model = model or settings.DEFAULT_MODEL
        use_fallback = (
            enable_fallback if enable_fallback is not None
            else settings.LLM_FALLBACK_ENABLED
        )

        # Build the sequence of models to try
        candidates: List[str] = [model]
        if use_fallback:
            for fb in self._FALLBACK_CHAIN:
                if fb != model:
                    candidates.append(fb)

        last_exc: Exception = RuntimeError("no candidates tried")
        for attempt, candidate in enumerate(candidates):
            try:
                provider = self.get_provider(candidate)
                response = await provider.call(
                    system_prompt, messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    user_id=user_id,
                )
                if attempt > 0:
                    logger.info(
                        "Fallback succeeded on '%s' (primary was '%s')",
                        candidate, model,
                    )
                return response
            except (InvalidAPIKeyError, LLMTimeoutError):
                raise   # non-retriable regardless of fallback setting
            except (RateLimitError, ModelUnavailableError) as exc:
                last_exc = exc
                if attempt < len(candidates) - 1:
                    next_model = candidates[attempt + 1]
                    logger.warning(
                        "Model '%s' unavailable (%s) — trying fallback '%s'",
                        candidate, exc, next_model,
                    )
            except LLMError as exc:
                last_exc = exc
                if attempt < len(candidates) - 1:
                    logger.warning(
                        "Model '%s' error (%s) — trying fallback '%s'",
                        candidate, exc, candidates[attempt + 1],
                    )

        raise last_exc

    async def stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream from the default or specified model."""
        model = model or settings.DEFAULT_MODEL
        provider = self.get_provider(model)
        async for chunk in provider.stream(
            system_prompt, messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk


# ── Module-level singleton ────────────────────────────────────────────────────
# Import and use this everywhere:
#   from app.services.llm_provider import llm_factory
llm_factory = LLMFactory()
