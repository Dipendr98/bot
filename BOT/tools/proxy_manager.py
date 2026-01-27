"""
Advanced Proxy Rotation Manager
===============================
Full-featured proxy rotation system with:
- Multiple rotation strategies (round-robin, random, weighted, least-used)
- Health monitoring with automatic bad proxy detection
- Statistics tracking (success/fail rates, latency)
- Sticky sessions for related requests
- Automatic proxy validation and cleanup
"""

from __future__ import annotations

import asyncio
import random
import time
import re
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import httpx

# Thread-safe locks
_rotation_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_rotation_indices: Dict[str, int] = defaultdict(int)

# In-memory proxy health cache (syncs to DB periodically)
_proxy_health: Dict[str, Dict[str, "ProxyHealth"]] = defaultdict(dict)
_sticky_sessions: Dict[str, Dict[str, str]] = defaultdict(dict)  # user_id -> {session_key: proxy}


class RotationStrategy(Enum):
    """Proxy rotation strategies."""
    RANDOM = "random"           # Random selection (default)
    ROUND_ROBIN = "round_robin" # Sequential rotation
    WEIGHTED = "weighted"       # Based on success rate
    LEAST_USED = "least_used"   # Least recently used
    FASTEST = "fastest"         # Based on latency


@dataclass
class ProxyHealth:
    """Tracks health metrics for a single proxy."""
    proxy: str
    success_count: int = 0
    fail_count: int = 0
    total_latency_ms: float = 0.0
    last_used: float = 0.0
    last_success: float = 0.0
    last_fail: float = 0.0
    consecutive_fails: int = 0
    is_disabled: bool = False
    disabled_until: float = 0.0
    created_at: float = field(default_factory=time.time)

    @property
    def total_requests(self) -> int:
        return self.success_count + self.fail_count

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0  # New proxy, assume good
        return self.success_count / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.success_count == 0:
            return 0.0
        return self.total_latency_ms / self.success_count

    @property
    def weight(self) -> float:
        """Calculate weight for weighted rotation (higher = better)."""
        if self.is_disabled:
            return 0.0

        # Base weight from success rate
        base = self.success_rate * 100

        # Penalty for high latency (normalize: 0-5000ms -> 0-50 penalty)
        latency_penalty = min(self.avg_latency_ms / 100, 50)

        # Penalty for consecutive failures
        fail_penalty = self.consecutive_fails * 20

        # Bonus for recent success
        if self.last_success > 0:
            seconds_since_success = time.time() - self.last_success
            if seconds_since_success < 60:  # Success in last minute
                base += 10

        return max(base - latency_penalty - fail_penalty, 1)

    def to_dict(self) -> dict:
        return {
            "proxy": self.proxy,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "total_latency_ms": self.total_latency_ms,
            "last_used": self.last_used,
            "last_success": self.last_success,
            "last_fail": self.last_fail,
            "consecutive_fails": self.consecutive_fails,
            "is_disabled": self.is_disabled,
            "disabled_until": self.disabled_until,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProxyHealth":
        return cls(
            proxy=data.get("proxy", ""),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            total_latency_ms=data.get("total_latency_ms", 0.0),
            last_used=data.get("last_used", 0.0),
            last_success=data.get("last_success", 0.0),
            last_fail=data.get("last_fail", 0.0),
            consecutive_fails=data.get("consecutive_fails", 0),
            is_disabled=data.get("is_disabled", False),
            disabled_until=data.get("disabled_until", 0.0),
            created_at=data.get("created_at", time.time()),
        )


class ProxyRotator:
    """
    Advanced proxy rotator with multiple strategies and health tracking.
    """

    # Configuration
    MAX_CONSECUTIVE_FAILS = 5          # Disable after this many consecutive failures
    DISABLE_DURATION_SECONDS = 300     # 5 minutes cooldown for bad proxies
    HEALTH_CHECK_TIMEOUT = 10          # Seconds
    MIN_SUCCESS_RATE = 0.2             # Minimum 20% success rate to stay active

    def __init__(self, user_id: str):
        self.user_id = str(user_id)
        self._strategy = RotationStrategy.RANDOM

    @property
    def strategy(self) -> RotationStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, value: RotationStrategy):
        self._strategy = value

    def _get_proxies(self) -> List[str]:
        """Get user's proxy list from store."""
        from BOT.db.store import get_proxy as _get_proxies
        return _get_proxies(self.user_id) or []

    def _get_health(self, proxy: str) -> ProxyHealth:
        """Get or create health record for a proxy."""
        if proxy not in _proxy_health[self.user_id]:
            _proxy_health[self.user_id][proxy] = ProxyHealth(proxy=proxy)
        return _proxy_health[self.user_id][proxy]

    def _get_available_proxies(self) -> List[str]:
        """Get proxies that are not disabled."""
        now = time.time()
        available = []
        for proxy in self._get_proxies():
            health = self._get_health(proxy)
            # Re-enable if cooldown expired
            if health.is_disabled and health.disabled_until <= now:
                health.is_disabled = False
                health.consecutive_fails = 0
            if not health.is_disabled:
                available.append(proxy)
        return available

    async def get_proxy(self, session_key: Optional[str] = None) -> Optional[str]:
        """
        Get next proxy based on rotation strategy.

        Args:
            session_key: Optional key for sticky sessions (e.g., card hash)

        Returns:
            Proxy URL or None if no proxies available
        """
        # Check for sticky session
        if session_key and session_key in _sticky_sessions[self.user_id]:
            sticky_proxy = _sticky_sessions[self.user_id][session_key]
            health = self._get_health(sticky_proxy)
            if not health.is_disabled:
                health.last_used = time.time()
                return sticky_proxy

        proxies = self._get_available_proxies()
        if not proxies:
            return None

        selected = await self._select_proxy(proxies)

        if selected:
            health = self._get_health(selected)
            health.last_used = time.time()

            # Store in sticky session if key provided
            if session_key:
                _sticky_sessions[self.user_id][session_key] = selected

        return selected

    async def _select_proxy(self, proxies: List[str]) -> Optional[str]:
        """Select proxy based on current strategy."""
        if not proxies:
            return None

        if self._strategy == RotationStrategy.RANDOM:
            return random.choice(proxies)

        elif self._strategy == RotationStrategy.ROUND_ROBIN:
            async with _rotation_locks[self.user_id]:
                idx = _rotation_indices[self.user_id]
                selected = proxies[idx % len(proxies)]
                _rotation_indices[self.user_id] = (idx + 1) % len(proxies)
                return selected

        elif self._strategy == RotationStrategy.WEIGHTED:
            weights = [self._get_health(p).weight for p in proxies]
            total = sum(weights)
            if total == 0:
                return random.choice(proxies)
            # Weighted random selection
            r = random.uniform(0, total)
            cumulative = 0
            for proxy, weight in zip(proxies, weights):
                cumulative += weight
                if r <= cumulative:
                    return proxy
            return proxies[-1]

        elif self._strategy == RotationStrategy.LEAST_USED:
            return min(proxies, key=lambda p: self._get_health(p).last_used)

        elif self._strategy == RotationStrategy.FASTEST:
            # Filter proxies that have been tested
            tested = [(p, self._get_health(p)) for p in proxies if self._get_health(p).success_count > 0]
            if tested:
                return min(tested, key=lambda x: x[1].avg_latency_ms)[0]
            return random.choice(proxies)

        return random.choice(proxies)

    def record_success(self, proxy: str, latency_ms: float = 0.0):
        """Record successful request through proxy."""
        health = self._get_health(proxy)
        health.success_count += 1
        health.last_success = time.time()
        health.consecutive_fails = 0
        if latency_ms > 0:
            health.total_latency_ms += latency_ms

    def record_failure(self, proxy: str):
        """Record failed request through proxy."""
        health = self._get_health(proxy)
        health.fail_count += 1
        health.last_fail = time.time()
        health.consecutive_fails += 1

        # Auto-disable after too many consecutive failures
        if health.consecutive_fails >= self.MAX_CONSECUTIVE_FAILS:
            health.is_disabled = True
            health.disabled_until = time.time() + self.DISABLE_DURATION_SECONDS

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all proxies."""
        proxies = self._get_proxies()
        stats = {
            "total_proxies": len(proxies),
            "strategy": self._strategy.value,
            "proxies": [],
        }

        active_count = 0
        disabled_count = 0
        total_success = 0
        total_fail = 0

        for proxy in proxies:
            health = self._get_health(proxy)
            proxy_stat = {
                "proxy": _mask_proxy(proxy),
                "success": health.success_count,
                "fail": health.fail_count,
                "success_rate": f"{health.success_rate * 100:.1f}%",
                "avg_latency": f"{health.avg_latency_ms:.0f}ms" if health.success_count > 0 else "N/A",
                "status": "Disabled" if health.is_disabled else "Active",
                "weight": f"{health.weight:.1f}",
            }
            stats["proxies"].append(proxy_stat)

            if health.is_disabled:
                disabled_count += 1
            else:
                active_count += 1
            total_success += health.success_count
            total_fail += health.fail_count

        stats["active_count"] = active_count
        stats["disabled_count"] = disabled_count
        stats["total_success"] = total_success
        stats["total_fail"] = total_fail
        stats["overall_success_rate"] = f"{(total_success / max(total_success + total_fail, 1)) * 100:.1f}%"

        return stats

    def reset_health(self, proxy: Optional[str] = None):
        """Reset health stats for one or all proxies."""
        if proxy:
            if proxy in _proxy_health[self.user_id]:
                del _proxy_health[self.user_id][proxy]
        else:
            _proxy_health[self.user_id].clear()

    def clear_sticky_sessions(self):
        """Clear all sticky sessions."""
        _sticky_sessions[self.user_id].clear()

    def remove_disabled_proxies(self) -> int:
        """Remove all disabled proxies from user's list. Returns count removed."""
        from BOT.db.store import get_proxy as _get_proxies, save_proxies, load_proxies

        proxies = _get_proxies(self.user_id) or []
        disabled = []
        remaining = []

        for proxy in proxies:
            health = self._get_health(proxy)
            if health.is_disabled or health.success_rate < self.MIN_SUCCESS_RATE:
                disabled.append(proxy)
                # Clean up health record
                if proxy in _proxy_health[self.user_id]:
                    del _proxy_health[self.user_id][proxy]
            else:
                remaining.append(proxy)

        if disabled:
            data = load_proxies()
            data[self.user_id] = remaining
            save_proxies(data)

        return len(disabled)

    def enable_all(self):
        """Re-enable all disabled proxies."""
        for proxy in self._get_proxies():
            health = self._get_health(proxy)
            health.is_disabled = False
            health.consecutive_fails = 0
            health.disabled_until = 0


# ============================================================================
# Helper Functions
# ============================================================================

def _mask_proxy(proxy: str) -> str:
    """Mask proxy credentials for display."""
    try:
        proxy_clean = proxy.replace("http://", "").replace("https://", "")
        if "@" in proxy_clean:
            creds, hostport = proxy_clean.split("@", 1)
            user = creds.split(":")[0]
            return f"{user[:3]}***@{hostport}"
        return proxy_clean
    except:
        return proxy[:20] + "..."


def normalize_proxy(proxy_raw: str) -> Optional[str]:
    """
    Normalize proxy string to standard format: http://user:pass@host:port

    Supports:
    - http://user:pass@host:port (full URL)
    - https://user:pass@host:port (full URL)
    - socks5://user:pass@host:port (SOCKS5)
    - user:pass@host:port
    - host:port:user:pass
    - host:port (no auth)
    """
    proxy_raw = proxy_raw.strip()
    if not proxy_raw:
        return None

    # Already full proxy URL with protocol
    if proxy_raw.startswith(("http://", "https://", "socks4://", "socks5://")):
        return proxy_raw

    # Format: USER:PASS@HOST:PORT
    match1 = re.fullmatch(r"(.+?):(.+?)@([a-zA-Z0-9.\-]+):(\d+)", proxy_raw)
    if match1:
        user, pwd, host, port = match1.groups()
        return f"http://{user}:{pwd}@{host}:{port}"

    # Format: HOST:PORT:USER:PASS
    match2 = re.fullmatch(r"([a-zA-Z0-9.\-]+):(\d+):(.+?):(.+)", proxy_raw)
    if match2:
        host, port, user, pwd = match2.groups()
        return f"http://{user}:{pwd}@{host}:{port}"

    # Format: HOST:PORT (no auth)
    match3 = re.fullmatch(r"([a-zA-Z0-9.\-]+):(\d+)", proxy_raw)
    if match3:
        host, port = match3.groups()
        return f"http://{host}:{port}"

    return None


async def validate_proxy(proxy_url: str, timeout: int = 10) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Validate proxy by checking connection to ipinfo.io.

    Returns:
        Tuple of (success, ip_address_or_error, latency_ms)
    """
    start = time.time()
    try:
        async with httpx.AsyncClient(
            proxies=proxy_url,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            res = await client.get("https://ipinfo.io/json")
            res.raise_for_status()
            latency = (time.time() - start) * 1000
            ip = res.json().get("ip")
            return True, ip, latency
    except httpx.TimeoutException:
        return False, "Connection timeout", None
    except httpx.ConnectError as e:
        return False, f"Connection failed: {str(e)[:50]}", None
    except Exception as e:
        return False, str(e)[:100], None


async def test_proxy_rotation(proxy_url: str, test_count: int = 3) -> Tuple[bool, List[str], str]:
    """
    Test if proxy provides IP rotation.

    Returns:
        Tuple of (is_rotating, list_of_ips, status_message)
    """
    ips = []
    errors = []

    for i in range(test_count):
        success, result, _ = await validate_proxy(proxy_url, timeout=15)
        if success:
            ips.append(result)
        else:
            errors.append(result)

        if i < test_count - 1:
            await asyncio.sleep(1)  # Small delay between tests

    if not ips:
        return False, [], f"All tests failed: {errors[0] if errors else 'Unknown error'}"

    unique_ips = list(set(ips))
    is_rotating = len(unique_ips) > 1

    if is_rotating:
        status = f"Rotating proxy - {len(unique_ips)} unique IPs detected"
    else:
        status = f"Static IP proxy - IP: {ips[0]}"

    return is_rotating, unique_ips, status


async def bulk_test_proxies(proxies: List[str], timeout: int = 10) -> List[Dict[str, Any]]:
    """
    Test multiple proxies concurrently.

    Returns:
        List of test results with proxy, status, ip, latency
    """
    async def test_one(proxy: str) -> Dict[str, Any]:
        success, result, latency = await validate_proxy(proxy, timeout)
        return {
            "proxy": _mask_proxy(proxy),
            "proxy_full": proxy,
            "success": success,
            "ip": result if success else None,
            "error": result if not success else None,
            "latency_ms": latency,
        }

    # Test up to 10 proxies concurrently
    results = []
    batch_size = 10
    for i in range(0, len(proxies), batch_size):
        batch = proxies[i:i + batch_size]
        batch_results = await asyncio.gather(*[test_one(p) for p in batch])
        results.extend(batch_results)

    return results


# ============================================================================
# User-level Rotation Functions (for use in checkers)
# ============================================================================

# Cache rotators per user
_rotators: Dict[str, ProxyRotator] = {}


def get_rotator(user_id: str) -> ProxyRotator:
    """Get or create rotator for user, loading saved settings."""
    uid = str(user_id)
    if uid not in _rotators:
        rotator = ProxyRotator(uid)
        # Load saved strategy from database
        try:
            from BOT.db.store import get_proxy_settings
            settings = get_proxy_settings(uid)
            strategy_str = settings.get("rotation_strategy", "random")
            try:
                rotator._strategy = RotationStrategy(strategy_str)
            except ValueError:
                rotator._strategy = RotationStrategy.RANDOM
        except Exception:
            pass
        _rotators[uid] = rotator
    return _rotators[uid]


async def get_rotating_proxy(user_id: str, session_key: Optional[str] = None) -> Optional[str]:
    """
    Get next proxy for user using configured rotation strategy.

    This is the main function to use in checkers.

    Args:
        user_id: User's ID
        session_key: Optional key for sticky sessions (use same proxy for related requests)

    Returns:
        Proxy URL or None
    """
    rotator = get_rotator(user_id)
    return await rotator.get_proxy(session_key)


def get_rotating_proxy_sync(user_id: str) -> Optional[str]:
    """
    Synchronous version of get_rotating_proxy for non-async contexts.
    Uses random selection by default.
    """
    from BOT.db.store import get_proxy as _get_proxies

    proxies = _get_proxies(str(user_id)) or []
    if not proxies:
        return None

    # Check health and filter disabled
    rotator = get_rotator(user_id)
    available = rotator._get_available_proxies()

    if not available:
        return None

    return random.choice(available)


def record_proxy_result(user_id: str, proxy: str, success: bool, latency_ms: float = 0.0):
    """
    Record result of a request through a proxy.
    Call this after each request to update health stats.

    Args:
        user_id: User's ID
        proxy: The proxy URL used
        success: Whether the request succeeded
        latency_ms: Response time in milliseconds (for successful requests)
    """
    rotator = get_rotator(user_id)
    if success:
        rotator.record_success(proxy, latency_ms)
    else:
        rotator.record_failure(proxy)


def set_rotation_strategy(user_id: str, strategy: str) -> bool:
    """
    Set rotation strategy for user and persist to database.

    Args:
        user_id: User's ID
        strategy: One of 'random', 'round_robin', 'weighted', 'least_used', 'fastest'

    Returns:
        True if valid strategy, False otherwise
    """
    try:
        strat = RotationStrategy(strategy.lower())
        rotator = get_rotator(user_id)
        rotator.strategy = strat
        # Persist to database
        try:
            from BOT.db.store import get_proxy_settings, save_proxy_settings
            settings = get_proxy_settings(str(user_id))
            settings["rotation_strategy"] = strategy.lower()
            save_proxy_settings(str(user_id), settings)
        except Exception:
            pass  # Still return True since in-memory worked
        return True
    except ValueError:
        return False


def get_rotation_strategy(user_id: str) -> str:
    """Get current rotation strategy for user."""
    return get_rotator(user_id).strategy.value


def get_proxy_stats(user_id: str) -> Dict[str, Any]:
    """Get proxy statistics for user."""
    return get_rotator(user_id).get_stats()


def clear_bad_proxies(user_id: str) -> int:
    """Remove disabled/bad proxies. Returns count removed."""
    return get_rotator(user_id).remove_disabled_proxies()


def reset_proxy_health(user_id: str, proxy: Optional[str] = None):
    """Reset health stats for one or all proxies."""
    get_rotator(user_id).reset_health(proxy)


def enable_all_proxies(user_id: str):
    """Re-enable all disabled proxies."""
    get_rotator(user_id).enable_all()
