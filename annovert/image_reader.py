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
    def read_tiff_metadata(image_path: Union[str, Path]) -> Optional[ImageMetadata]:
        try:
            from PIL import Image
        except ImportError:
            raise ImportError("Pillow is required for TIFF metadata reading")

        try:
            with Image.open(image_path) as img:
                width, height = img.size

                dpi = img.info.get("dpi", (72, 72))
                if isinstance(dpi, (list, tuple)) and len(dpi) >= 2:
                    x_dpi, y_dpi = dpi[0], dpi[1]
                else:
                    x_dpi, y_dpi = 72, 72

                mpp_x = 25400.0 / x_dpi if x_dpi > 0 else 1.0
                mpp_y = 25400.0 / y_dpi if y_dpi > 0 else 1.0

                return ImageMetadata(
                    offset_x=0.0,
                    offset_y=0.0,
                    mpp_x=mpp_x,
                    mpp_y=mpp_y,
                    width=width,
                    height=height,
                    level_0_width=width,
                    level_0_height=height,
                )
        except Exception:
            return None

    @staticmethod
    def read_image_metadata(image_path: Union[str, Path]) -> Optional[ImageMetadata]:
        image_path = Path(image_path)
        wsi_extensions = [
            ".mrxs",
            ".svs",
            ".ndpi",
            ".vms",
            ".vmu",
            ".scn",
            ".bif",
            ".svslide",
        ]
        tiff_extensions = [".tif", ".tiff"]

        if image_path.suffix.lower() in wsi_extensions:
            return ImageReader.read_mrxs_metadata(image_path)
        elif image_path.suffix.lower() in tiff_extensions:
            return ImageReader.read_tiff_metadata(image_path)
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
