# LRUCache — dict + doubly linked list, O(1) get/put

The cache combines two structures:

- A **hash map** (`self.map`) from key → linked-list node, giving O(1) lookup.
- A **doubly linked list** of nodes ordered by recency, with two sentinel nodes (`head` and `tail`) so insertion/removal never needs None checks. Nodes nearest `head` are most recently used; the node just before `tail` is the least recently used and is the eviction candidate.

Both `get` and `put` only do dict operations and a constant number of pointer updates, so each is O(1).

```python
class _Node:
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key: int = 0, value: int = 0):
        self.key = key
        self.value = value
        self.prev: "_Node | None" = None
        self.next: "_Node | None" = None


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.map: dict[int, _Node] = {}
        # Sentinels: head <-> tail. MRU lives right after head,
        # LRU right before tail.
        self.head = _Node()
        self.tail = _Node()
        self.head.next = self.tail
        self.tail.prev = self.head

    # ---- internal linked-list helpers (all O(1)) ----

    def _remove(self, node: _Node) -> None:
        """Unlink a node from the list."""
        node.prev.next = node.next
        node.next.prev = node.prev

    def _add_to_front(self, node: _Node) -> None:
        """Insert a node right after head (mark as most recently used)."""
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node
        self.head.next = node

    def _move_to_front(self, node: _Node) -> None:
        self._remove(node)
        self._add_to_front(node)

    # ---- public API ----

    def get(self, key: int) -> int:
        node = self.map.get(key)
        if node is None:
            return -1
        self._move_to_front(node)
        return node.value

    def put(self, key: int, value: int) -> None:
        node = self.map.get(key)
        if node is not None:
            # Existing key: update value and mark as most recently used.
            node.value = value
            self._move_to_front(node)
            return

        if len(self.map) >= self.capacity:
            # Evict the least recently used node (just before tail).
            lru = self.tail.prev
            self._remove(lru)
            del self.map[lru.key]

        node = _Node(key, value)
        self.map[key] = node
        self._add_to_front(node)
```

## How the required edge cases are handled

- **`put` on an existing key** updates `node.value` *and* moves the node to the front, so it becomes most recently used (no eviction occurs in this path, which also matters when the cache is full).
- **`get` on a hit** moves the node to the front before returning the value; on a miss it returns `-1`.
- **Eviction** happens only when inserting a *new* key at capacity: the node before the `tail` sentinel is the LRU entry. Each node stores its own `key` so the corresponding dict entry can be deleted in O(1).
- **`capacity >= 1`** works: with capacity 1 every new key evicts the previous one.
- No `functools.lru_cache` or `collections.OrderedDict` is used.

## Trace of the specified sequence

```python
c = LRUCache(2)
c.put(1, 1)    # list: 1
c.put(2, 2)    # list: 2, 1
c.get(1)       # -> 1; list: 1, 2
c.put(3, 3)    # full, evicts LRU=2; list: 3, 1
c.get(2)       # -> -1
c.put(4, 4)    # full, evicts LRU=1; list: 4, 3
c.get(1)       # -> -1
c.get(3)       # -> 3; list: 3, 4
c.get(4)       # -> 4; list: 4, 3
c.put(3, 30)   # existing key: value updated, moved to front; list: 3, 4
c.put(5, 5)    # full, evicts LRU=4; list: 5, 3
c.get(4)       # -> -1
c.get(3)       # -> 30
```

All results match the expected outputs exactly.
