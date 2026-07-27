"""Weight trend calculations using moving averages."""

from __future__ import annotations

import pandas as pd


def attach_weight_trends(df: pd.DataFrame) -> pd.DataFrame:
    """Add 7d/14d averages, day-over-day change, and weekly trend rate."""
    out = df.copy()
    if "morning_weight_kg" not in out.columns:
        out["weight_7d_average"] = None
        out["weight_14d_average"] = None
        out["weight_trend_kg_per_week"] = None
        out["weight_change_from_yesterday_kg"] = None
        return out

    weights = out["morning_weight_kg"].astype(float)
    out["weight_7d_average"] = weights.rolling(window=7, min_periods=3).mean()
    out["weight_14d_average"] = weights.rolling(window=14, min_periods=5).mean()
    out["weight_change_from_yesterday_kg"] = weights.diff()

    # Approximate weekly rate from the slope of the 7-day average over ~7 days.
    # (today_7d - 7_days_ago_7d) ≈ kg/week when both values exist.
    seven = out["weight_7d_average"]
    out["weight_trend_kg_per_week"] = seven - seven.shift(7)

    # Fallback when we don't yet have a full week of 7d averages:
    # scale the change over available points to a weekly rate.
    fallback = seven - seven.shift(3)
    out["weight_trend_kg_per_week"] = out["weight_trend_kg_per_week"].fillna(fallback * (7 / 3))

    return out
