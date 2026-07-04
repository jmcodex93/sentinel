def test_loaded_plugin_uses_package_check_cache_singleton(sentinel_module):
    from sentinel.common.cache import check_cache

    assert sentinel_module.check_cache is check_cache
