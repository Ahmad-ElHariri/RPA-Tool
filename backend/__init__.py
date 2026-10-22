"""Browser automation infrastructure and compatibility for the frozen legacy module."""

import sys
from importlib import import_module

# The legacy source keeps its original lowercase imports. Share the same modules
# so it uses the current registry and settings without editing that source file.
sys.modules.setdefault("Backend", sys.modules[__name__])
sys.modules.setdefault("backend", sys.modules[__name__])
for _name in ("config", "airtable_actions"):
    _module = import_module(f"Backend.{_name}")
    sys.modules[f"backend.{_name}"] = _module
