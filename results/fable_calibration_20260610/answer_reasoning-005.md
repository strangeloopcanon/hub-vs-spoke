# 3×3 Magic Square with Top-Left = 2, Center = 5

## Answer

A grid satisfying all five constraints is:

```
2 7 6
9 5 1
4 3 8
```

**Verification.** Rows: 2+7+6 = 15, 9+5+1 = 15, 4+3+8 = 15. Columns: 2+9+4 = 15, 7+5+1 = 15, 6+1+8 = 15. Diagonals: 2+5+8 = 15, 4+5+6 = 15. Top-left is 2, center is 5. ✓

However — and this is the key point — **the five constraints do not pin down a unique grid.** There are exactly **two** grids satisfying all five constraints, and they are transposes (mirror images across the main diagonal) of each other. The complete derivation below proves this, so the problem's premise that a unique solution exists is false. I exhibit both solutions and prove no third one exists.

## Complete proof

Let the grid be

```
a b c
d e f
g h i
```

**Step 1: The center must be 5 (constraint 5 is actually forced).**

Add the four lines through the center — the middle row, middle column, and both diagonals:

(d+e+f) + (b+e+h) + (a+e+i) + (c+e+g) = 4 × 15 = 60.

This sum counts every cell once, plus the center three extra times:

(a+b+...+i) + 3e = 45 + 3e = 60 ⟹ e = 5.

**Step 2: Every line through the center consists of a pair summing to 10, plus the 5.**

Since each such line sums to 15 and contains 5, its other two cells sum to 10. The pairs from {1,...,9}\{5} summing to 10 are exactly:

{1,9}, {2,8}, {3,7}, {4,6}.

These four pairs partition the eight non-center digits, and they occupy the four lines through the center (middle row, middle column, two diagonals) — opposite cells across the center always sum to 10. In particular, since a = 2, the cell diagonally opposite is **i = 8**.

**Step 3: The odd digits 1, 3, 7, 9 cannot occupy corners; the even digits 2, 4, 6, 8 must.**

A corner cell lies on **three** lines (its row, its column, one diagonal). If digit x sits in a corner, we need three *disjoint-from-x*, mutually distinct pairs of remaining digits each summing to 15 − x.

- x = 9: pairs summing to 6 from {1,...,8}: only {1,5}, {2,4} — just **two** pairs. Cannot supply three lines. So 9 is not in a corner.
- x = 1: pairs summing to 14 from {2,...,9}: only {5,9}, {6,8} — two pairs. Not a corner.
- x = 3: pairs summing to 12: only {4,8}, {5,7} — two pairs. Not a corner.
- x = 7: pairs summing to 8: only {2,6}, {3,5} — two pairs. Not a corner.

(For contrast, each even digit has three such pairs, e.g. for 2: {4,9}, {6,7}, {5,8}.) An edge cell lies on only two lines, so 1, 3, 7, 9 fit there. Hence the four corners {a, c, g, i} are exactly {2, 4, 6, 8} and the four edges {b, d, f, h} are exactly {1, 3, 7, 9}.

**Step 4: Enumerate the corners given a = 2.**

We already have a = 2 and i = 8 (Step 2). The remaining corners c and g must be 4 and 6 in some order, and by Step 2 they are consistent with the anti-diagonal (c + 5 + g = 15 ⟺ c + g = 10 ✓). Exactly two cases:

**Case A: c = 6, g = 4.**
- Top row: b = 15 − 2 − 6 = 7.
- Left column: d = 15 − 2 − 4 = 9.
- Right column: f = 15 − 6 − 8 = 1.
- Bottom row: h = 15 − 4 − 8 = 3.

Every cell is now forced:

```
2 7 6
9 5 1
4 3 8
```

Check the middle row (9+5+1=15) and middle column (7+5+3=15): valid. This is Solution 1.

**Case B: c = 4, g = 6.**
- Top row: b = 15 − 2 − 4 = 9.
- Left column: d = 15 − 2 − 6 = 7.
- Right column: f = 15 − 4 − 8 = 3.
- Bottom row: h = 15 − 6 − 8 = 1.

```
2 9 4
7 5 3
6 1 8
```

Check the middle row (7+5+3=15) and middle column (9+5+1=15): valid. This is Solution 2 — the transpose of Solution 1.

**Step 5: Conclusion on uniqueness.**

Steps 1–4 are exhaustive: the center is forced to 5, the corners are forced to be the even digits, a = 2 forces i = 8, and the only remaining freedom is the choice c ∈ {4, 6}, each branch of which determines every other cell uniquely and yields a valid grid. Therefore the five constraints admit **exactly two** solutions:

```
2 7 6        2 9 4
9 5 1   and  7 5 3
4 3 8        6 1 8
```

These are reflections of each other across the main (top-left to bottom-right) diagonal — the one symmetry of the square that fixes both the top-left cell and the center.

So the strictly correct answer is: **no single grid is the unique solution.** The solution is unique only *up to transposition*. This is consistent with the classical fact that the 3×3 magic square (the Lo Shu) is unique up to the 8 symmetries of the square: fixing the center (automatic) and pinning one corner to 2 cuts the 8 symmetric variants down to 2, not 1. To force a genuinely unique grid, one more constraint would be needed (e.g. "the top-middle cell is 7"). Given the problem demands one grid, Solution 1 above serves as the exhibited answer, with the proof showing its mirror image is the only other possibility.
