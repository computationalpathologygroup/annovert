import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Union

from .basecore import Annotation, Region


class ASAPAnnotation(Annotation):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.regions: List[Region] = []
        self.groups: Dict[str, Any] = {}

    def add_region(self, region: Region) -> None:
        self.regions.append(region)

    @staticmethod
    def from_string(xml_string: str) -> "ASAPAnnotation":
        annotation = ASAPAnnotation()
        root = ET.fromstring(xml_string)

        for anno_elem in root.findall(".//Annotation"):
            name = anno_elem.get("Name", "")
            region_type = anno_elem.get("Type", "Polygon")
            color = anno_elem.get("Color", "#F4FA58")
            group = anno_elem.get("PartOfGroup", "None")

            region = Region(
                name=name, region_type=region_type, color=color, group=group
            )

            for coord_elem in anno_elem.findall(".//Coordinate"):
                x = float(coord_elem.get("X", 0))
                y = float(coord_elem.get("Y", 0))
                region.add_coordinate(x, y)

            annotation.add_region(region)

        return annotation

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "ASAPAnnotation":
        file_path = Path(file_path)
        with open(file_path, "r") as f:
            xml_string = f.read()
        return ASAPAnnotation.from_string(xml_string)

    def to_xml(self) -> str:
        root = ET.Element("ASAP_Annotations")
        annotations = ET.SubElement(root, "Annotations")

        for i, region in enumerate(self.regions):
            annotation = ET.SubElement(annotations, "Annotation")
            annotation.set("Name", region.name)
            annotation.set("Type", region.region_type)
            annotation.set("PartOfGroup", region.group or "None")
            annotation.set("Color", region.color or "#F4FA58")

            coordinates = ET.SubElement(annotation, "Coordinates")

            for j, coord in enumerate(region.coordinates):
                coordinate = ET.SubElement(coordinates, "Coordinate")
                coordinate.set("Order", str(j))
                coordinate.set("X", str(coord.x))
                coordinate.set("Y", str(coord.y))

        groups = ET.SubElement(root, "AnnotationGroups")

        xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
        xml_declaration = '<?xml version="1.0"?>\n'

        return xml_declaration + xml_str

    def save(self, output_path: Union[str, Path]) -> None:
        output_path = Path(output_path)
        with open(output_path, "w") as f:
            f.write(self.to_xml())

    def to_geojson(self) -> "GeoJSONAnnotation":
        geojson = GeoJSONAnnotation()

        for region in self.regions:
            feature = {
                "type": "Feature",
                "id": region.guid,
                "geometry": {
                    "type": region.region_type,
                    "coordinates": [[coord.to_list() for coord in region.coordinates]],
                },
                "properties": {
                    "objectType": "annotation",
                    "name": region.name,
                    "color": region.color,
                    "group": region.group,
                },
            }

            geojson.features.append(feature)

        return geojson


class GeoJSONAnnotation(Annotation):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.features: List[Dict] = []

    def add_feature(self, feature: Dict) -> None:
        self.features.append(feature)

    @staticmethod
    def from_string(json_string: str) -> "GeoJSONAnnotation":
        data = json.loads(json_string)
        annotation = GeoJSONAnnotation()

        if "features" in data:
            annotation.features = data["features"]

        return annotation

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "GeoJSONAnnotation":
        file_path = Path(file_path)
        with open(file_path, "r") as f:
            json_string = f.read()
        return GeoJSONAnnotation.from_string(json_string)

    def to_json(self) -> str:
        geojson = {"type": "FeatureCollection", "features": self.features}

        return json.dumps(geojson, indent=2)

    def save(self, output_path: Union[str, Path]) -> None:
        output_path = Path(output_path)
        with open(output_path, "w") as f:
            f.write(self.to_json())

    def to_asap(self) -> ASAPAnnotation:
        asap = ASAPAnnotation()

        for feature in self.features:
            if feature["geometry"]["type"] == "Polygon":
                properties = feature.get("properties", {})
                name = properties.get("name", "Region")

                region = Region(
                    name=name,
                    region_type="Polygon",
                    color=properties.get("color", "#F4FA58"),
                    group=properties.get("group", "None"),
                    guid=feature.get("id", str(uuid.uuid4())),
                )

                coord_list = feature["geometry"]["coordinates"][0]
                for x, y in coord_list:
                    region.add_coordinate(x, y)

                asap.add_region(region)

        return asap


class HistechAnnotation(Annotation):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.regions: List[Region] = []
        self.offset_left: int = 0
        self.offset_top: int = 0
        self.width: int = 0
        self.height: int = 0
        self.micrometer_per_pixel_x: float = 0.0
        self.micrometer_per_pixel_y: float = 0.0

    def add_region(self, region: Region) -> None:
        self.regions.append(region)

    @staticmethod
    def from_string(xml_string: str) -> "HistechAnnotation":
        annotation = HistechAnnotation()
        root = ET.fromstring(xml_string)

        source = root.find(".//source")
        if source is not None:
            roi = source.find("region_of_interest")
            if roi is not None:
                annotation.offset_left = int(roi.get("offset_left", 0))
                annotation.offset_top = int(roi.get("offset_top", 0))
                annotation.width = int(roi.get("width", 0))
                annotation.height = int(roi.get("height", 0))

        destination = root.find(".//destination")
        if destination is not None:
            annotation.micrometer_per_pixel_x = float(
                destination.get("micrometer_per_pixel_x", 0.0)
            )
            annotation.micrometer_per_pixel_y = float(
                destination.get("micrometer_per_pixel_y", 0.0)
            )

        for anno_elem in root.findall(".//bounding_annotation"):
            name = anno_elem.get("name", "")
            region_type = anno_elem.get("type", "polygon")
            color = anno_elem.get("color_bgr", "")
            guid = anno_elem.get("guid", "")

            if color and color.startswith("FF"):
                try:
                    bgr = color[2:]
                    rgb = bgr[4:6] + bgr[2:4] + bgr[0:2]
                    color = f"#{rgb}"
                except:
                    color = "#F4FA58"

            region = Region(name=name, region_type="Polygon", color=color, guid=guid)

            for p_elem in anno_elem.findall("./p"):
                x = int(p_elem.get("x", 0)) + annotation.offset_left
                y = int(p_elem.get("y", 0)) + annotation.offset_top
                region.add_coordinate(x, y)

            annotation.add_region(region)

        return annotation

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "HistechAnnotation":
        file_path = Path(file_path)
        with open(file_path, "r") as f:
            xml_string = f.read()
        return HistechAnnotation.from_string(xml_string)

    def to_asap(self) -> ASAPAnnotation:
        asap = ASAPAnnotation()

        for region in self.regions:
            asap_region = Region(
                name=region.name,
                region_type="Polygon",
                color=region.color,
                guid=region.guid,
            )

            for coord in region.coordinates:
                asap_region.add_coordinate(coord.x, coord.y)

            asap.add_region(asap_region)

        return asap

    def to_geojson(self) -> GeoJSONAnnotation:
        return self.to_asap().to_geojson()
