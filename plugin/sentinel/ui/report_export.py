# -*- coding: utf-8 -*-
"""QC report export (JSON + client HTML) — extracted from the retired
``ui/panel.py`` (Fase 6.5). Test-covered; not currently wired to an SPA op.
"""
import json
import os

import c4d

from sentinel.common.helpers import safe_print
from sentinel.versioning import load_versions_for_doc
from sentinel.ui.reports import build_qc_report


def _scene_snapshot_b64(doc, artist_name):
    """Return base64 of the newest review still for this scene, or None.

    Read-only: searches the artist's stills tree for ``<scene>.png`` (never
    creates folders). Embedded into the client report when present.
    """
    import base64

    try:
        doc_path = doc.GetDocumentPath() or ""
        if not doc_path:
            return None
        project_root = os.path.dirname(os.path.dirname(doc_path))
        stills_root = os.path.join(project_root, "output", "stills")
        if not os.path.isdir(stills_root):
            return None
        scene_name = os.path.splitext(doc.GetDocumentName() or "untitled")[0]
        target = f"{scene_name}.png"
        newest = None
        newest_mtime = -1.0
        for root, _dirs, files in os.walk(stills_root):
            if target in files:
                full = os.path.join(root, target)
                mtime = os.path.getmtime(full)
                if mtime > newest_mtime:
                    newest, newest_mtime = full, mtime
        if not newest:
            return None
        with open(newest, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    except Exception as e:
        safe_print(f"Could not embed snapshot in client report: {e}")
        return None


def export_qc_report(doc, results, artist_name, qc_summary=None):
    """Export QC report as JSON + a self-contained client HTML report.

    Returns the JSON path (or None if cancelled). The ``<base>_report.html``
    companion is written next to the JSON via atomic tmp+rename.
    """
    report = build_qc_report(doc, results, artist_name, qc_summary)

    # Ask user where to save
    save_path = c4d.storage.SaveDialog(
        title="Save QC Report",
        force_suffix="json",
    )

    if not save_path:
        return None

    if not save_path.endswith(".json"):
        save_path += ".json"

    with open(save_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ── Client-readable HTML report (I7) ──
    # Written next to the chosen JSON, and (when the scene is saved) also as the
    # canonical <base>_report.html sidecar next to the .c4d so Scene Collector
    # can transport it into the delivery alongside the other sidecars.
    try:
        from sentinel.client_report import write_client_report_html
        from sentinel.versioning import parse_version_filename, report_html_path

        json_dir = os.path.dirname(save_path)
        scene_no_ext = os.path.splitext(doc.GetDocumentName() or "scene")[0]
        base, _v, _s = parse_version_filename(scene_no_ext)
        if not base:
            base = scene_no_ext or "scene"

        versions = load_versions_for_doc(doc)
        snapshot_b64 = _scene_snapshot_b64(doc, artist_name)

        targets = {os.path.join(json_dir, f"{base}_report.html")}
        doc_full = os.path.join(doc.GetDocumentPath() or "", doc.GetDocumentName() or "")
        if doc.GetDocumentPath():
            sidecar = report_html_path(doc_full)
            if sidecar:
                targets.add(sidecar)

        for html_path in targets:
            write_client_report_html(report, html_path, snapshot_b64=snapshot_b64, versions=versions)
            safe_print(f"Client HTML report written: {html_path}")
    except Exception as e:
        safe_print(f"Could not write client HTML report: {e}")

    return save_path
