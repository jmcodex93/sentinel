# -*- coding: utf-8 -*-
"""RenderView post effects a snapshot EXR records but does not contain.

A RenderView snapshot stores the clean render; the post settings the artist was
looking at (LUT, colour controls, bloom…) only travel as header attributes, so
RenderView can re-apply them on display. Measured 2026-10-02: two snapshots of
the same frame, LUT on and post off, were pixel-identical. This module rebuilds
what is verified against a RenderView PNG export — the LUT (``.cube``, with its
strength, after the OCIO view) and then the master RGB curve (natural cubic
spline) — and names everything else instead of guessing it.

Pure and stdlib only: the C4D adapter calls ``post_plan`` once per snapshot and
``apply_row`` per row of OCIO-view floats (0..1 display values).
"""
import os

CURVE_SAMPLES = 4096
DEFAULT_HIGHLIGHTS = 0.2          # RenderView's own default; seen with post off too
_LUT_CACHE = {}


def parse_cube(text):
    """``(size, table)`` from a 3D ``.cube`` LUT; table entries are ``(r, g, b)``
    with red varying fastest. Raises ``ValueError`` on anything unsupported."""
    size = None
    values = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif head == "LUT_1D_SIZE":
            raise ValueError("1D LUTs are not supported")
        elif head in ("DOMAIN_MIN", "DOMAIN_MAX"):
            expected = 0.0 if head == "DOMAIN_MIN" else 1.0
            if any(abs(float(v) - expected) > 1e-6 for v in line.split()[1:4]):
                raise ValueError("LUT domain other than 0..1 is not supported")
        elif head == "TITLE" or head.startswith("LUT_"):
            continue
        else:
            parts = line.split()
            if len(parts) != 3:
                raise ValueError("unexpected line in .cube: %r" % line[:40])
            values.append((float(parts[0]), float(parts[1]), float(parts[2])))
    if not size or size < 2:
        raise ValueError("missing LUT_3D_SIZE")
    if len(values) != size ** 3:
        raise ValueError("expected %d entries, found %d" % (size ** 3, len(values)))
    return size, values


def load_cube(path):
    """Parsed ``.cube`` cached by (path, mtime)."""
    key = (path, os.path.getmtime(path))
    if key not in _LUT_CACHE:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            _LUT_CACHE.clear()
            _LUT_CACHE[key] = parse_cube(handle.read())
    return _LUT_CACHE[key]


def curve_points(attrs, name):
    """Points of RenderView curve ``name`` (``RGB``, ``Red``, ``Green``, ``Blue``)."""
    count = attrs.get("curve_%s_numPoints" % name)
    if not isinstance(count, int) or count < 2:
        return []
    points = [attrs.get("curve_%s%d" % (name, i)) for i in range(count)]
    if any(not isinstance(p, tuple) or len(p) != 2 for p in points):
        return []
    return sorted((float(x), float(y)) for x, y in points)


def is_identity_curve(points):
    return not points or all(abs(x - y) < 1e-4 for x, y in points)


def spline_table(points, samples=CURVE_SAMPLES):
    """Natural cubic spline through ``points``, clamped outside them, sampled to
    ``samples`` 8-bit outputs (index = round(value × (samples − 1)))."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    if any(step <= 0 for step in h):
        raise ValueError("curve points must have increasing x")
    # Tridiagonal system for the second-derivative terms (natural ends).
    c = [0.0] * n
    if n > 2:
        sub = [0.0] * n
        diag = [1.0] * n
        sup = [0.0] * n
        rhs = [0.0] * n
        for i in range(1, n - 1):
            sub[i], diag[i], sup[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            rhs[i] = 3 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
        for i in range(1, n):                      # Thomas algorithm
            w = sub[i] / diag[i - 1]
            diag[i] -= w * sup[i - 1]
            rhs[i] -= w * rhs[i - 1]
        c[n - 1] = rhs[n - 1] / diag[n - 1]
        for i in range(n - 2, -1, -1):
            c[i] = (rhs[i] - sup[i] * c[i + 1]) / diag[i]
    b = [(ys[i + 1] - ys[i]) / h[i] - h[i] * (2 * c[i] + c[i + 1]) / 3 for i in range(n - 1)]
    d = [(c[i + 1] - c[i]) / (3 * h[i]) for i in range(n - 1)]
    table = []
    seg = 0
    for k in range(samples):
        v = k / (samples - 1.0)
        if v <= xs[0]:
            out = ys[0]
        elif v >= xs[-1]:
            out = ys[-1]
        else:
            while v > xs[seg + 1]:
                seg += 1
            t = v - xs[seg]
            out = ys[seg] + b[seg] * t + c[seg] * t * t + d[seg] * t * t * t
        table.append(0 if out <= 0 else 255 if out >= 1 else int(out * 255 + 0.5))
    return table


def _lut_path(attrs):
    name = str(attrs.get("LUT File") or "").strip()
    folder = str(attrs.get("LUT Location") or "").strip()
    if not name:
        return None, []
    candidates = [name] if os.path.isabs(name) else []
    if folder:
        candidates += [os.path.join(folder, name), os.path.join(folder, name + ".cube")]
    for path in candidates:
        if os.path.isfile(path):
            return path, candidates
    return None, candidates


def post_plan(attrs):
    """What to re-apply for a snapshot, from its EXR header.

    Returns ``{"lut", "strength", "curve", "applied", "notes"}``: ``lut`` is a
    parsed ``(size, table)`` or None, ``curve`` an 8-bit table or None,
    ``applied`` short labels of what will be reproduced and ``notes`` short
    labels of what will not (said to the artist, never silently dropped).
    """
    plan = {"lut": None, "strength": 1.0, "curve": None, "applied": [], "notes": []}
    strength = attrs.get("Lut Strength")
    strength = float(strength) if isinstance(strength, (int, float)) else 1.0
    # A LUT at 0 % strength is on in the UI but changes nothing (measured).
    if attrs.get("Lut Enabled") == 1 and strength > 1e-4:
        label = str(attrs.get("LUT File") or "LUT")
        if attrs.get("Apply color management before LUT") != 1 or \
                attrs.get("Convert to log space before applying LUT") == 1:
            plan["notes"].append("LUT %s (unsupported order)" % label)
        else:
            path, tried = _lut_path(attrs)
            if not path:
                plan["notes"].append("LUT %s not found" % label)
            else:
                try:
                    plan["lut"] = load_cube(path)
                    plan["strength"] = strength
                    plan["applied"].append("LUT %s %d%%" % (label, round(plan["strength"] * 100)))
                except (OSError, ValueError) as exc:
                    plan["notes"].append("LUT %s unreadable (%s)" % (label, exc))
    if attrs.get("Color Controls Enabled") == 1:
        master = curve_points(attrs, "RGB")
        if not is_identity_curve(master):
            try:
                plan["curve"] = spline_table(master)
                plan["applied"].append("RGB curve")
            except ValueError:
                plan["notes"].append("RGB curve")
        for channel in ("Red", "Green", "Blue"):
            if not is_identity_curve(curve_points(attrs, channel)):
                plan["notes"].append("%s curve" % channel.lower())
        neutral = (("Exposure (EV)", 0.0, "exposure"), ("Contrast", 0.0, "contrast"),
                   ("Saturation", 0.0, "saturation"), ("Gamma", 1.0, "gamma"),
                   ("Hue", 0.0, "hue"), ("Highlights", DEFAULT_HIGHLIGHTS, "highlights"))
        for key, value, label in neutral:
            current = attrs.get(key)
            if isinstance(current, (int, float)) and abs(current - value) > 1e-4:
                plan["notes"].append(label)
    for key, label in (("Photographic Exposure Enabled", "photographic exposure"),
                       ("Tonemap Parameters Enabled", "tone mapping"),
                       ("Bloom Enabled", "bloom"), ("Flare Enabled", "flare"),
                       ("Streak Enabled", "streak")):
        if attrs.get(key) == 1:
            plan["notes"].append(label)
    vignetting = attrs.get("Vignetting")
    if isinstance(vignetting, (int, float)) and abs(vignetting) > 1e-4:
        plan["notes"].append("vignetting")
    return plan


def plan_is_active(plan):
    return bool(plan and (plan["lut"] or plan["curve"]))


def applied_label(plan):
    """The ``{post}`` slate token: what was re-applied, e.g.
    ``"LUT Cinema Look 11 49% + RGB curve"``; ``""`` when nothing was."""
    return " + ".join(plan["applied"]) if plan else ""


def describe(plan):
    """One line for the artist: what was re-applied and what was not."""
    if not plan:
        return ""
    parts = []
    if plan["applied"]:
        parts.append("RenderView post applied: " + ", ".join(plan["applied"]))
    if plan["notes"]:
        parts.append("not reproduced: " + ", ".join(plan["notes"]))
    return " · ".join(parts)


def apply_row(values, plan):
    """OCIO-view floats ``[r, g, b, r, g, b, …]`` -> 8-bit ``bytearray``:
    LUT blended by its strength (trilinear), then the RGB curve."""
    lut = plan["lut"]
    curve = plan["curve"]
    k1 = CURVE_SAMPLES - 1
    out = bytearray(len(values))
    if lut is None:
        for j in range(len(values)):
            v = values[j]
            out[j] = curve[int((0.0 if v < 0 else 1.0 if v > 1 else v) * k1 + 0.5)]
        return out
    size, table = lut
    n1 = size - 1
    nn = size * size
    s = plan["strength"]
    inv = 1.0 - s
    for j in range(0, len(values), 3):
        r = values[j]
        g = values[j + 1]
        b = values[j + 2]
        if r < 0:
            r = 0.0
        elif r > 1:
            r = 1.0
        if g < 0:
            g = 0.0
        elif g > 1:
            g = 1.0
        if b < 0:
            b = 0.0
        elif b > 1:
            b = 1.0
        x = r * n1
        y = g * n1
        z = b * n1
        i0 = int(x)
        j0 = int(y)
        k0 = int(z)
        if i0 == n1:
            i0 -= 1
        if j0 == n1:
            j0 -= 1
        if k0 == n1:
            k0 -= 1
        fx = x - i0
        fy = y - j0
        fz = z - k0
        base = k0 * nn + j0 * size + i0
        a0 = table[base]
        a1 = table[base + 1]
        a2 = table[base + size]
        a3 = table[base + size + 1]
        c0 = table[base + nn]
        c1 = table[base + nn + 1]
        c2 = table[base + nn + size]
        c3 = table[base + nn + size + 1]
        gx = 1 - fx
        gy = 1 - fy
        gz = 1 - fz
        w0 = gx * gy * gz
        w1 = fx * gy * gz
        w2 = gx * fy * gz
        w3 = fx * fy * gz
        w4 = gx * gy * fz
        w5 = fx * gy * fz
        w6 = gx * fy * fz
        w7 = fx * fy * fz
        lr = w0 * a0[0] + w1 * a1[0] + w2 * a2[0] + w3 * a3[0] + w4 * c0[0] + w5 * c1[0] + w6 * c2[0] + w7 * c3[0]
        lg = w0 * a0[1] + w1 * a1[1] + w2 * a2[1] + w3 * a3[1] + w4 * c0[1] + w5 * c1[1] + w6 * c2[1] + w7 * c3[1]
        lb = w0 * a0[2] + w1 * a1[2] + w2 * a2[2] + w3 * a3[2] + w4 * c0[2] + w5 * c1[2] + w6 * c2[2] + w7 * c3[2]
        mr = r * inv + lr * s
        mg = g * inv + lg * s
        mb = b * inv + lb * s
        if curve is None:
            out[j] = 0 if mr <= 0 else 255 if mr >= 1 else int(mr * 255 + 0.5)
            out[j + 1] = 0 if mg <= 0 else 255 if mg >= 1 else int(mg * 255 + 0.5)
            out[j + 2] = 0 if mb <= 0 else 255 if mb >= 1 else int(mb * 255 + 0.5)
        else:
            out[j] = curve[int((0.0 if mr < 0 else 1.0 if mr > 1 else mr) * k1 + 0.5)]
            out[j + 1] = curve[int((0.0 if mg < 0 else 1.0 if mg > 1 else mg) * k1 + 0.5)]
            out[j + 2] = curve[int((0.0 if mb < 0 else 1.0 if mb > 1 else mb) * k1 + 0.5)]
    return out
