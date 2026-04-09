"""
Geometry-preservation tests using the real-world fixture
tests/fixtures/1ee4d067-3842-4722-b14f-a3dffee58095.geojson

All conversions that claim to be lossless for vector data are verified with
coordinate-level equality (to floating-point precision) so that regressions
are caught immediately.
"""
import json
from pathlib import Path

import pytest

from annovert.formats import ASAPAnnotation, GeoJSONAnnotation

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "1ee4d067-3842-4722-b14f-a3dffee58095.geojson"
)
EXPECTED_RING_LEN = 3721  # outer ring vertex count (including closing vertex)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ring(feature: dict) -> list:
    """Return the outer ring coordinate list of a Polygon feature."""
    return feature["geometry"]["coordinates"][0]


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Baseline: fixture sanity
# ---------------------------------------------------------------------------

class TestFixtureSanity:
    def test_single_polygon_feature(self) -> None:
        data = _load_geojson(FIXTURE)
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1

    def test_vertex_count(self) -> None:
        data = _load_geojson(FIXTURE)
        assert len(_ring(data["features"][0])) == EXPECTED_RING_LEN

    def test_geometry_type(self) -> None:
        data = _load_geojson(FIXTURE)
        assert data["features"][0]["geometry"]["type"] == "Polygon"


# ---------------------------------------------------------------------------
# GeoJSON → ASAP → GeoJSON
# ---------------------------------------------------------------------------

class TestGeoJSONToASAPRoundTrip:
    def test_vertex_count_preserved(self) -> None:
        geo = GeoJSONAnnotation.from_file(FIXTURE)
        asap = geo.to_asap()
        geo2 = asap.to_geojson()

        assert len(geo2.features) == 1
        ring = _ring(geo2.features[0])
        # ASAP→GeoJSON closes the ring; original may already be closed
        original_ring = _ring(GeoJSONAnnotation.from_file(FIXTURE).features[0])
        original_unique = (
            original_ring[:-1]
            if original_ring[0] == original_ring[-1]
            else original_ring
        )
        assert len(ring) - 1 == len(original_unique)  # ring is closed (+1)

    def test_coordinates_preserved(self) -> None:
        geo = GeoJSONAnnotation.from_file(FIXTURE)
        asap = geo.to_asap()
        geo2 = asap.to_geojson()

        original_ring = _ring(GeoJSONAnnotation.from_file(FIXTURE).features[0])
        if original_ring[0] == original_ring[-1]:
            original_ring = original_ring[:-1]

        result_ring = _ring(geo2.features[0])
        result_ring_open = result_ring[:-1]  # drop closing vertex

        assert len(result_ring_open) == len(original_ring)
        for (rx, ry), (ox, oy) in zip(result_ring_open, original_ring):
            assert rx == pytest.approx(ox)
            assert ry == pytest.approx(oy)


# ---------------------------------------------------------------------------
# GeoJSON → ASAP (file) → reload → GeoJSON
# ---------------------------------------------------------------------------

class TestGeoJSONToASAPFileSave:
    def test_vertex_count_after_save_reload(self, tmp_path: Path) -> None:
        geo = GeoJSONAnnotation.from_file(FIXTURE)
        asap = geo.to_asap()
        asap_path = tmp_path / "realworld.xml"
        asap.save(asap_path)

        reloaded = ASAPAnnotation.from_file(asap_path)
        assert len(reloaded.regions) == 1
        assert len(reloaded.regions[0].coordinates) == EXPECTED_RING_LEN - 1

    def test_coordinates_after_save_reload(self, tmp_path: Path) -> None:
        geo = GeoJSONAnnotation.from_file(FIXTURE)
        original_ring = _ring(geo.features[0])
        if original_ring[0] == original_ring[-1]:
            original_ring = original_ring[:-1]

        asap = geo.to_asap()
        asap_path = tmp_path / "realworld.xml"
        asap.save(asap_path)

        reloaded = ASAPAnnotation.from_file(asap_path)
        coords = reloaded.regions[0].coordinates

        assert len(coords) == len(original_ring)
        for coord, (ox, oy) in zip(coords, original_ring):
            assert coord.x == pytest.approx(ox)
            assert coord.y == pytest.approx(oy)


# ---------------------------------------------------------------------------
# GeoJSON → GeoJSON save/reload (baseline identity)
# ---------------------------------------------------------------------------

class TestGeoJSONIdentity:
    def test_save_reload_preserves_coordinates(self, tmp_path: Path) -> None:
        geo = GeoJSONAnnotation.from_file(FIXTURE)
        out = tmp_path / "out.geojson"
        geo.save(out)

        original_ring = _ring(GeoJSONAnnotation.from_file(FIXTURE).features[0])
        reloaded_ring = _ring(GeoJSONAnnotation.from_file(out).features[0])

        assert len(reloaded_ring) == len(original_ring)
        for (rx, ry), (ox, oy) in zip(reloaded_ring, original_ring):
            assert rx == pytest.approx(ox)
            assert ry == pytest.approx(oy)
