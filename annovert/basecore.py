from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, ConfigDict
import uuid
import re

FormatType = Literal[
    "asap", "geojson", "3dhistech", "geojson_qupath_mrxs", "binary_mask"
]


class ImageMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    offset_x: float = 0.0
    offset_y: float = 0.0
    mpp_x: float = 1.0
    mpp_y: float = 1.0
    width: int = 0
    height: int = 0
    level_0_width: int = 0
    level_0_height: int = 0


class Coordinate(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y}

    def to_list(self) -> List[float]:
        return [self.x, self.y]

    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


class Region(BaseModel):
    name: str
    region_type: str = "Polygon"
    coordinates: List[Coordinate] = Field(default_factory=list)
    color: Optional[str] = None
    group: Optional[str] = None
    guid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label_value: int = 1

    def add_coordinate(self, x: float, y: float) -> None:
        self.coordinates.append(Coordinate(x=x, y=y))

    def as_coordinate_list(self) -> List[List[float]]:
        return [[coord.x, coord.y] for coord in self.coordinates]

    def as_tuple_list(self) -> List[Tuple[float, float]]:
        return [coord.to_tuple() for coord in self.coordinates]

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        if not self.coordinates:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [c.x for c in self.coordinates]
        ys = [c.y for c in self.coordinates]
        return (min(xs), min(ys), max(xs), max(ys))


class AggregationConfig(BaseModel):
    enabled: bool = False
    grouping_strategy: str = Field(default="auto")
    separator_patterns: List[str] = Field(default_factory=lambda: ["_", "-", ".", " "])
    common_suffixes: List[str] = Field(
        default_factory=lambda: [
            "annotation",
            "anno",
            "region",
            "roi",
            "area",
            "zone",
            "mask",
        ]
    )
    custom_regex: Optional[str] = None
    min_group_size: int = 1
    preserve_individual_names: bool = True
    merge_overlapping_regions: bool = False


class FormatDetector:
    _PATTERNS = {
        "asap": r"<ASAP_Annotations>",
        "3dhistech": r"<annotation_meta_data",
        "geojson": r'"type"\s*:\s*"FeatureCollection"',
        "geojson_qupath_mrxs": r'"qupath_mrxs"\s*:\s*true',
    }

    @classmethod
    def detect_format(cls, content: str) -> FormatType:
        for format_type, pattern in cls._PATTERNS.items():
            if re.search(pattern, content):
                if format_type == "geojson" and re.search(
                    cls._PATTERNS["geojson_qupath_mrxs"], content
                ):
                    return "geojson_qupath_mrxs"
                return format_type
        raise ValueError("Unknown annotation format")


class Annotation:
    def __init__(self, name: str = "") -> None:
        self.name = name

    @staticmethod
    def detect_format(content: str) -> FormatType:
        return FormatDetector.detect_format(content)


class ConverterConfig(BaseModel):
    allow_auto_detect: bool = True
    default_source_format: Optional[FormatType] = None
    default_target_format: Optional[FormatType] = None
    output_directory: Optional[Path] = None
    mask_downsample_factor: float = 1.0
    default_label_value: int = 1
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    enable_parallel_processing: bool = True
    chunk_size: int = 1000

    def model_post_init(self, __context) -> None:
        if self.output_directory:
            self.output_directory.mkdir(parents=True, exist_ok=True)
