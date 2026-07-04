# -*- coding: utf-8 -*-
"""Runtime QC cache."""

import time

from .constants import CACHE_DURATION


class CheckCache:
    def __init__(self):
        self.cache = {}
        self.last_update = 0
        self.doc_id = None
        self.ancestor_vis_cache = {}  # Persistent ancestor visibility cache

    def get(self, doc, key):
        doc_id = id(doc)
        now = time.time()

        if (self.doc_id == doc_id and
            key in self.cache and
            now - self.last_update < CACHE_DURATION):
            return self.cache[key]
        return None

    def set(self, doc, key, value):
        self.doc_id = id(doc)
        self.cache[key] = value
        self.last_update = time.time()

    def get_ancestor_visibility(self, obj):
        """Get cached ancestor visibility or calculate and cache"""
        obj_id = id(obj)
        if obj_id in self.ancestor_vis_cache:
            return self.ancestor_vis_cache[obj_id]
        return None

    def set_ancestor_visibility(self, obj, vis_tuple):
        """Cache ancestor visibility for object"""
        obj_id = id(obj)
        self.ancestor_vis_cache[obj_id] = vis_tuple

    def clear(self):
        self.cache.clear()
        self.ancestor_vis_cache.clear()
        self.doc_id = None


# Global cache instance
check_cache = CheckCache()
