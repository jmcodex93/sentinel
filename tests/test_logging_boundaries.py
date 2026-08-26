"""Structured logging at Cinema 4D adapter boundaries."""

from types import SimpleNamespace


def test_guarded_block_logs_component_and_block(sentinel_module, monkeypatch):
    from sentinel.ui import panel_ops

    calls = []
    monkeypatch.setattr(
        panel_ops,
        "log_exception",
        lambda event, component, exc, **fields: calls.append(
            (event, component, type(exc).__name__, fields)
        ),
        raising=False,
    )

    def broken(_doc):
        raise ValueError("bad card")

    assert panel_ops._guarded_block("assets", broken, object()) is None
    assert calls == [
        ("panel.block_failed", "panel.overview", "ValueError", {"block": "assets"})
    ]


def test_bootstrap_keeps_all_six_registration_ids(sentinel_module, monkeypatch):
    module = sentinel_module
    registered = []

    def record(*args, **kwargs):
        registered.append(kwargs["id"])
        return True

    monkeypatch.setattr(module.plugins, "RegisterCommandPlugin", record)
    monkeypatch.setattr(module.plugins, "RegisterTagPlugin", record)
    monkeypatch.setattr(module.plugins, "RegisterMessagePlugin", record)
    monkeypatch.setattr(module, "_SENTINEL_FRAME_TAG_AVAILABLE", True)
    monkeypatch.setattr(module, "_SENTINEL_PIN_TAG_AVAILABLE", True)
    monkeypatch.setattr(module, "_SENTINEL_VARIANT_TAG_AVAILABLE", True)
    monkeypatch.setattr(module, "SentinelFrameTag", object)
    monkeypatch.setattr(module, "SentinelPinTag", object)
    monkeypatch.setattr(module, "SentinelVariantsTag", object)
    monkeypatch.setattr(
        module,
        "_frame_sync",
        SimpleNamespace(PLUGIN_ID=2099077, FrameSyncMessageData=lambda: object()),
    )

    assert module.Register() is True
    assert set(registered) == {
        2099073,
        2099075,
        2099076,
        2099077,
        2099078,
        2099079,
    }
