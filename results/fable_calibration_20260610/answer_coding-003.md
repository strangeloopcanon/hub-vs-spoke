# Refactored `process_sales_data`

The original function mixes four concerns in one loop: validating raw records, computing discounts, building result rows, and aggregating totals. The refactor below separates each concern into a small, single-purpose function while preserving the exact observable behavior.

```python
"""Sales data processing: validate raw records, apply tiered discounts, and summarize revenue."""

from typing import Any, Optional

# Discount tiers as (minimum_quantity, discount_rate), checked in order.
DISCOUNT_TIERS = [
    (100, 0.15),
    (50, 0.10),
    (10, 0.05),
]

BULK_QUANTITY_THRESHOLD = 50

REQUIRED_FIELDS = ("product", "quantity", "price")


def parse_record(record: Any) -> Optional[tuple[Any, int, float]]:
    """Validate and parse a raw record.

    Returns a (product, quantity, price) tuple, or None if the record is
    malformed: not a dict, missing required fields, non-numeric quantity or
    price, non-positive quantity, or negative price.
    """
    if not isinstance(record, dict):
        return None
    if any(field not in record for field in REQUIRED_FIELDS):
        return None

    try:
        quantity = int(record["quantity"])
        price = float(record["price"])
    except (ValueError, TypeError):
        return None

    if quantity <= 0 or price < 0:
        return None

    return record["product"], quantity, price


def discount_rate_for_quantity(quantity: int) -> float:
    """Return the discount rate for a given order quantity."""
    for min_quantity, rate in DISCOUNT_TIERS:
        if quantity >= min_quantity:
            return rate
    return 0.0


def categorize_quantity(quantity: int) -> str:
    """Classify an order as 'bulk' or 'standard' based on quantity."""
    return "bulk" if quantity >= BULK_QUANTITY_THRESHOLD else "standard"


def build_line_item(product: Any, quantity: int, price: float) -> tuple[dict, float]:
    """Compute revenue figures for a single valid sales record.

    Returns the output row plus the unrounded net revenue, which the caller
    needs for an exact running total (the row's 'net_revenue' is rounded for
    display).
    """
    gross_revenue = quantity * price
    discount = discount_rate_for_quantity(quantity)
    net_revenue = gross_revenue * (1 - discount)
    item = {
        "product": product,
        "quantity": quantity,
        "unit_price": price,
        "gross_revenue": gross_revenue,
        "discount_pct": discount,
        "net_revenue": round(net_revenue, 2),
        "category": categorize_quantity(quantity),
    }
    return item, net_revenue


def process_sales_data(records) -> dict:
    """Process raw sales records into a summary report.

    Invalid records are counted but skipped. Valid records are enriched with
    discount and revenue figures, sorted by net revenue (highest first), and
    totalled.
    """
    items = []
    total_revenue = 0.0
    error_count = 0

    for record in records:
        parsed = parse_record(record)
        if parsed is None:
            error_count += 1
            continue

        item, net_revenue = build_line_item(*parsed)
        total_revenue += net_revenue
        items.append(item)

    items.sort(key=lambda item: item["net_revenue"], reverse=True)

    return {
        "items": items,
        "total_revenue": round(total_revenue, 2),
        "record_count": len(items),
        "error_count": error_count,
    }
```

## What changed and why

- **`parse_record`** centralizes all validation (type check, required fields, numeric coercion, range checks) and returns `None` for any invalid record, so the main loop has a single rejection path that mirrors the original's four `continue` branches.
- **`discount_rate_for_quantity`** replaces the `if/elif` chain with a declarative `DISCOUNT_TIERS` table, making the tier thresholds easy to read and modify in one place.
- **`build_line_item`** owns the construction of one output row, keeping field names and rounding rules together. It also returns the unrounded net revenue so the running total stays exact.
- **`process_sales_data`** is now a short orchestrator: parse, build, accumulate, sort, summarize.

## Behavior preserved

- Same validation rules and the same `error_count` semantics (each invalid record counts once, whatever the reason).
- `total_revenue` is accumulated from **unrounded** per-item net revenue and rounded only once at the end, exactly as before — per-item `net_revenue` is rounded to 2 decimals independently, so the two can legitimately differ by a cent.
- Sorting is by the rounded `net_revenue` descending, using Python's stable sort, so tie ordering matches the original.
- The returned dict has identical keys, value types, and values for any input.
