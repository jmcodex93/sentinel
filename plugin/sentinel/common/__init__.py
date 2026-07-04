# -*- coding: utf-8 -*-
"""Common Sentinel utilities shared by the plugin bootstrap."""

__all__ = ["cache", "constants", "helpers", "settings"]


def __getattr__(name):
    if name in __all__:
        from importlib import import_module

        return import_module(f"{__name__}.{name}")
    raise AttributeError(name)
