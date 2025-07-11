import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Union, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from functools import lru_cache

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

    def _normalize_geometry_type(self, asap_type: str, coords_list: list) -> str:
        asap_type_lower = asap_type.lower()

        if asap_type_lower in ["rectangle", "polygon", "spline", "freehand"]:
            return "Polygon"
        elif asap_type_lower in ["line", "linestring"]:
            return "LineString"
        elif asap_type_lower in ["point", "dot"]:
            return "Point"
        else:
            if len(coords_list) == 1:
                return "Point"
            elif len(coords_list) == 2:
                return "LineString"
            else:
                return "Polygon"

    def to_geojson(self) -> "GeoJSONAnnotation":
        geojson = GeoJSONAnnotation()

        for region in self.regions:
            if len(region.coordinates) == 0:
                continue

            coords_list = [coord.to_list() for coord in region.coordinates]
            geometry_type = self._normalize_geometry_type(
                region.region_type, coords_list
            )

            if geometry_type == "Polygon":
                if len(coords_list) < 3:
                    continue
                if coords_list[0] != coords_list[-1]:
                    coords_list.append(coords_list[0])
                coordinates = [coords_list]
            elif geometry_type == "LineString":
                if len(coords_list) < 2:
                    continue
                coordinates = coords_list
            elif geometry_type == "Point":
                if len(coords_list) != 1:
                    continue
                coordinates = coords_list[0]
            else:
                continue

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
                "geometry": {"type": geometry_type, "coordinates": coordinates},
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
            geometry_type = feature["geometry"]["type"]
            properties = feature.get("properties", {})

            region = Region(
                name=properties.get("name", "Region"),
                region_type=properties.get("type", geometry_type),
                color=properties.get("color", "#F4FA58"),
                group=properties.get("group", "None"),
                guid=feature.get("id", str(uuid.uuid4())),
            )

            if geometry_type == "Polygon":
                coord_list = feature["geometry"]["coordinates"][0]
                if len(coord_list) > 1 and coord_list[0] == coord_list[-1]:
                    coord_list = coord_list[:-1]
                for x, y in coord_list:
                    region.add_coordinate(x, y)
            elif geometry_type == "LineString":
                coord_list = feature["geometry"]["coordinates"]
                for x, y in coord_list:
                    region.add_coordinate(x, y)
            elif geometry_type == "Point":
                x, y = feature["geometry"]["coordinates"]
                region.add_coordinate(x, y)
            else:
                continue

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
        self.mask: Optional[np.ndarray] = None
        self.metadata = metadata or ImageMetadata()
        self.label_mapping: Dict[int, str] = {}
        self.downsample_factor: float = 1.0
        self._bounds_cache: Optional[Tuple[float, float, float, float]] = None

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "BinaryMaskAnnotation":
        try:
            from PIL import Image
        except ImportError:
            raise ImportError(
                "Pillow is required for binary mask support. Install with: pip install Pillow"
            )

        annotation = BinaryMaskAnnotation()
        with Image.open(file_path) as img:
            annotation.mask = np.array(img.convert("L")).astype(np.uint8)
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
            self._save_image_format(output_path)
        else:
            self._save_tiff_format(output_path)

    def _save_image_format(self, output_path: Path) -> None:
        try:
            from PIL import Image
        except ImportError:
            raise ImportError(
                "Pillow is required for PNG/JPG support. Install with: pip install Pillow"
            )

        mask_binary = (self.mask > 0).astype(np.uint8) * 255
        Image.fromarray(mask_binary).save(output_path)

    def _save_tiff_format(self, output_path: Path) -> None:
        try:
            from PIL import Image
            import rasterio
            import warnings
        except ImportError:
            raise ImportError("Pillow and rasterio are required for TIFF support")

        Image.MAX_IMAGE_PIXELS = None

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", category=rasterio.errors.NotGeoreferencedWarning
            )

            mask_binary = (self.mask > 0).astype(np.uint8) * 255
            height, width = mask_binary.shape

            if self.metadata.mpp_x > 0:
                pixel_size_um = self.metadata.mpp_x * self.downsample_factor
            else:
                pixel_size_um = self.downsample_factor

            pixels_per_unit = 10000.0 / pixel_size_um

            profile = {
                "driver": "GTiff",
                "dtype": "uint8",
                "width": width,
                "height": height,
                "count": 1,
                "compress": "lzw",
                "tiled": True,
                "blockxsize": min(512, width),
                "blockysize": min(512, height),
                "BIGTIFF": "YES",
            }

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(mask_binary, 1)

                dst.update_tags(
                    TIFFTAG_XRESOLUTION=pixels_per_unit,
                    TIFFTAG_YRESOLUTION=pixels_per_unit,
                    TIFFTAG_RESOLUTIONUNIT=3,
                    ImageDescription=f"Binary mask, pixel size: {pixel_size_um:.3f} μm/pixel, downsample: {self.downsample_factor}x",
                )

    @lru_cache(maxsize=1)
    def _get_bounds(self) -> Tuple[float, float, float, float]:
        if self._bounds_cache is not None:
            return self._bounds_cache
        return (
            0,
            0,
            self.mask.shape[1] if self.mask is not None else 0,
            self.mask.shape[0] if self.mask is not None else 0,
        )

    def to_geojson(self) -> GeoJSONAnnotation:
        if self.mask is None:
            raise ValueError("No mask data to convert")

        try:
            import rasterio.features
            import shapely.geometry
        except ImportError:
            raise ImportError(
                "rasterio, shapely, and numpy are required for mask to polygon conversion"
            )

        geojson = GeoJSONAnnotation()

        for label_value, label_name in self.label_mapping.items():
            polygons = self._extract_polygons_for_label(label_value)
            for polygon in polygons:
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

    def _extract_polygons_for_label(self, label_value: int) -> List[Any]:
        import rasterio.features
        import shapely.geometry

        polygons = []
        for geom, value in rasterio.features.shapes(
            self.mask.astype(np.int16),
            mask=(self.mask == label_value),
            transform=rasterio.Affine(1.0, 0, 0, 0, 1.0, 0),
        ):
            polygon = shapely.geometry.shape(geom).buffer(0)
            if polygon.is_valid and not polygon.is_empty:
                polygons.append(polygon)
        return polygons

    def to_asap(self) -> ASAPAnnotation:
        return self.to_geojson().to_asap()

    @classmethod
    def from_geojson(
        cls,
        geojson: GeoJSONAnnotation,
        metadata: Optional[ImageMetadata] = None,
        downsample_factor: float = 1.0,
        enable_parallel: bool = True,
    ) -> "BinaryMaskAnnotation":
        try:
            import rasterio.features
            import shapely.geometry
        except ImportError:
            raise ImportError(
                "rasterio, shapely, and numpy are required for polygon to mask conversion"
            )

        annotation = cls(metadata=metadata)
        annotation.downsample_factor = downsample_factor

        if metadata and metadata.width > 0:
            mask_width = int(metadata.width / downsample_factor)
            mask_height = int(metadata.height / downsample_factor)
            offset_x, offset_y = metadata.offset_x, metadata.offset_y
        else:
            mask_width, mask_height, offset_x, offset_y = (
                cls._calculate_optimal_dimensions(geojson, downsample_factor)
            )

        annotation.mask = np.zeros((mask_height, mask_width), dtype=np.uint8)

        if enable_parallel and len(geojson.features) > 100:
            annotation._process_features_parallel(
                geojson, downsample_factor, offset_x, offset_y
            )
        else:
            annotation._process_features_sequential(
                geojson, downsample_factor, offset_x, offset_y
            )

        return annotation

    def _process_features_sequential(
        self,
        geojson: GeoJSONAnnotation,
        downsample_factor: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        import rasterio.features
        import shapely.geometry

        shapes = []
        label_counter = 1

        for feature in geojson.features:
            if feature["geometry"]["type"] == "Polygon":
                polygon, label_value, label_name = self._process_feature(
                    feature, downsample_factor, offset_x, offset_y, label_counter
                )
                if polygon:
                    shapes.append((polygon, label_value))
                    self.label_mapping[label_value] = label_name
                label_counter += 1

        if shapes:
            self.mask = rasterio.features.rasterize(
                shapes,
                out_shape=self.mask.shape,
                fill=0,
                dtype=np.uint8,
                all_touched=True,
            )

    def _process_features_parallel(
        self,
        geojson: GeoJSONAnnotation,
        downsample_factor: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        import rasterio.features

        chunk_size = 50
        feature_chunks = [
            geojson.features[i : i + chunk_size]
            for i in range(0, len(geojson.features), chunk_size)
        ]

        all_shapes = []
        label_counter = 1

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(
                    self._process_chunk,
                    chunk,
                    downsample_factor,
                    offset_x,
                    offset_y,
                    label_counter + i * chunk_size,
                )
                for i, chunk in enumerate(feature_chunks)
            ]

            for future in futures:
                shapes, mappings = future.result()
                all_shapes.extend(shapes)
                self.label_mapping.update(mappings)

        if all_shapes:
            self.mask = rasterio.features.rasterize(
                all_shapes,
                out_shape=self.mask.shape,
                fill=0,
                dtype=np.uint8,
                all_touched=True,
            )

    def _process_chunk(
        self,
        features: List[Dict],
        downsample_factor: float,
        offset_x: float,
        offset_y: float,
        start_label: int,
    ) -> Tuple[List[Tuple[Any, int]], Dict[int, str]]:
        import shapely.geometry

        shapes = []
        mappings = {}

        for i, feature in enumerate(features):
            if feature["geometry"]["type"] == "Polygon":
                polygon, label_value, label_name = self._process_feature(
                    feature, downsample_factor, offset_x, offset_y, start_label + i
                )
                if polygon:
                    shapes.append((polygon, label_value))
                    mappings[label_value] = label_name

        return shapes, mappings

    def _process_feature(
        self,
        feature: Dict,
        downsample_factor: float,
        offset_x: float,
        offset_y: float,
        label_counter: int,
    ) -> Tuple[Optional[Any], int, str]:
        import shapely.geometry

        properties = feature.get("properties", {})
        label_value = properties.get("label_value", label_counter)
        label_name = properties.get("name", f"region_{label_value}")

        coords = feature["geometry"]["coordinates"][0]
        scaled_coords = [
            ((x - offset_x) / downsample_factor, (y - offset_y) / downsample_factor)
            for x, y in coords
        ]

        try:
            polygon = shapely.geometry.Polygon(scaled_coords)
            if polygon.is_valid and not polygon.is_empty:
                return polygon, label_value, label_name
        except Exception:
            pass

        return None, label_value, label_name

    @staticmethod
    def _calculate_optimal_dimensions(
        geojson: GeoJSONAnnotation, downsample_factor: float
    ) -> Tuple[int, int, float, float]:
        if not geojson.features:
            raise ValueError("No features found in GeoJSON")

        all_coords = []
        for feature in geojson.features:
            if feature["geometry"]["type"] == "Polygon":
                coords = feature["geometry"]["coordinates"][0]
                all_coords.extend(coords)

        if not all_coords:
            raise ValueError("No polygon coordinates found in GeoJSON")

        coords_array = np.array(all_coords)
        min_x, min_y = coords_array.min(axis=0)
        max_x, max_y = coords_array.max(axis=0)

        mask_width = int((max_x - min_x) / downsample_factor)
        mask_height = int((max_y - min_y) / downsample_factor)

        return mask_width, mask_height, min_x, min_y
