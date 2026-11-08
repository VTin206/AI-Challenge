import os
from pathlib import Path

import pytest

from datamate.slm.frames import load_frames

ROOT = os.environ.get("DATAMATE_DATA_DIR")


@pytest.mark.skipif(not ROOT, reason="set DATAMATE_DATA_DIR to the folder holding train/ and public_test/")
@pytest.mark.parametrize("split", ["train", "public_test"])
def test_every_business_loads(split):
    data = Path(ROOT) / split / "data"
    businesses = sorted(p for p in data.iterdir() if p.is_dir())
    assert businesses
    for biz in businesses[:3]:
        frames = load_frames(biz)
        assert frames and all(len(df.columns) > 1 for df in frames.values())
