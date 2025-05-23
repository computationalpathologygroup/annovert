import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Union
import logging
from tqdm import tqdm

from .basecore import Annotation, ConverterConfig, FormatType, ImageMetadata
from .formats import (
    ASAPAnnotation,
    GeoJSONAnnotation,
    HistechAnnotation,
    BinaryMaskAnnotation,
)


class ConversionLogger:
    def __init__(self, name: str = "annovert"):
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(name)s | %(levelname)s | %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)


class Annovert:
    def __init__(self, config: ConverterConfig = None):
        self.config = config or ConverterConfig()
        self.results = {}
        self.logger = ConversionLogger()

    def _detect_format_from_path(self, file_path: Path) -> FormatType:
        suffix = file_path.suffix.lower()

        if suffix in [".geojson", ".json"]:
            with open(file_path, "r") as f:
                content = f.read(4096)
            try:
                format_type = Annotation.detect_format(content)
                if format_type in ["geojson", "geojson_qupath_mrxs"]:
                    return format_type
            except ValueError:
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
        elif suffix in [".tif", ".tiff"]:
            return "binary_mask"
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
        image_path: Optional[Union[str, Path]] = None,
        downsample_factor: Optional[float] = None,
    ) -> Any:
        input_path = Path(input_path)

        self.logger.info(f"Converting: {input_path}")

        if not source_format:
            if self.config.default_source_format:
                source_format = self.config.default_source_format
            elif self.config.allow_auto_detect:
                source_format = self._detect_format_from_path(input_path)
                self.logger.info(f"Detected format: {source_format}")
            else:
                raise ValueError(
                    f"Source format not specified and auto-detection disabled"
                )

        if target_format in ["geojson_qupath_mrxs", "binary_mask"] and not image_path:
            self.logger.warning(
                f"Target format '{target_format}' requires image metadata. "
                f"Provide image_path parameter for optimal results."
            )

        if source_format == "asap":
            annotation = ASAPAnnotation.from_file(input_path)
        elif source_format == "geojson":
            annotation = GeoJSONAnnotation.from_file(input_path)
        elif source_format == "geojson_qupath_mrxs":
            from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

            with open(input_path, "r") as f:
                annotation = QuPathMRXSGeoJSONAnnotation.from_string(f.read())
        elif source_format == "3dhistech":
            annotation = HistechAnnotation.from_file(input_path)
        elif source_format == "binary_mask":
            annotation = BinaryMaskAnnotation.from_file(input_path)
        else:
            raise ValueError(f"Unsupported source format: {source_format}")

        if not target_format:
            if output_path:
                suffix = Path(output_path).suffix.lower()
                if suffix in [".geojson", ".json"]:
                    if output_path.stem.endswith("_qupath_mrxs"):
                        target_format = "geojson_qupath_mrxs"
                    else:
                        target_format = "geojson"
                elif suffix == ".xml":
                    target_format = "asap"
                elif suffix in [".tif", ".tiff", ".png", ".jpg", ".jpeg"]:
                    target_format = "binary_mask"
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
        else:
            if output_path:
                suffix = Path(output_path).suffix.lower()

                if (
                    target_format in ["geojson", "geojson_qupath_mrxs"]
                    and suffix == ".xml"
                ):
                    self.logger.warning(
                        f"Target format '{target_format}' doesn't match output extension '{suffix}'. "
                        f"Auto-correcting to 'asap'"
                    )
                    target_format = "asap"
                elif target_format == "asap" and suffix in [".geojson", ".json"]:
                    self.logger.warning(
                        f"Target format '{target_format}' doesn't match output extension '{suffix}'. "
                        f"Auto-correcting to 'geojson'"
                    )
                    target_format = "geojson"
                elif target_format == "binary_mask" and suffix not in [
                    ".tif",
                    ".tiff",
                    ".png",
                    ".jpg",
                    ".jpeg",
                ]:
                    self.logger.warning(
                        f"Target format '{target_format}' doesn't match output extension '{suffix}'. "
                        f"Consider using .tif, .png, or .jpg extension"
                    )

        metadata = None
        if target_format in ["geojson_qupath_mrxs", "binary_mask"] and image_path:
            from .image_reader import ImageReader

            try:
                metadata = ImageReader.read_image_metadata(image_path)
                self.logger.info(f"Loaded image metadata: {Path(image_path).name}")
            except Exception as e:
                self.logger.warning(f"Could not read image metadata: {e}")

        if downsample_factor is None:
            downsample_factor = self.config.mask_downsample_factor

        self.logger.info(f"Converting: {source_format} → {target_format}")
        result = self.convert_object(
            annotation,
            target_format,
            metadata=metadata,
            downsample_factor=downsample_factor,
        )

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(result, "save"):
                result.save(output_path)
                self.logger.info(f"✓ Saved to: {output_path}")
            else:
                raise ValueError(f"Result does not have a save method: {type(result)}")
        else:
            self.logger.info("✓ Conversion completed (in-memory)")

        self.results[input_path.stem] = {
            "input_path": str(input_path),
            "source_format": source_format,
            "target_format": target_format,
            "output_path": str(output_path) if output_path else None,
            "image_path": str(image_path) if image_path else None,
            "success": True,
        }

        return result

    def convert_object(
        self,
        annotation,
        target_format: FormatType,
        metadata: Optional[ImageMetadata] = None,
        downsample_factor: float = 1.0,
    ) -> Any:
        if isinstance(annotation, ASAPAnnotation):
            if target_format == "asap":
                return annotation
            elif target_format == "geojson":
                return annotation.to_geojson()
            elif target_format == "geojson_qupath_mrxs":
                from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

                base_geojson = annotation.to_geojson()
                return QuPathMRXSGeoJSONAnnotation.from_geojson(base_geojson, metadata)
            elif target_format == "binary_mask":
                base_geojson = annotation.to_geojson()
                return BinaryMaskAnnotation.from_geojson(
                    base_geojson, metadata, downsample_factor
                )
            else:
                raise ValueError(f"Unsupported conversion from ASAP to {target_format}")

        elif isinstance(annotation, GeoJSONAnnotation):
            from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

            if isinstance(annotation, QuPathMRXSGeoJSONAnnotation):
                if target_format == "asap":
                    return annotation.to_standard_geojson().to_asap()
                elif target_format == "geojson":
                    return annotation.to_standard_geojson()
                elif target_format == "geojson_qupath_mrxs":
                    return annotation
                elif target_format == "binary_mask":
                    standard_geojson = annotation.to_standard_geojson()
                    return BinaryMaskAnnotation.from_geojson(
                        standard_geojson, metadata, downsample_factor
                    )
                else:
                    raise ValueError(
                        f"Unsupported conversion from QuPath MRXS GeoJSON to {target_format}"
                    )
            else:
                if target_format == "asap":
                    return annotation.to_asap()
                elif target_format == "geojson":
                    return annotation
                elif target_format == "geojson_qupath_mrxs":
                    return QuPathMRXSGeoJSONAnnotation.from_geojson(
                        annotation, metadata
                    )
                elif target_format == "binary_mask":
                    return BinaryMaskAnnotation.from_geojson(
                        annotation, metadata, downsample_factor
                    )
                else:
                    raise ValueError(
                        f"Unsupported conversion from GeoJSON to {target_format}"
                    )

        elif isinstance(annotation, HistechAnnotation):
            if target_format == "asap":
                return annotation.to_asap()
            elif target_format == "geojson":
                return annotation.to_geojson()
            elif target_format == "geojson_qupath_mrxs":
                from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

                base_geojson = annotation.to_geojson()
                return QuPathMRXSGeoJSONAnnotation.from_geojson(base_geojson, metadata)
            elif target_format == "binary_mask":
                base_geojson = annotation.to_geojson()
                return BinaryMaskAnnotation.from_geojson(
                    base_geojson, metadata, downsample_factor
                )
            else:
                raise ValueError(
                    f"Unsupported conversion from 3D Histech to {target_format}"
                )

        elif isinstance(annotation, BinaryMaskAnnotation):
            if target_format == "asap":
                return annotation.to_asap()
            elif target_format == "geojson":
                return annotation.to_geojson()
            elif target_format == "geojson_qupath_mrxs":
                from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

                base_geojson = annotation.to_geojson()
                return QuPathMRXSGeoJSONAnnotation.from_geojson(base_geojson, metadata)
            elif target_format == "binary_mask":
                return annotation
            else:
                raise ValueError(
                    f"Unsupported conversion from Binary Mask to {target_format}"
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
        image_dir: Optional[Union[str, Path]] = None,
        downsample_factor: Optional[float] = None,
    ) -> Dict[str, Any]:
        input_dir = Path(input_dir)
        if image_dir:
            image_dir = Path(image_dir)

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        elif self.config.output_directory:
            output_dir = self.config.output_directory
        else:
            raise ValueError("Output directory not specified in config or method call")

        input_files = list(input_dir.glob(file_pattern))

        if not input_files:
            self.logger.warning(
                f"No files found matching '{file_pattern}' in {input_dir}"
            )
            return self.results

        if target_format in ["geojson_qupath_mrxs", "binary_mask"] and not image_dir:
            self.logger.warning(
                f"Target format '{target_format}' requires image_dir parameter for optimal results."
            )

        if downsample_factor is None:
            downsample_factor = self.config.mask_downsample_factor

        self.logger.info(f"Input directory: {input_dir}")
        self.logger.info(f"Output directory: {output_dir}")
        if image_dir:
            self.logger.info(f"Image directory: {image_dir}")

        self.logger.info(
            f"Processing {len(input_files)} files: {source_format or 'auto'} → {target_format}"
        )

        unmatched_annotations = []

        with tqdm(input_files, desc="Converting", unit="file", ncols=80) as pbar:
            for input_file in pbar:
                pbar.set_postfix_str(input_file.name[:20])

                try:
                    curr_source_format = source_format

                    if not curr_source_format and self.config.allow_auto_detect:
                        try:
                            curr_source_format = self._detect_format_from_path(
                                input_file
                            )
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
                        if target_format == "asap":
                            output_suffix = ".xml"
                        elif target_format == "binary_mask":
                            output_suffix = ".png"
                        else:
                            output_suffix = ".geojson"

                        output_file = output_dir / f"{input_file.stem}{output_suffix}"

                        image_path = None
                        if (
                            target_format in ["geojson_qupath_mrxs", "binary_mask"]
                            and image_dir
                        ):
                            for ext in [
                                ".mrxs",
                                ".svs",
                                ".ndpi",
                                ".vms",
                                ".vmu",
                                ".scn",
                                ".tif",
                                ".tiff",
                            ]:
                                candidate = image_dir / f"{input_file.stem}{ext}"
                                if candidate.exists():
                                    image_path = candidate
                                    break

                            if not image_path:
                                unmatched_annotations.append(input_file.name)

                        self.convert_file(
                            input_file,
                            output_file,
                            source_format=curr_source_format,
                            target_format=target_format,
                            image_path=image_path,
                            downsample_factor=downsample_factor,
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

        successful = sum(1 for r in self.results.values() if r.get("success", False))
        total = len(input_files)

        self.logger.info(
            f"✓ Batch completed: {successful}/{total} files converted successfully"
        )

        if unmatched_annotations:
            self.logger.warning(
                f"⚠ {len(unmatched_annotations)} annotations have no matching images. "
                f"Use convert_file() with explicit image_path for precise control."
            )

        return self.results
