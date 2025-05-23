# annovert

`annovert` provides the functionalities for converting between different annotation formats used in digital pathology.

### Example usage

```python
from pathlib import Path
from annovert import Annovert, ConverterConfig

config = ConverterConfig(output_directory=Path("output"))
converter = Annovert(config)

converter.convert_file(
    input_path="annotation.xml",
    output_path="output/annotation.geojson",  # optional if config set
    target_format="geojson_qupath_mrxs", # see supported formats
    image_path="slide.mrxs"
)

converter.batch_process(
    input_dir="annotations/",
    output_dir="output/",              # optional if config set
    target_format="geojson_qupath_mrxs", # see supported formats
    image_dir="images/"
)
```

### Supported target formats

| `target_format` | Extension | Description |
|-----------------|-----------|-------------|
| `asap` | `.xml` | ASAP XML annotations |
| `geojson` | `.geojson` | Standard GeoJSON |
| `geojson_qupath_mrxs` | `.geojson` | GeoJSON with MRXS metadata¹ |
| `3dhistech` | `.xml` | 3D Histech annotations |

¹ *Requires `image_path` or `image_dir` for metadata*


### Installation
Either direct from Github:
```bash
pip install git+https://github.com/computationalpathologygroup/annovert.git
```


or from source
```bash
git clone git@github.com:computationalpathologygroup/annovert.git
cd annovert
pip install .
```


