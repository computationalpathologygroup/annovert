"""Scan an annovert output directory and build a typed data index."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_GROUP_PALETTE: tuple[str, ...] = (
    "#2563eb",  # blue
    "#dc2626",  # red
    "#16a34a",  # green
    "#9333ea",  # purple
    "#ea580c",  # orange
    "#0891b2",  # cyan
    "#be185d",  # pink
    "#65a30d",  # lime
    "#b45309",  # amber
    "#0d9488",  # teal
)

_UNGROUPED_COLOR = "#94a3b8"  # slate gray

_WSI_EXTENSIONS: tuple[str, ...] = (
    ".mrxs",
    ".tiff",
    ".tif",
    ".svs",
    ".ndpi",
    ".ndpis",
    ".qptiff",
    ".scn",
    ".vms",
    ".bif",
    ".btf",
    ".czi",
    ".lif",
)

_SOURCE_EXTENSIONS: tuple[str, ...] = (".xml", ".ndpa")


@dataclass
class AnnotationRecord:
    """A single annotation file entry."""

    stem: str
    geojson_path: str
    image_path: Optional[str]
    has_wsi: bool
    feature_count: int
    groups: list[str]
    group_counts: dict[str, int]
    source_path: Optional[str] = None


@dataclass
class IndexData:
    """Full index; JSON-serialisable via dataclasses.asdict."""

    output_dir: str
    annotations: list[AnnotationRecord] = field(default_factory=list)
    all_groups: list[str] = field(default_factory=list)
    group_colors: dict[str, str] = field(default_factory=dict)


def load_index(
    output_dir: Path,
    data_dir: Optional[Path] = None,
    source_dir: Optional[Path] = None,
) -> IndexData:
    """Return a structured IndexData for all GeoJSON files in output_dir."""
    output_dir = Path(output_dir).resolve()
    if data_dir:
        data_dir = Path(data_dir).resolve()
    if source_dir:
        source_dir = Path(source_dir).resolve()

    # Build stem->path lookup tables with a single directory traversal each.
    # This is O(total_files) instead of O(stems * total_files).
    wsi_index = _build_index(data_dir, _WSI_EXTENSIONS) if data_dir else None
    source_index = _build_index(source_dir, _SOURCE_EXTENSIONS) if source_dir else None

    geojson_files = sorted(output_dir.glob("*.geojson"))

    all_groups_set: set[str] = set()
    records: list[AnnotationRecord] = []

    for gj_path in geojson_files:
        stem = gj_path.stem

        try:
            data = json.loads(gj_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        features = data.get("features") or []
        feature_count = len(features)

        group_counts: dict[str, int] = {}
        for f in features:
            props = f.get("properties") or {}
            g = props.get("group")
            key = g if (g is not None and g != "") else "_ungrouped"
            group_counts[key] = group_counts.get(key, 0) + 1

        groups = sorted(group_counts.keys())
        all_groups_set.update(groups)

        image_path = wsi_index.get(stem) if wsi_index else None
        source_path = source_index.get(stem) if source_index else None

        records.append(
            AnnotationRecord(
                stem=stem,
                geojson_path=str(gj_path),
                image_path=str(image_path) if image_path else None,
                has_wsi=image_path is not None,
                feature_count=feature_count,
                groups=groups,
                group_counts=group_counts,
                source_path=str(source_path) if source_path else None,
            )
        )

    # Assign consistent colors to all groups across all files
    all_groups = sorted(all_groups_set)
    group_colors: dict[str, str] = {}
    palette_groups = [g for g in all_groups if g != "_ungrouped"]
    for i, g in enumerate(palette_groups):
        group_colors[g] = _GROUP_PALETTE[i % len(_GROUP_PALETTE)]
    if "_ungrouped" in all_groups_set:
        group_colors["_ungrouped"] = _UNGROUPED_COLOR

    return IndexData(
        output_dir=str(output_dir),
        annotations=records,
        all_groups=all_groups,
        group_colors=group_colors,
    )


def _build_index(directory: Path, extensions: tuple[str, ...]) -> dict[str, Path]:
    """List direct children of directory once and return {stem: path} for matching extensions."""
    ext_set = set(extensions)
    index: dict[str, Path] = {}
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in ext_set:
            index[p.stem] = p
    return index
