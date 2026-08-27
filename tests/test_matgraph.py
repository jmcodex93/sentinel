"""Pure-engine tests for ``sentinel.matgraph`` (v1.38, Task 1).

No ``import c4d`` needed for these — matgraph.py is pure. The one
exception is the table cross-check test, which imports
``sentinel.matwire_c4d`` (module-scope ``import c4d``) and therefore uses
the ``sentinel_module`` fake-c4d harness fixture + a lazy import inside
the test, mirroring ``tests/test_standard_ops.py``."""

from sentinel.matgraph import (
    CS_RAW,
    CS_SRGB,
    PASS_THROUGH_ASSETS,
    PORT_TO_CHANNEL,
    audit_colorspaces,
    find_dead_nodes,
    infer_channel,
)


# ---------------------------------------------------------------------
# infer_channel
# ---------------------------------------------------------------------

def test_infer_channel_by_name_only():
    channel, source = infer_channel("rock_roughness.png", None)
    assert channel == "roughness"
    assert source == "name"


def test_infer_channel_port_only_unrecognizable_filename():
    channel, source = infer_channel(
        "textura_final_v3.png",
        "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.refl_roughness")
    assert channel == "roughness"
    assert source == "port"


def test_infer_channel_both_agree():
    channel, source = infer_channel(
        "rock_basecolor.png",
        "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.base_color")
    assert channel == "basecolor"
    assert source == "both"


def test_infer_channel_name_vs_port_conflict():
    channel, source = infer_channel(
        "rock_gloss.png",
        "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.refl_roughness")
    assert channel is None
    assert source == "conflict"


def test_infer_channel_no_signal_is_unknown():
    channel, source = infer_channel("textura_final_v3.png", None)
    assert channel is None
    assert source is None


def test_infer_channel_orm_packed_name():
    channel, _source = infer_channel("metal_ORM.png", None)
    assert channel == "packed_orm"


def test_infer_channel_normal_via_bumpmap_input_port():
    channel, source = infer_channel(
        "textura_final_v3.png",
        "com.redshift3d.redshift4c4d.nodes.core.bumpmap.input")
    assert channel == "normal"
    assert source == "port"


def test_infer_channel_height_via_displacement_texmap_port():
    channel, source = infer_channel(
        "textura_final_v3.png",
        "com.redshift3d.redshift4c4d.nodes.core.displacement.texmap")
    assert channel == "height"
    assert source == "port"


def test_infer_channel_base_metalness_not_confused_with_metalness_key():
    # "base_metalness" (openpbr) ends with "metalness" (standard's key) —
    # the longest-suffix match must not collapse them onto the wrong key
    # (both map to the same channel here, but the mechanism is what's
    # under test: it must pick the longer, more specific key).
    channel, source = infer_channel(
        "textura_final_v3.png",
        "com.redshift3d.redshift4c4d.nodes.core.openpbrmaterial.base_metalness")
    assert channel == "metalness"
    assert source == "port"


# ---------------------------------------------------------------------
# audit_colorspaces
# ---------------------------------------------------------------------

def test_audit_mismatch_srgb_on_roughness():
    entries = [{"material": "m1", "file": "rock_roughness.png",
                "assigned": CS_SRGB, "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["verdict"] == "mismatch"
    assert verdict["channel"] == "roughness"
    assert verdict["expected"] == CS_RAW


def test_audit_mismatch_raw_on_basecolor():
    entries = [{"material": "m1", "file": "rock_basecolor.png",
                "assigned": CS_RAW, "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["verdict"] == "mismatch"
    assert verdict["channel"] == "basecolor"
    assert verdict["expected"] == CS_SRGB


def test_audit_ok_exact():
    entries = [{"material": "m1", "file": "rock_basecolor.png",
                "assigned": CS_SRGB, "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["verdict"] == "ok"
    assert verdict["expected"] == CS_SRGB


def test_audit_auto_is_unverified_even_when_channel_known():
    entries = [{"material": "m1", "file": "rock_roughness.png",
                "assigned": None, "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    # Channel IS inferable by name — but assigned=None (auto) must
    # unconditionally win as auto_unverified, never mismatch.
    assert verdict["channel"] == "roughness"
    assert verdict["verdict"] == "auto_unverified"


def test_audit_foreign_colorspace_string():
    entries = [{"material": "m1", "file": "rock_roughness.png",
                "assigned": "some_custom_ocio_space", "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["verdict"] == "foreign_cs"


def test_audit_conflict_is_info_not_a_judgment():
    entries = [{"material": "m1", "file": "rock_gloss.png",
                "assigned": CS_SRGB,
                "dest_port": ("com.redshift3d.redshift4c4d.nodes.core."
                              "standardmaterial.refl_roughness")}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["verdict"] == "conflict"
    assert verdict["channel"] is None
    assert verdict["expected"] is None


def test_audit_unknown_no_signal_is_silent():
    entries = [{"material": "m1", "file": "textura_final_v3.png",
                "assigned": CS_SRGB, "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["verdict"] == "unknown"


def test_audit_orm_packed_expects_raw():
    entries = [{"material": "m1", "file": "metal_ORM.png",
                "assigned": CS_SRGB, "dest_port": None}]
    [verdict] = audit_colorspaces(entries)
    assert verdict["channel"] == "packed_orm"
    assert verdict["expected"] == CS_RAW
    assert verdict["verdict"] == "mismatch"


# ---------------------------------------------------------------------
# find_dead_nodes
# ---------------------------------------------------------------------

def test_find_dead_nodes_live_chain_alive():
    # sampler -> cc -> base_color (root)
    nodes = {"sampler", "cc", "output"}
    edges = [("sampler", "cc"), ("cc", "output")]
    dead = find_dead_nodes(nodes, edges, root_ids={"output"}, sink_ids=set())
    assert dead == set()


def test_find_dead_nodes_wired_island_is_dead():
    # island: a <-> b, wired to each other but never reaching the root.
    nodes = {"sampler", "output", "island_a", "island_b"}
    edges = [("sampler", "output"), ("island_a", "island_b"),
             ("island_b", "island_a")]
    dead = find_dead_nodes(nodes, edges, root_ids={"output"}, sink_ids=set())
    assert dead == {"island_a", "island_b"}


def test_find_dead_nodes_displacement_root_branch_alive():
    nodes = {"height_sampler", "displacement", "surface_root"}
    edges = [("height_sampler", "displacement")]
    dead = find_dead_nodes(nodes, edges,
                            root_ids={"surface_root", "displacement"},
                            sink_ids=set())
    assert dead == set()


def test_find_dead_nodes_aov_sink_upstream_alive():
    # A branch that reaches ONLY an AOV sink (never the Output root) must
    # still be alive — this is what the "seed from roots only" mutation
    # (ignoring sinks) would break.
    nodes = {"sampler", "aov_store", "output"}
    edges = [("sampler", "aov_store")]
    dead = find_dead_nodes(nodes, edges, root_ids={"output"},
                            sink_ids={"aov_store"})
    assert dead == set()


def test_find_dead_nodes_empty_graph_is_empty_set():
    assert find_dead_nodes(set(), [], root_ids=set(), sink_ids=set()) == set()


def test_find_dead_nodes_disconnected_non_root_non_sink_is_dead():
    nodes = {"lonely", "output"}
    dead = find_dead_nodes(nodes, [], root_ids={"output"}, sink_ids=set())
    assert dead == {"lonely"}


# ---------------------------------------------------------------------
# Table cross-check — drift in matwire_c4d's port tables must break this.
# ---------------------------------------------------------------------

def test_port_to_channel_matches_matwire_c4d_tables(sentinel_module):
    from sentinel import matwire_c4d

    # Every PORT_TO_CHANNEL key that names a BRDF port (i.e. is a bare
    # port name appearing in BRDF_PORTS' values) must belong to the
    # channel->port table of AT LEAST one BRDF type, and map to the same
    # channel matwire_c4d associates it with.
    # matwire_c4d.BRDF_PORTS' dict keys are its OWN slot names, not always
    # matwire canonical channel names verbatim — "emission_color" is the
    # slot that receives the "emission" channel's texture (the sibling
    # slot "emission_amount" is a float constant, never a texture
    # destination). Translate slot name -> canonical channel here, the
    # same translation ``build_description`` performs via ``path(...)``.
    slot_to_channel = {"emission_color": "emission"}
    all_brdf_ports = set()
    for brdf_key, ports in matwire_c4d.BRDF_PORTS.items():
        for slot, port_name in ports.items():
            if slot in ("emission_amount", "bump"):
                # emission_amount is a float constant, never a texture
                # destination; "bump" is the BRDF's OWN bump-input port,
                # which a sampler never connects to directly (see
                # matgraph.PORT_TO_CHANNEL's docstring) — deliberately
                # excluded from the inverse table.
                continue
            channel = slot_to_channel.get(slot, slot)
            all_brdf_ports.add(port_name)
            assert port_name in PORT_TO_CHANNEL, (
                f"matwire_c4d BRDF port {port_name!r} ({brdf_key}/{slot}) "
                "is not represented in matgraph.PORT_TO_CHANNEL")
            # matwire_c4d's channel names ("basecolor", "roughness", ...)
            # match matgraph's canonical channel names 1:1 for these keys.
            assert PORT_TO_CHANNEL[port_name] == channel

    # Inverse direction: every PORT_TO_CHANNEL key that LOOKS like a bare
    # BRDF port name (i.e. not one of the two utility keys) must actually
    # be wired somewhere in matwire_c4d's tables — drift the other way
    # (a stale key nobody wires any more) must also break this test.
    utility_keys = {"bumpmap.input", "displacement.texmap"}
    for key in PORT_TO_CHANNEL:
        if key in utility_keys:
            continue
        assert key in all_brdf_ports, (
            f"matgraph.PORT_TO_CHANNEL key {key!r} does not correspond to "
            "any port matwire_c4d actually wires")

    # The two utility ports are exactly the ones matwire_c4d writes to
    # directly with a texture sampler (bumpmap.input for normal maps,
    # displacement.texmap for height) — spot check their node ids exist.
    assert (matwire_c4d._RS_CORE + "bumpmap.input").endswith("bumpmap.input")
    assert (matwire_c4d._RS_CORE + "displacement.texmap").endswith(
        "displacement.texmap")


def test_pass_through_assets_are_the_matwire_interposed_utilities():
    # Sanity: every entry is a plausible RS asset-id substring (lowercase,
    # no dots — these are matched as substrings of a full asset id).
    for asset in PASS_THROUGH_ASSETS:
        assert asset == asset.lower()
        assert "." not in asset
