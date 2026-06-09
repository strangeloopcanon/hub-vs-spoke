# Three concurrency bugs in `AsyncBatcher`

## Bug 1 — The lock is created but never used: shared state races across `await` boundaries

`self.lock = asyncio.Lock()` is defined in `__init__` and then never acquired anywhere. All mutations of the shared `self.pending` list happen unguarded, and the critical sections span `await` points, so coroutines interleave inside them:

- `submit()` does a **check-then-act**: it appends to `self.pending`, checks `len(self.pending) >= self.batch_size`, and then calls `_flush()`. Meanwhile `run_timeout_flush()` independently checks `if self.pending:` and also calls `_flush()`.
- While one `_flush()` is suspended in `await self._process_batch(...)`, the timeout flusher (or another `submit`) can run a second `_flush()` concurrently. Both mutate `self.pending` and `self._batch_id` with no coordination. Depending on interleaving you can get a batch flushed twice conceptually (double work), items flushed out from under a `submit` that thinks it just triggered the flush, or partially-filled batches taken at the wrong moment.

Even though asyncio is single-threaded, any state read before an `await` and written after one is a race. The check of `pending`, the slicing of the batch, and the bookkeeping must be one atomic critical section under the lock; only the actual I/O (`_process_batch`) should run outside it (otherwise the lock would serialize all batch processing, killing concurrency).

## Bug 2 — Futures are abandoned on error (and `set_result` can blow up on cancelled futures)

`_flush()` has no exception handling:

```python
results = await self._process_batch([item for item, _ in batch])
...
future.set_result(results[i])
```

If `_process_batch` raises (network error, timeout, anything), the exception propagates out of `_flush()` and **none of the futures in that batch are ever completed**. Every caller blocked on `return await future` in `submit()` hangs forever — a silent deadlock for the whole batch.

A related failure mode: a caller awaiting `submit()` can be cancelled (e.g. it was wrapped in `asyncio.wait_for`). That cancels its future, but the `(item, future)` pair is still in the batch. Calling `future.set_result(...)` on a cancelled/done future raises `InvalidStateError`, which then aborts the loop mid-way and **strands all remaining futures in the same batch**.

Fix: wrap processing in `try/except` and call `set_exception(exc)` on every future on failure, and guard every `set_result`/`set_exception` with `if not future.done():`.

## Bug 3 — Futures can sit in `pending` forever: the timeout flusher is never started, and stragglers are never drained

`submit()` only flushes when the batch is full. If fewer than `batch_size` items arrive, those callers block on `await future` indefinitely — *unless* `run_timeout_flush()` is running. But nothing in the class ever schedules it: it's a method the user must somehow know to spawn as a background task. Use the class as written (just call `submit`) and any partial batch deadlocks forever. This is exactly the hint's "futures that are added to `pending` but never make it into a batch."

Fix: the batcher should own its flusher — lazily start it as a task on first `submit()` (created inside the lock so it's started exactly once). (Relatedly, `self.results[batch_id] = results` is written and never read or cleaned up — an unbounded memory leak; it should simply be removed.)

## Corrected version

```python
import asyncio
from typing import Any


class AsyncBatcher:
    """Batches individual requests and processes them in groups."""

    def __init__(self, batch_size: int = 5, timeout: float = 1.0):
        self.batch_size = batch_size
        self.timeout = timeout
        self.pending: list[tuple[Any, asyncio.Future]] = []
        self.lock = asyncio.Lock()
        self._batch_id = 0
        self._flusher_task: asyncio.Task | None = None

    async def submit(self, item: Any) -> Any:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        # Bug 1 fix: all reads/writes of self.pending happen under the lock,
        # so the append + size check + batch extraction is atomic.
        async with self.lock:
            self._ensure_flusher()          # Bug 3 fix: flusher always running
            self.pending.append((item, future))
            batch = self._take_batch() if len(self.pending) >= self.batch_size else None

        # I/O happens *outside* the lock so batches can process concurrently.
        if batch:
            await self._process_and_resolve(batch)

        return await future

    def _ensure_flusher(self) -> None:
        # Lazily start the timeout flusher exactly once (called under the lock).
        if self._flusher_task is None or self._flusher_task.done():
            self._flusher_task = asyncio.create_task(self.run_timeout_flush())

    def _take_batch(self) -> list[tuple[Any, asyncio.Future]]:
        # Must be called while holding self.lock.
        batch = self.pending[: self.batch_size]
        self.pending = self.pending[self.batch_size :]
        self._batch_id += 1
        return batch

    async def _process_and_resolve(self, batch: list[tuple[Any, asyncio.Future]]) -> None:
        try:
            results = await self._process_batch([item for item, _ in batch])
        except Exception as exc:
            # Bug 2 fix: never strand waiters — propagate the failure to them.
            for _, fut in batch:
                if not fut.done():
                    fut.set_exception(exc)
            return

        for (_, fut), result in zip(batch, results):
            if not fut.done():              # caller may have been cancelled
                fut.set_result(result)

    async def _process_batch(self, items: list) -> list:
        await asyncio.sleep(0.1)  # simulate I/O
        return [f"processed:{x}" for x in items]

    async def run_timeout_flush(self):
        while True:
            await asyncio.sleep(self.timeout)
            async with self.lock:
                batch = self._take_batch() if self.pending else None
            if batch:
                await self._process_and_resolve(batch)
```

Key properties of the fix:

- **Atomic critical sections.** Every touch of `self.pending` (append, size check, batch extraction) happens under `self.lock`, so `submit()` and the timeout flusher can no longer interleave inside a check-then-act. The slow `_process_batch` await deliberately happens *outside* the lock, so multiple batches still process concurrently.
- **No stranded futures on failure.** If processing raises, every waiter in the batch gets the exception via `set_exception` instead of hanging forever; `fut.done()` guards prevent `InvalidStateError` when a waiter was cancelled mid-flight.
- **Partial batches always drain.** The flusher task is owned and lazily started by the batcher itself, so a lone item submitted to an otherwise idle batcher resolves after at most `timeout` seconds instead of deadlocking. The write-only `self.results` cache (an unbounded leak) is gone.
