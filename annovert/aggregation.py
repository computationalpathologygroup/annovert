from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import re

from .basecore import Region
from .formats import HistechAnnotation


class AggregationConfig:
    def __init__(
        self,
        enabled: bool = False,
        grouping_strategy: str = "auto",
        separator_patterns: Optional[List[str]] = None,
        common_suffixes: Optional[List[str]] = None,
        custom_regex: Optional[str] = None,
        min_group_size: int = 1,
        preserve_individual_names: bool = True,
        merge_overlapping_regions: bool = False,
    ) -> None:
        valid_strategies = {"auto", "prefix", "suffix", "regex"}
        if grouping_strategy not in valid_strategies:
            raise ValueError(f"grouping_strategy must be one of {valid_strategies}")

        self.enabled = enabled
        self.grouping_strategy = grouping_strategy
        self.separator_patterns = separator_patterns or ["_", "-", ".", " "]
        self.common_suffixes = common_suffixes or [
            "annotation",
            "anno",
            "region",
            "roi",
            "area",
            "zone",
            "mask",
        ]
        self.custom_regex = custom_regex
        self.min_group_size = min_group_size
        self.preserve_individual_names = preserve_individual_names
        self.merge_overlapping_regions = merge_overlapping_regions


@dataclass
class AnnotationGroup:
    base_name: str
    files: List[Path]


class AnnotationGrouper:
    def __init__(self, config: AggregationConfig) -> None:
        self.config = config

    def group_files(self, annotation_files: List[Path]) -> List[AnnotationGroup]:
        if not self.config.enabled:
            return [
                AnnotationGroup(base_name=f.stem, files=[f]) for f in annotation_files
            ]

        grouped = self._group_by_strategy(annotation_files)
        return [
            group
            for group in grouped.values()
            if len(group.files) >= self.config.min_group_size
        ]

    def _group_by_strategy(self, files: List[Path]) -> Dict[str, AnnotationGroup]:
        strategy_map = {
            "auto": self._group_auto,
            "prefix": self._group_by_prefix,
            "suffix": self._group_by_suffix,
            "regex": self._group_by_regex,
        }
        return strategy_map[self.config.grouping_strategy](files)

    def _group_auto(self, files: List[Path]) -> Dict[str, AnnotationGroup]:
        groups: Dict[str, AnnotationGroup] = {}
        for file_path in files:
            base_name = self._extract_auto_base_name(file_path.stem)
            if base_name not in groups:
                groups[base_name] = AnnotationGroup(base_name=base_name, files=[])
            groups[base_name].files.append(file_path)
        return groups

    def _extract_auto_base_name(self, filename: str) -> str:
        filename_lower = filename.lower()

        for suffix in self.config.common_suffixes:
            for sep in self.config.separator_patterns:
                patterns = [
                    f"{re.escape(sep)}{re.escape(suffix)}$",
                    f"{re.escape(sep)}{re.escape(suffix)}{re.escape(sep)}\\d+$",
                    f"{re.escape(sep)}\\d+{re.escape(sep)}{re.escape(suffix)}$",
                ]
                for pattern in patterns:
                    match = re.search(pattern, filename_lower)
                    if match:
                        return filename[: match.start()]

        number_pattern = r"[_\-\.]\d+$"
        match = re.search(number_pattern, filename)
        if match:
            return filename[: match.start()]
        return filename

    def _group_by_prefix(self, files: List[Path]) -> Dict[str, AnnotationGroup]:
        groups: Dict[str, AnnotationGroup] = {}
        prefixes = self._find_common_prefixes([f.stem for f in files])

        for file_path in files:
            prefix = max(
                prefixes,
                key=lambda p: len(p) if file_path.stem.startswith(p) else 0,
                default="",
            )
            if prefix not in groups:
                groups[prefix] = AnnotationGroup(base_name=prefix, files=[])
            groups[prefix].files.append(file_path)
        return groups

    def _group_by_suffix(self, files: List[Path]) -> Dict[str, AnnotationGroup]:
        groups: Dict[str, AnnotationGroup] = {}
        for file_path in files:
            base_name = file_path.stem
            for sep in self.config.separator_patterns:
                if sep in base_name:
                    base_name = base_name.split(sep)[0]
                    break
            if base_name not in groups:
                groups[base_name] = AnnotationGroup(base_name=base_name, files=[])
            groups[base_name].files.append(file_path)
        return groups

    def _group_by_regex(self, files: List[Path]) -> Dict[str, AnnotationGroup]:
        if not self.config.custom_regex:
            return self._group_auto(files)

        compiled_regex = re.compile(self.config.custom_regex)
        groups: Dict[str, AnnotationGroup] = {}

        for file_path in files:
            match = compiled_regex.search(file_path.stem)
            base_name = match.group(1) if match and match.groups() else file_path.stem
            if base_name not in groups:
                groups[base_name] = AnnotationGroup(base_name=base_name, files=[])
            groups[base_name].files.append(file_path)
        return groups

    def _find_common_prefixes(self, names: List[str]) -> Set[str]:
        prefixes: Set[str] = set()
        for i, name1 in enumerate(names):
            for name2 in names[i + 1 :]:
                prefix = self._longest_common_prefix(name1, name2)
                if len(prefix) > 3:
                    prefixes.add(prefix)
        return prefixes

    def _longest_common_prefix(self, s1: str, s2: str) -> str:
        min_len = min(len(s1), len(s2))
        for i in range(min_len):
            if s1[i] != s2[i]:
                return s1[:i]
        return s1[:min_len]


class HistechAggregator:
    def __init__(self, config: AggregationConfig) -> None:
        self.config = config

    def aggregate_annotations(self, annotation_files: List[Path]) -> HistechAnnotation:
        aggregated = HistechAnnotation()
        region_counter = 1

        for file_path in annotation_files:
            try:
                annotation = HistechAnnotation.from_file(file_path)
                for region in annotation.regions:
                    new_region = Region(
                        name=self._generate_region_name(
                            region, file_path, region_counter
                        ),
                        region_type=region.region_type,
                        coordinates=region.coordinates.copy(),
                        color=region.color,
                        group=region.group,
                        guid=region.guid,
                        label_value=region.label_value,
                    )

                    if (
                        not self.config.merge_overlapping_regions
                        or not self._is_overlapping(new_region, aggregated.regions)
                    ):
                        aggregated.add_region(new_region)
                        region_counter += 1

                if (
                    not aggregated.micrometer_per_pixel_x
                    and annotation.micrometer_per_pixel_x
                ):
                    aggregated.micrometer_per_pixel_x = (
                        annotation.micrometer_per_pixel_x
                    )
                    aggregated.micrometer_per_pixel_y = (
                        annotation.micrometer_per_pixel_y
                    )
                    aggregated.offset_left = annotation.offset_left
                    aggregated.offset_top = annotation.offset_top
                    aggregated.width = annotation.width
                    aggregated.height = annotation.height
            except Exception:
                continue
        return aggregated

    def _generate_region_name(
        self, region: Region, file_path: Path, counter: int
    ) -> str:
        if (
            self.config.preserve_individual_names
            and region.name
            and not region.name.startswith("slide-")
        ):
            return region.name

        annotation_part = self._extract_annotation_name_from_filename(file_path.name)
        return annotation_part if annotation_part else f"Region_{counter}"

    def _extract_annotation_name_from_filename(self, filename: str) -> Optional[str]:
        name = filename.replace(".xml", "")
        patterns = [r" - (.+)$", r"_(.+)$"]

        for pattern in patterns:
            match = re.search(pattern, name)
            if match:
                annotation_part = match.group(1).strip()
                parts = annotation_part.split("_")
                if len(parts) == 2 and parts[0] == parts[1]:
                    return parts[0]
                return annotation_part
        return None

    def _is_overlapping(
        self, new_region: Region, existing_regions: List[Region]
    ) -> bool:
        if not self.config.merge_overlapping_regions:
            return False
        return any(
            self._regions_overlap(new_region, existing) for existing in existing_regions
        )

    def _regions_overlap(self, region1: Region, region2: Region) -> bool:
        coords1 = [(c.x, c.y) for c in region1.coordinates]
        coords2 = [(c.x, c.y) for c in region2.coordinates]

        if not coords1 or not coords2:
            return False

        min_x1, max_x1 = min(x for x, y in coords1), max(x for x, y in coords1)
        min_y1, max_y1 = min(y for x, y in coords1), max(y for x, y in coords1)
        min_x2, max_x2 = min(x for x, y in coords2), max(x for x, y in coords2)
        min_y2, max_y2 = min(y for x, y in coords2), max(y for x, y in coords2)

        return not (
            max_x1 < min_x2 or max_x2 < min_x1 or max_y1 < min_y2 or max_y2 < min_y1
        )
