import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar, Dict, Optional

from client.artifacts import build_artifact_submission_payload, build_payload_hash, submit_artifact_submission


def _artifact_bytes() -> bytes:
    return b"artifact-data"


def _artifact_sha256() -> str:
    return hashlib.sha256(_artifact_bytes()).hexdigest()


def _run_create_template(byte_size: int) -> Dict[str, object]:
    run_create: Dict[str, object] = {
        "benchmarkProtocol": {
            "protocolVersion": "7.0",
            "sourceSuiteVersion": "encodingdb-test-suite-v1",
            "minimumClientVersion": "client/0.2.0",
            "canonicalRecipeRules": {"artifactUploadRequired": True},
            "canonicalOutputRules": {"singleVideoStream": True, "noAudio": True},
            "metricWorkerVersion": "authoritative-analysis/v1",
        },
        "testClip": {
            "suiteId": "encodingdb-test-suite",
            "suiteVersion": "encodingdb-test-suite-v1",
            "clipKey": "sports-action-960x540-24p",
            "sha256": "a" * 64,
            "workloadId": "sports-action-960x540-24p",
        },
        "recipe": {
            "fingerprint": "b" * 64,
            "canonicalJson": {"codecFamily": "h264"},
            "identity": {
                "codecFamily": "h264",
                "encoderImplementation": "libx264",
                "pixelFormat": "yuv420p",
                "bitDepth": 8,
                "chromaSubsampling": "4:2:0",
                "requestedRateControl": {"mode": "crf", "qualityValue": 24},
                "effectiveRateControl": {"mode": "crf", "qualityValue": 24},
            },
        },
        "environment": {
            "fingerprint": "c" * 64,
            "canonicalJson": {"cpuModel": "CPU"},
            "identity": {
                "cpuModel": "CPU",
                "cpuArchitecture": "x86_64",
                "physicalMemoryBytes": 17179869184,
                "ffmpegBuildFingerprint": "ffmpeg-build",
                "ffmpegVersion": "ffmpeg version n7",
                "clientVersion": "client/0.2.0",
                "osName": "testos",
                "osVersion": "1.0",
            },
        },
        "workloadId": "sports-action-960x540-24p",
        "expectedMetricModelId": "vmaf-v1-sdr-1080p",
        "inputHash": "d" * 64,
        "campaignId": "campaign-1",
        "repetitionGroupId": "campaign-1:recipe-1",
        "repetitionIndex": 1,
        "encodeWallTimeMs": 1_000,
        "encodeFps": 120.0,
        "sourceFps": 24.0,
        "realTimeRatio": 5.0,
        "sourceFrameCount": 120,
        "encodedFrameCount": 120,
        "telemetry": {"cpuUtilAvg": 15.0},
        "telemetrySources": {"hardwareMonitor": ["cpuUtilAvg"]},
        "telemetryMissing": [],
        "preRunEnvironmentCheck": {"snapshot": {"background_cpu_pct": 5.0}},
        "ffmpegProgressTelemetry": {"elapsedMs": 1_000, "frameCount": 120},
        "clientQualityDebug": {"vmafMean": 0.1, "vmafP5": 0.05},
        "artifact": {
            "role": "ENCODED",
            "sha256": _artifact_sha256(),
            "byteSize": byte_size,
            "mediaContainer": "mp4",
        },
    }
    run_create["payloadHash"] = build_payload_hash(run_create)
    return run_create


class _ArtifactFlowHandler(BaseHTTPRequestHandler):
    created_runs: ClassVar[Dict[str, Dict[str, object]]] = {}
    upload_attempts: ClassVar[int] = 0
    successful_uploads: ClassVar[int] = 0
    retry_once: ClassVar[bool] = False
    last_client_quality_debug: ClassVar[Optional[dict]] = None

    def _json_body(self) -> dict:
        body_len = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(body_len).decode("utf-8") if body_len > 0 else "{}"
        return json.loads(raw)

    def _bundle(self, run: Dict[str, object]) -> Dict[str, object]:
        return {
            "benchmarkRun": {
                "id": run["id"],
                "status": "ACCEPTED" if run.get("uploaded") else "PENDING",
                "statusReason": None,
                "workloadId": "sports-action-960x540-24p",
                "clientQualityDebug": run["clientQualityDebug"],
            },
            "artifact": {
                "id": f"artifact-{run['id']}",
                "role": "ENCODED",
                "sha256": _artifact_sha256(),
                "byteSize": len(_artifact_bytes()),
                "storageState": "RETAINED" if run.get("uploaded") else "PENDING",
                "stateReason": None,
                "mediaContainer": "mp4",
                "storageKey": "objects/test",
                "uploadedAt": None,
                "verifiedAt": None,
                "retainedAt": None,
                "deletedAt": None,
            },
            "analyses": [] if not run.get("uploaded") else [{
                "id": f"analysis-{run['id']}",
                "status": "COMPLETE",
                "metricModelId": "vmaf-v1-sdr-1080p",
                "qualityContextId": "vmaf-v1-sdr-1080p-yuv420p",
                "analysisWorkerVersion": "authoritative-analysis/v1",
                "vmafMean": 95.25,
                "vmafP5": 90.25,
                "xpsnr": 41.5,
                "ssim": 0.992,
                "psnr": 45.1,
                "videoBitrateBps": 2_222_222,
                "fileSizeBytes": len(_artifact_bytes()),
                "createdAt": "2026-08-12T00:00:00.000Z",
                "updatedAt": "2026-08-12T00:00:00.000Z",
            }],
        }

    def do_POST(self) -> None:
        if self.path == "/v7/benchmark-runs":
            body = self._json_body()
            payload_hash = str(body["payloadHash"])
            run = type(self).created_runs.get(payload_hash)
            if run is None:
                run = {
                    "id": f"run-{len(type(self).created_runs) + 1}",
                    "clientQualityDebug": body.get("clientQualityDebug"),
                    "uploaded": False,
                }
                type(self).created_runs[payload_hash] = run
                status = 201
            else:
                status = 200
            type(self).last_client_quality_debug = run["clientQualityDebug"]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"created": status == 201, **self._bundle(run)}).encode("utf-8"))
            return

        if self.path.endswith("/upload-authorizations"):
            _ = self._json_body()
            run_id = self.path.split("/")[3]
            run = next((value for value in type(self).created_runs.values() if value["id"] == run_id), None)
            if run is None:
                self.send_response(404)
                self.end_headers()
                return
            if run.get("uploaded"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"uploadRequired": False, **self._bundle(run)}).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"uploadRequired": True, "token": run_id}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_PUT(self) -> None:
        if not self.path.startswith("/v7/artifact-uploads/"):
            self.send_response(404)
            self.end_headers()
            return
        type(self).upload_attempts += 1
        if type(self).retry_once and type(self).upload_attempts == 1:
            self.send_response(503)
            self.end_headers()
            return
        body_len = int(self.headers.get("Content-Length", "0"))
        uploaded = self.rfile.read(body_len) if body_len > 0 else b""
        if uploaded != _artifact_bytes():
            self.send_response(400)
            self.end_headers()
            return
        run_id = self.path.rsplit("/", 1)[-1]
        run = next((value for value in type(self).created_runs.values() if value["id"] == run_id), None)
        if run is None:
            self.send_response(404)
            self.end_headers()
            return
        run["uploaded"] = True
        type(self).successful_uploads += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self._bundle(run)).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class ArtifactSubmissionTests(unittest.TestCase):
    def _start_server(self) -> tuple[HTTPServer, threading.Thread, str]:
        _ArtifactFlowHandler.created_runs = {}
        _ArtifactFlowHandler.upload_attempts = 0
        _ArtifactFlowHandler.successful_uploads = 0
        _ArtifactFlowHandler.retry_once = False
        _ArtifactFlowHandler.last_client_quality_debug = None
        server = HTTPServer(("127.0.0.1", 0), _ArtifactFlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_port}"

    def _submission(self, artifact_path: str) -> Dict[str, object]:
        return build_artifact_submission_payload(
            artifact_path=artifact_path,
            media_container="mp4",
            run_create=_run_create_template(len(_artifact_bytes())),
        )

    def test_server_analysis_remains_canonical_when_client_debug_quality_is_wrong(self) -> None:
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as td:
                artifact_path = os.path.join(td, "artifact.mp4")
                with open(artifact_path, "wb") as handle:
                    handle.write(_artifact_bytes())
                result = submit_artifact_submission(base_url, self._submission(artifact_path), retries=1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(_ArtifactFlowHandler.last_client_quality_debug, {"vmafMean": 0.1, "vmafP5": 0.05})
        self.assertEqual(result["analyses"][0]["vmafMean"], 95.25)
        self.assertEqual(result["analyses"][0]["vmafP5"], 90.25)

    def test_duplicate_submissions_are_idempotent(self) -> None:
        server, thread, base_url = self._start_server()
        try:
            with tempfile.TemporaryDirectory() as td:
                artifact_path = os.path.join(td, "artifact.mp4")
                with open(artifact_path, "wb") as handle:
                    handle.write(_artifact_bytes())
                submission = self._submission(artifact_path)
                first = submit_artifact_submission(base_url, submission, retries=1)
                second = submit_artifact_submission(base_url, submission, retries=1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(first["analyses"][0]["vmafMean"], 95.25)
        self.assertEqual(second["analyses"][0]["vmafMean"], 95.25)
        self.assertEqual(_ArtifactFlowHandler.successful_uploads, 1)
        self.assertEqual(len(_ArtifactFlowHandler.created_runs), 1)


if __name__ == "__main__":
    unittest.main()
