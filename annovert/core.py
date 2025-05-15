import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .basecore import Annotation, ConverterConfig, FormatType
from .formats import ASAPAnnotation, GeoJSONAnnotation, HistechAnnotation


class Annovert:
    def __init__(self, config: ConverterConfig = None):
        self.config = config or ConverterConfig()
        self.results = {}

    def _detect_format_from_path(self, file_path: Path) -> FormatType:
        suffix = file_path.suffix.lower()

        if suffix in [".geojson", ".json"]:
            return "geojson"
        elif suffix == ".xml":
            with open(file_path, "r") as f:
                content = f.read(4096)

            try:
                return Annotation.detect_format(content)
            except ValueError:
                try:
                    root = ET.fromstring(content)
                    if root.tag == "ASAP_Annotations":
                        return "asap"
                    elif root.tag == "annotation_meta_data":
                        return "3dhistech"
                    else:
                        raise ValueError(
                            f"Unknown XML annotation format with root tag: {root.tag}"
                        )
                except ET.ParseError:
                    raise ValueError("Invalid XML format")
        else:
            raise ValueError(
                f"Cannot determine annotation format from file: {file_path}"
            )

    def convert_file(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        source_format: Optional[FormatType] = None,
        target_format: Optional[FormatType] = None,
    ) -> Any:
        input_path = Path(input_path)

        if not source_format:
            if self.config.default_source_format:
                source_format = self.config.default_source_format
            elif self.config.allow_auto_detect:
                source_format = self._detect_format_from_path(input_path)
            else:
                raise ValueError(
                    f"Source format not specified and auto-detection disabled"
                )

        if source_format == "asap":
            annotation = ASAPAnnotation.from_file(input_path)
        elif source_format == "geojson":
            annotation = GeoJSONAnnotation.from_file(input_path)
        elif source_format == "3dhistech":
            annotation = HistechAnnotation.from_file(input_path)
        else:
            raise ValueError(f"Unsupported source format: {source_format}")

        if not target_format:
            if output_path:
                suffix = Path(output_path).suffix.lower()
                if suffix in [".geojson", ".json"]:
                    target_format = "geojson"
                elif suffix == ".xml":
                    target_format = "asap"
                else:
                    if self.config.default_target_format:
                        target_format = self.config.default_target_format
                    else:
                        raise ValueError(
                            f"Cannot determine target format from output path: {output_path}"
                        )
            elif self.config.default_target_format:
                target_format = self.config.default_target_format
            else:
                raise ValueError("Target format not specified and cannot be determined")

        result = self.convert_object(annotation, target_format)

        if output_path:
            output_path = Path(output_path)
            if hasattr(result, "save"):
                result.save(output_path)
            else:
                raise ValueError(f"Result does not have a save method: {type(result)}")

        self.results[input_path.stem] = {
            "input_path": str(input_path),
            "source_format": source_format,
            "target_format": target_format,
            "output_path": str(output_path) if output_path else None,
            "success": True,
        }

        return result

    def convert_object(self, annotation, target_format: FormatType) -> Any:
        if isinstance(annotation, ASAPAnnotation):
            if target_format == "asap":
                return annotation
            elif target_format == "geojson":
                return annotation.to_geojson()
            else:
                raise ValueError(f"Unsupported conversion from ASAP to {target_format}")

        elif isinstance(annotation, GeoJSONAnnotation):
            if target_format == "asap":
                return annotation.to_asap()
            elif target_format == "geojson":
                return annotation
            else:
                raise ValueError(
                    f"Unsupported conversion from GeoJSON to {target_format}"
                )

        elif isinstance(annotation, HistechAnnotation):
            if target_format == "asap":
                return annotation.to_asap()
            elif target_format == "geojson":
                return annotation.to_geojson()
            else:
                raise ValueError(
                    f"Unsupported conversion from 3D Histech to {target_format}"
                )

        else:
            raise ValueError(f"Unsupported annotation type: {type(annotation)}")

    def batch_process(
        self,
        input_dir: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        source_format: Optional[FormatType] = None,
        target_format: Optional[FormatType] = None,
        file_pattern: str = "*.*",
    ) -> Dict[str, Any]:
        input_dir = Path(input_dir)

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        elif self.config.output_directory:
            output_dir = self.config.output_directory
        else:
            raise ValueError("Output directory not specified in config or method call")

        input_files = list(input_dir.glob(file_pattern))

        for input_file in input_files:
            try:
                curr_source_format = source_format

                if not curr_source_format and self.config.allow_auto_detect:
                    try:
                        curr_source_format = self._detect_format_from_path(input_file)
                    except ValueError:
                        self.results[input_file.stem] = {
                            "input_path": str(input_file),
                            "source_format": None,
                            "target_format": target_format,
                            "output_path": None,
                            "success": False,
                            "error": "Could not auto-detect source format",
                        }
                        continue

                if curr_source_format:
                    output_suffix = ".xml" if target_format == "asap" else ".geojson"
                    output_file = output_dir / f"{input_file.stem}{output_suffix}"

                    self.convert_file(
                        input_file,
                        output_file,
                        source_format=curr_source_format,
                        target_format=target_format,
                    )
            except Exception as e:
                self.results[input_file.stem] = {
                    "input_path": str(input_file),
                    "source_format": curr_source_format,
                    "target_format": target_format,
                    "output_path": None,
                    "success": False,
                    "error": str(e),
                }

        return self.results
