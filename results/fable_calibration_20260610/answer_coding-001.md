# IntervalStore

```python
class IntervalStore:
    """Manages a collection of numeric intervals.

    Intervals are stored exactly as added (raw). Use `merge` to obtain a
    normalized view where overlapping or adjacent intervals are combined;
    use `query` to test membership against the raw stored intervals.
    """

    def __init__(self) -> None:
        """Create an empty interval store."""
        self._intervals: list[tuple[float, float]] = []

    def add(self, start: float, end: float) -> None:
        """Store a new interval from `start` to `end` (inclusive).

        If `start > end`, the endpoints are swapped so the stored interval
        is always well-formed. Single-point intervals (start == end) are
        allowed.

        Args:
            start: Left endpoint of the interval.
            end: Right endpoint of the interval.
        """
        if start > end:
            start, end = end, start
        self._intervals.append((start, end))

    def merge(self) -> list[tuple[float, float]]:
        """Return a new list of merged intervals.

        Overlapping or adjacent intervals (i.e. where one interval's start
        is <= the previous interval's end) are combined into a single
        interval. The result is sorted by start point. The stored intervals
        are not modified.

        Returns:
            A new list of (start, end) tuples with no overlaps, in
            ascending order. Empty list if the store is empty.
        """
        if not self._intervals:
            return []

        ordered = sorted(self._intervals)
        merged: list[tuple[float, float]] = [ordered[0]]
        for start, end in ordered[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:  # overlapping or adjacent (touching)
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    def query(self, point: float) -> bool:
        """Check whether `point` lies within any raw stored interval.

        Endpoints are inclusive, so a single-point interval (a, a)
        contains exactly the point `a`.

        Args:
            point: The value to test.

        Returns:
            True if any stored interval contains the point, else False.
        """
        return any(start <= point <= end for start, end in self._intervals)
```

## Notes on edge cases

- **Empty store**: `merge()` returns `[]`; `query()` returns `False` for any point.
- **Single-point intervals**: `(a, a)` is stored as-is; `query(a)` is `True`. In `merge`, a point interval touching another interval's endpoint is absorbed (adjacency uses `start <= last_end`).
- **Fully overlapping additions**: a contained interval never shrinks the merged result because the merge keeps `max(last_end, end)`.
- **Arbitrary insertion order**: `merge` sorts a copy of the stored intervals first, so insertion order does not matter; the raw list (used by `query`) is left untouched.
- **Reversed endpoints**: `add(5, 2)` is normalized to `(2, 5)` so all stored intervals are well-formed.

### Quick examples

```python
store = IntervalStore()
store.query(1.0)          # False (empty store)

store.add(5, 7)
store.add(1, 3)
store.add(3, 4)           # adjacent to (1, 3)
store.add(6, 6)           # single point, inside (5, 7)

store.merge()             # [(1.0, 4.0), (5.0, 7.0)]
store.query(3.5)          # True  (inside raw (3, 4))
store.query(4.5)          # False (in no raw interval)
store.query(6.0)          # True
```
