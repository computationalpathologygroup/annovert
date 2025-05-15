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

results = converter.batch_process(
    input_dir=Path(input_dir), file_pattern="*.geojson", target_format="asap"
)

# converter.convert_file(
#     Path(input_dir) / "example.xml",
#     Path(output_dir) / "example.geojson"
# )
