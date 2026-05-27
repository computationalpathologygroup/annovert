from pathlib import Path

import numpy as np
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def asap_file() -> Path:
    return FIXTURES_DIR / "sample.asap.xml"


@pytest.fixture
def geojson_file() -> Path:
    return FIXTURES_DIR / "sample.geojson"


@pytest.fixture
def qupath_mrxs_file() -> Path:
    return FIXTURES_DIR / "sample_qupath_mrxs.geojson"


@pytest.fixture
def histech_file() -> Path:
    return FIXTURES_DIR / "sample.histech.xml"


@pytest.fixture
def ndpa_file() -> Path:
    return FIXTURES_DIR / "sample.ndpa"


@pytest.fixture
def binary_mask_file(tmp_path: Path) -> Path:
    """Generate a minimal 64×64 binary mask PNG with a 32×32 white square."""
    from PIL import Image

    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[16:48, 16:48] = 255
    img_path = tmp_path / "mask.png"
    Image.fromarray(mask).save(img_path)
    return img_path
