"""Pure post-render validation helpers for Sentinel."""

import os
import re
import statistics


# Conservative floor for a viable rendered image header/payload. Zero-byte files
# are classified separately; 1..1023 bytes are hard-truncated render artifacts.
MIN_VIABLE_BYTES = 1024


def expected_frames(start, end, step):
    """Return the inclusive expected frame list for a render range."""
    return list(range(start, end + 1, step))


def detect_stale_cluster(mtimes_by_frame, gap_factor=6.0):
    """Return frames in the oldest mtime cluster when a session gap is detected."""
    if len(mtimes_by_frame) < 3:
        return []

    ordered = sorted(mtimes_by_frame.items(), key=lambda item: item[1])
    mtimes = [mtime for _, mtime in ordered]
    deltas = [b - a for a, b in zip(mtimes, mtimes[1:])]
    median_delta = statistics.median(deltas)
    if median_delta == 0:
        return []

    largest_index, largest_gap = max(enumerate(deltas), key=lambda item: item[1])
    if largest_gap > gap_factor * median_delta:
        return sorted(frame for frame, _ in ordered[: largest_index + 1])
    return []


def scan_sequence(folder, prefix, frame_set, ext):
    """Enumerate a rendered sequence and classify missing or suspect frames."""
    expected = set(frame_set)
    result = {
        "found": [],
        "missing": [],
        "zero_byte": [],
        "truncated": [],
        "stale": [],
    }
    prefix_lower = str(prefix).lower()
    ext_lower = "." + str(ext).lower().lstrip(".")
    paths_by_frame = {}

    try:
        names = os.listdir(folder)
    except OSError:
        result["missing"] = sorted(expected)
        return result

    for name in names:
        if not name.lower().endswith(ext_lower):
            continue
        stem = name[: -len(ext_lower)]
        if not stem.lower().startswith(prefix_lower):
            continue
        digit_runs = re.findall(r"\d+", stem)
        if not digit_runs:
            continue
        frame = int(digit_runs[-1])
        if frame in expected:
            paths_by_frame[frame] = os.path.join(folder, name)

    valid_mtimes = {}
    candidates = []
    for frame in sorted(expected):
        path = paths_by_frame.get(frame)
        if path is None:
            result["missing"].append(frame)
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            result["missing"].append(frame)
            continue
        if size == 0:
            result["zero_byte"].append(frame)
            continue
        if size < MIN_VIABLE_BYTES:
            result["truncated"].append(frame)
            continue
        try:
            valid_mtimes[frame] = os.path.getmtime(path)
        except OSError:
            result["missing"].append(frame)
            continue
        candidates.append(frame)

    # Mtime can be unreliable on copied/synced folders, so later units should
    # treat this as a warning signal. U3 only separates older-session frames.
    stale = set(detect_stale_cluster(valid_mtimes))
    result["stale"] = sorted(stale)
    result["found"] = [frame for frame in candidates if frame not in stale]
    return result


def size_outliers(sizes_by_frame, sigma=3.0):
    """Flag frames whose size deviates beyond a robust median/MAD threshold."""
    if len(sizes_by_frame) <= 2:
        return []

    sizes = list(sizes_by_frame.values())
    median_size = statistics.median(sizes)
    deviations = [abs(size - median_size) for size in sizes]
    # MAD scaled by 1.4826 gives a sigma-comparable robust deviation estimate.
    robust_deviation = statistics.median(deviations) * 1.4826
    if robust_deviation == 0:
        return []

    threshold = sigma * robust_deviation
    return sorted(
        frame
        for frame, size in sizes_by_frame.items()
        if abs(size - median_size) > threshold
    )
