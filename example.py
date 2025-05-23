from pathlib import Path
from annovert import Annovert, ConverterConfig

input_dir = "sandbox/anno"
output_dir = "sandbox/anno_geojson_qupath"

config = ConverterConfig(
    output_directory=Path(output_dir),
)

converter = Annovert(config)

converter.convert_file(
    "sandbox/anno/example.xml",
    "sandbox/anno_gj/example.geojson",
    target_format="geojson_qupath_mrxs",
    image_path="sandbox/imgs/example.mrxs",
)

results = converter.batch_process(
    input_dir=Path(input_dir),
    file_pattern="*.xml",
    target_format="geojson_qupath_mrxs",
    image_dir=Path("sandbox/imgs"),
)

converter.convert_file(
    "annotations.xml",
    "mask.tif",
    target_format="binary_mask",
    image_path="slide.mrxs",
    downsample_factor=8.0,
)

converter.convert_file("tissue_mask.tif", "regions.geojson", target_format="geojson")

converter.batch_process(
    input_dir="masks/", file_pattern="*.tif", target_format="geojson"
)
