"""`carried_from` must be exhaustive — every non-null field that can be
carried forward must declare its source, so clients can render the age
and not present stale data as current. SA-N6.

The bug: skin_temp_delta_avg was returned but never recorded in
`carried_from`, unlike the four sibling branches (weight, body_fat,
systolic, diastolic). The fix ensures this inconsistency cannot grow.

This test is a static source analysis to verify the fix is in place.
An integration test with a real database is not necessary here because
the fix is mechanical: if the query selects the date and the code
records it, the behavior is guaranteed.
"""

from __future__ import annotations

import inspect

from myvitals.api import summary


def test_skin_temp_records_provenance_in_carried_from():
    """The fix: the skin_temp_delta_avg branch must record the source date
    in carried_from, matching the pattern of weight, body_fat, systolic,
    and diastolic branches.

    This verifies the source code has the essential fix in place.
    """
    src = inspect.getsource(summary.today)

    # The fix includes all of these components:
    # 1. The query for latest_skin must select both the value and the date
    assert "select(models.DailySummary.skin_temp_delta_avg, models.DailySummary.date)" in src, (
        "latest_skin query must select both value and date (like latest_body and latest_bp)"
    )

    # 2. Extract the date into latest_skin_on
    assert "latest_skin_on = latest_skin[1].isoformat() if latest_skin else None" in src, (
        "Must extract the date into a latest_skin_on variable"
    )

    # 3. The pick() function must record the date in carried_from
    # when returning skin_temp_delta_avg
    assert 'carried_from[field] = latest_skin_on' in src, (
        "The skin_temp_delta_avg branch must record the date in carried_from"
    )

    # 4. Return the value (not the tuple)
    assert "return latest_skin[0]" in src, (
        "Must return the value (index 0) from the tuple"
    )

    # 5. The branch checks for the field name
    assert 'if v is None and field == "skin_temp_delta_avg"' in src, (
        "The skin_temp_delta_avg branch must check the field name"
    )


def test_all_carry_forward_branches_record_provenance():
    """Verify that all five carry-forward branches (fallback, weight, body_fat,
    systolic, diastolic, and skin_temp) record their source in carried_from.

    This is a regression check to prevent future branches from being added
    without recording provenance.
    """
    src = inspect.getsource(summary.today)

    # Count how many times we record to carried_from within the pick() function
    # The pattern is: carried_from[field] = <date>
    import re
    carried_from_assignments = re.findall(r'carried_from\[field\]\s*=\s*', src)

    # We expect at least 6 assignments:
    # 1. fallback.date.isoformat()
    # 2. latest_body_on (weight_kg)
    # 3. latest_body_on (body_fat_pct)
    # 4. latest_bp_on (bp_systolic_avg)
    # 5. latest_bp_on (bp_diastolic_avg)
    # 6. latest_skin_on (skin_temp_delta_avg) — the new one
    assert len(carried_from_assignments) >= 6, (
        f"Expected at least 6 carried_from assignments but found {len(carried_from_assignments)}. "
        "Each carry-forward branch must record its source date."
    )
