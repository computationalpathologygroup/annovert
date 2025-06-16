import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, Tuple
import logging
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

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


class FormatResolver:
    _EXTENSION_MAPPING = {
        ".geojson": "geojson",
        ".json": "geojson",
        ".xml": None,
        ".tif": "binary_mask",
        ".tiff": "binary_mask",
    }

    @classmethod
    def detect_from_path(cls, file_path: Path) -> FormatType:
        suffix = file_path.suffix.lower()

        if suffix in [".geojson", ".json"]:
            return cls._detect_json_format(file_path)
        elif suffix == ".xml":
            return cls._detect_xml_format(file_path)
        elif suffix in [".tif", ".tiff"]:
            return "binary_mask"

        raise ValueError(f"Cannot determine annotation format from file: {file_path}")

    @classmethod
    def _detect_json_format(cls, file_path: Path) -> FormatType:
        with open(file_path, "r") as f:
            content = f.read(4096)
        try:
            format_type = Annotation.detect_format(content)
            if format_type in ["geojson", "geojson_qupath_mrxs"]:
                return format_type
        except ValueError:
            pass
        return "geojson"

    @classmethod
    def _detect_xml_format(cls, file_path: Path) -> FormatType:
        with open(file_path, "r") as f:
            content = f.read(4096)
        try:
            return Annotation.detect_format(content)
        except ValueError:
            return cls._detect_xml_by_root_tag(content)

    @classmethod
    def _detect_xml_by_root_tag(cls, content: str) -> FormatType:
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


class AnnotationLoader:
    @staticmethod
    def load(input_path: Path, source_format: FormatType) -> Any:
        loaders = {
            "geojson_qupath_mrxs": AnnotationLoader._load_qupath_geojson,
            "asap": lambda p: ASAPAnnotation.from_file(p),
            "geojson": lambda p: GeoJSONAnnotation.from_file(p),
            "3dhistech": lambda p: HistechAnnotation.from_file(p),
            "binary_mask": lambda p: BinaryMaskAnnotation.from_file(p),
        }

        loader = loaders.get(source_format)
        if not loader:
            raise ValueError(f"Unsupported source format: {source_format}")

        return loader(input_path)

    @staticmethod
    def _load_qupath_geojson(input_path: Path) -> Any:
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        with open(input_path, "r") as f:
            return QuPathMRXSGeoJSONAnnotation.from_string(f.read())


class MetadataLoader:
    @staticmethod
    def load(
        image_path: Optional[Union[str, Path]], target_format: FormatType
    ) -> Optional[ImageMetadata]:
        if target_format in ["geojson_qupath_mrxs", "binary_mask"] and image_path:
            from .image_reader import ImageReader

            try:
                return ImageReader.read_image_metadata(image_path)
            except Exception:
                return None
        return None


class ConversionEngine:
    def __init__(self) -> None:
        self._converters = self._build_converter_map()

    def _build_converter_map(self) -> Dict[Tuple[str, str], callable]:
        return {
            ("ASAPAnnotation", "asap"): lambda a, t, m, d: a,
            ("ASAPAnnotation", "geojson"): lambda a, t, m, d: a.to_geojson(),
            ("ASAPAnnotation", "geojson_qupath_mrxs"): self._asap_to_qupath,
            ("ASAPAnnotation", "binary_mask"): self._asap_to_binary_mask,
            ("GeoJSONAnnotation", "asap"): lambda a, t, m, d: a.to_asap(),
            ("GeoJSONAnnotation", "geojson"): lambda a, t, m, d: a,
            ("GeoJSONAnnotation", "geojson_qupath_mrxs"): self._geojson_to_qupath,
            ("GeoJSONAnnotation", "binary_mask"): self._geojson_to_binary_mask,
            ("HistechAnnotation", "asap"): lambda a, t, m, d: a.to_asap(),
            ("HistechAnnotation", "geojson"): lambda a, t, m, d: a.to_geojson(),
            ("HistechAnnotation", "geojson_qupath_mrxs"): self._histech_to_qupath,
            ("HistechAnnotation", "binary_mask"): self._histech_to_binary_mask,
            ("BinaryMaskAnnotation", "asap"): lambda a, t, m, d: a.to_asap(),
            ("BinaryMaskAnnotation", "geojson"): lambda a, t, m, d: a.to_geojson(),
            (
                "BinaryMaskAnnotation",
                "geojson_qupath_mrxs",
            ): self._binary_mask_to_qupath,
            ("BinaryMaskAnnotation", "binary_mask"): lambda a, t, m, d: a,
        }

    def convert(
        self,
        annotation: Any,
        target_format: FormatType,
        metadata: Optional[ImageMetadata] = None,
        downsample_factor: float = 1.0,
    ) -> Any:
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        if isinstance(annotation, QuPathMRXSGeoJSONAnnotation):
            return self._convert_qupath_geojson(
                annotation, target_format, metadata, downsample_factor
            )

        annotation_type = type(annotation).__name__
        converter_key = (annotation_type, target_format)

        converter = self._converters.get(converter_key)
        if not converter:
            raise ValueError(
                f"Unsupported conversion from {annotation_type} to {target_format}"
            )

        return converter(annotation, target_format, metadata, downsample_factor)

    def _convert_qupath_geojson(
        self, annotation, target_format: FormatType, metadata, downsample_factor: float
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

    def _asap_to_qupath(self, annotation, target_format, metadata, downsample_factor):
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        base_geojson = annotation.to_geojson()
        return QuPathMRXSGeoJSONAnnotation.from_geojson(base_geojson, metadata)

    def _asap_to_binary_mask(
        self, annotation, target_format, metadata, downsample_factor
    ):
        base_geojson = annotation.to_geojson()
        return BinaryMaskAnnotation.from_geojson(
            base_geojson, metadata, downsample_factor
        )

    def _geojson_to_qupath(
        self, annotation, target_format, metadata, downsample_factor
    ):
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        return QuPathMRXSGeoJSONAnnotation.from_geojson(annotation, metadata)

    def _geojson_to_binary_mask(
        self, annotation, target_format, metadata, downsample_factor
    ):
        return BinaryMaskAnnotation.from_geojson(
            annotation, metadata, downsample_factor
        )

    def _histech_to_qupath(
        self, annotation, target_format, metadata, downsample_factor
    ):
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        base_geojson = annotation.to_geojson()
        return QuPathMRXSGeoJSONAnnotation.from_geojson(base_geojson, metadata)

    def _histech_to_binary_mask(
        self, annotation, target_format, metadata, downsample_factor
    ):
        base_geojson = annotation.to_geojson()
        return BinaryMaskAnnotation.from_geojson(
            base_geojson, metadata, downsample_factor
        )

    def _binary_mask_to_qupath(
        self, annotation, target_format, metadata, downsample_factor
    ):
        from .qupath_geojson import QuPathMRXSGeoJSONAnnotation

        base_geojson = annotation.to_geojson()
        return QuPathMRXSGeoJSONAnnotation.from_geojson(base_geojson, metadata)


class FileProcessor:
    def __init__(self, config: ConverterConfig, logger: ConversionLogger):
        self.config = config
        self.logger = logger
        self.engine = ConversionEngine()

    def process_single_file(
        self,
        input_file: Path,
        output_dir: Path,
        source_format: Optional[FormatType],
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
        unmatched_annotations: List[str],
    ) -> Dict[str, Any]:
        try:
            curr_source_format = self._resolve_source_format(input_file, source_format)
            effective_target_format = target_format or "geojson"

            output_suffix = self._get_output_suffix(effective_target_format)
            output_file = output_dir / f"{input_file.stem}{output_suffix}"
            image_path = self._find_matching_image(
                input_file, image_dir, effective_target_format, unmatched_annotations
            )

            annotation = AnnotationLoader.load(input_file, curr_source_format)
            metadata = MetadataLoader.load(image_path, effective_target_format)

            result = self.engine.convert(
                annotation, effective_target_format, metadata, downsample_factor
            )

            if hasattr(result, "save"):
                result.save(output_file)

            return {
                "input_path": str(input_file),
                "source_format": curr_source_format,
                "target_format": effective_target_format,
                "output_path": str(output_file),
                "success": True,
            }

        except Exception as e:
            return {
                "input_path": str(input_file),
                "source_format": source_format,
                "target_format": target_format,
                "output_path": None,
                "success": False,
                "error": str(e),
            }

    def _resolve_source_format(
        self, input_file: Path, source_format: Optional[FormatType]
    ) -> FormatType:
        if source_format:
            return source_format
        if self.config.default_source_format:
            return self.config.default_source_format
        if self.config.allow_auto_detect:
            return FormatResolver.detect_from_path(input_file)
        raise ValueError("Source format not specified and auto-detection disabled")

    @lru_cache(maxsize=100)
    def _get_output_suffix(self, target_format: FormatType) -> str:
        suffixes = {
            "asap": ".xml",
            "binary_mask": ".png",
            "3dhistech": ".xml",
            "geojson": ".geojson",
            "geojson_qupath_mrxs": ".geojson",
        }
        return suffixes.get(target_format, ".geojson")

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


class Annovert:
    def __init__(self, config: Optional[ConverterConfig] = None) -> None:
        self.config = config or ConverterConfig()
        self.results: Dict[str, Any] = {}
        self.logger = ConversionLogger()
        self.engine = ConversionEngine()
        self.file_processor = FileProcessor(self.config, self.logger)

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
        downsample_factor = downsample_factor or self.config.mask_downsample_factor

        annotation = AnnotationLoader.load(input_path, source_format)
        metadata = MetadataLoader.load(image_path, target_format)

        self.logger.info(f"Converting: {source_format} → {target_format}")
        result = self.engine.convert(
            annotation, target_format, metadata, downsample_factor
        )

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(result, "save"):
                result.save(output_path)
                self.logger.info(f"✓ Saved to: {output_path}")

        self.results[input_path.stem] = {
            "input_path": str(input_path),
            "source_format": source_format,
            "target_format": target_format,
            "output_path": str(output_path) if output_path else None,
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
            detected = FormatResolver.detect_from_path(input_path)
            self.logger.info(f"Detected format: {detected}")
            return detected
        raise ValueError("Source format not specified and auto-detection disabled")

    def _resolve_target_format(
        self,
        output_path: Optional[Union[str, Path]],
        target_format: Optional[FormatType],
    ) -> FormatType:
        if target_format:
            return target_format
        if output_path:
            return self._infer_format_from_extension(Path(output_path))
        if self.config.default_target_format:
            return self.config.default_target_format
        raise ValueError("Target format not specified and cannot be determined")

    def _infer_format_from_extension(self, output_path: Path) -> FormatType:
        suffix = output_path.suffix.lower()
        if suffix in [".geojson", ".json"]:
            return (
                "geojson_qupath_mrxs"
                if "_qupath_mrxs" in output_path.stem
                else "geojson"
            )
        elif suffix == ".xml":
            return "asap"
        elif suffix in [".tif", ".tiff", ".png", ".jpg", ".jpeg"]:
            return "binary_mask"
        elif self.config.default_target_format:
            return self.config.default_target_format
        raise ValueError(
            f"Cannot determine target format from output path: {output_path}"
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

    def _batch_process_individual(
        self,
        input_files: List[Path],
        output_dir: Path,
        source_format: Optional[FormatType],
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
    ) -> Dict[str, Any]:
        unmatched_annotations: List[str] = []

        if self.config.enable_parallel_processing and len(input_files) > 10:
            return self._process_files_parallel(
                input_files,
                output_dir,
                source_format,
                target_format,
                image_dir,
                downsample_factor,
                unmatched_annotations,
            )
        else:
            return self._process_files_sequential(
                input_files,
                output_dir,
                source_format,
                target_format,
                image_dir,
                downsample_factor,
                unmatched_annotations,
            )

    def _process_files_sequential(
        self,
        input_files: List[Path],
        output_dir: Path,
        source_format: Optional[FormatType],
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
        unmatched_annotations: List[str],
    ) -> Dict[str, Any]:
        with tqdm(input_files, desc="Converting", unit="file", ncols=80) as pbar:
            for input_file in pbar:
                pbar.set_postfix_str(input_file.name[:20])
                result = self.file_processor.process_single_file(
                    input_file,
                    output_dir,
                    source_format,
                    target_format,
                    image_dir,
                    downsample_factor,
                    unmatched_annotations,
                )
                self.results[input_file.stem] = result

        self._log_batch_completion(len(input_files), unmatched_annotations)
        return self.results

    def _process_files_parallel(
        self,
        input_files: List[Path],
        output_dir: Path,
        source_format: Optional[FormatType],
        target_format: Optional[FormatType],
        image_dir: Optional[Path],
        downsample_factor: float,
        unmatched_annotations: List[str],
    ) -> Dict[str, Any]:
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_file = {
                executor.submit(
                    self.file_processor.process_single_file,
                    input_file,
                    output_dir,
                    source_format,
                    target_format,
                    image_dir,
                    downsample_factor,
                    unmatched_annotations,
                ): input_file
                for input_file in input_files
            }

            with tqdm(
                total=len(input_files), desc="Converting", unit="file", ncols=80
            ) as pbar:
                for future in as_completed(future_to_file):
                    input_file = future_to_file[future]
                    result = future.result()
                    self.results[input_file.stem] = result
                    pbar.update(1)

        self._log_batch_completion(len(input_files), unmatched_annotations)
        return self.results

    def _log_batch_completion(
        self, total_files: int, unmatched_annotations: List[str]
    ) -> None:
        successful = sum(1 for r in self.results.values() if r.get("success", False))
        self.logger.info(
            f"✓ Batch completed: {successful}/{total_files} files converted successfully"
        )

        if unmatched_annotations:
            self.logger.warning(
                f"⚠ {len(unmatched_annotations)} annotations have no matching images"
            )

    def _resolve_output_dir(self, output_dir: Optional[Union[str, Path]]) -> Path:
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            return output_path
        elif self.config.output_directory:
            return self.config.output_directory
        else:
            raise ValueError("Output directory not specified")

    def _detect_batch_format(
        self, files: List[Path], source_format: Optional[FormatType]
    ) -> Optional[FormatType]:
        if source_format:
            return source_format
        if not self.config.allow_auto_detect:
            return None
        for file_path in files[:5]:
            try:
                return FormatResolver.detect_from_path(file_path)
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
            raise ValueError("Aggregation config is required")

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
            f"✓ Aggregated batch completed: {successful}/{len(groups)} groups converted"
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

            output_suffix = self.file_processor._get_output_suffix(
                effective_target_format
            )
            output_name = slide_name or group.base_name
            output_file = output_dir / f"{output_name}{output_suffix}"

            metadata = self._find_slide_metadata(
                group.base_name, image_dir, effective_target_format
            )

            result = self.engine.convert(
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
                "error": str(e),
                "success": False,
            }

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
        for ext in slide_extensions:
            slide_files = list(image_dir.glob(f"*{base_name}*{ext}"))
            if slide_files:
                return MetadataLoader.load(slide_files[0], target_format)
        return None
