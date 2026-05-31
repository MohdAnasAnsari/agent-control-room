"""
Redis-based distributed rate limiter with in-memory fallback.

Strategy: fixed-window using Redis INCR + EXPIREAT.
Key format: rl:{rule_key}:{identifier}:{window_ts}

Falls back to a per-process sliding-window store when Redis is unreachable.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    log.warning("redis package not installed — rate limiter will use in-memory fallback only")


# ── Rule definitions ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RateLimitRule:
    limit: int     # max requests allowed per window
    window_s: int  # window size in seconds
    key_by: str    # "ip" = per-IP; "user" = per user/API-key (falls back to IP)


# Endpoint → rule mapping (most specific rules checked first in middleware)
RULES: dict[str, RateLimitRule] = {
    "auth_login":       RateLimitRule(limit=5,    window_s=60,   key_by="ip"),
    "api_agents":       RateLimitRule(limit=100,  window_s=60,   key_by="user"),
    "workflow_execute": RateLimitRule(limit=10,   window_s=60,   key_by="user"),
    "api_v1_default":   RateLimitRule(limit=1000, window_s=3600, key_by="user"),
    "ip_global":        RateLimitRule(limit=1000, window_s=60,   key_by="ip"),
}

# User-agent substrings that indicate scripted/bot clients (lowercase match)
_BOT_UA_FRAGMENTS: frozenset[str] = frozenset({
    "python-requests",
    "python-urllib",
    "libwww-perl",
    "wget/",
    "curl/",
    "go-http-client",
    "scrapy",
    "mechanize",
    "java/",
    "aiohttp/",
    "httpie",
    "axios/",      # legitimate in browsers but flag for direct-to-API abuse
})

BAN_TTL_S = 300  # 5-minute IP ban for detected DDoS/bot patterns


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_ts: int    # unix timestamp when the current window resets
    retry_after: int # seconds until retry is safe (0 when allowed)


# ── In-memory fallback (sliding window) ───────────────────────────────────────

class _MemoryStore:
    """Per-process sliding-window rate limiter. Not distributed."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        now = time.time()
        cutoff = now - rule.window_s
        bucket = [t for t in self._buckets[key] if t > cutoff]
        count = len(bucket)
        reset_ts = int(now) + rule.window_s

        if count < rule.limit:
            bucket.append(now)
            self._buckets[key] = bucket
            return RateLimitResult(
                allowed=True,
                limit=rule.limit,
                remaining=rule.limit - count - 1,
                reset_ts=reset_ts,
                retry_after=0,
            )

        # Determine when the oldest request ages out of the window
        oldest = min(bucket) if bucket else now
        retry_after = max(1, int(oldest + rule.window_s - now))
        self._buckets[key] = bucket
        return RateLimitResult(
            allowed=False,
            limit=rule.limit,
            remaining=0,
            reset_ts=reset_ts,
            retry_after=retry_after,
        )

    def clear(self) -> None:
        self._buckets.clear()


# ── Redis-backed limiter ───────────────────────────────────────────────────────

class RateLimiter:
    """
    Distributed rate limiter backed by Redis with transparent in-memory fallback.

    Lifecycle:
        limiter = RateLimiter(redis_url)
        await limiter.startup()        # call from app startup hook
        result = await limiter.check("user:abc123", "api_v1_default")
        await limiter.shutdown()       # call from app shutdown hook
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None  # type: ignore[name-defined]
        self._redis_ok = False
        self._memory = _MemoryStore()

    # ── lifecycle ──────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        if not _REDIS_AVAILABLE:
            log.warning("Rate limiter: redis not installed — using in-memory fallback")
            return
        try:
            self._client = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=1,
            )
            await self._client.ping()
            self._redis_ok = True
            log.info("Rate limiter: connected to Redis at %s", self._redis_url)
        except Exception as exc:
            log.warning(
                "Rate limiter: Redis unavailable (%s) — using in-memory fallback", exc
            )

    async def shutdown(self) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    # ── core check ─────────────────────────────────────────────────────────────

    async def check(self, identifier: str, rule_key: str) -> RateLimitResult:
        """
        Check and increment the counter for `identifier` against `rule_key`.
        Returns a RateLimitResult indicating whether the request is allowed.
        """
        rule = RULES[rule_key]
        key = f"rl:{rule_key}:{identifier}"

        if self._redis_ok and self._client is not None:
            result = await self._redis_check(key, rule)
            if result is not None:
                return result

        # Redis unavailable or failed — fall back silently
        return self._memory.check(key, rule)

    async def _redis_check(
        self, key: str, rule: RateLimitRule
    ) -> Optional[RateLimitResult]:
        now = int(time.time())
        # Align to window boundary so all counters in the same window share a key
        window_ts = now - (now % rule.window_s)
        reset_ts = window_ts + rule.window_s
        redis_key = f"{key}:{window_ts}"

        try:
            pipe = self._client.pipeline()  # type: ignore[union-attr]
            pipe.incr(redis_key)
            # expire slightly after the window so the key doesn't vanish mid-window
            pipe.expireat(redis_key, reset_ts + 10)
            count, _ = await pipe.execute()

            allowed = count <= rule.limit
            remaining = max(0, rule.limit - count)
            retry_after = max(0, reset_ts - now) if not allowed else 0

            return RateLimitResult(
                allowed=allowed,
                limit=rule.limit,
                remaining=remaining,
                reset_ts=reset_ts,
                retry_after=retry_after,
            )
        except Exception as exc:
            log.warning("Rate limiter: Redis check failed (%s) — allowing request", exc)
            self._redis_ok = False
            return None

    # ── IP ban management ──────────────────────────────────────────────────────

    async def is_banned(self, ip: str) -> bool:
        """True if the IP is currently serving a temporary ban."""
        if not self._redis_ok or self._client is None:
            return False
        try:
            return bool(await self._client.exists(f"ban:{ip}"))
        except Exception:
            return False

    async def ban_ip(self, ip: str, ttl_s: int = BAN_TTL_S) -> None:
        """Temporarily ban an IP (DDoS/bot response). No-op if Redis is down."""
        if not self._redis_ok or self._client is None:
            return
        try:
            await self._client.setex(f"ban:{ip}", ttl_s, "1")
            log.warning("DDoS protection: IP %s banned for %d s", ip, ttl_s)
        except Exception as exc:
            log.warning("Rate limiter: could not ban IP %s — %s", ip, exc)

    # ── Bot detection ──────────────────────────────────────────────────────────

    @staticmethod
    def is_suspicious_ua(user_agent: str) -> bool:
        """
        Returns True if the User-Agent looks like a scripted/bot client.
        An empty UA is always considered suspicious.
        """
        ua = user_agent.strip().lower()
        if not ua:
            return True
        return any(frag in ua for frag in _BOT_UA_FRAGMENTS)

    # ── Test helpers ───────────────────────────────────────────────────────────

    def _reset_memory(self) -> None:
        """Clear all in-memory counters. For use in tests only."""
        self._memory.clear()

    @property
    def using_redis(self) -> bool:
        return self._redis_ok
