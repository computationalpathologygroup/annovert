import re
import uuid
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union

FormatType = Literal["asap", "geojson", "3dhistech", "geojson_qupath_mrxs"]


class ImageMetadata:
    def __init__(
        self,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        mpp_x: float = 1.0,
        mpp_y: float = 1.0,
        width: int = 0,
        height: int = 0,
        level_0_width: int = 0,
        level_0_height: int = 0,
    ):
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.mpp_x = mpp_x
        self.mpp_y = mpp_y
        self.width = width
        self.height = height
        self.level_0_width = level_0_width
        self.level_0_height = level_0_height

    def __repr__(self):
        return (
            f"ImageMetadata(offset=({self.offset_x}, {self.offset_y}), "
            f"mpp=({self.mpp_x}, {self.mpp_y}), size=({self.width}, {self.height}))"
        )


class Coordinate:
    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)

    def __repr__(self):
        return f"Coordinate(x={self.x}, y={self.y})"

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
        coordinates: List[Coordinate] = None,
        color: str = None,
        group: str = None,
        guid: str = None,
    ):
        self.name = name
        self.region_type = region_type
        self.coordinates = coordinates or []
        self.color = color
        self.group = group
        self.guid = guid or str(uuid.uuid4())

    def __repr__(self):
        return f"Region(name='{self.name}', type='{self.region_type}', coordinates={len(self.coordinates)})"

    def add_coordinate(self, x: float, y: float) -> None:
        self.coordinates.append(Coordinate(x, y))

    def as_coordinate_list(self) -> List[List[float]]:
        return [[coord.x, coord.y] for coord in self.coordinates]

    def as_tuple_list(self) -> List[Tuple[float, float]]:
        return [coord.to_tuple() for coord in self.coordinates]


class Annotation:
    def __init__(self, name: str = ""):
        self.name = name

    @staticmethod
    def detect_format(content: str) -> FormatType:
        if re.search(r"<ASAP_Annotations>", content):
            return "asap"
        elif re.search(r"<annotation_meta_data", content):
            return "3dhistech"
        elif re.search(r'"type"\s*:\s*"FeatureCollection"', content):
            if re.search(r'"qupath_mrxs"\s*:\s*true', content):
                return "geojson_qupath_mrxs"
            return "geojson"
        else:
            raise ValueError("Unknown annotation format")


class ConverterConfig:
    def __init__(
        self,
        allow_auto_detect: bool = True,
        default_source_format: Optional[FormatType] = None,
        default_target_format: Optional[FormatType] = None,
        output_directory: Optional[Union[str, Path]] = None,
    ):
        self.allow_auto_detect = allow_auto_detect
        self.default_source_format = default_source_format
        self.default_target_format = default_target_format

        if output_directory:
            self.output_directory = Path(output_directory)
            self.output_directory.mkdir(parents=True, exist_ok=True)
        else:
            self.output_directory = None
