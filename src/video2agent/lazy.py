from __future__ import annotations

import importlib
from typing import Any, Callable


class LazyModule:
    """Import a heavy module only when one of its attributes is first used."""

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._module: Any = None

    def _load(self) -> Any:
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


def lazy_call(module_name: str, function_name: str) -> Callable[..., Any]:
    """A module-level callable that imports its module only at call time.

    Keeping a real function object at module scope preserves unittest.mock patch
    seams: patch('video2agent.pipeline.extract_frame') still replaces the name the
    implementation actually calls.
    """

    def call(*args: Any, **kwargs: Any) -> Any:
        module = importlib.import_module(module_name)
        return getattr(module, function_name)(*args, **kwargs)

    call.__name__ = function_name
    call.__qualname__ = function_name
    return call
