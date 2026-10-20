"""
Mini ARK operation circuit breaker.

The kill switch (journal.py) is manual: it stops mutations once a human
notices something's wrong. This module is the automatic counterpart --
it halts an operation based on its OWN size/shape, before a human has
had any chance to notice anything, regardless of what permission tier
authorized it.

An operation being technically permitted is not the same as an
operation being ordinary. This is where "that seems like a lot" gets
enforced in code instead of relying on hope.
"""


class OperationTooLarge(Exception):
    """Raised when an operation's scope exceeds a sane default threshold.
    This is NOT the same as a permission failure -- the operation may be
    fully authorized and still get blocked here for being abnormally
    large, requiring fresh explicit confirmation before proceeding."""
    pass


# Defaults are deliberately conservative. These are meant to catch
# "something is very wrong" (a bad glob, a runaway loop, a
# misinterpreted instruction), not to be a normal ceiling on real work.
DEFAULT_MAX_ITEMS_PER_OPERATION = 200
DEFAULT_MAX_FRACTION_OF_SCOPE = 0.5  # refuse to touch >50% of a directory in one go


def check_operation_magnitude(item_count: int, total_items_in_scope: int = None,
                                max_items: int = DEFAULT_MAX_ITEMS_PER_OPERATION,
                                max_fraction: float = DEFAULT_MAX_FRACTION_OF_SCOPE,
                                operation_label: str = "operation") -> None:
    """
    Call this BEFORE any batch mutating operation actually executes.
    Raises OperationTooLarge if the operation looks abnormal by either
    absolute count or by fraction of the total scope it would affect.

    This check is independent of and in addition to permission tiers.
    A Tier 3 'approved reversible' grant does not exempt an operation
    from this -- authorization and magnitude are separate questions.
    """
    if item_count > max_items:
        raise OperationTooLarge(
            f"{operation_label} would affect {item_count} items, "
            f"exceeding the default ceiling of {max_items}. "
            f"This requires explicit confirmation of the larger scope, "
            f"not just the original permission grant."
        )

    if total_items_in_scope and total_items_in_scope > 0:
        fraction = item_count / total_items_in_scope
        if fraction > max_fraction:
            raise OperationTooLarge(
                f"{operation_label} would affect {item_count} of "
                f"{total_items_in_scope} items ({fraction:.0%} of scope), "
                f"exceeding the default ceiling of {max_fraction:.0%}. "
                f"Touching most of a directory in one operation needs "
                f"fresh explicit confirmation, even if pre-authorized."
            )
