# -*- coding: utf-8 -*-
"""RenderView post re-applied to snapshots (sentinel.rvpost) — pure helpers."""
import random

import pytest

from sentinel import rvpost


def cube_text(size, fn, header=""):
    lines = [header, "TITLE \"t\"", "# comment", "LUT_3D_SIZE %d" % size]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                lines.append("%f %f %f" % fn(r / (size - 1), g / (size - 1), b / (size - 1)))
    return "\n".join(lines)


def to8(v):
    return 0 if v <= 0 else 255 if v >= 1 else int(v * 255 + 0.5)


# ── .cube parsing ────────────────────────────────────────────────────────────
def test_parse_cube_reads_size_and_red_fastest_order():
    size, table = rvpost.parse_cube(cube_text(2, lambda r, g, b: (r, g, b)))
    assert size == 2 and len(table) == 8
    assert table[1] == (1.0, 0.0, 0.0) and table[2] == (0.0, 1.0, 0.0) and table[4] == (0.0, 0.0, 1.0)


@pytest.mark.parametrize("text, fragment", [
    ("LUT_1D_SIZE 4\n0 0 0", "1D"),
    ("LUT_3D_SIZE 2\nDOMAIN_MAX 2 2 2\n" + "0 0 0\n" * 8, "domain"),
    ("LUT_3D_SIZE 2\n" + "0 0 0\n" * 7, "expected 8"),
    ("0 0 0", "LUT_3D_SIZE"),
])
def test_parse_cube_rejects_what_it_cannot_apply(text, fragment):
    with pytest.raises(ValueError) as err:
        rvpost.parse_cube(text)
    assert fragment in str(err.value)


# ── curves ───────────────────────────────────────────────────────────────────
RV_CURVE = [(0.0609, 0.0348), (0.3261, 0.3087), (0.7478, 0.7783), (1.0, 1.0)]


def curve_attrs(name, points):
    attrs = {"curve_%s_numPoints" % name: len(points)}
    for i, p in enumerate(points):
        attrs["curve_%s%d" % (name, i)] = p
    return attrs


def test_curve_points_and_identity():
    attrs = curve_attrs("RGB", RV_CURVE)
    assert rvpost.curve_points(attrs, "RGB") == RV_CURVE
    assert not rvpost.is_identity_curve(RV_CURVE)
    assert rvpost.is_identity_curve([(0.0, 0.0), (1.0, 1.0)])
    assert rvpost.curve_points({}, "RGB") == []


def test_spline_passes_through_its_points_and_clamps_outside():
    table = rvpost.spline_table(RV_CURVE)
    k1 = rvpost.CURVE_SAMPLES - 1
    for x, y in RV_CURVE:
        assert abs(table[int(x * k1 + 0.5)] - y * 255) <= 1
    assert table[0] == to8(0.0348)          # below the first point: its value
    assert rvpost.spline_table([(0.0, 0.0), (1.0, 1.0)])[k1 // 2] == to8((k1 // 2) / k1)


# ── plan from the EXR header ────────────────────────────────────────────────
def lut_attrs(folder, **extra):
    attrs = {"Lut Enabled": 1, "LUT File": "Look", "LUT Location": str(folder),
             "Lut Strength": 0.492, "Apply color management before LUT": 1,
             "Convert to log space before applying LUT": 0}
    attrs.update(extra)
    return attrs


def test_plan_loads_the_lut_with_its_strength(tmp_path):
    (tmp_path / "Look.cube").write_text(cube_text(2, lambda r, g, b: (r, g, b)))
    plan = rvpost.post_plan(lut_attrs(tmp_path))
    assert plan["lut"][0] == 2 and plan["strength"] == pytest.approx(0.492)
    assert plan["applied"] == ["LUT Look 49%"] and plan["notes"] == []
    assert rvpost.plan_is_active(plan)


def test_plan_names_a_missing_lut_and_an_unsupported_order(tmp_path):
    assert rvpost.post_plan(lut_attrs(tmp_path))["notes"] == ["LUT Look not found"]
    (tmp_path / "Look.cube").write_text(cube_text(2, lambda r, g, b: (r, g, b)))
    plan = rvpost.post_plan(lut_attrs(tmp_path, **{"Convert to log space before applying LUT": 1}))
    assert plan["lut"] is None and plan["notes"] == ["LUT Look (unsupported order)"]


def test_plan_applies_the_master_curve_and_names_the_rest():
    attrs = {"Color Controls Enabled": 1, "Highlights": 0.2, "Exposure (EV)": 0.5,
             "Bloom Enabled": 1, "Vignetting": 0.3}
    attrs.update(curve_attrs("RGB", RV_CURVE))
    attrs.update(curve_attrs("Red", [(0.0, 0.1), (1.0, 1.0)]))
    plan = rvpost.post_plan(attrs)
    assert plan["curve"] is not None and plan["applied"] == ["RGB curve"]
    assert plan["notes"] == ["red curve", "exposure", "bloom", "vignetting"]
    assert rvpost.describe(plan) == ("RenderView post applied: RGB curve · "
                                     "not reproduced: red curve, exposure, bloom, vignetting")


def test_neutral_post_is_inactive_and_silent():
    attrs = {"Color Controls Enabled": 1, "Highlights": 0.2, "Contrast": 0.0, "Gamma": 1.0,
             "Lut Enabled": 0, "Bloom Enabled": 0}
    attrs.update(curve_attrs("RGB", [(0.0, 0.0), (1.0, 1.0)]))
    plan = rvpost.post_plan(attrs)
    assert not rvpost.plan_is_active(plan) and rvpost.describe(plan) == ""


# ── applying ─────────────────────────────────────────────────────────────────
def reference_trilinear(table, size, r, g, b):
    def at(i, j, k):
        return table[(k * size + j) * size + i]
    x, y, z = (min(max(v, 0.0), 1.0) * (size - 1) for v in (r, g, b))
    i0, j0, k0 = (min(int(v), size - 2) for v in (x, y, z))
    fx, fy, fz = x - i0, y - j0, z - k0
    out = []
    for c in range(3):
        acc = 0.0
        for di, wx in ((0, 1 - fx), (1, fx)):
            for dj, wy in ((0, 1 - fy), (1, fy)):
                for dk, wz in ((0, 1 - fz), (1, fz)):
                    acc += wx * wy * wz * at(i0 + di, j0 + dj, k0 + dk)[c]
        out.append(acc)
    return out


def test_apply_row_matches_a_reference_trilinear_blend():
    rng = random.Random(7)
    size = 5
    table = [(rng.random(), rng.random(), rng.random()) for _ in range(size ** 3)]
    plan = {"lut": (size, table), "strength": 0.492, "curve": None}
    values = [rng.uniform(-0.1, 1.1) for _ in range(300)]
    got = rvpost.apply_row(values, plan)
    for j in range(0, 300, 3):
        r, g, b = values[j:j + 3]
        lut = reference_trilinear(table, size, r, g, b)
        clamped = [min(max(v, 0.0), 1.0) for v in (r, g, b)]
        expected = [to8(c * (1 - 0.492) + l * 0.492) for c, l in zip(clamped, lut)]
        assert list(got[j:j + 3]) == expected


def test_identity_lut_at_full_strength_changes_nothing():
    plan = {"lut": rvpost.parse_cube(cube_text(3, lambda r, g, b: (r, g, b))),
            "strength": 1.0, "curve": None}
    values = [i / 299.0 for i in range(300)]
    assert list(rvpost.apply_row(values, plan)) == [to8(v) for v in values]


def test_curve_only_maps_through_the_table():
    plan = {"lut": None, "strength": 1.0, "curve": rvpost.spline_table(RV_CURVE)}
    out = rvpost.apply_row([0.0, 0.3261, 1.0], plan)
    assert out[0] == to8(0.0348) and abs(out[1] - 0.3087 * 255) <= 1 and out[2] == 255
