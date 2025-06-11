from pathlib import Path
from typing import Optional, Union

from .basecore import ImageMetadata


class ImageReader:
    @staticmethod
    def read_mrxs_metadata(image_path: Union[str, Path]) -> ImageMetadata:
        try:
            import openslide
        except ImportError:
            raise ImportError(
                "openslide-python is required for reading MRXS metadata. Install it with: pip install openslide-python"
            )

        try:
            slide = openslide.OpenSlide(str(image_path))

            offset_x = float(slide.properties.get("openslide.bounds-x", 0))
            offset_y = float(slide.properties.get("openslide.bounds-y", 0))
            mpp_x = float(slide.properties.get("openslide.mpp-x", 1.0))
            mpp_y = float(slide.properties.get("openslide.mpp-y", 1.0))
            width, height = slide.dimensions
            level_0_width, level_0_height = (
                slide.level_dimensions[0] if slide.level_dimensions else (width, height)
            )

            slide.close()

            return ImageMetadata(
                offset_x=offset_x,
                offset_y=offset_y,
                mpp_x=mpp_x,
                mpp_y=mpp_y,
                width=width,
                height=height,
                level_0_width=level_0_width,
                level_0_height=level_0_height,
            )
        except Exception as e:
            raise ValueError(
                f"Failed to read MRXS metadata from {image_path}: {str(e)}"
            )

    @staticmethod
    def read_image_metadata(image_path: Union[str, Path]) -> Optional[ImageMetadata]:
        image_path = Path(image_path)
        supported_extensions = [
            ".mrxs",
            ".svs",
            ".ndpi",
            ".vms",
            ".vmu",
            ".scn",
            ".bif",
            ".svslide",
        ]

        if image_path.suffix.lower() in supported_extensions:
            return ImageReader.read_mrxs_metadata(image_path)
        return None

    @staticmethod
    def is_openslide_compatible(image_path: Union[str, Path]) -> bool:
        try:
            import openslide

            return openslide.OpenSlide.detect_format(str(image_path)) is not None
        except ImportError:
            raise ImportError(
                "openslide-python is required for compatibility checks. Install it with: pip install openslide-python"
            )
        except Exception:
            return False
