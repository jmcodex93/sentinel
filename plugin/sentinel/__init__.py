# -*- coding: utf-8 -*-
"""Sentinel package bootstrap."""

PLUGIN_VERSION = "1.23.1"
PLUGIN_NAME = f"Sentinel v{PLUGIN_VERSION}"

from . import common

__all__ = ["PLUGIN_VERSION", "PLUGIN_NAME", "common"]
