"""PLA-546 C02: cold Small contributions fetch only their frozen quick clip.

Synthetic media only (never production suite resources). A loopback HTTP server
stands in for the published per-clip host; request logs prove exactly which
assets each run transferred.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import posixpath
import shutil
import stat
import threading
from unittest import mock

import pytest
from client import campaign, suite
from scripts.prepare_client_suite_distribution import build_clip_bundle

from test_suite_v1 import small_media_fixture


def add_notices(root: Path, manifest) -> None:
    notices = root / "notices"
    notices.mkdir(exist_ok=True)
    for clip in manifest.clips:
        license_id = str(clip.provenance.get("license") or "CC-BY-4.0")
        (notices / f"{license_id}.txt").write_text(f"license text for {license_id}\n")
        (notices / f"{clip.clip_id}.txt").write_text(
            f"Attribution notice for {clip.clip_id}\nLicense: {license_id}; see {license_id}.txt\n"
        )


class ClipServer:
    """Serves the staged per-clip bundle; supports Range and tampered assets."""

    def __init__(self, root: Path, distribution, *, corrupt_paths=(), short_paths=()):
        manifest = json.loads((root / "manifest.json").read_text())
        by_id = {clip["id"]: clip for clip in manifest["clips"]}
        self.files = {}
        for entry in distribution["clips"].values():
            for asset in entry["assets"]:
                if str(asset["role"]) == "clip":
                    clip_id = str(asset["path"]).split("/")[0]
                    data = (root / "canonical" / by_id[clip_id]["fileName"]).read_bytes()
                else:
                    data = (root / "notices" / posixpath.basename(str(asset["path"]))).read_bytes()
                if str(asset["path"]) in corrupt_paths:
                    data = bytes([data[0] ^ 255]) + data[1:]
                self.files["/" + str(asset["downloadName"])] = data
        self.short_paths = set(short_paths)
        self.requests = []
        self.range_headers = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                server.requests.append(self.path)
                data = server.files.get(self.path)
                range_header = self.headers.get("Range")
                if range_header:
                    server.range_headers.append((self.path, range_header))
                if data is None:
                    self.send_error(404)
                    return
                if self.path in server.short_paths:
                    # A truncated complete response: declared short, body short.
                    truncated = data[: max(1, len(data) // 2)]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(truncated)))
                    self.end_headers()
                    self.wfile.write(truncated)
                    return
                start = 0
                if range_header and range_header.startswith("bytes=") and range_header.endswith("-"):
                    start = int(range_header[6:-1])
                if start:
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                    self.send_header("Content-Length", str(len(data) - start))
                    self.end_headers()
                    self.wfile.write(data[start:])
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.serving = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.serving.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.serving.join(timeout=2)
        campaign.wait_for_owned_acquisition()


def staged_fixture(tmp_path, **server_kwargs):
    """Staged suite tree: metadata + notices + served media, no local canonical bytes."""
    outer = small_media_fixture()
    root, manifest = outer.__enter__()
    server = None
    try:
        add_notices(root, manifest)
        distribution_path = suite.write_clip_distribution_metadata(str(root))
        metadata = json.loads(Path(distribution_path).read_text())
        clip = manifest.clips[0]
        clip_bytes = (root / "canonical" / clip.file_name).read_bytes()
        server = ClipServer(root, metadata, **server_kwargs)
        # A distributed client tree carries no canonical bytes; only the pack or
        # the published per-clip host can supply the media.
        shutil.rmtree(root / "canonical")
        cache = str(tmp_path / "cache")
        with mock.patch.dict(os.environ, {suite.SUITE_CLIP_BASE_URL_ENV: server.base_url}):
            yield server, cache, clip, manifest, clip_bytes
    finally:
        if server is not None:
            server.close()
        outer.__exit__(None, None, None)


@pytest.fixture
def clip_env(tmp_path):
    yield from staged_fixture(tmp_path)


def distribution_entry(clip_id):
    payload = json.loads(Path(suite.get_clip_distribution_path()).read_text())
    return payload["clips"][clip_id]


def test_cold_quick_clip_downloads_only_selected_clip_assets(clip_env):
    server, cache, clip, manifest, clip_bytes = clip_env
    prepared = suite.ensure_suite_clip(clip, cache_root=cache)
    served_ids = {path.lstrip("/").split("--", 1)[0] for path in server.requests}
    assert served_ids == {clip.clip_id}
    assert not any("pack" in path or path.endswith(".tar.gz") for path in server.requests)
    installed = Path(cache) / "canonical" / clip.file_name
    assert installed.read_bytes() == clip_bytes
    assert Path(prepared.path) == installed
    assert prepared.input_hash == clip.sha256
    # License notices install with matching frozen hashes.
    for asset in distribution_entry(clip.clip_id)["assets"]:
        if str(asset["role"]) == "clip":
            continue
        installed_notice = Path(suite._clip_asset_target(cache, clip, asset))
        assert hashlib.sha256(installed_notice.read_bytes()).hexdigest() == asset["sha256"]


def test_repeat_uses_hash_verified_cache_without_requests(clip_env):
    server, cache, clip, manifest, clip_bytes = clip_env
    suite.ensure_suite_clip(clip, cache_root=cache)
    before = len(server.requests)
    suite.ensure_suite_clip(clip, cache_root=cache)
    assert len(server.requests) == before
    estimate = suite.acquisition_estimate(clip_ids=[clip.clip_id], cache_root=cache, manifest=manifest)
    assert estimate["strategy"] == "cache"
    assert estimate["bytesToTransfer"] == 0


def test_estimate_is_truthful_before_any_download(clip_env):
    server, cache, clip, manifest, clip_bytes = clip_env
    entry = distribution_entry(clip.clip_id)
    expected = sum(int(asset["byteSize"]) for asset in entry["assets"])
    estimate = suite.acquisition_estimate(clip_ids=[clip.clip_id], cache_root=cache, manifest=manifest)
    assert server.requests == []  # the estimate itself transfers nothing
    assert estimate["strategy"] == "clip"
    assert estimate["bytesToTransfer"] == expected
    assert estimate["peakStorageBytes"] >= expected
    assert estimate["clipRouteAvailable"] is True
    assert estimate["storageOk"] is True
    suite.ensure_suite_clip(clip, cache_root=cache)
    assert len(server.requests) == len(entry["assets"])  # one GET per declared asset


def test_full_suite_only_downloads_missing_clips(clip_env):
    server, cache, clip, manifest, clip_bytes = clip_env
    suite.ensure_suite_clip(clip, cache_root=cache)
    server.requests.clear()
    server.range_headers.clear()
    prepared = suite.ensure_suite(manifest, cache_root=cache)
    assert len(prepared) == len(manifest.clips)
    served_ids = {path.lstrip("/").split("--", 1)[0] for path in server.requests}
    assert clip.clip_id not in served_ids
    assert served_ids == {other.clip_id for other in manifest.clips if other.clip_id != clip.clip_id}


def test_truncated_response_never_installs_and_resumes_with_range(clip_env, monkeypatch):
    server, cache, clip, manifest, clip_bytes = clip_env
    monkeypatch.setenv(suite.SUITE_ALLOW_FULL_PACK_ENV, "0")  # surface the clip-route error
    entry = distribution_entry(clip.clip_id)
    clip_asset = next(asset for asset in entry["assets"] if asset["role"] == "clip")
    server.short_paths.add("/" + clip_asset["downloadName"])
    with pytest.raises(RuntimeError, match="size mismatch"):
        suite.ensure_suite_clip(clip, cache_root=cache)
    target = Path(cache) / "canonical" / clip.file_name
    part = Path(str(target) + ".part")
    assert not target.exists()
    assert not part.exists()  # corrupt/incomplete bytes are never retained
    # A retained partial from an interrupted run must resume via Range.
    target.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(clip_bytes[: len(clip_bytes) // 2])
    server.short_paths.clear()
    server.requests.clear()
    server.range_headers.clear()
    prepared = suite.ensure_suite_clip(clip, cache_root=cache)
    assert Path(prepared.path).read_bytes() == clip_bytes
    resumed = [path for path, header in server.range_headers if header.startswith("bytes=")]
    assert any(clip.file_name in path for path in resumed)


def test_corrupt_clip_response_never_installs(tmp_path):
    outer = small_media_fixture()
    root, manifest = outer.__enter__()
    server = None
    try:
        add_notices(root, manifest)
        distribution_path = suite.write_clip_distribution_metadata(str(root))
        metadata = json.loads(Path(distribution_path).read_text())
        clip = manifest.clips[0]
        corrupt = [asset["path"] for asset in metadata["clips"][clip.clip_id]["assets"] if asset["role"] == "clip"]
        server = ClipServer(root, metadata, corrupt_paths=corrupt)
        shutil.rmtree(root / "canonical")
        cache = str(tmp_path / "cache")
        with mock.patch.dict(os.environ, {suite.SUITE_CLIP_BASE_URL_ENV: server.base_url,
                                          suite.SUITE_ALLOW_FULL_PACK_ENV: "0"}):
            with pytest.raises(RuntimeError, match="checksum mismatch"):
                suite.ensure_suite_clip(clip, cache_root=cache)
        target = Path(cache) / "canonical" / clip.file_name
        assert not target.exists()
        assert not Path(str(target) + ".part").exists()
    finally:
        if server is not None:
            server.close()
        outer.__exit__(None, None, None)


def test_full_pack_fallback_requires_explicit_size_disclosure(clip_env, capsys):
    server, cache, clip, manifest, clip_bytes = clip_env
    clip_error = "forced per-clip failure"
    with mock.patch.dict(os.environ, {suite.SUITE_ALLOW_FULL_PACK_ENV: "0"}), \
         mock.patch.object(suite, "_materialize_clip_from_distribution", side_effect=RuntimeError(clip_error)):
        with pytest.raises(RuntimeError, match="disabled") as blocked:
            suite.ensure_suite_clip(clip, cache_root=cache)
    assert suite.SUITE_ALLOW_FULL_PACK_ENV in str(blocked.value)

    pack_bytes = int(suite.load_suite_pack_metadata()["distribution"]["byteSize"])

    def fake_pack(clip_arg, pack_metadata, cache_root=None):
        target = Path(suite.clip_cache_path(clip_arg, cache_root))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(clip_bytes)
        return str(target)

    with mock.patch.object(suite, "_materialize_clip_from_distribution", side_effect=RuntimeError(clip_error)), \
         mock.patch.object(suite, "_materialize_clip_from_suite_pack", side_effect=fake_pack) as pack:
        prepared = suite.ensure_suite_clip(clip, cache_root=cache)
    pack.assert_called_once()
    assert Path(prepared.path).read_bytes() == clip_bytes
    err = capsys.readouterr().err
    assert f"{pack_bytes:,} bytes" in err  # size disclosed before the pack transfer
    assert clip_error in err


def test_full_pack_compatibility_is_preserved_by_default(tmp_path):
    outer = small_media_fixture()
    root, manifest = outer.__enter__()
    try:
        clip = manifest.clips[0]
        clip_bytes = (root / "canonical" / clip.file_name).read_bytes()
        shutil.rmtree(root / "canonical")  # distributed tree: no packaged media
        cache = str(tmp_path / "cache")

        def fake_pack(clip_arg, pack_metadata, cache_root=None):
            target = Path(suite.clip_cache_path(clip_arg, cache_root))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(clip_bytes)
            return str(target)

        with mock.patch.object(suite, "_materialize_clip_from_suite_pack", side_effect=fake_pack) as pack:
            prepared = suite.ensure_suite_clip(clip, cache_root=cache)
        pack.assert_called_once()  # no clip-distribution.json -> pack route unchanged
        assert Path(prepared.path).read_bytes() == clip_bytes
    finally:
        outer.__exit__(None, None, None)


def test_protected_cache_reports_clear_error_without_partial_install(clip_env):
    server, cache, clip, manifest, clip_bytes = clip_env
    if os.name == "nt":
        pytest.skip("POSIX permission semantics")
    locked = Path(cache) / "canonical"
    locked.mkdir(parents=True)
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(RuntimeError, match="not writable|write-protected"):
            suite.ensure_suite_clip(clip, cache_root=cache)
    finally:
        locked.chmod(stat.S_IRWXU)
    assert not list(locked.glob("*.part"))
    assert not list(locked.glob(clip.file_name))
    assert server.requests == []  # blocked before any transfer


def test_disk_exhaustion_gate_stops_before_any_transfer(clip_env, monkeypatch):
    server, cache, clip, manifest, clip_bytes = clip_env
    monkeypatch.setenv(suite.SUITE_MIN_FREE_MB_ENV, "4194304")  # 4 TiB floor
    with pytest.raises(RuntimeError, match="bytes free"):
        suite.ensure_suite_clip(clip, cache_root=cache)
    assert server.requests == []
    estimate = suite.acquisition_estimate(clip_ids=[clip.clip_id], cache_root=cache, manifest=manifest)
    assert estimate["storageOk"] is False


def test_tampered_clip_distribution_fails_closed(tmp_path):
    outer = small_media_fixture()
    root, manifest = outer.__enter__()
    try:
        add_notices(root, manifest)
        path = suite.write_clip_distribution_metadata(str(root))
        payload = json.loads(Path(path).read_text())
        clip = manifest.clips[0]
        payload["clips"][clip.clip_id]["assets"][0]["sha256"] = "0" * 64
        Path(path).write_text(json.dumps(payload))
        with pytest.raises(RuntimeError, match="identity mismatch"):
            suite.load_clip_distribution_metadata()
    finally:
        outer.__exit__(None, None, None)


def test_frozen_clip_distribution_matches_repo_suite_locks():
    metadata = suite.load_clip_distribution_metadata()
    assert metadata is not None
    assert metadata["source"] == "staged-unpublished"
    assert metadata["distribution"]["published"] is False
    assert metadata["distribution"]["baseUrl"] == ""
    frozen = suite.load_default_suite_manifest()
    lock = json.loads(Path(suite.get_suite_lock_path()).read_text())
    # The lock binds the manifest's canonical JSON, not its file bytes.
    suite_root = Path(suite.get_suite_lock_path()).parent
    manifest_payload = json.loads((suite_root / "manifest.json").read_text())
    assert suite._sha256_text(suite._canonical_json(manifest_payload)) == lock["manifestSha256"]
    lock_clips = {entry["id"]: entry for entry in lock["clips"]}
    for clip in frozen.clips:
        entry = metadata["clips"][clip.clip_id]
        clip_asset = next(asset for asset in entry["assets"] if asset["role"] == "clip")
        assert clip_asset["sha256"] == clip.sha256 == lock_clips[clip.clip_id]["sha256"]
        assert clip_asset["byteSize"] == clip.byte_size == lock_clips[clip.clip_id]["byteSize"]
        assert clip_asset["downloadName"] == f"{clip.clip_id}--{clip.file_name}"
        roles = [asset["role"] for asset in entry["assets"]]
        assert roles.count("clip") == 1
        assert "notice" in roles and "license" in roles


def test_full_pack_estimate_counts_one_shared_download(tmp_path):
    manifest = suite.load_default_suite_manifest()
    clips = manifest.clips[:2]
    with mock.patch.object(suite, "_packaged_canonical_path", return_value=None), \
            mock.patch.object(suite, "_pack_state", return_value={"packCached": False, "extracted": False}):
        estimate = suite.acquisition_estimate(
            [clip.clip_id for clip in clips], cache_root=str(tmp_path), manifest=manifest,
        )
    pack_bytes = estimate["fullPackBytes"]
    assert estimate["strategy"] == "pack"
    assert estimate["bytesToTransfer"] == pack_bytes
    assert estimate["peakStorageBytes"] == 2 * pack_bytes + sum(clip.byte_size for clip in clips)
    assert estimate["clips"][clips[0].clip_id]["transferBytes"] == pack_bytes
    assert estimate["clips"][clips[1].clip_id]["transferBytes"] == 0


def test_release_clip_bundle_uses_flat_unique_asset_names(tmp_path):
    outer = small_media_fixture()
    root, manifest = outer.__enter__()
    try:
        add_notices(root, manifest)
        bundle = tmp_path / "bundle"
        with mock.patch.object(suite, "load_default_suite_manifest", return_value=manifest):
            build_clip_bundle(source_suite_dir=root, bundle_out=bundle)
        metadata = json.loads((bundle / "clip-distribution.json").read_text())
        names = [asset["downloadName"] for entry in metadata["clips"].values()
                 for asset in entry["assets"]]
        assert len(names) == len(set(names))
        assert {path.name for path in bundle.iterdir()} == set(names) | {"clip-distribution.json"}
        assert all(path.is_file() for path in bundle.iterdir())
    finally:
        outer.__exit__(None, None, None)
