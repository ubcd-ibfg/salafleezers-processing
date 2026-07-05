"""Backward-compatibility shim — signal utilities now live in analysis/filters.py.

All symbols re-exported here so existing imports continue to work.
"""

from salafleezers.analysis.filters import (  # noqa: F401
    bilateral_filter,
    decimate_trace,
    smooth,
    window_filter,
)
