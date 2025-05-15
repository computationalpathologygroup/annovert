from pathlib import Path

from annovert import (
    Annovert,
    ConverterConfig,
)

input_dir = "data"
output_dir = "output"

config = ConverterConfig(
    output_directory=Path(output_dir),
)

converter = Annovert(config)

# results = converter.batch_process(
#     input_dir=Path(input_dir), file_pattern="*.xml", target_format="geojson"
# )


converter.convert_file(
    "annotation_asap.xml", "annotation_geojson.geojson", target_format="geojson"
)
