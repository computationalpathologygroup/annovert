"""
Round-trip identity tests: format A → format B → format A.

Rules:
- Vector-to-vector conversions: coordinates must survive unchanged (to
  floating-point precision) and vertex count must be preserved.
- Vector-to-raster (BinaryMask) conversions: rasterisation is inherently lossy
  so checks are approximate (foreground pixel count, polygon area, centroid).
- Every source format that can complete a round-trip has a dedicated class.
- Tests run on both the minimal synthetic fixtures and the real-world
  3721-vertex polygon from tests/fixtures/1ee4d067-…geojson.

Formats that cannot be serialised from another format (HistechAnnotation,
HamamatsuNDPA) are covered by one-way chain tests instead.
"""
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pytest

from annovert.formats import (
    ASAPAnnotation,
    BinaryMaskAnnotation,
    GeoJSONAnnotation,
    HamamatsuNDPA,
    HistechAnnotation,
)
from annovert.basecore import ImageMetadata
REAL_WORLD = (
    Path(__file__).parent
    / "fixtures"
    / "1ee4d067-3842-4722-b14f-a3dffee58095.geojson"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _asap_coords(anno: ASAPAnnotation) -> List[List[Tuple[float, float]]]:
    return [[(c.x, c.y) for c in r.coordinates] for r in anno.regions]


def _geo_rings(anno: GeoJSONAnnotation) -> List[List[Tuple[float, float]]]:
    rings = []
    for f in anno.features:
        geom = f["geometry"]
        if geom["type"] == "Polygon":
            rings.append([tuple(p) for p in geom["coordinates"][0]])
        elif geom["type"] == "Point":
            rings.append([tuple(geom["coordinates"])])
        elif geom["type"] == "LineString":
            rings.append([tuple(p) for p in geom["coordinates"]])
    return rings


def _open_ring(ring: List[Tuple]) -> List[Tuple]:
    """Remove closing vertex if ring is explicitly closed."""
    if len(ring) > 1 and ring[0] == ring[-1]:
        return ring[:-1]
    return ring


def _approx_coords(a: List[Tuple], b: List[Tuple]) -> None:
    assert len(a) == len(b), f"vertex count mismatch: {len(a)} vs {len(b)}"
    for (ax, ay), (bx, by) in zip(a, b):
        assert ax == pytest.approx(bx), f"x mismatch: {ax} vs {bx}"
        assert ay == pytest.approx(by), f"y mismatch: {ay} vs {by}"


# ---------------------------------------------------------------------------
# ASAP → GeoJSON → ASAP
# ---------------------------------------------------------------------------

class TestAsapGeoJSONAsap:
    """ASAP ➜ GeoJSON ➜ ASAP — vertex coordinates must be identical."""

    def _check(self, asap_path: Path) -> None:
        original = ASAPAnnotation.from_file(asap_path)
        roundtripped = original.to_geojson().to_asap()

        assert len(roundtripped.regions) == len(original.regions)
        for orig_region, rt_region in zip(original.regions, roundtripped.regions):
            orig_coords = [(c.x, c.y) for c in orig_region.coordinates]
            rt_coords = [(c.x, c.y) for c in rt_region.coordinates]
            _approx_coords(orig_coords, rt_coords)

    def test_synthetic(self, asap_file: Path) -> None:
        self._check(asap_file)

    def test_real_world_via_intermediate(self) -> None:
        # Build ASAP from the real-world GeoJSON, then round-trip it
        asap = GeoJSONAnnotation.from_file(REAL_WORLD).to_asap()
        roundtripped = asap.to_geojson().to_asap()
        assert len(roundtripped.regions) == len(asap.regions)
        for orig, rt in zip(asap.regions, roundtripped.regions):
            orig_coords = [(c.x, c.y) for c in orig.coordinates]
            rt_coords = [(c.x, c.y) for c in rt.coordinates]
            _approx_coords(orig_coords, rt_coords)


# ---------------------------------------------------------------------------
# GeoJSON → ASAP → GeoJSON
# ---------------------------------------------------------------------------

class TestGeoJSONAsapGeoJSON:
    """GeoJSON ➜ ASAP ➜ GeoJSON — outer ring vertices must be identical."""

    def _check(self, geo_path: Path) -> None:
        original = GeoJSONAnnotation.from_file(geo_path)
        roundtripped = original.to_asap().to_geojson()

        orig_rings = _geo_rings(original)
        rt_rings = _geo_rings(roundtripped)

        assert len(rt_rings) == len(orig_rings)
        for o_ring, rt_ring in zip(orig_rings, rt_rings):
            _approx_coords(_open_ring(o_ring), _open_ring(rt_ring))

    def test_synthetic(self, geojson_file: Path) -> None:
        self._check(geojson_file)

    def test_real_world(self) -> None:
        self._check(REAL_WORLD)

    def test_real_world_vertex_count(self) -> None:
        original = GeoJSONAnnotation.from_file(REAL_WORLD)
        roundtripped = original.to_asap().to_geojson()
        orig_ring = _open_ring(_geo_rings(original)[0])
        rt_ring = _open_ring(_geo_rings(roundtripped)[0])
        assert len(rt_ring) == len(orig_ring)


# ---------------------------------------------------------------------------
# GeoJSON → ASAP → GeoJSON (file-based, exercises save/load paths)
# ---------------------------------------------------------------------------

class TestGeoJSONAsapGeoJSONViaDisk:
    """Same round-trip but serialised to disk between each step."""

    def _check(self, geo_path: Path, tmp_path: Path) -> None:
        original = GeoJSONAnnotation.from_file(geo_path)

        asap_path = tmp_path / "intermediate.xml"
        original.to_asap().save(asap_path)

        geo2_path = tmp_path / "roundtripped.geojson"
        ASAPAnnotation.from_file(asap_path).to_geojson().save(geo2_path)

        roundtripped = GeoJSONAnnotation.from_file(geo2_path)
        orig_rings = _geo_rings(original)
        rt_rings = _geo_rings(roundtripped)

        assert len(rt_rings) == len(orig_rings)
        for o_ring, rt_ring in zip(orig_rings, rt_rings):
            _approx_coords(_open_ring(o_ring), _open_ring(rt_ring))

    def test_synthetic(self, geojson_file: Path, tmp_path: Path) -> None:
        self._check(geojson_file, tmp_path)

    def test_real_world(self, tmp_path: Path) -> None:
        self._check(REAL_WORLD, tmp_path)


# ---------------------------------------------------------------------------
# Histech → ASAP → GeoJSON  (one-way chain; Histech cannot be written back)
# ---------------------------------------------------------------------------

class TestHistechChain:
    """HistechAnnotation has no writer, so we verify the full chain
    Histech ➜ ASAP ➜ GeoJSON preserves vertex count and coordinates."""

    def test_histech_to_asap_to_geojson(self, histech_file: Path) -> None:
        histech = HistechAnnotation.from_file(histech_file)
        asap = histech.to_asap()
        geo = asap.to_geojson()

        assert len(geo.features) == len(histech.regions)

        for h_region, feature in zip(histech.regions, geo.features):
            h_coords = [(c.x, c.y) for c in h_region.coordinates]
            ring = _open_ring(_geo_rings(geo)[0])
            _approx_coords(h_coords, ring)

    def test_histech_direct_to_geojson_matches_via_asap(
        self, histech_file: Path
    ) -> None:
        histech = HistechAnnotation.from_file(histech_file)
        via_asap = histech.to_asap().to_geojson()
        direct = histech.to_geojson()

        assert len(via_asap.features) == len(direct.features)
        for r_via, r_direct in zip(_geo_rings(via_asap), _geo_rings(direct)):
            _approx_coords(_open_ring(r_via), _open_ring(r_direct))


# ---------------------------------------------------------------------------
# NDPA → GeoJSON → ASAP  (one-way chain; NDPA requires physical params to write)
# ---------------------------------------------------------------------------

class TestNDPAChain:
    """HamamatsuNDPA ➜ GeoJSON ➜ ASAP preserves pixel coordinates
    after set_params is applied."""

    def test_ndpa_to_geojson_to_asap_vertex_count(self, ndpa_file: Path) -> None:
        ndpa = HamamatsuNDPA.from_string(ndpa_file.read_text())
        ndpa.set_params(px_nm=1000, py_nm=1000)
        geo = ndpa.to_geojson()
        asap = geo.to_asap()

        assert len(asap.regions) == len(ndpa.regions)

    def test_ndpa_to_geojson_to_asap_coordinates(self, ndpa_file: Path) -> None:
        ndpa = HamamatsuNDPA.from_string(ndpa_file.read_text())
        ndpa.set_params(px_nm=1000, py_nm=1000)

        geo = ndpa.to_geojson()
        asap = geo.to_asap()

        ndpa_coords = [(c.x, c.y) for c in ndpa.regions[0].coordinates]
        asap_coords = [(c.x, c.y) for c in asap.regions[0].coordinates]

        _approx_coords(ndpa_coords, asap_coords)


# ---------------------------------------------------------------------------
# BinaryMask round-trips  (lossy — rasterisation rounds polygon edges)
# ---------------------------------------------------------------------------

class TestBinaryMaskRoundTrips:
    """
    Rasterisation is lossy (polygon edges are rounded to the pixel grid), so
    exact coordinate equality is not meaningful.  Instead we use IoU:

    - Mask → GeoJSON → Mask:  pixel-level IoU ≥ 0.95
    - GeoJSON → Mask → GeoJSON:  polygon IoU ≥ 0.95
    - Synthetic 32×32 square: IoU should be essentially 1.0 (clean rectangle)

    Compactness (4π·area/perimeter²) is deliberately *not* checked because
    rasterisation introduces staircase artifacts on the perimeter that reliably
    lower it even for perfectly preserved shapes.  Solidity is implied by IoU.
    """

    _MIN_IOU = 0.95

    @staticmethod
    def _pixel_iou(a: "np.ndarray", b: "np.ndarray") -> float:
        intersection = int(np.sum((a > 0) & (b > 0)))
        union = int(np.sum((a > 0) | (b > 0)))
        return intersection / union if union > 0 else 1.0

    @staticmethod
    def _polygon_iou(poly_a, poly_b) -> float:
        inter = poly_a.intersection(poly_b).area
        union = poly_a.union(poly_b).area
        return inter / union if union > 0 else 1.0

    # --- Mask → GeoJSON → Mask: pixel IoU ---

    def test_mask_to_geojson_to_mask_iou(self, binary_mask_file: Path) -> None:
        original = BinaryMaskAnnotation.from_file(binary_mask_file)
        geo = original.to_geojson()
        meta = ImageMetadata(
            width=original.mask.shape[1],
            height=original.mask.shape[0],
        )
        reconstructed = BinaryMaskAnnotation.from_geojson(geo, metadata=meta)
        iou = self._pixel_iou(original.mask, reconstructed.mask)
        assert iou >= self._MIN_IOU, f"pixel IoU {iou:.4f} below threshold {self._MIN_IOU}"

    # --- Mask → GeoJSON → ASAP: produces valid regions ---

    def test_mask_to_geojson_to_asap_produces_regions(
        self, binary_mask_file: Path
    ) -> None:
        asap = BinaryMaskAnnotation.from_file(binary_mask_file).to_asap()
        assert len(asap.regions) >= 1
        for region in asap.regions:
            assert len(region.coordinates) >= 3

    # --- GeoJSON (real-world) → Mask → GeoJSON: polygon IoU ---

    def test_geojson_to_mask_to_geojson_iou(self) -> None:
        import shapely.geometry

        original_geo = GeoJSONAnnotation.from_file(REAL_WORLD)
        orig_ring = _geo_rings(original_geo)[0]

        # Shift polygon to a zero-origin canvas for rasterisation
        orig_poly = shapely.geometry.Polygon(orig_ring)
        minx, miny, maxx, maxy = orig_poly.bounds
        width = int(maxx - minx) + 2
        height = int(maxy - miny) + 2

        shifted_ring = [
            [x - int(minx), y - int(miny)]
            for x, y in original_geo.features[0]["geometry"]["coordinates"][0]
        ]
        shifted_poly = shapely.geometry.Polygon(shifted_ring)

        shifted_geo = GeoJSONAnnotation()
        shifted_geo.features = [{
            **original_geo.features[0],
            "geometry": {"type": "Polygon", "coordinates": [shifted_ring]},
        }]

        mask = BinaryMaskAnnotation.from_geojson(
            shifted_geo, metadata=ImageMetadata(width=width, height=height)
        )
        geo2 = mask.to_geojson()

        assert len(geo2.features) >= 1
        recon_poly = shapely.geometry.Polygon(_geo_rings(geo2)[0])

        iou = self._polygon_iou(shifted_poly, recon_poly)
        assert iou >= self._MIN_IOU, f"polygon IoU {iou:.4f} below threshold {self._MIN_IOU}"

    # --- Mask save/reload preserves binary content exactly ---

    def test_mask_save_reload_identical(
        self, binary_mask_file: Path, tmp_path: Path
    ) -> None:
        original = BinaryMaskAnnotation.from_file(binary_mask_file)
        out = tmp_path / "saved.png"
        original.save(out)
        reloaded = BinaryMaskAnnotation.from_file(out)
        assert np.array_equal(original.mask > 0, reloaded.mask > 0)
