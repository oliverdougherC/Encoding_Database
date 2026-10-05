#!/usr/bin/env python3
"""Exercise a hash-pinned native package against a bounded LOOPBACK FIXTURE.

Uses a copy of a real retained envelope/artifact. Never contacts a real backend,
changes original campaign IDs, or encodes. Fixture evidence is explicitly not
production-backend acceptance. All output paths are create-only task ownership.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(args):
    package = args.package.resolve(strict=True)
    if digest(package) != args.package_sha256:
        raise ValueError("Native executable hash differs from pin")
    payload = json.loads(args.envelope.read_text())
    envelope_digest = digest(args.envelope)
    source = args.artifact.resolve(strict=True)
    if digest(source) != payload["artifactSha256"] or source.stat().st_size != payload["artifactByteSize"]:
        raise ValueError("Source media differs from real retained envelope")
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Use a retained artifact smaller than32MiB")
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    queue = root / "queue"
    (queue / "artifacts").mkdir(parents=True)
    artifact = queue / "artifacts" / (payload["artifactSha256"] + ".mp4")
    shutil.copyfile(source, artifact)
    payload.update(artifactPath=str(artifact), artifactManaged=True)
    identity = {k: v for k, v in payload.items() if k not in ("artifactPath", "artifactManaged")}
    local_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    entry = {"version": 1, "localHash": local_hash, "payload": payload, "queuedAt": int(time.time()),
             "attempts": 0, "nextAttemptAt": 0, "retryDeadlineAt": time.time() + 3600}
    entry_path = queue / (local_hash + ".json")
    entry_path.write_text(json.dumps(entry))
    ledger = {"kind": "packaged-native-loopback-fixture-fault", "phase": args.phase,
              "realBackend": False, "packageSha256": args.package_sha256, "payloadHash": payload["runCreate"]["payloadHash"],
              "sourceEnvelopeSha256": envelope_digest,
              "sourceArtifactSha256": payload["artifactSha256"], "localHash": local_hash,
              "startedAt": datetime.now(timezone.utc).isoformat(), "events": [], "runs": []}
    ledger_path = root / "result.json"
    reached, release = threading.Event(), threading.Event()
    state = {"phase": args.phase, "committed": False, "putCount": 0}

    def event(phase):
        ledger["events"].append({"phase": phase, "time": time.time()})

    def bundle():
        return {"benchmarkRun": {"id": "fixture-original-run", "payloadHash": payload["runCreate"]["payloadHash"], "status": "PENDING"},
                "artifact": {"id": "fixture-original-artifact", "benchmarkRunId": "fixture-original-run", "role": "ENCODED",
                             "sha256": payload["artifactSha256"], "byteSize": payload["artifactByteSize"],
                             "storageState": "RETAINED" if state["committed"] else "PENDING"},
                "analyses": [{"id": "fixture-analysis", "benchmarkRunId": "fixture-original-run",
                              "artifactId": "fixture-original-artifact", "metricModelId": "fixture-pending-model",
                              "status": "PENDING"}] if state["committed"] else []}

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def body(self):
            size = int(self.headers.get("Content-Length", "0"))
            if size > max(source.stat().st_size, 1024 * 1024):
                raise ValueError("Unexpected fixture request size")
            return self.rfile.read(size)

        def respond(self, value):
            raw = json.dumps(value).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def barrier(self, phase):
            event(phase)
            if state["phase"] == phase:
                reached.set()
                if args.gui_driver_root:
                    (root / "barrier.json").write_text(json.dumps({"phase": phase, "time": time.time()}))
                release.wait(60 if args.gui_driver_root else 20)

        def drop(self):
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()

        def do_GET(self):
            if self.path != "/v7/compatibility":
                self.send_error(404)
                return
            self.respond({"protocolVersion": "7.1", "minimumClientVersion": "client/0.3.0",
                          "encodeTimerBoundary": "ffmpeg-process-v1", "sourceSuiteVersion": "encodingdb-test-suite-v1",
                          "suiteFingerprint": args.suite_fingerprint})

        def do_POST(self):
            body = self.body()
            if self.path == "/v7/benchmark-runs":
                create = json.loads(body)
                if create != payload["runCreate"]:
                    self.send_error(400)
                    return
                self.barrier("create")
                if state["phase"] == "lost-ack" and state["committed"]:
                    self.drop()
                    return
                self.respond(bundle())
            elif self.path.endswith("/upload-authorizations"):
                self.barrier("auth")
                self.respond({**bundle(), "uploadRequired": False} if state["committed"]
                             else {"uploadRequired": True, "token": "fixture-only"})
            else:
                self.send_error(404)

        def do_PUT(self):
            self.barrier("put")
            raw = self.body()
            if hashlib.sha256(raw).hexdigest() != payload["artifactSha256"]:
                self.send_error(400)
                return
            state["committed"] = True
            state["putCount"] += 1
            event("fixture-commit")
            self.barrier("read")
            if state["phase"] == "lost-ack":
                event("response-dropped-after-fixture-commit")
                self.drop()
            else:
                self.respond(bundle())

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("ENCODINGDB_", "DYLD_")) or key in ("API_KEY", "FFMPEG_EXE", "FFPROBE_EXE", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH") or key.lower().endswith("_proxy"):
            env.pop(key)
    env["ENCODINGDB_STATE_DIR"] = str(root / "state")
    command = [str(package), "--cli", "--upload-only", "--queue-dir", str(queue),
               "--base-url", f"http://127.0.0.1:{server.server_port}", "--retries", "1"]

    def execute(name, cancel):
        if args.gui_driver_root:
            control = {"package": str(package), "packageSha256": args.package_sha256,
                       "queue": str(queue), "baseUrl": f"http://127.0.0.1:{server.server_port}",
                       "state": str(root / "gui-state"), "action": name, "cancel": cancel,
                       "phase": args.phase, "localHash": local_hash, "result": str(root / (name + "-gui-result.json"))}
            (root / "gui-request.json").write_text(json.dumps(control))
            label = "fault-" + args.phase + "-" + name + "-" + str(int(time.time()))[-6:]
            command = ["powershell", "-NoProfile", "-File", str(args.gui_driver_root / "windows-desktop-launch.ps1"),
                       "-Root", str(args.gui_driver_root), "-RunLabel", label,
                       "-Driver", "native-windows-retry-driver.ps1", "-Scenario", str(root)]
            with (root / (name + "-launch.log")).open("xb") as log:
                subprocess.run(command, stdout=log, stderr=log, check=True, timeout=45)
            deadline = time.monotonic() + 120
            result_path = Path(control["result"])
            while not result_path.exists() and time.monotonic() < deadline:
                time.sleep(.25)
            if not result_path.exists():
                raise ValueError("GUI driver did not return its bounded result")
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            ledger["runs"].append(result)
            if not result.get("passed"):
                raise ValueError("GUI driver failed: " + str(result.get("error")))
            return result["exitCode"]
        with (root / (name + ".stdout")).open("xb") as out, (root / (name + ".stderr")).open("xb") as err:
            process = subprocess.Popen(command, env=env, stdout=out, stderr=err,
                                       start_new_session=os.name != "nt")
            start = time.monotonic()
            try:
                if cancel:
                    if os.name == "nt":
                        raise ValueError("Windows phase Stop needs an ordinary-session GUI driver; do not substitute forced termination")
                    if not reached.wait(30):
                        raise ValueError("Native client never reached requested network barrier")
                    event("sigint-at-" + args.phase)
                    os.killpg(process.pid, signal.SIGINT)
                code = process.wait(timeout=35)
                ledger["runs"].append({"name": name, "exitCode": code, "seconds": time.monotonic() - start})
                return code
            finally:
                if process.poll() is None:
                    ledger["forcedCleanup"] = True
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)

    try:
        first = execute("interrupted", args.phase != "lost-ack")
        expected_first = 0 if args.gui_driver_root else (10 if args.phase == "lost-ack" else 130)
        if first != expected_first:
            raise ValueError("Unexpected native interrupted exit code: " + str(first))
        if not entry_path.is_file() or not artifact.is_file() or digest(artifact) != payload["artifactSha256"]:
            raise ValueError("Unacknowledged evidence was not preserved")
        ledger["retainedAfterInterruption"] = True
        pending = json.loads(entry_path.read_text())
        state["phase"] = "pass"
        release.set()
        due_in = max(0, float(pending.get("nextAttemptAt") or 0) - time.time())
        if due_in > 15:
            raise ValueError("Fixture retry is unexpectedly delayed")
        time.sleep(due_in + .1)
        second = execute("replay", False)
        if second != 0:
            raise ValueError("Native replay did not complete")
        receipt = json.loads((queue / "receipts" / (local_hash + ".json")).read_text())
        proof = receipt["acknowledgment"]
        if proof["payloadHash"] != payload["runCreate"]["payloadHash"] or proof["artifactSha256"] != payload["artifactSha256"]:
            raise ValueError("Replay receipt has foreign identity")
        if state["putCount"] != 1:
            raise ValueError("Replay caused duplicate artifact PUT")
        if list(queue.rglob("attempt-*.json")) or digest(args.envelope) != envelope_digest:
            raise ValueError("Upload-only fixture changed measurement evidence")
        ledger.update(passed=True, putCount=state["putCount"], runIdentity=proof["benchmarkRunId"],
                      originalMediaUnchanged=digest(source) == payload["artifactSha256"],
                      originalEnvelopeUnchanged=True, newAttemptRecords=0)
    except Exception as exc:
        ledger.update(passed=False, error=str(exc), putCount=state["putCount"])
        raise
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        ledger_path.write_text(json.dumps(ledger, indent=2))
    print(json.dumps({"passed": ledger["passed"], "phase": args.phase, "realBackend": False, "out": str(root)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--suite-fingerprint", required=True)
    parser.add_argument("--phase", choices=["create", "auth", "put", "read", "lost-ack"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gui-driver-root", type=Path, help="Windows only: new owned ordinary-session Retry/Stop driver root")
    run(parser.parse_args())
