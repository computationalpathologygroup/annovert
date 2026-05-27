"""
Integration tests for the Annovert high-level API (format detection + convert_file).
"""
import json
from pathlib import Path

import pytest

from annovert import Annovert, ConverterConfig, Format
from annovert.basecore import FormatDetector


class TestFormatDetection:
    def test_detect_asap(self, asap_file: Path) -> None:
        assert FormatDetector.detect_format(asap_file.read_text()) == Format.ASAP

    def test_detect_geojson(self, geojson_file: Path) -> None:
        fmt = FormatDetector.detect_format(geojson_file.read_text())
        assert fmt == Format.GEOJSON

    def test_detect_qupath_mrxs(self, qupath_mrxs_file: Path) -> None:
        fmt = FormatDetector.detect_format(qupath_mrxs_file.read_text())
        assert fmt == Format.GEOJSON_QUPATH_MRXS

    def test_detect_histech(self, histech_file: Path) -> None:
        assert FormatDetector.detect_format(histech_file.read_text()) == Format.HISTECH_3D

    def test_detect_ndpa(self, ndpa_file: Path) -> None:
        assert FormatDetector.detect_format(ndpa_file.read_text()) == Format.HAMAMATSU_NDPA


class TestConvertFile:
    def test_asap_to_geojson(self, asap_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.geojson"
        Annovert().convert_file(
            input_path=asap_file,
            output_path=out,
            source_format=Format.ASAP,
            target_format=Format.GEOJSON,
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1

    def test_geojson_to_asap(self, geojson_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.xml"
        Annovert().convert_file(
            input_path=geojson_file,
            output_path=out,
            source_format=Format.GEOJSON,
            target_format=Format.ASAP,
        )
        assert out.exists()
        assert "ASAP_Annotations" in out.read_text()

    def test_histech_to_geojson(self, histech_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.geojson"
        Annovert().convert_file(
            input_path=histech_file,
            output_path=out,
            source_format=Format.HISTECH_3D,
            target_format=Format.GEOJSON,
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data["features"]) == 1

    def test_mask_to_geojson(self, binary_mask_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.geojson"
        Annovert().convert_file(
            input_path=binary_mask_file,
            output_path=out,
            source_format=Format.BINARY_MASK,
            target_format=Format.GEOJSON,
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data["features"]) >= 1

    def test_auto_detect_asap_to_geojson(self, asap_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.geojson"
        Annovert(config=ConverterConfig(allow_auto_detect=True)).convert_file(
            input_path=asap_file,
            output_path=out,
        )
        assert out.exists()

    def test_auto_detect_geojson_to_asap(self, geojson_file: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.xml"
        Annovert(config=ConverterConfig(allow_auto_detect=True)).convert_file(
            input_path=geojson_file,
            output_path=out,
        )
        assert out.exists()
        assert "ASAP_Annotations" in out.read_text()
