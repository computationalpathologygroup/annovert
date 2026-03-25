import json
import logging
import math
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .basecore import Annotation, ImageMetadata, Region

logger = logging.getLogger(__name__)


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


class HamamatsuNDPA(Annotation):
    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.regions: List[Region] = []
        self.px_nm: Optional[float] = None
        self.py_nm: Optional[float] = None
        self.xoffset_nm: Optional[float] = None
        self.yoffset_nm: Optional[float] = None
        self._raw_coordinates: Dict[str, List[Tuple[float, float]]] = {}

    def add_region(self, region: Region) -> None:
        self.regions.append(region)

    def set_params(
        self,
        px_nm: float = 1,
        py_nm: float = 1,
        xoffset_nm: float = 0,
        yoffset_nm: float = 0,
    ) -> None:
        """Set physical coordinate parameters for NDPA format."""
        self.px_nm = px_nm
        self.py_nm = py_nm
        self.xoffset_nm = xoffset_nm
        self.yoffset_nm = yoffset_nm

        # Apply coordinate conversion to existing regions
        self._apply_coordinate_conversion()

    def _apply_coordinate_conversion(self) -> None:
        """Apply coordinate conversion to all regions using current parameters."""
        if self.px_nm is None or self.py_nm is None:
            return

        for region in self.regions:
            region_id = region.guid
            if region_id in self._raw_coordinates:
                # Clear existing converted coordinates
                region.coordinates.clear()

                # Convert and add coordinates
                for x_nm, y_nm in self._raw_coordinates[region_id]:
                    x_pixel, y_pixel = self.ndpacoords_to_coords(x_nm, y_nm)
                    region.add_coordinate(x_pixel, y_pixel)

    def ndpacoords_to_coords(self, x: float, y: float) -> Tuple[float, float]:
        """Convert physical NDPA coordinates to pixel coordinates."""
        if self.px_nm is None or self.py_nm is None:
            return x, y

        x_pixel = (x - (self.xoffset_nm or 0)) / self.px_nm
        y_pixel = (y - (self.yoffset_nm or 0)) / self.py_nm
        return x_pixel, y_pixel

    def coords_to_ndpacoords(self, x: float, y: float) -> Tuple[float, float]:
        """Convert pixel coordinates to physical NDPA coordinates."""
        if self.px_nm is None or self.py_nm is None:
            return x, y

        x_physical = x * self.px_nm + (self.xoffset_nm or 0)
        y_physical = y * self.py_nm + (self.yoffset_nm or 0)
        return x_physical, y_physical

    @staticmethod
    def from_string(xml_string: str) -> "HamamatsuNDPA":
        """Parse NDPA XML content and create HamamatsuNDPA instance."""
        annotation = HamamatsuNDPA()
        root = ET.fromstring(xml_string)

        # Process all ndpviewstate nodes
        nodes = root.findall("ndpviewstate")

        for ndpviewstate_node in nodes:
            # Get annotation metadata
            title_elem = ndpviewstate_node.find("title")
            details_elem = ndpviewstate_node.find("details")

            annotation_name = (
                title_elem.text if title_elem is not None and title_elem.text else ""
            )
            class_name = (
                details_elem.text
                if details_elem is not None and details_elem.text
                else ""
            )

            # Process annotation nodes within this ndpviewstate
            for annotation_node in ndpviewstate_node.findall("annotation"):
                annotation_type = annotation_node.get("type", "").upper()
                color = annotation_node.get("color", "#F4FA58")

                # Convert BGR color format if needed
                if color and not color.startswith("#"):
                    try:
                        color_int = int(color, 16) if isinstance(color, str) else color
                        # Convert BGR to RGB hex
                        b = (color_int >> 16) & 0xFF
                        g = (color_int >> 8) & 0xFF
                        r = color_int & 0xFF
                        color = f"#{r:02x}{g:02x}{b:02x}"
                    except (ValueError, TypeError):
                        color = "#F4FA58"

                region = Region(
                    name=annotation_name or class_name or f"Region_{annotation_type}",
                    region_type="Polygon"
                    if annotation_type == "FREEHAND"
                    else annotation_type,
                    color=color,
                    group=class_name
                    if class_name and class_name != annotation_name
                    else None,
                )

                # Store raw coordinates for later conversion
                raw_coords = []

                # Parse coordinates based on annotation type
                if annotation_type == "FREEHAND":
                    pointlist_node = annotation_node.find("pointlist")
                    if pointlist_node is not None:
                        for point_node in pointlist_node.findall("point"):
                            x_elem = point_node.find("x")
                            y_elem = point_node.find("y")
                            if x_elem is not None and y_elem is not None:
                                x = float(x_elem.text)
                                y = float(y_elem.text)
                                raw_coords.append((x, y))

                elif annotation_type == "CIRCLE":
                    x_elem = annotation_node.find("x")
                    y_elem = annotation_node.find("y")
                    radius_elem = annotation_node.find("radius")

                    if all(elem is not None for elem in [x_elem, y_elem, radius_elem]):
                        x = float(x_elem.text)
                        y = float(y_elem.text)
                        radius = float(radius_elem.text)

                        # Generate circle points in raw coordinates
                        num_points = 50
                        for i in range(num_points):
                            angle = 2 * math.pi * i / num_points
                            circle_x = x + radius * math.cos(angle)
                            circle_y = y + radius * math.sin(angle)
                            raw_coords.append((circle_x, circle_y))

                elif annotation_type == "PIN":
                    x_elem = annotation_node.find("x")
                    y_elem = annotation_node.find("y")

                    if x_elem is not None and y_elem is not None:
                        x = float(x_elem.text)
                        y = float(y_elem.text)
                        raw_coords.append((x, y))
                        region.region_type = "Point"

                elif annotation_type == "LINEARMEASURE":
                    x1_elem = annotation_node.find("x1")
                    y1_elem = annotation_node.find("y1")
                    x2_elem = annotation_node.find("x2")
                    y2_elem = annotation_node.find("y2")

                    if all(
                        elem is not None
                        for elem in [x1_elem, y1_elem, x2_elem, y2_elem]
                    ):
                        x1, y1 = float(x1_elem.text), float(y1_elem.text)
                        x2, y2 = float(x2_elem.text), float(y2_elem.text)

                        raw_coords.append((x1, y1))
                        raw_coords.append((x2, y2))
                        region.region_type = "LineString"

                # Store raw coordinates and add region if it has coordinates
                if raw_coords:
                    annotation._raw_coordinates[region.guid] = raw_coords
                    # If parameters are available, convert coordinates immediately
                    if annotation.px_nm is not None and annotation.py_nm is not None:
                        for x_nm, y_nm in raw_coords:
                            x_pixel, y_pixel = annotation.ndpacoords_to_coords(
                                x_nm, y_nm
                            )
                            region.add_coordinate(x_pixel, y_pixel)
                    # Always add region, even if coordinates aren't converted yet
                    annotation.add_region(region)

        return annotation

    @staticmethod
    def from_file(file_path: Union[str, Path]) -> "HamamatsuNDPA":
        """Load NDPA annotation from file."""
        file_path = Path(file_path)

        with open(file_path, "r", encoding="utf-8") as f:
            annotation = HamamatsuNDPA.from_string(f.read())

        # Try to load NDPI parameters if corresponding NDPI file exists
        ndpi_path = None
        if file_path.name.endswith(".ndpi.ndpa"):
            # Look for .ndpi file - remove .ndpa suffix
            base_name = file_path.name[:-5]  # Remove .ndpa (keeps .ndpi)
            potential_ndpi = file_path.parent / base_name
            if potential_ndpi.exists():
                ndpi_path = potential_ndpi
        elif file_path.name.endswith(".ndpa"):
            # Look for .ndpi file with same base name
            base_name = file_path.name[:-5]  # Remove .ndpa
            potential_ndpi = file_path.parent / (base_name + ".ndpi")
            if potential_ndpi.exists():
                ndpi_path = potential_ndpi

        if ndpi_path:
            try:
                annotation._load_ndpi_parameters(ndpi_path)
            except Exception as e:
                logger.warning(f"Could not load NDPI parameters from {ndpi_path}: {e}")

        return annotation

    def _load_ndpi_parameters(self, ndpi_path: Union[str, Path]) -> None:
        """Load pixel size and offset parameters from NDPI file."""
        try:
            import tifffile
        except ImportError:
            logger.warning("tifffile not available, cannot read NDPI parameters")
            return

        try:
            with tifffile.TiffFile(ndpi_path) as tif:
                # Get pixel size from resolution tags
                if (
                    "XResolution" in tif.pages[0].tags
                    and "YResolution" in tif.pages[0].tags
                ):
                    # Resolution is in pixels per centimeter
                    xres = tif.pages[0].tags["XResolution"].value[0]
                    yres = tif.pages[0].tags["YResolution"].value[0]

                    # Convert to nanometers per pixel
                    px_nm = (1e-2 / xres) * 1e9  # cm to nm
                    py_nm = (1e-2 / yres) * 1e9  # cm to nm

                    # Get image center
                    width = tif.pages[0].tags["ImageWidth"].value
                    height = tif.pages[0].tags["ImageLength"].value
                    xcenter_nm = (width / 2) * px_nm
                    ycenter_nm = (height / 2) * py_nm

                    # Get slide offsets from NDPI-specific tags if available
                    xoffset_nm = 0
                    yoffset_nm = 0

                    if hasattr(tif.pages[0], "ndpi_tags"):
                        ndpi_tags = tif.pages[0].ndpi_tags
                        if "XOffsetFromSlideCenter" in ndpi_tags:
                            xoffset_nm = (
                                ndpi_tags["XOffsetFromSlideCenter"] - xcenter_nm
                            )
                        if "YOffsetFromSlideCenter" in ndpi_tags:
                            yoffset_nm = (
                                ndpi_tags["YOffsetFromSlideCenter"] - ycenter_nm
                            )

                    # Set the parameters
                    self.set_params(px_nm, py_nm, xoffset_nm, yoffset_nm)
                    logger.debug(
                        f"Loaded NDPI parameters: px_nm={px_nm:.2f}, py_nm={py_nm:.2f}"
                    )
                else:
                    logger.warning("Could not find resolution tags in NDPI file")
        except Exception as e:
            logger.warning(f"Error reading NDPI file {ndpi_path}: {e}")

    def _normalize_geometry_type(self, ndpa_type: str, coords_list: list) -> str:
        """Convert NDPA annotation types to GeoJSON geometry types."""
        ndpa_type_upper = ndpa_type.upper()

        if ndpa_type_upper in ["FREEHAND", "CIRCLE"]:
            return "Polygon"
        elif ndpa_type_upper == "LINEARMEASURE":
            return "LineString"
        elif ndpa_type_upper == "PIN":
            return "Point"
        else:
            # Fallback based on coordinate count
            if len(coords_list) == 1:
                return "Point"
            elif len(coords_list) == 2:
                return "LineString"
            else:
                return "Polygon"

    def to_geojson(self) -> "GeoJSONAnnotation":
        """Convert to GeoJSON format."""
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
                # Ensure polygon is closed
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
                "source": "hamamatsu_ndpa",
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

    def to_asap(self) -> ASAPAnnotation:
        """Convert to ASAP format via GeoJSON."""
        return self.to_geojson().to_asap()

    def to_xml(self) -> str:
        """Convert back to NDPA XML format."""
        root = ET.Element("annotations")

        for i, region in enumerate(self.regions):
            # Create ndpviewstate node with id attribute
            ndpviewstate = ET.SubElement(root, "ndpviewstate")
            ndpviewstate.set("id", str(i + 1))  # Add id attribute starting from 1
            ET.SubElement(ndpviewstate, "title").text = region.name
            ET.SubElement(ndpviewstate, "details").text = region.group or region.name
            ET.SubElement(ndpviewstate, "coordformat").text = "nanometers"
            ET.SubElement(ndpviewstate, "lens").text = "40"
            ET.SubElement(ndpviewstate, "x").text = "0"
            ET.SubElement(ndpviewstate, "y").text = "0"
            ET.SubElement(ndpviewstate, "z").text = "0"

            # Create annotation node
            annotation_node = ET.SubElement(ndpviewstate, "annotation")
            annotation_node.set("type", region.region_type.lower())
            annotation_node.set("displayname", f"Annotate{region.region_type}")
            annotation_node.set("color", region.color or "#F4FA58")

            ET.SubElement(annotation_node, "measuretype").text = "0"

            # Add coordinates based on type
            region_type_upper = region.region_type.upper()

            if region_type_upper == "FREEHAND":
                ET.SubElement(annotation_node, "closed").text = "1"
                pointlist = ET.SubElement(annotation_node, "pointlist")

                for coord in region.coordinates:
                    point = ET.SubElement(pointlist, "point")
                    x_physical, y_physical = self.coords_to_ndpacoords(coord.x, coord.y)
                    ET.SubElement(point, "x").text = str(int(x_physical))
                    ET.SubElement(point, "y").text = str(int(y_physical))

            elif region_type_upper == "PIN" and len(region.coordinates) == 1:
                coord = region.coordinates[0]
                x_physical, y_physical = self.coords_to_ndpacoords(coord.x, coord.y)
                ET.SubElement(annotation_node, "x").text = str(int(x_physical))
                ET.SubElement(annotation_node, "y").text = str(int(y_physical))
                ET.SubElement(annotation_node, "icon").text = "placered"
                ET.SubElement(annotation_node, "stricon").text = "iconplacered"

            elif region_type_upper == "LINEARMEASURE" and len(region.coordinates) == 2:
                coord1, coord2 = region.coordinates[0], region.coordinates[1]
                x1_physical, y1_physical = self.coords_to_ndpacoords(coord1.x, coord1.y)
                x2_physical, y2_physical = self.coords_to_ndpacoords(coord2.x, coord2.y)

                ET.SubElement(annotation_node, "x1").text = str(int(x1_physical))
                ET.SubElement(annotation_node, "y1").text = str(int(y1_physical))
                ET.SubElement(annotation_node, "x2").text = str(int(x2_physical))
                ET.SubElement(annotation_node, "y2").text = str(int(y2_physical))

        # Convert to string with XML declaration
        xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

    def save(self, output_path: Union[str, Path]) -> None:
        """Save as NDPA file."""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.to_xml())


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

        if suffix in {".png", ".jpg", ".jpeg"}:
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
            import warnings

            from PIL import Image
        except ImportError:
            raise ImportError("Pillow is required for TIFF support")

        Image.MAX_IMAGE_PIXELS = None

        mask_binary = (self.mask > 0).astype(np.uint8) * 255
        height, width = mask_binary.shape

        if self.metadata and self.metadata.mpp_x > 0:
            pixel_size_um = self.metadata.mpp_x * self.downsample_factor
        else:
            default_original_pixel_size = 0.25
            pixel_size_um = default_original_pixel_size * self.downsample_factor

        dpi = 25400.0 / pixel_size_um

        estimated_size_gb = (height * width) / (1024**3)
        needs_bigtiff = estimated_size_gb > 3.5 or height > 65535 or width > 65535

        if needs_bigtiff:
            try:
                import rasterio

                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", category=rasterio.errors.NotGeoreferencedWarning
                    )

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
            except ImportError:
                raise ImportError(
                    "rasterio is required for large TIFF files. Install with: pip install rasterio"
                )
        else:
            img = Image.fromarray(mask_binary)
            img.save(
                output_path,
                format="TIFF",
                dpi=(dpi, dpi),
                compression="lzw",
                description=f"Binary mask, pixel size: {pixel_size_um:.3f} μm/pixel, downsample: {self.downsample_factor}x",
            )

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
