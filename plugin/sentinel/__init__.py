# -*- coding: utf-8 -*-
"""Sentinel package bootstrap."""

PLUGIN_VERSION = "1.15.0"
PLUGIN_NAME = f"Sentinel v{PLUGIN_VERSION}"

from . import common

__all__ = ["PLUGIN_VERSION", "PLUGIN_NAME", "common"]
