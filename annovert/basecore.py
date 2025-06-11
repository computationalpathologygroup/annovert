import re
import uuid
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .aggregation import AggregationConfig

FormatType = Literal[
    "asap", "geojson", "3dhistech", "geojson_qupath_mrxs", "binary_mask"
]


@dataclass
class ImageMetadata:
    offset_x: float = 0.0
    offset_y: float = 0.0
    mpp_x: float = 1.0
    mpp_y: float = 1.0
    width: int = 0
    height: int = 0
    level_0_width: int = 0
    level_0_height: int = 0


@dataclass
class Coordinate:
    x: float
    y: float

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y}

    def to_list(self) -> List[float]:
        return [self.x, self.y]

    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


class Region:
    def __init__(
        self,
        name: str,
        region_type: str = "Polygon",
        coordinates: Optional[List[Coordinate]] = None,
        color: Optional[str] = None,
        group: Optional[str] = None,
        guid: Optional[str] = None,
        label_value: int = 1,
    ) -> None:
        self.name = name
        self.region_type = region_type
        self.coordinates = coordinates or []
        self.color = color
        self.group = group
        self.guid = guid or str(uuid.uuid4())
        self.label_value = label_value

    def add_coordinate(self, x: float, y: float) -> None:
        self.coordinates.append(Coordinate(x=x, y=y))

    def as_coordinate_list(self) -> List[List[float]]:
        return [[coord.x, coord.y] for coord in self.coordinates]

    def as_tuple_list(self) -> List[Tuple[float, float]]:
        return [coord.to_tuple() for coord in self.coordinates]


class Annotation:
    def __init__(self, name: str = "") -> None:
        self.name = name

    @staticmethod
    def detect_format(content: str) -> FormatType:
        patterns = {
            "asap": r"<ASAP_Annotations>",
            "3dhistech": r"<annotation_meta_data",
            "geojson": r'"type"\s*:\s*"FeatureCollection"',
            "geojson_qupath_mrxs": r'"qupath_mrxs"\s*:\s*true',
        }

        for format_type, pattern in patterns.items():
            if re.search(pattern, content):
                if format_type == "geojson" and re.search(
                    patterns["geojson_qupath_mrxs"], content
                ):
                    return "geojson_qupath_mrxs"
                return format_type  # type: ignore

        raise ValueError("Unknown annotation format")


class ConverterConfig:
    def __init__(
        self,
        allow_auto_detect: bool = True,
        default_source_format: Optional[FormatType] = None,
        default_target_format: Optional[FormatType] = None,
        output_directory: Optional[Union[str, Path]] = None,
        mask_downsample_factor: float = 1.0,
        default_label_value: int = 1,
        aggregation: Optional["AggregationConfig"] = None,
    ) -> None:
        self.allow_auto_detect = allow_auto_detect
        self.default_source_format = default_source_format
        self.default_target_format = default_target_format
        self.mask_downsample_factor = mask_downsample_factor
        self.default_label_value = default_label_value

        if aggregation is None:
            from .aggregation import AggregationConfig

            self.aggregation: "AggregationConfig" = AggregationConfig()
        else:
            self.aggregation = aggregation

        self.output_directory: Optional[Path]
        if output_directory:
            self.output_directory = Path(output_directory)
            self.output_directory.mkdir(parents=True, exist_ok=True)
        else:
            self.output_directory = None
