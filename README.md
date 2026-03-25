<img src="docs/title.svg" alt="annovert" height="42">

`annovert` provides the functionalities for converting between different annotation formats used in digital pathology.


### Example usage

```python
from pathlib import Path
from annovert import Annovert, ConverterConfig, Format

config = ConverterConfig(output_directory=Path("output"))
converter = Annovert(config)

converter.convert_file(
    input_path="annotation.xml",
    output_path="output/annotation.geojson",  # optional if config set
    target_format=Format.GEOJSON_QUPATH_MRXS,
    image_path="slide.mrxs"
)

converter.convert_file(
    input_path="annotation.xml",
    output_path="output/mask.tiff",  # or .jpg, .tif, .png
    target_format=Format.BINARY_MASK,
    image_path="slide.mrxs",
    downsample_factor=8.0
)

converter.batch_process(
    input_dir="annotations/",
    output_dir="output/",              # optional if config set
    target_format=Format.BINARY_MASK,
    image_dir="images/",
    downsample_factor=4.0
)
```

### Supported formats

| `Format` | Value | Extension | Description |
|----------|-------|-----------|-------------|
| `Format.ASAP` | `"asap"` | `.xml` | ASAP XML annotations |
| `Format.GEOJSON` | `"geojson"` | `.geojson` | Standard GeoJSON |
| `Format.GEOJSON_QUPATH_MRXS` | `"geojson_qupath_mrxs"` | `.geojson` | GeoJSON with MRXS offset/mpp metadata¹ |
| `Format.HISTECH_3D` | `"3dhistech"` | `.xml` | 3D Histech / CaseViewer XML (source only) |
| `Format.BINARY_MASK` | `"binary_mask"` | `.png` `.jpg` `.tif` | Binary segmentation mask¹ |
| `Format.HAMAMATSU_NDPA` | `"hamamatsu_ndpa"` | `.ndpa` | Hamamatsu NanoZoomer NDPA XML |

¹ *Requires `image_path` or `image_dir` for slide metadata*

Plain strings are accepted everywhere for backward compatibility (`"geojson_qupath_mrxs"` is equivalent to `Format.GEOJSON_QUPATH_MRXS`).

### Installation from source

```bash
git clone git@github.com:computationalpathologygroup/annovert.git
cd annovert
pip install -e .
```