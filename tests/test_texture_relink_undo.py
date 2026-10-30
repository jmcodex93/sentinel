# -*- coding: utf-8 -*-
"""Undo contract of the node-graph relink writer (W8, Windows round 7).

Measured live (C4D 2026.304, 2026-10-30): one relink batch writes N ports in
N transactions inside the caller's StartUndo/EndUndo. With ``UNDO_MODE.ADD``
each transaction adds its own entry — Undo reverts them all, but Redo
replays only the FIRST (3 maps in one material: redo 1/3; two materials
grouped per graph: redo 3/6). With ``UNDO_MODE.NONE`` the transaction
registers nothing and the material snapshot ``AddUndo(UNDOTYPE_CHANGE,
host)`` taken before each write carries undo AND redo (redo 6/6, one step).
"""
import sys
import types

import pytest


class _DataDictionary(dict):
    def Set(self, key, value):
        self[key] = value


class _Transaction:
    def __init__(self, log, user_data):
        self.log = log
        self.user_data = user_data

    def __enter__(self):
        self.log.append(("begin", dict(self.user_data)))
        return self

    def __exit__(self, *exc):
        return False

    def Commit(self):
        self.log.append(("commit",))


class _Graph:
    def __init__(self, log):
        self.log = log

    def BeginTransaction(self, user_data):
        return _Transaction(self.log, user_data)


class _Port:
    def __init__(self, log):
        self.log = log

    def SetPortValue(self, value):
        self.log.append(("set", value))


class _Doc:
    def __init__(self, log):
        self.log = log

    def AddUndo(self, kind, node):
        self.log.append(("AddUndo", kind, node))


@pytest.fixture
def fake_maxon(monkeypatch):
    nodes = types.SimpleNamespace(
        UndoMode="undo-mode",
        UNDO_MODE=types.SimpleNamespace(NONE="none", ADD="add", START="start"),
    )
    maxon = types.SimpleNamespace(
        Url=lambda path: ("url", path),
        DataDictionary=_DataDictionary,
        nodes=nodes,
    )
    monkeypatch.setitem(sys.modules, "maxon", maxon)
    return maxon


@pytest.mark.parametrize("source_type", ["rs_node", "arnold_node"])
def test_node_relink_snapshots_the_material_and_adds_no_undo_of_its_own(
        sentinel_module, fake_maxon, monkeypatch, source_type):
    from sentinel import textures
    monkeypatch.setattr(textures, "MAXON_AVAILABLE", True)
    # Whichever fake c4d textures bound first (test order) — pin the constant.
    monkeypatch.setattr(textures.c4d, "UNDOTYPE_CHANGE", "undo-change", raising=False)
    log = []
    host = object()
    record = {"source_type": source_type, "host": host,
              "context": {"port": _Port(log), "graph": _Graph(log)}}

    assert textures.apply_texture_path_change(record, "tex/rock.<UDIM>.png", doc=_Doc(log)) is True

    assert log == [
        ("AddUndo", "undo-change", host),
        ("begin", {"undo-mode": "none"}),
        ("set", ("url", "tex/rock.<UDIM>.png")),
        ("commit",),
    ]
