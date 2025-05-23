import json
from typing import Dict, Optional

from .basecore import ImageMetadata
from .formats import GeoJSONAnnotation


class QuPathMRXSGeoJSONAnnotation(GeoJSONAnnotation):
    def __init__(self, name: str = "", metadata: Optional[ImageMetadata] = None):
        super().__init__(name)
        self.metadata = metadata or ImageMetadata()

    def add_feature_with_transform(self, feature: Dict) -> None:
        transformed_feature = self._transform_feature(feature)
        self.features.append(transformed_feature)

    def _transform_feature(self, feature: Dict) -> Dict:
        if self.metadata.offset_x == 0 and self.metadata.offset_y == 0:
            return feature

        transformed = feature.copy()

        if "geometry" in transformed and "coordinates" in transformed["geometry"]:
            coords = transformed["geometry"]["coordinates"]

            if transformed["geometry"]["type"] == "Polygon":
                transformed_coords = []
                for ring in coords:
                    transformed_ring = [
                        [x - self.metadata.offset_x, y - self.metadata.offset_y]
                        for x, y in ring
                    ]
                    transformed_coords.append(transformed_ring)
                transformed["geometry"]["coordinates"] = transformed_coords
            elif transformed["geometry"]["type"] == "Point":
                x, y = coords
                transformed["geometry"]["coordinates"] = [
                    x - self.metadata.offset_x,
                    y - self.metadata.offset_y,
                ]
            elif transformed["geometry"]["type"] == "LineString":
                transformed["geometry"]["coordinates"] = [
                    [x - self.metadata.offset_x, y - self.metadata.offset_y]
                    for x, y in coords
                ]

        if "properties" not in transformed:
            transformed["properties"] = {}

        transformed["properties"].update(
            {
                "qupath_mrxs": True,
                "offset_x": self.metadata.offset_x,
                "offset_y": self.metadata.offset_y,
                "mpp_x": self.metadata.mpp_x,
                "mpp_y": self.metadata.mpp_y,
                "source_format": "mrxs",
            }
        )

        return transformed

    @classmethod
    def from_geojson(
        cls, geojson: GeoJSONAnnotation, metadata: Optional[ImageMetadata] = None
    ) -> "QuPathMRXSGeoJSONAnnotation":
        qupath_geojson = cls(metadata=metadata)
        for feature in geojson.features:
            qupath_geojson.add_feature_with_transform(feature)
        return qupath_geojson

    def to_json(self) -> str:
        geojson = {
            "type": "FeatureCollection",
            "features": self.features,
            "metadata": {
                "qupath_mrxs": True,
                "image_offset_x": self.metadata.offset_x,
                "image_offset_y": self.metadata.offset_y,
                "microns_per_pixel_x": self.metadata.mpp_x,
                "microns_per_pixel_y": self.metadata.mpp_y,
                "image_width": self.metadata.width,
                "image_height": self.metadata.height,
                "level_0_width": self.metadata.level_0_width,
                "level_0_height": self.metadata.level_0_height,
            },
        }

        return json.dumps(geojson, indent=2)

    def to_standard_geojson(self) -> GeoJSONAnnotation:
        standard = GeoJSONAnnotation(self.name)

        for feature in self.features:
            untransformed = feature.copy()

            if (
                "geometry" in untransformed
                and "coordinates" in untransformed["geometry"]
            ):
                coords = untransformed["geometry"]["coordinates"]

                if untransformed["geometry"]["type"] == "Polygon":
                    untransformed_coords = []
                    for ring in coords:
                        untransformed_ring = [
                            [x + self.metadata.offset_x, y + self.metadata.offset_y]
                            for x, y in ring
                        ]
                        untransformed_coords.append(untransformed_ring)
                    untransformed["geometry"]["coordinates"] = untransformed_coords
                elif untransformed["geometry"]["type"] == "Point":
                    x, y = coords
                    untransformed["geometry"]["coordinates"] = [
                        x + self.metadata.offset_x,
                        y + self.metadata.offset_y,
                    ]
                elif untransformed["geometry"]["type"] == "LineString":
                    untransformed["geometry"]["coordinates"] = [
                        [x + self.metadata.offset_x, y + self.metadata.offset_y]
                        for x, y in coords
                    ]

            if "properties" in untransformed:
                props_copy = untransformed["properties"].copy()
                for key in [
                    "qupath_mrxs",
                    "offset_x",
                    "offset_y",
                    "mpp_x",
                    "mpp_y",
                    "source_format",
                ]:
                    props_copy.pop(key, None)
                untransformed["properties"] = props_copy

            standard.add_feature(untransformed)

        return standard

    @staticmethod
    def from_string(json_string: str) -> "QuPathMRXSGeoJSONAnnotation":
        data = json.loads(json_string)

        metadata = ImageMetadata()
        if "metadata" in data:
            meta = data["metadata"]
            metadata = ImageMetadata(
                offset_x=meta.get("image_offset_x", 0),
                offset_y=meta.get("image_offset_y", 0),
                mpp_x=meta.get("microns_per_pixel_x", 1.0),
                mpp_y=meta.get("microns_per_pixel_y", 1.0),
                width=meta.get("image_width", 0),
                height=meta.get("image_height", 0),
                level_0_width=meta.get("level_0_width", 0),
                level_0_height=meta.get("level_0_height", 0),
            )

        annotation = QuPathMRXSGeoJSONAnnotation(metadata=metadata)

        if "features" in data:
            annotation.features = data["features"]

        return annotation
