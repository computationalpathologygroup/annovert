from pathlib import Path
from annovert import Annovert, ConverterConfig

input_dir = "sandbox/anno"
output_dir = "sandbox/anno_geojson_qupath"

config = ConverterConfig(
    output_directory=Path(output_dir),
)

converter = Annovert(config)

print("=== Single File Conversion ===")
converter.convert_file(
    "sandbox/anno/example.xml",
    "sandbox/anno_gj/example.geojson",
    target_format="geojson_qupath_mrxs",
    image_path="sandbox/imgs/example.mrxs",
)

print("\n=== Batch Processing ===")
results = converter.batch_process(
    input_dir=Path(input_dir),
    file_pattern="*.xml",
    target_format="geojson_qupath_mrxs",
    image_dir=Path("sandbox/imgs"),
)
