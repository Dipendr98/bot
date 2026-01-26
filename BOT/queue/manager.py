"""
Global Priority Queue Manager for Mass Card Checking

Architecture:
- Priority Min-Heap: Lower priority value = processed first
- Premium Users: Priority 1 (processed first)
- Free Users: Priority 10 (processed when resources available)
- Fixed Global Worker Pool: 500 concurrent workers
- Thread-safe with asyncio locks

Visual Flow:
┌─────────────┐     ┌────────────────────┐     ┌─────────────────┐
│ User 1 /msh │ ──► │                    │     │                 │
│ (Premium)   │     │  Global Priority   │ ──► │  Worker Pool    │
│ Priority: 1 │     │      Queue         │     │  (500 workers)  │
└─────────────┘     │                    │     │                 │
                    │  [P1] ████████     │     │  ┌───┐ ┌───┐    │
┌─────────────┐     │  [P1] ████████     │     │  │ W │ │ W │    │
│ User 2 /mst │ ──► │  [P10] ██████      │     │  └───┘ └───┘    │
│ (Free)      │     │  [P10] ██████      │     │  ... x 500      │
│ Priority: 10│     │                    │     │                 │
└─────────────┘     └────────────────────┘     └─────────────────┘
"""

import asyncio
import heapq
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import defaultdict


class Priority(IntEnum):
    """Priority levels for card checking tasks."""
    OWNER = 0       # Owner - highest priority
    VIP = 1         # VIP plan
    ELITE = 2       # Elite plan
    PLUS = 3        # Plus plan
    STANDARD = 5    # Standard plan
    FREE = 10       # Free users - lowest priority


def get_priority_for_plan(plan_name: str) -> Priority:
    """Get priority level based on user plan."""
    plan_upper = (plan_name or "Free").upper()
    if plan_upper == "OWNER":
        return Priority.OWNER
    elif plan_upper == "VIP":
        return Priority.VIP
    elif plan_upper == "ELITE":
        return Priority.ELITE
    elif plan_upper in ("PLUS", "PLAN1"):
        return Priority.PLUS
    elif plan_upper in ("STANDARD", "PLAN2"):
        return Priority.STANDARD
    else:
        return Priority.FREE


@dataclass
class CardTask:
    """A single card checking task in the queue."""
    task_id: str
    user_id: str
    card: str
    gateway: str  # "shopify" or "stripe"
    priority: int
    created_at: float

    # Shopify-specific
    proxy: Optional[str] = None
    sites: Optional[List[dict]] = None

    # Metadata
    batch_id: str = ""  # Groups cards from same /msh or /mst command
    plan: str = "Free"
    badge: str = "🧿"
    checked_by: str = ""
    message_id: int = 0
    chat_id: int = 0

    # For heap ordering (priority, created_at, task_id)
    def __lt__(self, other):
        if self.priority != other.priority:
            return self.priority < other.priority
        if self.created_at != other.created_at:
            return self.created_at < other.created_at
        return self.task_id < other.task_id


@dataclass
class TaskResult:
    """Result of a card check."""
    task_id: str
    batch_id: str
    user_id: str
    card: str
    gateway: str
    status: str  # "charged", "approved", "declined", "error"
    response: str
    retries: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)
    processed_at: float = field(default_factory=time.time)


@dataclass
class BatchProgress:
    """Track progress for a batch (single /msh or /mst command)."""
    batch_id: str
    user_id: str
    total_cards: int
    processed: int = 0
    charged: int = 0
    approved: int = 0
    declined: int = 0
    errors: int = 0
    retries: int = 0
    started_at: float = field(default_factory=time.time)
    stopped: bool = False

    # Callback info for progress updates
    chat_id: int = 0
    message_id: int = 0
    gateway: str = ""
    plan: str = "Free"
    badge: str = "🧿"
    checked_by: str = ""


class CardQueue:
    """
    Global Priority Queue for Card Checking

    Features:
    - Min-Heap based priority queue
    - Premium users processed first (lower priority number)
    - Fixed global worker pool (500 concurrent)
    - Thread-safe async operations
    - Real-time progress tracking per batch
    - Stop support for individual batches
    """

    # Global configuration
    MAX_WORKERS = 500  # Total concurrent workers across all users

    def __init__(self):
        # Priority heap: stores (priority, timestamp, task_id, CardTask)
        self._heap: List[Tuple[int, float, str, CardTask]] = []
        self._heap_lock = asyncio.Lock()

        # Task lookup
        self._tasks: Dict[str, CardTask] = {}

        # Batch tracking
        self._batches: Dict[str, BatchProgress] = {}
        self._batch_lock = asyncio.Lock()

        # Stop requests per batch
        self._stop_requested: Dict[str, bool] = {}

        # Result callbacks per batch
        self._result_callbacks: Dict[str, Callable] = {}
        self._progress_callbacks: Dict[str, Callable] = {}
        self._completion_callbacks: Dict[str, Callable] = {}

        # Worker management
        self._workers_running = False
        self._worker_semaphore: Optional[asyncio.Semaphore] = None
        self._worker_tasks: List[asyncio.Task] = []

        # Statistics
        self._stats = {
            "total_queued": 0,
            "total_processed": 0,
            "total_charged": 0,
            "total_approved": 0,
            "premium_processed": 0,
            "free_processed": 0,
        }
        self._stats_lock = asyncio.Lock()

    async def start_workers(self):
        """Start the global worker pool."""
        if self._workers_running:
            return

        self._workers_running = True
        self._worker_semaphore = asyncio.Semaphore(self.MAX_WORKERS)

        # Start the main worker dispatcher
        asyncio.create_task(self._worker_dispatcher())
        print(f"[CardQueue] Started with {self.MAX_WORKERS} global workers")

    async def stop_workers(self):
        """Stop all workers gracefully."""
        self._workers_running = False
        # Cancel all worker tasks
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
        self._worker_tasks.clear()

    async def _worker_dispatcher(self):
        """Main dispatcher that continuously processes the queue."""
        while self._workers_running:
            try:
                # Get next task from queue
                task = await self._get_next_task()

                if task is None:
                    # Queue empty, wait a bit
                    await asyncio.sleep(0.05)
                    continue

                # Check if batch was stopped
                if self._stop_requested.get(task.batch_id):
                    # Mark task as cancelled and continue
                    await self._handle_cancelled_task(task)
                    continue

                # Acquire worker slot and process
                await self._worker_semaphore.acquire()
                worker_task = asyncio.create_task(self._process_task(task))
                self._worker_tasks.append(worker_task)

                # Cleanup completed worker tasks periodically
                self._worker_tasks = [t for t in self._worker_tasks if not t.done()]

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[CardQueue] Dispatcher error: {e}")
                await asyncio.sleep(0.1)

    async def _get_next_task(self) -> Optional[CardTask]:
        """Get the highest priority task from the queue."""
        async with self._heap_lock:
            while self._heap:
                _, _, task_id, task = heapq.heappop(self._heap)

                # Check if task still exists (not cancelled)
                if task_id in self._tasks:
                    del self._tasks[task_id]
                    return task

            return None

    async def _process_task(self, task: CardTask):
        """Process a single card task using the appropriate gateway."""
        try:
            result = None

            if task.gateway == "shopify":
                result = await self._check_shopify(task)
            elif task.gateway == "stripe":
                result = await self._check_stripe(task)
            else:
                result = TaskResult(
                    task_id=task.task_id,
                    batch_id=task.batch_id,
                    user_id=task.user_id,
                    card=task.card,
                    gateway=task.gateway,
                    status="error",
                    response="Unknown gateway"
                )

            # Update batch progress
            await self._update_batch_progress(result)

            # Call result callback
            if task.batch_id in self._result_callbacks:
                try:
                    await self._result_callbacks[task.batch_id](result)
                except Exception as e:
                    print(f"[CardQueue] Result callback error: {e}")

            # Update global stats
            async with self._stats_lock:
                self._stats["total_processed"] += 1
                if result.status == "charged":
                    self._stats["total_charged"] += 1
                elif result.status == "approved":
                    self._stats["total_approved"] += 1

                if task.priority <= Priority.PLUS:
                    self._stats["premium_processed"] += 1
                else:
                    self._stats["free_processed"] += 1

        except Exception as e:
            print(f"[CardQueue] Task processing error: {e}")
            # Create error result
            error_result = TaskResult(
                task_id=task.task_id,
                batch_id=task.batch_id,
                user_id=task.user_id,
                card=task.card,
                gateway=task.gateway,
                status="error",
                response=f"Processing error: {str(e)[:50]}"
            )
            await self._update_batch_progress(error_result)

        finally:
            # Release worker slot
            self._worker_semaphore.release()

    async def _check_shopify(self, task: CardTask) -> TaskResult:
        """Check card using Shopify gateway."""
        from BOT.Charge.Shopify.slf.api import autoshopify_with_captcha_retry
        from BOT.Charge.Shopify.tls_session import TLSAsyncSession
        from BOT.Charge.Shopify.slf.site_manager import SiteRotator
        from BOT.tools.proxy import get_rotating_proxy

        retries = 0
        last_response = "UNKNOWN"

        try:
            if not task.sites:
                return TaskResult(
                    task_id=task.task_id,
                    batch_id=task.batch_id,
                    user_id=task.user_id,
                    card=task.card,
                    gateway="shopify",
                    status="error",
                    response="NO_SITES_CONFIGURED"
                )

            # Get proxy
            proxy = task.proxy or get_rotating_proxy(task.user_id)

            rotator = SiteRotator(task.user_id, max_retries=2)

            while retries < 2:
                current_site = rotator.get_current_site()
                if not current_site:
                    break

                site_url = current_site.get("url")

                try:
                    # Rotate proxy on retry
                    if retries > 0:
                        proxy = get_rotating_proxy(task.user_id)

                    async with TLSAsyncSession(timeout_seconds=60, proxy=proxy) as session:
                        result = await autoshopify_with_captcha_retry(
                            site_url, task.card, session,
                            max_captcha_retries=2, proxy=proxy
                        )

                    response = str(result.get("Response", "UNKNOWN"))
                    last_response = response

                    # Determine status
                    status = self._classify_shopify_response(response)

                    if rotator.is_real_response(response):
                        rotator.mark_current_success()
                        return TaskResult(
                            task_id=task.task_id,
                            batch_id=task.batch_id,
                            user_id=task.user_id,
                            card=task.card,
                            gateway="shopify",
                            status=status,
                            response=response,
                            retries=retries,
                            extra={"site": site_url, "price": result.get("Price", "0")}
                        )

                    if rotator.should_retry(response) and retries < 1:
                        retries += 1
                        rotator.mark_current_failed()
                        next_site = rotator.get_next_site()
                        if not next_site:
                            break
                        await asyncio.sleep(0.1)
                        continue
                    else:
                        return TaskResult(
                            task_id=task.task_id,
                            batch_id=task.batch_id,
                            user_id=task.user_id,
                            card=task.card,
                            gateway="shopify",
                            status=status,
                            response=response,
                            retries=retries,
                            extra={"site": site_url}
                        )

                except Exception as e:
                    last_response = f"ERROR: {str(e)[:30]}"
                    retries += 1
                    next_site = rotator.get_next_site()
                    if not next_site:
                        break
                    await asyncio.sleep(0.05)

            return TaskResult(
                task_id=task.task_id,
                batch_id=task.batch_id,
                user_id=task.user_id,
                card=task.card,
                gateway="shopify",
                status="error",
                response=last_response,
                retries=retries
            )

        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                batch_id=task.batch_id,
                user_id=task.user_id,
                card=task.card,
                gateway="shopify",
                status="error",
                response=f"ERROR: {str(e)[:40]}",
                retries=retries
            )

    async def _check_stripe(self, task: CardTask) -> TaskResult:
        """Check card using Stripe gateway."""
        from BOT.Charge.Stripe.api import async_stripe_charge

        try:
            parts = task.card.split("|")
            if len(parts) != 4:
                return TaskResult(
                    task_id=task.task_id,
                    batch_id=task.batch_id,
                    user_id=task.user_id,
                    card=task.card,
                    gateway="stripe",
                    status="error",
                    response="Invalid card format"
                )

            card, mes, ano, cvv = parts
            result = await async_stripe_charge(card, mes, ano, cvv)

            status = result.get("status", "error")
            response = result.get("response", "Unknown")

            return TaskResult(
                task_id=task.task_id,
                batch_id=task.batch_id,
                user_id=task.user_id,
                card=task.card,
                gateway="stripe",
                status=status,
                response=response,
                extra=result
            )

        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                batch_id=task.batch_id,
                user_id=task.user_id,
                card=task.card,
                gateway="stripe",
                status="error",
                response=f"ERROR: {str(e)[:40]}"
            )

    def _classify_shopify_response(self, response: str) -> str:
        """Classify Shopify response into status."""
        response_upper = (response or "").upper()

        # Error patterns
        error_patterns = [
            "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
            "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP",
            "CONNECTION FAILED", "IP RATE LIMIT", "REQUEST TIMEOUT",
            "ERROR", "BLOCKED", "PROXY", "TIMEOUT", "DEAD", "EMPTY"
        ]

        # Charged patterns
        charged_patterns = [
            "ORDER_PLACED", "THANK YOU", "SUCCESS", "CHARGED", "COMPLETE"
        ]

        # Approved/CCN patterns
        approved_patterns = [
            "3D CC", "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED",
            "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP",
            "INCORRECT_CVC", "INVALID_CVC", "CVV_MISMATCH",
            "INSUFFICIENT_FUNDS"
        ]

        if any(p in response_upper for p in error_patterns):
            return "error"
        elif any(p in response_upper for p in charged_patterns):
            return "charged"
        elif any(p in response_upper for p in approved_patterns):
            return "approved"
        else:
            return "declined"

    async def _handle_cancelled_task(self, task: CardTask):
        """Handle a cancelled task (batch was stopped)."""
        result = TaskResult(
            task_id=task.task_id,
            batch_id=task.batch_id,
            user_id=task.user_id,
            card=task.card,
            gateway=task.gateway,
            status="cancelled",
            response="Cancelled by user"
        )
        await self._update_batch_progress(result)

    async def _update_batch_progress(self, result: TaskResult):
        """Update progress for a batch."""
        async with self._batch_lock:
            batch = self._batches.get(result.batch_id)
            if not batch:
                return

            batch.processed += 1
            batch.retries += result.retries

            if result.status == "charged":
                batch.charged += 1
            elif result.status == "approved":
                batch.approved += 1
            elif result.status in ("error", "cancelled"):
                batch.errors += 1
            else:
                batch.declined += 1

            # Call progress callback
            if result.batch_id in self._progress_callbacks:
                try:
                    await self._progress_callbacks[result.batch_id](batch)
                except Exception as e:
                    print(f"[CardQueue] Progress callback error: {e}")

            # Check if batch is complete
            if batch.processed >= batch.total_cards or batch.stopped:
                if result.batch_id in self._completion_callbacks:
                    try:
                        await self._completion_callbacks[result.batch_id](batch)
                    except Exception as e:
                        print(f"[CardQueue] Completion callback error: {e}")

                # Cleanup
                self._cleanup_batch(result.batch_id)

    def _cleanup_batch(self, batch_id: str):
        """Clean up resources for a completed batch."""
        self._stop_requested.pop(batch_id, None)
        self._result_callbacks.pop(batch_id, None)
        self._progress_callbacks.pop(batch_id, None)
        self._completion_callbacks.pop(batch_id, None)
        # Keep batch in _batches for a while for stats

    # =========================================================================
    # Public API
    # =========================================================================

    async def add_batch(
        self,
        user_id: str,
        cards: List[str],
        gateway: str,
        plan: str = "Free",
        badge: str = "🧿",
        checked_by: str = "",
        chat_id: int = 0,
        message_id: int = 0,
        proxy: Optional[str] = None,
        sites: Optional[List[dict]] = None,
        on_result: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
    ) -> str:
        """
        Add a batch of cards to the queue.

        Returns: batch_id for tracking
        """
        batch_id = f"{user_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        priority = get_priority_for_plan(plan)

        # Create batch tracker
        batch = BatchProgress(
            batch_id=batch_id,
            user_id=user_id,
            total_cards=len(cards),
            chat_id=chat_id,
            message_id=message_id,
            gateway=gateway,
            plan=plan,
            badge=badge,
            checked_by=checked_by,
        )

        async with self._batch_lock:
            self._batches[batch_id] = batch

        # Register callbacks
        if on_result:
            self._result_callbacks[batch_id] = on_result
        if on_progress:
            self._progress_callbacks[batch_id] = on_progress
        if on_complete:
            self._completion_callbacks[batch_id] = on_complete

        # Add cards to queue
        async with self._heap_lock:
            for card in cards:
                task_id = f"{batch_id}_{uuid.uuid4().hex[:8]}"
                task = CardTask(
                    task_id=task_id,
                    user_id=user_id,
                    card=card,
                    gateway=gateway,
                    priority=priority,
                    created_at=time.time(),
                    proxy=proxy,
                    sites=sites,
                    batch_id=batch_id,
                    plan=plan,
                    badge=badge,
                    checked_by=checked_by,
                    message_id=message_id,
                    chat_id=chat_id,
                )

                self._tasks[task_id] = task
                heapq.heappush(self._heap, (priority, task.created_at, task_id, task))

            self._stats["total_queued"] += len(cards)

        return batch_id

    async def stop_batch(self, batch_id: str) -> bool:
        """Stop a running batch."""
        async with self._batch_lock:
            if batch_id in self._batches:
                self._batches[batch_id].stopped = True
                self._stop_requested[batch_id] = True
                return True
        return False

    async def get_batch_progress(self, batch_id: str) -> Optional[BatchProgress]:
        """Get current progress for a batch."""
        async with self._batch_lock:
            return self._batches.get(batch_id)

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get global queue statistics."""
        async with self._heap_lock:
            queue_size = len(self._heap)

            # Count by priority
            priority_counts = defaultdict(int)
            for p, _, _, task in self._heap:
                priority_counts[p] += 1

        async with self._batch_lock:
            active_batches = len([b for b in self._batches.values()
                                  if b.processed < b.total_cards and not b.stopped])

        async with self._stats_lock:
            stats = self._stats.copy()

        return {
            "queue_size": queue_size,
            "active_batches": active_batches,
            "max_workers": self.MAX_WORKERS,
            "priority_breakdown": dict(priority_counts),
            **stats,
        }

    async def get_user_position(self, user_id: str) -> Dict[str, Any]:
        """Get queue position info for a user."""
        async with self._heap_lock:
            user_tasks = 0
            position = 0
            found_first = False

            for i, (_, _, _, task) in enumerate(sorted(self._heap)):
                if task.user_id == user_id:
                    user_tasks += 1
                    if not found_first:
                        position = i + 1
                        found_first = True

        return {
            "user_id": user_id,
            "tasks_in_queue": user_tasks,
            "estimated_position": position,
        }


# Global queue instance
_global_queue: Optional[CardQueue] = None
_queue_lock = asyncio.Lock()


async def get_global_queue() -> CardQueue:
    """Get or create the global queue instance."""
    global _global_queue

    async with _queue_lock:
        if _global_queue is None:
            _global_queue = CardQueue()
            await _global_queue.start_workers()

        return _global_queue


async def init_queue():
    """Initialize the global queue (call on bot startup)."""
    queue = await get_global_queue()
    print(f"[CardQueue] Initialized with {queue.MAX_WORKERS} workers")
    return queue
