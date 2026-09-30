# -*- coding: utf-8 -*-
"""Tests for QC check #13 (``sentinel.checks.matgraph.check_rs_colorspace``)
and its fix (``sentinel.fixes.fix_rs_colorspace``).

Reuses the fake maxon/graph harness from ``test_matgraph_c4d.py`` (same
directory, importable without a package — see ``test_hub_ops.py``'s
``from test_imagemeta import make_png`` for the existing precedent in this
repo) rather than re-modeling the RS node-graph surface a second time.
"""

import os

import pytest

from test_matgraph_c4d import (
    FakeDoc,
    FakeGraph,
    FakeMaterial,
    _FakeMaxon,
    _add_brdf,
    _add_output,
    _add_sampler,
    _in_port,
    _out_port,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _FakeRulesContext:
    """A no-op rules context — this check has no ruleset params of its
    own, so a bare stand-in is enough everywhere the ordering itself isn't
    under test."""
    params = {}


@pytest.fixture
def matgraph_check(sentinel_module, monkeypatch):
    """Patches both ``maxon`` surfaces the check's import chain touches:
    ``sentinel.matgraph_c4d`` (the adapter ``collect()``/``write_colorspaces``
    live in) and, transitively, ``sentinel.checks.matgraph`` /
    ``sentinel.fixes`` which import functions FROM that module — patching
    the module's own ``maxon`` global is what makes those functions (bound
    to that module's globals) see the fake, regardless of how the caller
    imported them (mirrors ``test_matgraph_c4d.py``'s own ``matgraph_c4d``
    fixture)."""
    from sentinel import matgraph_c4d
    from sentinel.checks import matgraph as check_module
    from sentinel.common.cache import check_cache

    monkeypatch.setattr(matgraph_c4d, "maxon", _FakeMaxon)
    check_cache.clear()
    return check_module


def _mismatch_auto_foreign_graph():
    """One material, three samplers:

    - ``sampler_mismatch``: basecolor filename (expects SRGB) wired to
      ``base_color``, but assigned RAW -> ``mismatch``.
    - ``sampler_auto``: roughness filename wired to ``refl_roughness``,
      assigned ``None`` (unset colorspace port) -> ``auto_unverified``
      unconditionally, even though the channel IS known.
    - ``sampler_foreign``: metalness filename, assigned a string outside
      the known RS vocabulary -> ``foreign_cs``.
    """
    graph = FakeGraph()
    brdf = _add_brdf(graph, "brdf1", ["base_color", "refl_roughness", "metalness"])
    out = _add_output(graph, "out1")
    _out_port(brdf, "outcolor").connect_to(_in_port(out, "surface"))

    mismatch = _add_sampler(graph, "sampler_mismatch", "/tex/wood_basecolor.png",
                            "RS_INPUT_COLORSPACE_RAW")
    _out_port(mismatch, "outcolor").connect_to(_in_port(brdf, "base_color"))

    auto = _add_sampler(graph, "sampler_auto", "/tex/wood_roughness.png", None)
    _out_port(auto, "outcolor").connect_to(_in_port(brdf, "refl_roughness"))

    foreign = _add_sampler(graph, "sampler_foreign", "/tex/wood_metalness.png",
                           "OCIO_custom_space")
    _out_port(foreign, "outcolor").connect_to(_in_port(brdf, "metalness"))

    return graph


def _write_rules(directory, payload, mtime=None):
    import json

    path = directory / "sentinel_rules.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class FakeDocWithPath(FakeDoc):
    """``FakeDoc`` (materials only) that also answers ``GetDocumentPath``,
    so project rules discovery actually runs — mirrors
    ``test_scene_check_results.py``'s own ``FakeDocWithPath``."""

    def __init__(self, doc_path, materials):
        super().__init__(materials)
        self._doc_path = str(doc_path)

    def GetDocumentPath(self):
        return self._doc_path

    def GetDocumentName(self):
        return "shot.c4d"


# ---------------------------------------------------------------------------
# check_rs_colorspace
# ---------------------------------------------------------------------------

class TestCheckRsColorspace:
    def test_counts_only_mismatches_with_full_info_detail(self, matgraph_check):
        graph = _mismatch_auto_foreign_graph()
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())

        # Only the ONE mismatch counts — auto_unverified/foreign_cs never do.
        assert len(result.to_legacy()) == 1
        assert len(result.violations) == 1
        # Info shows the check's WHOLE picture (mismatch + auto + foreign):
        # audit_colorspaces only stays silent on "unknown"/"ok".
        assert len(result.metadata["info"]) == 3
        reasons = {row["reason"] for row in result.metadata["info"]}
        assert reasons == {"mismatch", "auto_unverified", "foreign_cs"}

    def test_mismatch_violation_identity_and_message(self, matgraph_check):
        graph = FakeGraph()
        brdf = _add_brdf(graph, "brdf1", ["base_color"])
        out = _add_output(graph, "out1")
        _out_port(brdf, "outcolor").connect_to(_in_port(out, "surface"))
        sampler = _add_sampler(graph, "sampler1", "/tex/wood_basecolor.png",
                               "RS_INPUT_COLORSPACE_RAW")
        _out_port(sampler, "outcolor").connect_to(_in_port(brdf, "base_color"))
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())

        assert len(result.violations) == 1
        violation = result.violations[0]
        identity = violation["identity"]
        assert identity == {
            "type": "parameter",
            "param": "rs_colorspace",
            "value": "wood_basecolor.png",
            "preset": "wood_mat",
            "field": "basecolor",
        }
        assert violation["message"] == (
            "wood_mat: wood_basecolor.png is RS_INPUT_COLORSPACE_RAW, "
            "basecolor expects RS_INPUT_COLORSPACE_SRGB"
        )

    def test_conflict_and_unknown_never_count(self, matgraph_check):
        """A cross-colorspace name/port disagreement (``conflict``) and a
        sampler with no signal at all (``unknown``) both never count —
        ``unknown`` is also silent (absent from Info; the OTHER two, plus
        an accompanying mismatch, are all that appears there)."""
        graph = FakeGraph()
        brdf = _add_brdf(graph, "brdf1", ["base_color", "specular_roughness"])
        out = _add_output(graph, "out1")
        _out_port(brdf, "outcolor").connect_to(_in_port(out, "surface"))

        # name says basecolor (SRGB), port says roughness (RAW) -> conflict.
        conflict = _add_sampler(graph, "sampler_conflict", "/tex/wood_basecolor.png",
                                "RS_INPUT_COLORSPACE_SRGB")
        _out_port(conflict, "outcolor").connect_to(_in_port(brdf, "specular_roughness"))

        # No recognizable filename, unconnected -> no signal at all -> unknown.
        unknown = _add_sampler(graph, "sampler_unknown", "/tex/mystery_file.png",
                               "RS_INPUT_COLORSPACE_SRGB")

        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())

        assert result.to_legacy() == []
        assert result.violations == []
        reasons = [row["reason"] for row in result.metadata["info"]]
        assert reasons == ["conflict"]

    def test_no_document_and_no_materials_pass_clean(self, matgraph_check):
        doc = FakeDoc([])
        result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
        assert result.to_legacy() == []
        assert result.metadata["info"] == []

    def test_cache_hit_returns_same_structured_result(self, matgraph_check):
        graph = _mismatch_auto_foreign_graph()
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        first = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
        second = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
        assert second is first

    def test_rules_resolved_before_cache_read_reruns_after_ruleset_change(
        self, matgraph_check, tmp_path
    ):
        """The v1.36.5 ordering pin, replicated from
        ``test_scene_check_results.py``'s own render-conflicts version:
        this check has no ruleset params of its own, but resolving the
        rules context BEFORE the cache read is what lets a ruleset EDIT
        (any edit — ``rules.get_active_rules`` clears the WHOLE
        ``check_cache`` when the ruleset file's ``(path, mtime)`` changes)
        invalidate this check's cached row too. Swap the two lines and
        this test fails: the second call would serve the FIRST scene's
        stale cached mismatch count instead of re-auditing the SECOND
        scene's graph.
        """
        from sentinel import rules

        _write_rules(tmp_path, {"standard_fps": 24}, mtime=1_000_000)
        rules.invalidate()

        graph_with_mismatch = _mismatch_auto_foreign_graph()
        mat1 = FakeMaterial("wood_mat", graph=graph_with_mismatch)
        doc1 = FakeDocWithPath(tmp_path / "shot.c4d", [mat1])

        first = matgraph_check.check_rs_colorspace(doc1)
        assert len(first.to_legacy()) == 1

        # Edit the ruleset on disk (content + mtime) — any key works, this
        # check reads none of them; what matters is that the FILE's
        # (path, mtime) identity changes. Deliberately NO ``rules.invalidate()``
        # here: that would wipe the "previous identity" tracking that lets
        # ``get_active_rules`` detect the change on its own by comparing a
        # freshly-read ``os.path.getmtime`` against what it saw last call —
        # calling invalidate() again would make this test pass for the
        # WRONG reason (a full reset) instead of the real one (mtime diff
        # detected because rules were resolved, in order, on both calls).
        _write_rules(tmp_path, {"standard_fps": 30}, mtime=2_000_000)

        # Same document, same id() — mutate its materials to a graph with
        # NO violations, so the assertion below can only pass if the
        # SECOND call actually re-audits instead of serving the FIRST
        # call's cached (1-mismatch) structured result.
        mat2 = FakeMaterial("clean_mat", graph=FakeGraph())
        doc1._materials = [mat2]
        second = matgraph_check.check_rs_colorspace(doc1)

        assert len(second.to_legacy()) == 0


# ---------------------------------------------------------------------------
# fix_rs_colorspace
# ---------------------------------------------------------------------------

class TestFixRsColorspace:
    def test_writes_only_expected_values_via_whitelist_writer(self, matgraph_check):
        from sentinel import fixes

        graph = _mismatch_auto_foreign_graph()
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        result = fixes.fix_rs_colorspace(doc, manage_undo=True)

        assert result == {"written": 1, "materials": 1}
        # The whitelist writer only ever writes CS_SRGB/CS_RAW, and only to
        # the ONE mismatched sampler's colorspace port.
        assert graph.set_port_calls == [
            ("sampler_mismatch", "colorspace", "RS_INPUT_COLORSPACE_SRGB")
        ]

    def test_one_undo_bracket_for_the_whole_batch(self, matgraph_check):
        from sentinel import fixes

        graph = _mismatch_auto_foreign_graph()
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        fixes.fix_rs_colorspace(doc, manage_undo=True)

        assert doc.start_count == 1
        assert doc.end_count == 1

    def test_manage_undo_false_leaves_bracket_to_caller(self, matgraph_check):
        from sentinel import fixes

        graph = _mismatch_auto_foreign_graph()
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        fixes.fix_rs_colorspace(doc, manage_undo=False)

        assert doc.start_count == 0
        assert doc.end_count == 0

    def test_no_mismatches_writes_nothing(self, matgraph_check):
        from sentinel import fixes

        mat = FakeMaterial("clean_mat", graph=FakeGraph())
        doc = FakeDoc([mat])

        result = fixes.fix_rs_colorspace(doc, manage_undo=True)

        assert result == {"written": 0, "materials": 0}

    def test_reruns_audit_fresh_never_trusts_cached_rows(self, matgraph_check):
        """Prime the QC check's cache (at this exact ``id(doc)``) with a
        CLEAN result, then mutate the live graph out-of-band (no cache
        invalidation) to introduce a mismatch. The fix must still find and
        correct it — it re-collects and re-audits itself fresh, per its
        own docstring/the brief, rather than trusting ``check_cache``'s
        now-stale row for this same document."""
        from sentinel import fixes
        from sentinel.checks import matgraph as check_module

        graph = FakeGraph()
        brdf = _add_brdf(graph, "brdf1", ["base_color"])
        out = _add_output(graph, "out1")
        _out_port(brdf, "outcolor").connect_to(_in_port(out, "surface"))
        sampler = _add_sampler(graph, "sampler1", "/tex/wood_basecolor.png",
                               "RS_INPUT_COLORSPACE_SRGB")
        _out_port(sampler, "outcolor").connect_to(_in_port(brdf, "base_color"))
        mat = FakeMaterial("wood_mat", graph=graph)
        doc = FakeDoc([mat])

        primed = check_module.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
        assert primed.to_legacy() == []  # cached as CLEAN at id(doc)

        # Mutate the live graph out-of-band — no check_cache invalidation
        # happens here, so a cache-trusting fix would still see "clean".
        tex0 = next(c for c in sampler.inputs.GetChildren() if c.GetId().endswith("tex0"))
        cs_port = next(c for c in tex0.GetChildren() if c.GetId() == "colorspace")
        cs_port._value = "RS_INPUT_COLORSPACE_RAW"

        result = fixes.fix_rs_colorspace(doc, manage_undo=True)

        assert result == {"written": 1, "materials": 1}
        assert graph.set_port_calls == [
            ("sampler1", "colorspace", "RS_INPUT_COLORSPACE_SRGB")
        ]


# Readiness regression: exercise graph -> check -> score -> reports/gates.
@pytest.mark.parametrize('failure', ['walk', 'get_graph', 'materials', 'collect'])
def test_unreadable_coverage_never_passes_qc_or_gate(matgraph_check, monkeypatch, failure, tmp_path):
    from types import SimpleNamespace
    from sentinel import gate
    from sentinel.qc.score import compute_score
    from sentinel.bridge.reports import qc_report_payload, group_qc_by_severity, top_qc_checks
    from sentinel.bridge.forms import gate_state_payload, gate_can_proceed
    from sentinel.ui.dialogs import gate_dialog_can_proceed
    from sentinel.ui.reports import build_qc_report, build_baseline_artifact_details

    graph = FakeGraph()
    mat = FakeMaterial('unreadable_mat', graph=graph)
    doc = FakeDocWithPath(tmp_path, [mat])
    def unreadable(*args):
        raise RuntimeError('simulated unreadable graph')
    if failure == 'walk':
        graph._view_root.raise_on_get_inner_nodes = True
    elif failure == 'get_graph':
        ref = mat.GetNodeMaterialReference()
        monkeypatch.setattr(ref, 'GetGraph', unreadable)
        monkeypatch.setattr(mat, 'GetNodeMaterialReference', lambda: ref)
    elif failure == 'materials':
        monkeypatch.setattr(doc, 'GetMaterials', unreadable)
    else:
        monkeypatch.setattr(matgraph_check, 'collect', unreadable)
    result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
    assert result.to_legacy() == []
    assert result.violations == []  # Unknown coverage is never baselineable.
    assert len(result.metadata['unverified']) == 1
    assert result.metadata['info'][0]['reason'] == 'scan_unverified'
    assert matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext()) is result
    pair = {'legacy_result': [], 'structured_result': result, 'disabled': False}
    results = {'rs_colorspace': pair}
    invalid = tmp_path / 'invalid_baseline.json'
    invalid.write_text('{invalid', encoding='utf-8')
    for kwargs in ({}, {'baseline_entries': []}, {'baseline_path': str(invalid)},
                   {'baseline_path': str(tmp_path / 'missing.json')}):
        score = compute_score(results, **kwargs)
        assert score['score'] == '12/13'
        assert score['pass'] is False
        assert score['counts']['rs_colorspace'] == 0
        assert score['unverified_counts'] == {'rs_colorspace': 1}
        assert gate.count_new_fails(score) == 1
        assert 'unverified' in ' '.join(gate.build_preflight_issues(score)).lower()
        evaluated = gate.evaluate_gate(score)
        assert evaluated['passed'] is False
        assert evaluated['fixable'] == []
        assert evaluated['blocking'][0]['violations'] == []
        assert evaluated['blocking'][0]['unverified_count'] == 1
        assert gate_can_proceed(evaluated) is False
        assert gate_dialog_can_proceed(evaluated['blocking'], [], {'rs_colorspace': 'baseline'}, 'accepted') is False
        state = gate_state_payload(evaluated)
        assert state['checks'][0]['has_fix'] is False
        assert 'unverified' in state['checks'][0]['label'].lower()
        report = qc_report_payload('shot.c4d', None, score, {'rs_colorspace': result.to_dict()})
        row = next(r for r in report['checks'] if r['id'] == 'rs_colorspace')
        assert row['status'] != 'ok'
        assert row['unverified_count'] == 1
        assert 'unverified' in row['details'][0]['message'].lower()
        group = group_qc_by_severity(report['checks'])['fail'][0]
        assert group['can_fix'] is False
        assert group['accepted_all'] is False
        assert top_qc_checks(report['checks'])[0]['check_id'] == 'rs_colorspace'
        legacy_report = build_qc_report(doc, {}, '', qc_summary=score)
        assert legacy_report['checks']['rs_colorspace']['status'] == 'UNVERIFIED'
        if score.get('schema') == 2:
            assert build_baseline_artifact_details(score)['rs_colorspace']['unverified_count'] == 1
    disabled = SimpleNamespace(params={'checks_enabled': {'rs_colorspace': False}})
    # Explicit disabled pair is also the contract produced by run_all_checks.
    disabled_score = compute_score({'rs_colorspace': dict(pair, disabled=True)}, disabled, baseline_entries=[])
    assert disabled_score['score'] == '12/12'
    assert disabled_score['pass'] is True
    assert disabled_score.get('unverified_counts', {}) == {}
    assert gate.count_new_fails(disabled_score) == 0


@pytest.mark.parametrize('brdf_kind,normal_port', [('standardmaterial', 'bump_input'), ('openpbrmaterial', 'geometry_normal')])
def test_generic_named_sampler_keeps_bump_input_semantics(matgraph_check, brdf_kind, normal_port):
    from test_matgraph_c4d import FakePort
    from sentinel import fixes
    graph = FakeGraph()
    core = 'com.redshift3d.redshift4c4d.nodes.core.'
    brdf = graph.add_node('brdf', core + brdf_kind)
    brdf.inputs.add_child(FakePort(core + brdf_kind + '.' + normal_port, brdf))
    bump = graph.add_node('bump', core + 'bumpmap')
    bump.inputs.add_child(FakePort(core + 'bumpmap.input', bump))
    bump.outputs.add_child(FakePort(core + 'bumpmap.out', bump))
    sampler = _add_sampler(graph, 'sampler', '/tex/texture_123.png', 'RS_INPUT_COLORSPACE_SRGB')
    _out_port(sampler, 'outcolor').connect_to(_in_port(bump, 'input'))
    _out_port(bump, 'out').connect_to(_in_port(brdf, normal_port))
    doc = FakeDoc([FakeMaterial('normal_mat', graph=graph)])
    result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
    assert len(result.violations) == 1
    assert result.to_legacy()[0]['channel'] == 'normal'
    assert result.to_legacy()[0]['expected'] == 'RS_INPUT_COLORSPACE_RAW'
    assert fixes.fix_rs_colorspace(doc) == {'written': 1, 'materials': 1}
    assert graph.set_port_calls == [('sampler', 'colorspace', 'RS_INPUT_COLORSPACE_RAW')]


def test_accepting_known_mismatch_does_not_accept_unreadable_material(matgraph_check):
    from sentinel import baseline, gate
    from sentinel.qc.score import compute_score
    broken = FakeGraph()
    broken._view_root.raise_on_get_inner_nodes = True
    doc = FakeDoc([FakeMaterial('broken', graph=broken),
                   FakeMaterial('known', graph=_mismatch_auto_foreign_graph())])
    result = matgraph_check.check_rs_colorspace(doc, rules_context=_FakeRulesContext())
    acceptance = baseline.entry_from_violation(result.to_dict()['violations'][0], 'Artist', 'Approved')
    assert acceptance is not None
    score = compute_score({'rs_colorspace': {'legacy_result': result.to_legacy(),
                           'structured_result': result}}, baseline_entries=[acceptance])
    assert score['counts']['rs_colorspace'] == 0
    assert score['accepted_counts']['rs_colorspace'] == 1
    assert score['unverified_counts']['rs_colorspace'] == 1
    assert score['score'] == '12/13'
    assert score['pass'] is False
    assert gate.evaluate_gate(score)['blocking'][0]['unverified_count'] == 1


def test_informational_colorspaces_preserve_clean_score_and_metadata(matgraph_check):
    from sentinel.qc.score import compute_score
    graph = _mismatch_auto_foreign_graph()
    sampler = next(n for n in graph.nodes if n.node_id == 'sampler_mismatch')
    tex0 = sampler.inputs.GetChildren()[0]
    next(p for p in tex0.GetChildren() if p.GetId() == 'colorspace')._value = 'RS_INPUT_COLORSPACE_SRGB'
    result = matgraph_check.check_rs_colorspace(FakeDoc([FakeMaterial('info', graph=graph)]),
                                               rules_context=_FakeRulesContext())
    assert result.to_legacy() == []
    assert 'unverified' not in result.metadata
    assert {r['reason'] for r in result.metadata['info']} == {'auto_unverified', 'foreign_cs'}
    score = compute_score({'rs_colorspace': {'legacy_result': [], 'structured_result': result}}, baseline_entries=[])
    assert score['score'] == '13/13'
    assert score['pass'] is True
    assert 'unverified_counts' not in score
