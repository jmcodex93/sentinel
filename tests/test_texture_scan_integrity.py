# -*- coding: utf-8 -*-
"""Block-2 texture-scan integrity: record cap + truncation metadata.

scan_all_texture_paths needs a live C4D document, so these tests exercise
the contract at the seams that ARE pure: the module-level meta contract,
and the truncation CheckResult builder in the QC check wrapper.
"""
import pytest


# -- Module meta contract (textures.py) -------------------------------------

class TestScanMetaContract:
    def test_meta_keys_shape(self, sentinel_module):
        from sentinel.textures import get_last_scan_meta
# -- Module meta contract (textures.py) -------------------------------------

class TestScanMetaContract:
    def test_meta_keys_shape(self):
        from sentinel.textures import get_last_scan_meta
        meta = get_last_scan_meta()
        assert set(meta.keys()) == {
            "truncated", "errors", "materials_scanned", "objects_scanned"}
        assert isinstance(meta["truncated"], bool)
        assert isinstance(meta["errors"], list)

    def test_meta_is_a_copy(self):
        from sentinel.textures import get_last_scan_meta
        meta = get_last_scan_meta()
        meta["truncated"] = True  # mutating the copy must not stick
        assert get_last_scan_meta()["truncated"] is False

    def test_record_cap_exists_and_is_positive(self):
        from sentinel import textures
        assert textures._SCAN_RECORD_CAP >= 100


# -- Truncation result builder (checks/assets.py) ---------------------------

class TestTruncationResult:
    # checks/assets imports qc.results which imports the real c4d module —
    # request sentinel_module first so conftest installs the fake c4d.
    def _build(self):
        from sentinel.checks.assets import _truncation_result
        return _truncation_result()

    def test_has_violation(self, sentinel_module):
        result = self._build()
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert violation.identity["type"] == "texture_scan_truncated"

    def test_metadata_carries_flag(self, sentinel_module):
        result = self._build()
        assert result.metadata.get("scan_truncated") is True
        assert "scan_meta" in result.metadata

    def test_legacy_item_marks_truncation(self, sentinel_module):
        result = self._build()
        legacy = result.to_legacy()
        assert legacy and legacy[0]["issue"] == "scan_truncated"
