from pathlib import Path

from annovert import (
    Annovert,
    ConverterConfig,
)

input_dir = "sandbox/anno"
output_dir = "sandbox/anno_geojson_qupath"

config = ConverterConfig(
    output_directory=Path(output_dir),
)

converter = Annovert(config)

# converter.convert_file(
#     "annotation_asap.xml",
#     "annotation_geojson.geojson",
#     target_format="geojson"
# )

converter.convert_file(
    "sandbox/anno/example.xml",
    "sandbox/anno_gj/example.geojson",
    target_format="geojson_qupath_mrxs",
    image_path="sandbox/imgs/example.mrxs",
)

# converter.convert_file(
#     "standard_annotation.geojson",
#     "qupath_mrxs_annotation.geojson",
#     target_format="geojson_qupath_mrxs",
#     image_path="slide.mrxs"
# )

# results = converter.batch_process(
#     input_dir=Path(input_dir),
#     file_pattern="*.xml",
#     target_format="geojson_qupath_mrxs",
#     image_dir=Path("sandbox/imgs")
# )
