"""
Round-trip tests for every annotation format parser/serialiser.

Each class exercises:
  - parsing from fixture file
  - serialisation and re-parsing (round-trip)
  - conversion to at least one other format
  - save-to-disk and reload
"""
from pathlib import Path

import pytest

from annovert.formats import (
    ASAPAnnotation,
    BinaryMaskAnnotation,
    GeoJSONAnnotation,
    HamamatsuNDPA,
    HistechAnnotation,
)


class TestASAPAnnotation:
    def test_parse_from_file(self, asap_file: Path) -> None:
        anno = ASAPAnnotation.from_file(asap_file)
        assert len(anno.regions) == 1
        r = anno.regions[0]
        assert r.name == "tumor_0"
        assert r.group == "tumor"
        assert len(r.coordinates) == 4

    def test_round_trip_xml(self, asap_file: Path) -> None:
        original = ASAPAnnotation.from_file(asap_file)
        reloaded = ASAPAnnotation.from_string(original.to_xml())
        assert len(reloaded.regions) == len(original.regions)
        assert reloaded.regions[0].name == original.regions[0].name

    def test_to_geojson(self, asap_file: Path) -> None:
        geo = ASAPAnnotation.from_file(asap_file).to_geojson()
        assert len(geo.features) == 1
        assert geo.features[0]["geometry"]["type"] == "Polygon"

    def test_save_and_reload(self, asap_file: Path, tmp_path: Path) -> None:
        anno = ASAPAnnotation.from_file(asap_file)
        out = tmp_path / "out.xml"
        anno.save(out)
        reloaded = ASAPAnnotation.from_file(out)
        assert len(reloaded.regions) == 1


class TestGeoJSONAnnotation:
    def test_parse_from_file(self, geojson_file: Path) -> None:
        anno = GeoJSONAnnotation.from_file(geojson_file)
        assert len(anno.features) == 1

    def test_round_trip_json(self, geojson_file: Path) -> None:
        original = GeoJSONAnnotation.from_file(geojson_file)
        reloaded = GeoJSONAnnotation.from_string(original.to_json())
        assert len(reloaded.features) == len(original.features)

    def test_to_asap(self, geojson_file: Path) -> None:
        asap = GeoJSONAnnotation.from_file(geojson_file).to_asap()
        assert len(asap.regions) == 1
        assert asap.regions[0].region_type == "Polygon"

    def test_save_and_reload(self, geojson_file: Path, tmp_path: Path) -> None:
        anno = GeoJSONAnnotation.from_file(geojson_file)
        out = tmp_path / "out.geojson"
        anno.save(out)
        assert len(GeoJSONAnnotation.from_file(out).features) == 1

    def test_qupath_mrxs_feature_has_flag(self, qupath_mrxs_file: Path) -> None:
        anno = GeoJSONAnnotation.from_file(qupath_mrxs_file)
        assert len(anno.features) == 1
        props = anno.features[0].get("properties", {})
        assert props.get("qupath_mrxs") is True


class TestHistechAnnotation:
    def test_parse_from_file(self, histech_file: Path) -> None:
        anno = HistechAnnotation.from_file(histech_file)
        assert len(anno.regions) == 1
        r = anno.regions[0]
        assert r.name == "tumor"
        assert len(r.coordinates) == 4

    def test_metadata_parsed(self, histech_file: Path) -> None:
        anno = HistechAnnotation.from_file(histech_file)
        assert anno.offset_left == 0
        assert anno.micrometer_per_pixel_x == pytest.approx(0.25)

    def test_to_asap(self, histech_file: Path) -> None:
        asap = HistechAnnotation.from_file(histech_file).to_asap()
        assert len(asap.regions) == 1

    def test_to_geojson(self, histech_file: Path) -> None:
        geo = HistechAnnotation.from_file(histech_file).to_geojson()
        assert len(geo.features) == 1


class TestHamamatsuNDPA:
    def test_parse_from_file(self, ndpa_file: Path) -> None:
        anno = HamamatsuNDPA.from_string(ndpa_file.read_text())
        assert len(anno.regions) == 1
        assert anno.regions[0].name == "tumor_0"

    def test_coordinate_conversion(self, ndpa_file: Path) -> None:
        anno = HamamatsuNDPA.from_string(ndpa_file.read_text())
        # 1 pixel = 1000 nm, no offset → 100 000 nm / 1000 = 100 px
        anno.set_params(px_nm=1000, py_nm=1000, xoffset_nm=0, yoffset_nm=0)
        coords = anno.regions[0].coordinates
        assert len(coords) == 4
        assert coords[0].x == pytest.approx(100.0)
        assert coords[0].y == pytest.approx(100.0)

    def test_to_geojson(self, ndpa_file: Path) -> None:
        anno = HamamatsuNDPA.from_string(ndpa_file.read_text())
        anno.set_params(px_nm=1000, py_nm=1000)
        geo = anno.to_geojson()
        assert len(geo.features) == 1


class TestBinaryMaskAnnotation:
    def test_parse_from_file(self, binary_mask_file: Path) -> None:
        anno = BinaryMaskAnnotation.from_file(binary_mask_file)
        assert anno.mask is not None
        assert anno.mask.shape == (64, 64)

    def test_to_geojson(self, binary_mask_file: Path) -> None:
        geo = BinaryMaskAnnotation.from_file(binary_mask_file).to_geojson()
        assert len(geo.features) >= 1

    def test_to_asap(self, binary_mask_file: Path) -> None:
        asap = BinaryMaskAnnotation.from_file(binary_mask_file).to_asap()
        assert len(asap.regions) >= 1

    def test_save_and_reload(self, binary_mask_file: Path, tmp_path: Path) -> None:
        original = BinaryMaskAnnotation.from_file(binary_mask_file)
        out = tmp_path / "out_mask.png"
        original.save(out)
        reloaded = BinaryMaskAnnotation.from_file(out)
        assert reloaded.mask is not None
        assert reloaded.mask.shape == original.mask.shape
