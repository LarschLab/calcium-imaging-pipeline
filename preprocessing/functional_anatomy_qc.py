"""Backward-compatible imports for the renamed drift-analysis module.

New code should import :mod:`preprocessing.drift_analysis`. This file remains
so existing scripts continue to work without modification.
"""

from preprocessing import drift_analysis as _drift_analysis

# Preserve direct imports of helpers that existed before the module was renamed.
# ``__all__`` remains intentionally narrow for wildcard imports, matching the
# previous module, while explicit imports and notebook attribute access continue
# to see the complete historical namespace.
for _name in dir(_drift_analysis):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_drift_analysis, _name)

__all__ = _drift_analysis.__all__

del _name
