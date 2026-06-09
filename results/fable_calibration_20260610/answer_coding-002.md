# Bug: the window start can move *backwards*

## The bug

The faulty line is:

```python
if char in seen:
    start = seen[char] + 1
```

`seen` is never cleaned up, so it remembers the last index of **every** character ever encountered — including characters that are no longer inside the current window. When the function meets a repeated character whose previous occurrence lies *before* `start` (i.e. outside the current window), it still executes `start = seen[char] + 1`, which **moves `start` backwards** and re-opens a window that actually contains a duplicate.

## Why `'abba'` fails

Trace through `s = 'abba'`:

| end | char | seen (before) | action | start | window | max |
|-----|------|---------------|--------|-------|--------|-----|
| 0 | `a` | `{}` | not seen | 0 | `a` | `a` (1) |
| 1 | `b` | `{a:0}` | not seen | 0 | `ab` | `ab` (2) |
| 2 | `b` | `{a:0, b:1}` | seen at 1 ≥ start → `start = 2` | 2 | `b` | `ab` (2) |
| 3 | `a` | `{a:0, b:2}` | seen at 0, **but 0 < start=2** → `start = 0+1 = 1` ❌ | 1 | `bba` | `bba` (3) |

At `end = 3`, the old `a` at index 0 is *outside* the window (which starts at 2), so it is not a real duplicate. But the code blindly resets `start` to `seen['a'] + 1 = 1`, moving the window start **backwards** from 2 to 1. The window `s[1:4] = 'bba'` is then treated as duplicate-free and reported as the answer, even though it contains two `b`s.

## The fix

Only advance `start` — never let it retreat. The previous occurrence matters only if it is inside the current window (`seen[char] >= start`). The standard idiom is `max`:

```python
def longest_unique_substring(s: str) -> str:
    start = 0
    max_start = 0
    max_len = 0
    seen = {}

    for end, char in enumerate(s):
        if char in seen and seen[char] >= start:
            start = seen[char] + 1
        seen[char] = end
        if end - start + 1 > max_len:
            max_len = end - start + 1
            max_start = start

    return s[max_start:max_start + max_len]
```

Equivalently, replace the conditional update with:

```python
if char in seen:
    start = max(start, seen[char] + 1)
```

## Verification

- `longest_unique_substring('abba')` → `'ab'` (length 2) ✔ — at `end=3`, `seen['a']=0 < start=2`, so `start` stays 2; window is `'ba'`, max remains `'ab'`.
- `longest_unique_substring('abcabcbb')` → `'abc'` ✔
- `longest_unique_substring('bbbbb')` → `'b'` ✔
- `longest_unique_substring('pwwkew')` → `'wke'` ✔
- `longest_unique_substring('')` → `''` ✔
- `longest_unique_substring('tmmzuxt')` → `'mzuxt'` ✔ (another case that breaks the original: the final `t`'s previous index 0 is outside the window)

The algorithm remains O(n) time and O(min(n, |alphabet|)) space; the fix is purely the guard that prevents the sliding window's left edge from moving backwards.
