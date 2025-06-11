import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, Tuple
import logging
from tqdm import tqdm  # type: ignore

from .basecore import Annotation, ConverterConfig, FormatType, ImageMetadata
from .aggregation import AnnotationGrouper, HistechAggregator
from .formats import (
    ASAPAnnotation,
    GeoJSONAnnotation,
    HistechAnnotation,
    BinaryMaskAnnotation,
)


class ConversionLogger:
    def __init__(self, name: str = "annovert") -> None:
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(name)s | %(levelname)s | %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)


class Annovert:
    def __init__(self, config: Optional[ConverterConfig] = None) -> None:
        self.config = config or ConverterConfig()
        self.results: Dict[str, Any] = {}
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

        raise ValueError(f"Cannot determine annotation format from file: {file_path}")

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

        source_format = self._resolve_source_format(input_path, source_format)
        target_format = self._resolve_target_format(output_path, target_format)

        if target_format in ["geojson_qupath_mrxs", "binary_mask"] and not image_path:
            self.logger.warning(
                f"Target format '{target_format}' requires image metadata."
            )

        annotation = self._load_annotation(input_path, source_format)
        metadata = self._load_metadata(image_path, target_format)
        downsample_factor = downsample_factor or self.config.mask_downsample_factor

        self.logger.info(f"Converting: {source_format} → {target_format}")
        result = self.convert_object(
            annotation, target_format, metadata, downsample_factor
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

    def _resolve_source_format(
        self, input_path: Path, source_format: Optional[FormatType]
    ) -> FormatType:
        if source_format:
            return source_format
        if self.config.default_source_format:
            return self.config.default_source_format
        if self.config.allow_auto_detect:
            detected = self._detect_format_from_path(input_path)
            self.logger.info(f"Detected format: {detected}")
            return detected
        raise ValueError("Source format not specified and auto-detection disabled")

    def _resolve_target_format(
        self,
        output_path: Optional[Union[str, Path]],
        target_format: Optional[FormatType],
    ) -> FormatType:
        if target_format:
            return self._validate_target_format(output_path, target_format)
        if output_path:
            return self._infer_format_from_extension(Path(output_path))
        if self.config.default_target_format:
            return self.config.default_target_format
        raise ValueError("Target format not specified and cannot be determined")

    def _infer_format_from_extension(self, output_path: Path) -> FormatType:
        suffix = output_path.suffix.lower()
        if suffix in [".geojson", ".json"]:
            if output_path.stem.endswith("_qupath_mrxs"):
                return "geojson_qupath_mrxs"
            return "geojson"
        elif suffix == ".xml":
            return "asap"
        elif suffix in [".tif", ".tiff", ".png", ".jpg", ".jpeg"]:
            return "binary_mask"
        elif self.config.default_target_format:
            return self.config.default_target_format

        raise ValueError(
            f"Cannot determine target format from output path: {output_path}"
        )

    def _validate_target_format(
        self, output_path: Optional[Union[str, Path]], target_format: FormatType
    ) -> FormatType:
        if not output_path:
            return target_format

        suffix = Path(output_path).suffix.lower()
        corrections: Dict[Tuple[str, str], FormatType] = {
            ("geojson", ".xml"): "asap",
            ("geojson_qupath_mrxs", ".xml"): "asap",
            ("asap", ".geojson"): "geojson",
            ("asap", ".json"): "geojson",
        }

        key = (target_format, suffix)
        if key in corrections:
            corrected: FormatType = corrections[key]
            self.logger.warning(
                f"Target format '{target_format}' doesn't match extension '{suffix}'. Auto-correcting to '{corrected}'"
            )
            return corrected
        elif target_format == "binary_mask" and suffix not in [
            ".tif",
            ".tiff",
            ".png",
            ".jpg",
            ".jpeg",
        ]:
            self.logger.warning(
                f"Target format '{target_format}' doesn't match extension '{suffix}'. Consider using .tif, .png, or .jpg extension"
            )

        return target_format

    def _load_annotation(self, input_path: Path, source_format: FormatType) -> Any:
        if source_format == "geojson_qupath_mrxs":
            from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

            with open(input_path, "r") as f:
                return QuPathMRXSGeoJSONAnnotation.from_string(f.read())
        elif source_format == "asap":
            return ASAPAnnotation.from_file(input_path)
        elif source_format == "geojson":
            return GeoJSONAnnotation.from_file(input_path)
        elif source_format == "3dhistech":
            return HistechAnnotation.from_file(input_path)
        elif source_format == "binary_mask":
            return BinaryMaskAnnotation.from_file(input_path)
        else:
            raise ValueError(f"Unsupported source format: {source_format}")

    def _load_metadata(
        self, image_path: Optional[Union[str, Path]], target_format: FormatType
    ) -> Optional[ImageMetadata]:
        if target_format in ["geojson_qupath_mrxs", "binary_mask"] and image_path:
            from .image_reader import ImageReader

            try:
                metadata = ImageReader.read_image_metadata(image_path)
                self.logger.info(f"Loaded image metadata: {Path(image_path).name}")
                return metadata
            except Exception as e:
                self.logger.warning(f"Could not read image metadata: {e}")
        return None

    def convert_object(
        self,
        annotation: Any,
        target_format: FormatType,
        metadata: Optional[ImageMetadata] = None,
        downsample_factor: float = 1.0,
    ) -> Any:
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        if isinstance(annotation, ASAPAnnotation):
            return self._convert_from_asap(
                annotation, target_format, metadata, downsample_factor
            )
        elif isinstance(annotation, QuPathMRXSGeoJSONAnnotation):
            return self._convert_from_qupath_geojson(
                annotation, target_format, metadata, downsample_factor
            )
        elif isinstance(annotation, GeoJSONAnnotation):
            return self._convert_from_geojson(
                annotation, target_format, metadata, downsample_factor
            )
        elif isinstance(annotation, HistechAnnotation):
            return self._convert_from_histech(
                annotation, target_format, metadata, downsample_factor
            )
        elif isinstance(annotation, BinaryMaskAnnotation):
            return self._convert_from_binary_mask(
                annotation, target_format, metadata, downsample_factor
            )
        else:
            raise ValueError(f"Unsupported annotation type: {type(annotation)}")

    def _convert_from_asap(
        self,
        annotation: ASAPAnnotation,
        target_format: FormatType,
        metadata: Optional[ImageMetadata],
        downsample_factor: float,
    ) -> Any:
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

    def _convert_from_geojson(
        self,
        annotation: GeoJSONAnnotation,
        target_format: FormatType,
        metadata: Optional[ImageMetadata],
        downsample_factor: float,
    ) -> Any:
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        if isinstance(annotation, QuPathMRXSGeoJSONAnnotation):
            return self._convert_from_qupath_geojson(
                annotation, target_format, metadata, downsample_factor
            )

        if target_format == "asap":
            return annotation.to_asap()
        elif target_format == "geojson":
            return annotation
        elif target_format == "geojson_qupath_mrxs":
            return QuPathMRXSGeoJSONAnnotation.from_geojson(annotation, metadata)
        elif target_format == "binary_mask":
            return BinaryMaskAnnotation.from_geojson(
                annotation, metadata, downsample_factor
            )
        else:
            raise ValueError(f"Unsupported conversion from GeoJSON to {target_format}")

    def _convert_from_qupath_geojson(
        self,
        annotation,
        target_format: FormatType,
        metadata: Optional[ImageMetadata],
        downsample_factor: float,
    ) -> Any:
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

    def _convert_from_histech(
        self,
        annotation: HistechAnnotation,
        target_format: FormatType,
        metadata: Optional[ImageMetadata],
        downsample_factor: float,
    ) -> Any:
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

    def _convert_from_binary_mask(
        self,
        annotation: BinaryMaskAnnotation,
        target_format: FormatType,
        metadata: Optional[ImageMetadata],
        downsample_factor: float,
    ) -> Any:
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

    def batch_process(
        self,
        input_dir: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        source_format: Optional[FormatType] = None,
        target_format: Optional[FormatType] = None,
        file_pattern: str = "*.*",
        image_dir: Optional[Union[str, Path]] = None,
        downsample_factor: Optional[float] = None,
        slide_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        input_dir = Path(input_dir)
        image_dir = Path(image_dir) if image_dir else None
        output_dir = self._resolve_output_dir(output_dir)
        downsample_factor = downsample_factor or self.config.mask_downsample_factor

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

        self._log_batch_info(input_dir, output_dir, image_dir)
        detected_format = self._detect_batch_format(input_files, source_format)

        if (
            detected_format == "3dhistech"
            and self.config.aggregation
            and self.config.aggregation.enabled
        ):
            return self._batch_process_with_aggregation(
                input_files,
                output_dir,
                target_format,
                image_dir,
                downsample_factor,
                slide_name,
            )
        else:
            return self._batch_process_individual(
                input_files,
                output_dir,
                source_format,
                target_format,
                image_dir,
                downsample_factor,
            )

    def _resolve_output_dir(self, output_dir: Optional[Union[str, Path]]) -> Path:
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            return output_path
        elif self.config.output_directory:
            return self.config.output_directory
        else:
            raise ValueError("Output directory not specified in config or method call")

    def _log_batch_info(
        self, input_dir: Path, output_dir: Path, image_dir: Optional[Path]
    ) -> None:
        self.logger.info(f"Input directory: {input_dir}")
        self.logger.info(f"Output directory: {output_dir}")
        if image_dir:
            self.logger.info(f"Image directory: {image_dir}")

    def _detect_batch_format(
        self, files: List[Path], source_format: Optional[FormatType]
    ) -> Optional[FormatType]:
        if source_format:
            return source_format
        if not self.config.allow_auto_detect:
            return None
        for file_path in files[:5]:
            try:
                return self._detect_format_from_path(file_path)
            except ValueError:
                continue
        return None

    def _batch_process_with_aggregation(
        self,
        input_files: List[Path],
        output_dir: Path,
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
        slide_name: Optional[str],
    ) -> Dict[str, Any]:
        if not self.config.aggregation:
            raise ValueError("Aggregation config is required for aggregated processing")

        grouper = AnnotationGrouper(self.config.aggregation)
        aggregator = HistechAggregator(self.config.aggregation)
        groups = grouper.group_files(input_files)

        self.logger.info(f"Processing {len(groups)} groups with aggregation enabled")

        with tqdm(groups, desc="Converting groups", unit="group", ncols=80) as pbar:
            for group in pbar:
                pbar.set_postfix_str(f"{group.base_name} ({len(group.files)} files)")
                self._process_aggregated_group(
                    group,
                    aggregator,
                    output_dir,
                    target_format,
                    image_dir,
                    downsample_factor,
                    slide_name,
                )

        successful = sum(1 for r in self.results.values() if r.get("success", False))
        self.logger.info(
            f"✓ Aggregated batch completed: {successful}/{len(groups)} groups converted successfully"
        )
        return self.results

    def _process_aggregated_group(
        self,
        group,
        aggregator,
        output_dir: Path,
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
        slide_name: Optional[str],
    ) -> None:
        try:
            aggregated_annotation = aggregator.aggregate_annotations(group.files)
            effective_target_format = (
                target_format or self.config.default_target_format or "geojson"
            )

            output_suffix = self._get_output_suffix(effective_target_format)
            output_name = slide_name or group.base_name
            output_file = output_dir / f"{output_name}{output_suffix}"

            metadata = self._find_slide_metadata(
                group.base_name, image_dir, effective_target_format
            )

            self.logger.info(
                f"Converting aggregated: 3dhistech → {effective_target_format}"
            )
            result = self.convert_object(
                aggregated_annotation,
                effective_target_format,
                metadata,
                downsample_factor,
            )

            if hasattr(result, "save"):
                result.save(output_file)
                self.logger.info(f"✓ Saved aggregated to: {output_file}")

            self.results[output_name] = {
                "input_files": [str(f) for f in group.files],
                "source_format": "3dhistech",
                "target_format": effective_target_format,
                "output_path": str(output_file),
                "aggregated": True,
                "success": True,
            }
        except Exception as e:
            output_name = slide_name or group.base_name
            self.results[output_name] = {
                "input_files": [str(f) for f in group.files],
                "source_format": "3dhistech",
                "target_format": target_format,
                "output_path": None,
                "aggregated": True,
                "success": False,
                "error": str(e),
            }

    def _get_output_suffix(self, target_format: FormatType) -> str:
        suffixes = {
            "asap": ".xml",
            "binary_mask": ".png",
            "3dhistech": ".xml",
            "geojson": ".geojson",
            "geojson_qupath_mrxs": ".geojson",
        }
        return suffixes.get(target_format, ".geojson")

    def _find_slide_metadata(
        self, base_name: str, image_dir: Optional[Path], target_format: FormatType
    ) -> Optional[ImageMetadata]:
        if target_format not in ["geojson_qupath_mrxs", "binary_mask"] or not image_dir:
            return None

        slide_extensions = [
            ".mrxs",
            ".svs",
            ".ndpi",
            ".vms",
            ".vmu",
            ".scn",
            ".tif",
            ".tiff",
        ]
        slide_files: List[Path] = []
        for ext in slide_extensions:
            slide_files.extend(image_dir.glob(f"*{base_name}*{ext}"))

        if slide_files:
            from .image_reader import ImageReader

            try:
                metadata = ImageReader.read_image_metadata(slide_files[0])
                self.logger.info(f"Loaded metadata from: {slide_files[0].name}")
                return metadata
            except Exception as e:
                self.logger.warning(f"Could not read image metadata: {e}")
        return None

    def _batch_process_individual(
        self,
        input_files: List[Path],
        output_dir: Path,
        source_format: Optional[FormatType],
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
    ) -> Dict[str, Any]:
        self.logger.info(
            f"Processing {len(input_files)} files: {source_format or 'auto'} → {target_format}"
        )
        unmatched_annotations: List[str] = []

        with tqdm(input_files, desc="Converting", unit="file", ncols=80) as pbar:
            for input_file in pbar:
                pbar.set_postfix_str(input_file.name[:20])
                self._process_individual_file(
                    input_file,
                    output_dir,
                    source_format,
                    target_format,
                    image_dir,
                    downsample_factor,
                    unmatched_annotations,
                )

        successful = sum(1 for r in self.results.values() if r.get("success", False))
        self.logger.info(
            f"✓ Batch completed: {successful}/{len(input_files)} files converted successfully"
        )

        if unmatched_annotations:
            self.logger.warning(
                f"⚠ {len(unmatched_annotations)} annotations have no matching images. "
                f"Use convert_file() with explicit image_path for precise control."
            )
        return self.results

    def _process_individual_file(
        self,
        input_file: Path,
        output_dir: Path,
        source_format: Optional[FormatType],
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
        unmatched_annotations: List[str],
    ) -> None:
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
                    return

            if curr_source_format:
                effective_target_format = target_format or "geojson"
                output_suffix = self._get_output_suffix(effective_target_format)
                output_file = output_dir / f"{input_file.stem}{output_suffix}"
                image_path = self._find_matching_image(
                    input_file,
                    image_dir,
                    effective_target_format,
                    unmatched_annotations,
                )

                self.convert_file(
                    input_file,
                    output_file,
                    source_format=curr_source_format,
                    target_format=effective_target_format,
                    image_path=image_path,
                    downsample_factor=downsample_factor,
                )
        except Exception as e:
            self.results[input_file.stem] = {
                "input_path": str(input_file),
                "source_format": curr_source_format
                if "curr_source_format" in locals()
                else None,
                "target_format": target_format,
                "output_path": None,
                "success": False,
                "error": str(e),
            }

    def _find_matching_image(
        self,
        input_file: Path,
        image_dir: Optional[Path],
        target_format: FormatType,
        unmatched_annotations: List[str],
    ) -> Optional[Path]:
        if target_format not in ["geojson_qupath_mrxs", "binary_mask"] or not image_dir:
            return None

        slide_extensions = [
            ".mrxs",
            ".svs",
            ".ndpi",
            ".vms",
            ".vmu",
            ".scn",
            ".tif",
            ".tiff",
        ]
        for ext in slide_extensions:
            candidate = image_dir / f"{input_file.stem}{ext}"
            if candidate.exists():
                return candidate

        unmatched_annotations.append(input_file.name)
        return None
