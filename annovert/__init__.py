from .basecore import (
    Annotation,
    ConverterConfig,
    Coordinate,
    FormatType,
    ImageMetadata,
    Region,
    FormatDetector,
    AggregationConfig,
)
from .core import Annovert
from .formats import (
    ASAPAnnotation,
    GeoJSONAnnotation,
    HistechAnnotation,
    BinaryMaskAnnotation,
)
from .image_reader import ImageReader
from .qupath_geojson import QuPathMRXSGeoJSONAnnotation
from .aggregation import (
    AnnotationGrouper,
    HistechAggregator,
)

__version__ = "0.1.0"
