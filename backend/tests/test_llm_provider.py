"""
LLM Provider test suite
════════════════════════════════════════════════════════════════════════════════

Scenarios covered
─────────────────
 1.  ClaudeLLM  — successful call, response parsing
 2.  GPTProvider — successful call, response parsing
 3.  GroqProvider — successful call, response parsing
 4.  Tool call flow — Claude: tool_use block → ToolCall objects
 5.  Tool call flow — OpenAI/Groq: tool_calls → ToolCall objects
 6.  Cost calculation — all models, free-tier zero-cost check
 7.  Token counting  — base estimate, GPT tiktoken path
 8.  Fallback logic  — Claude RateLimitError → Groq retried
 9.  Fallback logic  — Claude ModelUnavailable → Groq retried
10.  No fallback when already on fallback model
11.  Retry on transient error (first call fails, second succeeds)
12.  Retry exhaustion raises last exception
13.  Rate-limit error mapped correctly (Claude, OpenAI, Groq)
14.  Invalid API key mapped to InvalidAPIKeyError
15.  Factory: correct provider class per model name
16.  Factory: unknown model raises ValueError
17.  Factory: available_models lists all registered models
18.  Factory: models_by_provider groups correctly
19.  Tool format converters — Claude wire format
20.  Tool format converters — OpenAI wire format
21.  UsageTracker — DB write called on success
22.  LLMResponse.to_dict serialises cleanly
23.  Streaming — yields chunks from mock async generator
24.  Timeout — asyncio.TimeoutError → LLMTimeoutError
25.  cost_for_model helper
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.services.llm_provider import (
    ClaudeLLM,
    GPTProvider,
    GroqProvider,
    InvalidAPIKeyError,
    LLMError,
    LLMFactory,
    LLMResponse,
    LLMTimeoutError,
    ModelUnavailableError,
    RateLimitError,
    ToolCall,
    ToolDefinition,
    UsageTracker,
    _tools_to_claude,
    _tools_to_openai,
    cost_for_model,
    llm_factory,
)

# ─────────────────────────────── Helpers ─────────────────────────────────────

SAMPLE_TOOL = ToolDefinition(
    name="search",
    description="Search the web",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

SYSTEM = "You are a helpful assistant."
MESSAGES = [{"role": "user", "content": "Hello, world!"}]


def _make_claude_response(
    text: str = "Hi there!",
    input_tokens: int = 10,
    output_tokens: int = 5,
    tool_use: bool = False,
) -> MagicMock:
    """Build a mock Anthropic message response."""
    content_blocks = []

    if text:
        block = MagicMock()
        block.type = "text"
        block.text = text
        content_blocks.append(block)

    if tool_use:
        tb = MagicMock()
        tb.type = "tool_use"
        tb.id = "toolu_abc123"
        tb.name = "search"
        tb.input = {"query": "test"}
        content_blocks.append(tb)

    resp = MagicMock()
    resp.content = content_blocks
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


def _make_openai_response(
    text: str = "Hi there!",
    input_tokens: int = 10,
    output_tokens: int = 5,
    tool_calls_raw: bool = False,
) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None

    if tool_calls_raw:
        tc = MagicMock()
        tc.id = "call_xyz"
        tc.function.name = "search"
        tc.function.arguments = json.dumps({"query": "openai test"})
        msg.tool_calls = [tc]

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=input_tokens, completion_tokens=output_tokens)
    return resp


def _patch_db():
    """Stub the DB session so UsageTracker doesn't need a real Postgres."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return patch(
        "app.services.llm_provider.AsyncSessionLocal",
        MagicMock(return_value=mock_session),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. ClaudeLLM — success path
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_claude_call_success():
    provider = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test-key")
    mock_resp = _make_claude_response(input_tokens=20, output_tokens=8)

    with patch.object(provider._client.messages, "create", new=AsyncMock(return_value=mock_resp)):
        with _patch_db():
            result = await provider.call(SYSTEM, MESSAGES)

    assert isinstance(result, LLMResponse)
    assert result.content == "Hi there!"
    assert result.model == "claude-sonnet-4-6"
    assert result.provider == "claude"
    assert result.input_tokens == 20
    assert result.output_tokens == 8
    assert result.finish_reason == "end_turn"
    assert result.cost_usd > 0  # $3/$15 per 1M tokens


@pytest.mark.asyncio
async def test_claude_call_passes_system_and_messages():
    provider = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")
    mock_create = AsyncMock(return_value=_make_claude_response())
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return _make_claude_response()

    with patch.object(provider._client.messages, "create", side_effect=capture):
        with _patch_db():
            await provider.call(SYSTEM, MESSAGES)

    assert captured["system"] == SYSTEM
    assert captured["messages"] == MESSAGES
    assert captured["model"] == "claude-sonnet-4-6"


# ═════════════════════════════════════════════════════════════════════════════
# 2. GPTProvider — success path
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gpt_call_success():
    provider = GPTProvider(model_name="gpt-4o", api_key="test-key")
    mock_resp = _make_openai_response(input_tokens=15, output_tokens=6)

    with patch.object(
        provider._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)
    ):
        with _patch_db():
            result = await provider.call(SYSTEM, MESSAGES)

    assert isinstance(result, LLMResponse)
    assert result.content == "Hi there!"
    assert result.provider == "openai"
    assert result.input_tokens == 15
    assert result.output_tokens == 6


@pytest.mark.asyncio
async def test_gpt_prepends_system_message():
    provider = GPTProvider(model_name="gpt-4o", api_key="test")
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return _make_openai_response()

    with patch.object(provider._client.chat.completions, "create", side_effect=capture):
        with _patch_db():
            await provider.call(SYSTEM, MESSAGES)

    first_msg = captured["messages"][0]
    assert first_msg["role"] == "system"
    assert first_msg["content"] == SYSTEM


# ═════════════════════════════════════════════════════════════════════════════
# 3. GroqProvider — success path
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_groq_call_success():
    provider = GroqProvider(model_name="llama-3.3-70b-versatile", api_key="test-key")
    mock_resp = _make_openai_response(text="Groq response", input_tokens=12, output_tokens=4)

    with patch.object(
        provider._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)
    ):
        with _patch_db():
            result = await provider.call(SYSTEM, MESSAGES)

    assert result.provider == "groq"
    assert result.content == "Groq response"
    assert result.cost_usd == 0.0  # free tier


# ═════════════════════════════════════════════════════════════════════════════
# 4 & 5. Tool calling
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_claude_tool_call_parsing():
    provider = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")
    mock_resp = _make_claude_response(tool_use=True)

    with patch.object(provider._client.messages, "create", new=AsyncMock(return_value=mock_resp)):
        with _patch_db():
            result = await provider.call(SYSTEM, MESSAGES, tools=[SAMPLE_TOOL])

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "toolu_abc123"
    assert tc.name == "search"
    assert tc.arguments == {"query": "test"}


@pytest.mark.asyncio
async def test_openai_tool_call_parsing():
    provider = GPTProvider(model_name="gpt-4o", api_key="test")
    mock_resp = _make_openai_response(tool_calls_raw=True)

    with patch.object(
        provider._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)
    ):
        with _patch_db():
            result = await provider.call(SYSTEM, MESSAGES, tools=[SAMPLE_TOOL])

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "call_xyz"
    assert tc.name == "search"
    assert tc.arguments == {"query": "openai test"}


@pytest.mark.asyncio
async def test_claude_tool_definition_forwarded():
    provider = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return _make_claude_response()

    with patch.object(provider._client.messages, "create", side_effect=capture):
        with _patch_db():
            await provider.call(SYSTEM, MESSAGES, tools=[SAMPLE_TOOL])

    assert "tools" in captured
    assert captured["tools"][0]["name"] == "search"
    assert "input_schema" in captured["tools"][0]  # Claude-specific key


@pytest.mark.asyncio
async def test_gpt_tool_definition_forwarded():
    provider = GPTProvider(model_name="gpt-4o", api_key="test")
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)
        return _make_openai_response()

    with patch.object(provider._client.chat.completions, "create", side_effect=capture):
        with _patch_db():
            await provider.call(SYSTEM, MESSAGES, tools=[SAMPLE_TOOL])

    assert "tools" in captured
    assert captured["tools"][0]["type"] == "function"
    assert captured["tools"][0]["function"]["name"] == "search"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Cost calculation
# ═════════════════════════════════════════════════════════════════════════════


def test_cost_for_claude_sonnet():
    # $3.00 / 1M input + $15.00 / 1M output
    cost = cost_for_model("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(3.00)

    cost = cost_for_model("claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000)
    assert cost == pytest.approx(15.00)


def test_cost_for_claude_opus():
    cost = cost_for_model("claude-opus-4-8", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(90.00)


def test_cost_for_gpt4o():
    cost = cost_for_model("gpt-4o", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(20.00)  # $5 + $15


def test_cost_for_groq_is_zero():
    cost = cost_for_model("llama-3.3-70b-versatile", input_tokens=999_999, output_tokens=999_999)
    assert cost == 0.0


def test_cost_for_unknown_model_is_zero():
    cost = cost_for_model("some-unknown-model", input_tokens=1_000, output_tokens=1_000)
    assert cost == 0.0


def test_cost_precision_small_call():
    # 100 input + 50 output with claude-sonnet-4-6
    cost = cost_for_model("claude-sonnet-4-6", input_tokens=100, output_tokens=50)
    expected = (100 * 3.0 + 50 * 15.0) / 1_000_000
    assert cost == pytest.approx(expected)


# ═════════════════════════════════════════════════════════════════════════════
# 7. Token counting
# ═════════════════════════════════════════════════════════════════════════════


def test_token_count_estimate_base():
    provider = GroqProvider.__new__(GroqProvider)
    LLMProvider.__init__(provider, "llama-3.3-70b-versatile", "key")

    text = "Hello world!"  # 12 chars → 3 tokens at 4 chars/token
    count = provider.count_tokens(text)
    # Rough estimate: within 2x of character / 4
    assert count >= 1
    assert count <= len(text)


def test_token_count_empty_string():
    provider = ClaudeLLM.__new__(ClaudeLLM)
    LLMProvider.__init__(provider, "claude-sonnet-4-6", "key")
    assert provider.count_tokens("") == 1  # max(1, 0) guard


def test_token_count_long_text():
    provider = ClaudeLLM.__new__(ClaudeLLM)
    LLMProvider.__init__(provider, "claude-sonnet-4-6", "key")
    long_text = "word " * 1000  # 5000 chars → ~1250 tokens
    count = provider.count_tokens(long_text)
    assert 900 <= count <= 1500  # allow variation in the estimate


def test_gpt_token_count_falls_back_gracefully():
    provider = GPTProvider.__new__(GPTProvider)
    LLMProvider.__init__(provider, "gpt-4o", "key")
    # tiktoken may or may not be installed — either way it shouldn't raise
    count = provider.count_tokens("Test sentence.")
    assert count >= 1


# ═════════════════════════════════════════════════════════════════════════════
# 8 & 9. Fallback logic
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_factory_falls_back_on_rate_limit():
    """Claude raises RateLimitError → factory retries with Groq."""
    factory = LLMFactory()

    claude = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")
    groq = GroqProvider(model_name="llama-3.3-70b-versatile", api_key="test")

    claude_call = AsyncMock(side_effect=RateLimitError("rate limited"))
    groq_resp = _make_openai_response(text="fallback response")
    groq_call = AsyncMock(return_value=groq_resp)

    with patch.object(claude, "call", claude_call), \
         patch.object(groq, "call", groq_call), \
         patch.object(factory, "get_provider") as mock_get:

        mock_get.side_effect = lambda m: (
            claude if "sonnet" in m else groq
        )

        with patch("app.services.llm_provider.settings") as mock_settings:
            mock_settings.DEFAULT_MODEL = "claude-sonnet-4-6"
            mock_settings.TEST_MODEL = "llama-3.3-70b-versatile"
            mock_settings.LLM_FALLBACK_ENABLED = True
            mock_settings.LLM_TIMEOUT_S = 30.0
            mock_settings.LLM_MAX_RETRIES = 1

            with _patch_db():
                result = await factory.call(
                    SYSTEM, MESSAGES,
                    model="claude-sonnet-4-6",
                    enable_fallback=True,
                )

    claude_call.assert_called_once()
    groq_call.assert_called_once()
    assert result.content == "fallback response"


@pytest.mark.asyncio
async def test_factory_falls_back_on_model_unavailable():
    """Claude raises ModelUnavailableError → factory retries with Groq."""
    factory = LLMFactory()

    claude = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")
    groq = GroqProvider(model_name="llama-3.3-70b-versatile", api_key="test")

    groq_resp = _make_openai_response(text="groq fallback")

    with patch.object(claude, "call", AsyncMock(side_effect=ModelUnavailableError("503"))), \
         patch.object(groq, "call", AsyncMock(return_value=groq_resp)), \
         patch.object(factory, "get_provider") as mock_get:

        mock_get.side_effect = lambda m: (
            claude if "sonnet" in m else groq
        )

        with patch("app.services.llm_provider.settings") as mock_settings:
            mock_settings.DEFAULT_MODEL = "claude-sonnet-4-6"
            mock_settings.TEST_MODEL = "llama-3.3-70b-versatile"
            mock_settings.LLM_FALLBACK_ENABLED = True
            mock_settings.LLM_TIMEOUT_S = 30.0
            mock_settings.LLM_MAX_RETRIES = 1

            with _patch_db():
                result = await factory.call(
                    SYSTEM, MESSAGES, model="claude-sonnet-4-6", enable_fallback=True
                )

    assert result.content == "groq fallback"


@pytest.mark.asyncio
async def test_no_infinite_fallback_when_already_on_fallback_model():
    """If the fallback model itself fails, the error propagates — no infinite loop."""
    factory = LLMFactory()
    groq = GroqProvider(model_name="llama-3.3-70b-versatile", api_key="test")

    with patch.object(groq, "call", AsyncMock(side_effect=RateLimitError("groq rate"))), \
         patch.object(factory, "get_provider", return_value=groq):

        with patch("app.services.llm_provider.settings") as mock_settings:
            mock_settings.DEFAULT_MODEL = "llama-3.3-70b-versatile"
            mock_settings.TEST_MODEL = "llama-3.3-70b-versatile"
            mock_settings.LLM_FALLBACK_ENABLED = True
            mock_settings.LLM_TIMEOUT_S = 30.0
            mock_settings.LLM_MAX_RETRIES = 1

            with pytest.raises(RateLimitError):
                await factory.call(SYSTEM, MESSAGES, model="llama-3.3-70b-versatile")


# ═════════════════════════════════════════════════════════════════════════════
# 11 & 12. Retry logic
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    provider = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")
    call_count = 0

    async def flaky(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMError("transient error")
        return _make_claude_response()

    with patch.object(provider._client.messages, "create", side_effect=flaky):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with _patch_db():
                result = await provider.call(SYSTEM, MESSAGES)

    assert call_count == 2
    assert result.content == "Hi there!"


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_last_error():
    provider = ClaudeLLM(
        model_name="claude-sonnet-4-6", api_key="test", max_retries=2
    )

    async def always_fail(**kwargs):
        raise LLMError("permanent failure")

    with patch.object(provider._client.messages, "create", side_effect=always_fail):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(LLMError, match="permanent failure"):
                await provider.call(SYSTEM, MESSAGES)


# ═════════════════════════════════════════════════════════════════════════════
# 13 & 14. Error mapping
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_claude_rate_limit_maps_to_rate_limit_error():
    import anthropic as ant
    provider = ClaudeLLM(model_name="claude-sonnet-4-6", api_key="test")

    async def raise_rate_limit(**kwargs):
        raise ant.RateLimitError(
            "rate limited",
            response=MagicMock(status_code=429, headers={}),
            body={},
        )

    with patch.object(provider._client.messages, "create", side_effect=raise_rate_limit):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError):
                await provider.call(SYSTEM, MESSAGES)


@pytest.mark.asyncio
async def test_claude_auth_error_maps_to_invalid_api_key():
    import anthropic as ant
    provider = ClaudeLLM(
        model_name="claude-sonnet-4-6", api_key="bad-key", max_retries=1
    )

    async def raise_auth(**kwargs):
        raise ant.AuthenticationError(
            "invalid api key",
            response=MagicMock(status_code=401, headers={}),
            body={},
        )

    with patch.object(provider._client.messages, "create", side_effect=raise_auth):
        with pytest.raises(InvalidAPIKeyError):
            await provider.call(SYSTEM, MESSAGES)


@pytest.mark.asyncio
async def test_groq_rate_limit_string_parsing():
    provider = GroqProvider(model_name="llama-3.3-70b-versatile", api_key="test")

    async def raise_rate_limit(**kwargs):
        raise Exception("Rate limit exceeded 429")

    with patch.object(provider._client.chat.completions, "create", side_effect=raise_rate_limit):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError):
                await provider.call(SYSTEM, MESSAGES)


# ═════════════════════════════════════════════════════════════════════════════
# 15-18. Factory
# ═════════════════════════════════════════════════════════════════════════════


def test_factory_returns_claude_for_sonnet():
    factory = LLMFactory()
    p = factory.get_provider("claude-sonnet-4-6")
    assert isinstance(p, ClaudeLLM)
    assert p.model_name == "claude-sonnet-4-6"


def test_factory_returns_gpt_for_gpt4o():
    factory = LLMFactory()
    p = factory.get_provider("gpt-4o")
    assert isinstance(p, GPTProvider)


def test_factory_returns_groq_for_llama():
    factory = LLMFactory()
    p = factory.get_provider("llama-3.3-70b-versatile")
    assert isinstance(p, GroqProvider)


def test_factory_caches_provider_instances():
    factory = LLMFactory()
    p1 = factory.get_provider("gpt-4o")
    p2 = factory.get_provider("gpt-4o")
    assert p1 is p2  # same instance


def test_factory_raises_for_unknown_model():
    factory = LLMFactory()
    with pytest.raises(ValueError, match="Unknown model"):
        factory.get_provider("gpt-99-ultra-mega")


def test_factory_available_models_is_complete():
    factory = LLMFactory()
    models = factory.available_models()
    assert "claude-sonnet-4-6" in models
    assert "gpt-4o" in models
    assert "llama-3.3-70b-versatile" in models
    assert len(models) >= 8


def test_factory_models_by_provider():
    factory = LLMFactory()
    grouped = factory.models_by_provider()
    assert "claude" in grouped
    assert "openai" in grouped
    assert "groq" in grouped
    assert all(isinstance(v, list) for v in grouped.values())


# ═════════════════════════════════════════════════════════════════════════════
# 19 & 20. Tool format converters
# ═════════════════════════════════════════════════════════════════════════════


def test_tools_to_claude_format():
    result = _tools_to_claude([SAMPLE_TOOL])
    assert len(result) == 1
    tool = result[0]
    assert tool["name"] == "search"
    assert tool["description"] == "Search the web"
    assert "input_schema" in tool
    assert tool["input_schema"]["type"] == "object"


def test_tools_to_openai_format():
    result = _tools_to_openai([SAMPLE_TOOL])
    assert len(result) == 1
    tool = result[0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "search"
    assert "parameters" in tool["function"]


def test_tools_to_claude_multiple():
    tools = [
        ToolDefinition("t1", "d1", {"type": "object", "properties": {}}),
        ToolDefinition("t2", "d2", {"type": "object", "properties": {}}),
    ]
    result = _tools_to_claude(tools)
    assert len(result) == 2
    assert result[0]["name"] == "t1"
    assert result[1]["name"] == "t2"


# ═════════════════════════════════════════════════════════════════════════════
# 21. UsageTracker
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_usage_tracker_writes_record():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.llm_provider.AsyncSessionLocal",
        MagicMock(return_value=mock_session),
    ):
        await UsageTracker.record(
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            cost=0.00125,
            user_id=None,
        )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_usage_tracker_silently_ignores_db_failure():
    with patch(
        "app.services.llm_provider.AsyncSessionLocal",
        MagicMock(side_effect=Exception("DB is down")),
    ):
        # Should not raise
        await UsageTracker.record(
            model="gpt-4o", input_tokens=10, output_tokens=5, cost=0.0
        )


# ═════════════════════════════════════════════════════════════════════════════
# 22. LLMResponse serialisation
# ═════════════════════════════════════════════════════════════════════════════


def test_llm_response_to_dict():
    r = LLMResponse(
        content="hello",
        model="claude-sonnet-4-6",
        provider="claude",
        input_tokens=10,
        output_tokens=5,
        tool_calls=[ToolCall(id="tc1", name="fn", arguments={"k": "v"})],
        finish_reason="end_turn",
        cost_usd=0.001,
    )
    d = r.to_dict()
    assert d["content"] == "hello"
    assert d["provider"] == "claude"
    assert d["input_tokens"] == 10
    assert d["output_tokens"] == 5
    assert d["tool_calls"][0]["name"] == "fn"
    assert d["tool_calls"][0]["arguments"] == {"k": "v"}


def test_llm_response_total_tokens():
    r = LLMResponse(
        content="x", model="gpt-4o", provider="openai",
        input_tokens=30, output_tokens=70,
    )
    assert r.total_tokens == 100


# ═════════════════════════════════════════════════════════════════════════════
# 23. Streaming
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_groq_stream_yields_chunks():
    provider = GroqProvider(model_name="llama-3.3-70b-versatile", api_key="test")

    async def fake_stream(**kwargs):
        chunks = ["Hello", " ", "world", "!"]

        class FakeStreamResp:
            async def __aiter__(self):
                for c in chunks:
                    delta = MagicMock()
                    delta.content = c
                    choice = MagicMock()
                    choice.delta = delta
                    pkt = MagicMock()
                    pkt.choices = [choice]
                    yield pkt

        return FakeStreamResp()

    with patch.object(provider._client.chat.completions, "create", side_effect=fake_stream):
        collected = []
        async for chunk in provider.stream(SYSTEM, MESSAGES):
            collected.append(chunk)

    assert collected == ["Hello", " ", "world", "!"]
    assert "".join(collected) == "Hello world!"


# ═════════════════════════════════════════════════════════════════════════════
# 24. Timeout
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_timeout_raises_llm_timeout_error():
    provider = ClaudeLLM(
        model_name="claude-sonnet-4-6", api_key="test",
        timeout_s=0.001,  # 1 ms — will always timeout
        max_retries=1,
    )

    async def slow_call(**kwargs):
        await asyncio.sleep(10)  # simulate slow API
        return _make_claude_response()

    with patch.object(provider._client.messages, "create", side_effect=slow_call):
        with pytest.raises(LLMTimeoutError):
            await provider.call(SYSTEM, MESSAGES)


# ═════════════════════════════════════════════════════════════════════════════
# 25. cost_for_model precision
# ═════════════════════════════════════════════════════════════════════════════


def test_cost_for_model_zero_tokens():
    assert cost_for_model("claude-sonnet-4-6", 0, 0) == 0.0


def test_cost_for_model_mixed():
    # 500K input @ $3/M + 200K output @ $15/M
    cost = cost_for_model("claude-sonnet-4-6", 500_000, 200_000)
    assert cost == pytest.approx(1.50 + 3.00)  # $4.50 total


def test_llm_factory_singleton_is_reachable():
    """Module-level singleton should be an LLMFactory instance."""
    assert isinstance(llm_factory, LLMFactory)
