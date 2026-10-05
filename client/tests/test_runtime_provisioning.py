"""The CI runtime recovery path must reject unreviewed archive bytes."""

import pytest

from scripts.provision_pinned_runtime import provision


@pytest.mark.parametrize("platform", ["linux", "win"])
def test_candidate_archive_tamper_fails_before_extract(tmp_path, platform):
    archive = tmp_path / "candidate"
    archive.write_bytes(b"unreviewed")
    with pytest.raises(RuntimeError, match="reviewed SHA-256/size"):
        provision(platform, tmp_path / "out", archive_path=archive)
    assert not list((tmp_path / "out").rglob("ffmpeg*"))
