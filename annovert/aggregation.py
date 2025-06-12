from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from pydantic import BaseModel
import re
from functools import lru_cache
from abc import ABC, abstractmethod

from .basecore import Region, AggregationConfig


class AnnotationGroup(BaseModel):
    base_name: str
    files: List[Path]

    class Config:
        arbitrary_types_allowed = True


class GroupingStrategy(ABC):
    @abstractmethod
    def group_files(
        self, files: List[Path], config: AggregationConfig
    ) -> Dict[str, AnnotationGroup]:
        pass


class AutoGroupingStrategy(GroupingStrategy):
    @lru_cache(maxsize=1000)
    def _extract_base_name(
        self, filename: str, config_suffixes: tuple, config_separators: tuple
    ) -> str:
        filename_lower = filename.lower()

        for suffix in config_suffixes:
            for sep in config_separators:
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

    def group_files(
        self, files: List[Path], config: AggregationConfig
    ) -> Dict[str, AnnotationGroup]:
        groups: Dict[str, AnnotationGroup] = {}
        config_suffixes = tuple(config.common_suffixes)
        config_separators = tuple(config.separator_patterns)

        for file_path in files:
            base_name = self._extract_base_name(
                file_path.stem, config_suffixes, config_separators
            )
            if base_name not in groups:
                groups[base_name] = AnnotationGroup(base_name=base_name, files=[])
            groups[base_name].files.append(file_path)
        return groups


class PrefixGroupingStrategy(GroupingStrategy):
    def group_files(
        self, files: List[Path], config: AggregationConfig
    ) -> Dict[str, AnnotationGroup]:
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


class SuffixGroupingStrategy(GroupingStrategy):
    def group_files(
        self, files: List[Path], config: AggregationConfig
    ) -> Dict[str, AnnotationGroup]:
        groups: Dict[str, AnnotationGroup] = {}
        for file_path in files:
            base_name = file_path.stem
            for sep in config.separator_patterns:
                if sep in base_name:
                    base_name = base_name.split(sep)[0]
                    break
            if base_name not in groups:
                groups[base_name] = AnnotationGroup(base_name=base_name, files=[])
            groups[base_name].files.append(file_path)
        return groups


class RegexGroupingStrategy(GroupingStrategy):
    def group_files(
        self, files: List[Path], config: AggregationConfig
    ) -> Dict[str, AnnotationGroup]:
        if not config.custom_regex:
            return AutoGroupingStrategy().group_files(files, config)

        compiled_regex = re.compile(config.custom_regex)
        groups: Dict[str, AnnotationGroup] = {}

        for file_path in files:
            match = compiled_regex.search(file_path.stem)
            base_name = match.group(1) if match and match.groups() else file_path.stem
            if base_name not in groups:
                groups[base_name] = AnnotationGroup(base_name=base_name, files=[])
            groups[base_name].files.append(file_path)
        return groups


class AnnotationGrouper:
    def __init__(self, config: AggregationConfig) -> None:
        self.config = config
        self._strategies = {
            "auto": AutoGroupingStrategy(),
            "prefix": PrefixGroupingStrategy(),
            "suffix": SuffixGroupingStrategy(),
            "regex": RegexGroupingStrategy(),
        }

    def group_files(self, annotation_files: List[Path]) -> List[AnnotationGroup]:
        if not self.config.enabled:
            return [
                AnnotationGroup(base_name=f.stem, files=[f]) for f in annotation_files
            ]

        strategy = self._strategies[self.config.grouping_strategy]
        grouped = strategy.group_files(annotation_files, self.config)

        return [
            group
            for group in grouped.values()
            if len(group.files) >= self.config.min_group_size
        ]


class RegionOverlapCalculator:
    @staticmethod
    def regions_overlap(region1: Region, region2: Region) -> bool:
        if not region1.coordinates or not region2.coordinates:
            return False

        bounds1 = region1.bounds
        bounds2 = region2.bounds

        return not (
            bounds1[2] < bounds2[0]
            or bounds2[2] < bounds1[0]
            or bounds1[3] < bounds2[1]
            or bounds2[3] < bounds1[1]
        )


class HistechAggregator:
    def __init__(self, config: AggregationConfig) -> None:
        self.config = config
        self.overlap_calculator = RegionOverlapCalculator()

    def aggregate_annotations(self, annotation_files: List[Path]) -> Any:
        from .formats import HistechAnnotation

        aggregated = HistechAnnotation()
        region_counter = 1

        for file_path in annotation_files:
            try:
                annotation = HistechAnnotation.from_file(file_path)
                self._merge_annotation(
                    annotation, aggregated, file_path, region_counter
                )
                region_counter += len(annotation.regions)
                self._update_metadata_if_needed(annotation, aggregated)
            except Exception:
                continue

        return aggregated

    def _merge_annotation(
        self, source: Any, target: Any, file_path: Path, region_counter: int
    ) -> None:
        for region in source.regions:
            new_region = self._create_merged_region(region, file_path, region_counter)

            if not self.config.merge_overlapping_regions or not self._is_overlapping(
                new_region, target.regions
            ):
                target.add_region(new_region)
                region_counter += 1

    def _create_merged_region(
        self, region: Region, file_path: Path, counter: int
    ) -> Region:
        return Region(
            name=self._generate_region_name(region, file_path, counter),
            region_type=region.region_type,
            coordinates=region.coordinates.copy(),
            color=region.color,
            group=region.group,
            guid=region.guid,
            label_value=region.label_value,
        )

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

    @lru_cache(maxsize=1000)
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
            self.overlap_calculator.regions_overlap(new_region, existing)
            for existing in existing_regions
        )

    def _update_metadata_if_needed(self, source: Any, target: Any) -> None:
        if not target.micrometer_per_pixel_x and source.micrometer_per_pixel_x:
            target.micrometer_per_pixel_x = source.micrometer_per_pixel_x
            target.micrometer_per_pixel_y = source.micrometer_per_pixel_y
            target.offset_left = source.offset_left
            target.offset_top = source.offset_top
            target.width = source.width
            target.height = source.height
