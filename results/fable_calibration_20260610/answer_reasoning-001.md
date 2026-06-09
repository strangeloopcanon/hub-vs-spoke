# Solution

## Setup

The bag contains 5 red, 4 blue, and 3 green marbles — 12 marbles total. We draw 4 without replacement.

Total number of equally likely draws:

$$\binom{12}{4} = \frac{12 \cdot 11 \cdot 10 \cdot 9}{4!} = 495$$

## Counting favourable outcomes

We need **exactly 2 red** marbles AND **at least 1 green** marble.

Fix exactly 2 red marbles: $\binom{5}{2} = 10$ ways.

The remaining 2 marbles must come from the 7 non-red marbles (4 blue + 3 green), and must include at least 1 green. Split by the number of green marbles $g$:

**Case $g = 1$:** 1 green and 1 blue:
$$\binom{3}{1}\binom{4}{1} = 3 \cdot 4 = 12$$

**Case $g = 2$:** 2 green and 0 blue:
$$\binom{3}{2}\binom{4}{0} = 3 \cdot 1 = 3$$

So the non-red pair can be chosen in $12 + 3 = 15$ ways.

(Check by complement: all pairs from the 7 non-red marbles minus all-blue pairs: $\binom{7}{2} - \binom{4}{2} = 21 - 6 = 15$. ✓)

Favourable outcomes:
$$\binom{5}{2} \times 15 = 10 \times 15 = 150$$

## Probability

$$P = \frac{150}{495}$$

Simplify: $\gcd(150, 495) = 15$, so

$$P = \frac{150 \div 15}{495 \div 15} = \frac{10}{33}$$

## Answer

$$\boxed{\dfrac{10}{33}}$$
