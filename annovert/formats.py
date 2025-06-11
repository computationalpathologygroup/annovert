import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Union, Optional, Tuple

from .basecore import Annotation, Region, ImageMetadata


class ASAPAnnotation(Annotation):
    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
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
        with open(file_path, "r") as f:
            return ASAPAnnotation.from_string(f.read())

    def to_xml(self) -> str:
        root = ET.Element("ASAP_Annotations")
        annotations = ET.SubElement(root, "Annotations")

        for region in self.regions:
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

        ET.SubElement(root, "AnnotationGroups")
        xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
        return '<?xml version="1.0"?>\n' + xml_str

    def save(self, output_path: Union[str, Path]) -> None:
        with open(output_path, "w") as f:
            f.write(self.to_xml())

    def to_geojson(self) -> "GeoJSONAnnotation":
        geojson = GeoJSONAnnotation()

        for region in self.regions:
            if len(region.coordinates) < 3:
                continue

            coords_list = [coord.to_list() for coord in region.coordinates]
            if coords_list[0] != coords_list[-1]:
                coords_list.append(coords_list[0])

            properties = {
                "objectType": "annotation",
                "name": region.name,
                "type": region.region_type,
                "source": "asap_xml",
            }

            if region.group and region.group != "None":
                properties["group"] = region.group

            feature = {
                "type": "Feature",
                "id": region.guid,
                "geometry": {"type": region.region_type, "coordinates": [coords_list]},
                "properties": properties,
            }
            geojson.features.append(feature)
        return geojson


class GeoJSONAnnotation(Annotation):
    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.features: List[Dict[str, Any]] = []

    def add_feature(self, feature: Dict[str, Any]) -> None:
        self.features.append(feature)

    @staticmethod
    def from_string(json_string: str) -> "GeoJSONAnnotation":
        data = json.loads(json_string)

        if data.get("metadata", {}).get("qupath_mrxs"):
            from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

            return QuPathMRXSGeoJSONAnnotation.from_string(json_string)

        annotation = GeoJSONAnnotation()
        if "features" in data:
            annotation.features = data["features"]
        return annotation

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "GeoJSONAnnotation":
        with open(file_path, "r") as f:
            return GeoJSONAnnotation.from_string(f.read())

    def to_json(self) -> str:
        geojson = {"type": "FeatureCollection", "features": self.features}
        return json.dumps(geojson, indent=2)

    def save(self, output_path: Union[str, Path]) -> None:
        with open(output_path, "w") as f:
            f.write(self.to_json())

    def to_asap(self) -> ASAPAnnotation:
        asap = ASAPAnnotation()

        for feature in self.features:
            if feature["geometry"]["type"] == "Polygon":
                properties = feature.get("properties", {})
                region = Region(
                    name=properties.get("name", "Region"),
                    region_type=properties.get("type", "Polygon"),
                    color=properties.get("color", "#F4FA58"),
                    group=properties.get("group", "None"),
                    guid=feature.get("id", str(uuid.uuid4())),
                )

                coord_list = feature["geometry"]["coordinates"][0]
                if len(coord_list) > 1 and coord_list[0] == coord_list[-1]:
                    coord_list = coord_list[:-1]

                for x, y in coord_list:
                    region.add_coordinate(x, y)

                asap.add_region(region)
        return asap


class HistechAnnotation(Annotation):
    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
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
            color = anno_elem.get("color_bgr", "")
            guid = anno_elem.get("guid", "")

            try:
                if color and color.startswith("FF") and len(color) >= 8:
                    bgr = color[2:]
                    rgb = bgr[4:6] + bgr[2:4] + bgr[0:2]
                    color = f"#{rgb}"
                elif not color or not color.startswith("#") or len(color) != 7:
                    color = "#F4FA58"
            except Exception:
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
        with open(file_path, "r") as f:
            return HistechAnnotation.from_string(f.read())

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


class BinaryMaskAnnotation(Annotation):
    def __init__(
        self, name: str = "", metadata: Optional[ImageMetadata] = None
    ) -> None:
        super().__init__(name=name)
        self.mask: Optional[Any] = None
        self.metadata = metadata or ImageMetadata()
        self.label_mapping: Dict[int, str] = {}

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "BinaryMaskAnnotation":
        try:
            import rasterio  # type: ignore
            import numpy as np
        except ImportError:
            raise ImportError(
                "rasterio and numpy are required for binary mask support. Install with: pip install rasterio numpy"
            )

        annotation = BinaryMaskAnnotation()
        with rasterio.open(file_path) as src:
            annotation.mask = src.read(1).astype(np.uint8)
            unique_labels = np.unique(annotation.mask)
            unique_labels = unique_labels[unique_labels > 0]
            for label in unique_labels:
                annotation.label_mapping[int(label)] = f"region_{label}"
        return annotation

    def save(self, output_path: Union[str, Path]) -> None:
        if self.mask is None:
            raise ValueError("No mask data to save")

        output_path = Path(output_path)
        suffix = output_path.suffix.lower()

        if suffix in [".png", ".jpg", ".jpeg"]:
            try:
                from PIL import Image  # type: ignore
            except ImportError:
                raise ImportError(
                    "Pillow is required for PNG/JPG support. Install with: pip install Pillow"
                )

            mask_binary = (self.mask > 0).astype("uint8") * 255
            Image.fromarray(mask_binary).save(output_path)
        else:
            try:
                import rasterio  # type: ignore
            except ImportError:
                raise ImportError(
                    "rasterio is required for TIF support. Install with: pip install rasterio"
                )

            mask_binary = (self.mask > 0).astype("uint8") * 255
            transform = rasterio.transform.from_bounds(
                0,
                0,
                self.mask.shape[1],
                self.mask.shape[0],
                self.mask.shape[1],
                self.mask.shape[0],
            )

            with rasterio.open(
                output_path,
                "w",
                driver="GTiff",
                height=self.mask.shape[0],
                width=self.mask.shape[1],
                count=1,
                dtype="uint8",
                transform=transform,
                compress="lzw",
            ) as dst:
                dst.write(mask_binary, 1)

    def to_geojson(self) -> GeoJSONAnnotation:
        if self.mask is None:
            raise ValueError("No mask data to convert")

        try:
            import rasterio.features  # type: ignore
            import shapely.geometry  # type: ignore
            import numpy as np
        except ImportError:
            raise ImportError(
                "rasterio, shapely, and numpy are required for mask to polygon conversion. Install with: pip install rasterio shapely numpy"
            )

        geojson = GeoJSONAnnotation()
        for label_value, label_name in self.label_mapping.items():
            for geom, value in rasterio.features.shapes(
                self.mask.astype(np.int16),
                mask=(self.mask == label_value),
                transform=rasterio.Affine(1.0, 0, 0, 0, 1.0, 0),
            ):
                polygon = shapely.geometry.shape(geom).buffer(0)
                if polygon.geom_type == "Polygon" and len(polygon.exterior.coords) > 3:
                    coords_list = list(polygon.exterior.coords)
                    feature = {
                        "type": "Feature",
                        "id": str(uuid.uuid4()),
                        "geometry": {"type": "Polygon", "coordinates": [coords_list]},
                        "properties": {
                            "objectType": "annotation",
                            "name": label_name,
                            "type": "Polygon",
                            "source": "binary_mask",
                            "label_value": label_value,
                        },
                    }
                    geojson.add_feature(feature)
        return geojson

    def to_asap(self) -> ASAPAnnotation:
        return self.to_geojson().to_asap()

    @classmethod
    def from_geojson(
        cls,
        geojson: GeoJSONAnnotation,
        metadata: Optional[ImageMetadata] = None,
        downsample_factor: float = 1.0,
    ) -> "BinaryMaskAnnotation":
        try:
            import rasterio.features  # type: ignore
            import shapely.geometry  # type: ignore
            import numpy as np
        except ImportError:
            raise ImportError(
                "rasterio, shapely, and numpy are required for polygon to mask conversion. Install with: pip install rasterio shapely numpy"
            )

        annotation = cls(metadata=metadata)

        if metadata and metadata.width > 0:
            mask_width = int(metadata.width / downsample_factor)
            mask_height = int(metadata.height / downsample_factor)
            annotation.mask = np.zeros((mask_height, mask_width), dtype=np.uint8)
            offset_x, offset_y = 0, 0
        else:
            (
                mask_width,
                mask_height,
                offset_x,
                offset_y,
            ) = cls._calculate_mask_dimensions_with_offset(geojson, downsample_factor)
            annotation.mask = np.zeros((mask_height, mask_width), dtype=np.uint8)

        shapes = []
        label_counter = 1

        for feature in geojson.features:
            if feature["geometry"]["type"] == "Polygon":
                properties = feature.get("properties", {})
                label_value = properties.get("label_value", label_counter)
                label_name = properties.get("name", f"region_{label_value}")
                annotation.label_mapping[label_value] = label_name

                coords = feature["geometry"]["coordinates"][0]
                scaled_coords = [
                    (
                        (x - offset_x) / downsample_factor,
                        (y - offset_y) / downsample_factor,
                    )
                    for x, y in coords
                ]
                polygon = shapely.geometry.Polygon(scaled_coords)

                if polygon.is_valid and not polygon.is_empty:
                    shapes.append((polygon, label_value))
                label_counter += 1

        if shapes:
            annotation.mask = rasterio.features.rasterize(
                shapes, out_shape=(mask_height, mask_width), fill=0, dtype=np.uint8
            )

        print(
            f"Created mask {mask_width}x{mask_height}, values: {np.unique(annotation.mask)}, {len(shapes)} polygons"
        )
        return annotation

    @staticmethod
    def _calculate_mask_dimensions_with_offset(
        geojson: GeoJSONAnnotation, downsample_factor: float
    ) -> Tuple[int, int, float, float]:
        all_coords = []
        for feature in geojson.features:
            if feature["geometry"]["type"] == "Polygon":
                coords = feature["geometry"]["coordinates"][0]
                all_coords.extend(coords)

        if not all_coords:
            raise ValueError("No polygon coordinates found in GeoJSON")

        xs, ys = zip(*all_coords)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        mask_width = int((max_x - min_x) / downsample_factor)
        mask_height = int((max_y - min_y) / downsample_factor)

        return mask_width, mask_height, min_x, min_y
