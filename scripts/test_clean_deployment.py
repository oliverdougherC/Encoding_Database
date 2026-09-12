#!/usr/bin/env python3
"""Exercise deploy.sh from a fresh committed checkout against an isolated stack.

Requires Git, Node 20, Docker Compose and OpenSSL (for the test TLS certificate).
No host Python packages, FFmpeg, pre-extracted suite, or adjacent pack are used.
The public 1.5 GB pack is downloaded by the supported deployment path itself.
Logs and summary.json survive failures; only this run's uniquely named stack is
removed. Production services, configuration and named volumes are never used.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PL_KEYS = ("PL_V7_REFERENCE_CONTEXT_PATH", "PL_V7_REFERENCE_CONTEXT_VERSION", "PL_V7_REFERENCE_BITRATES_JSON")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def isolated_config(config, project, checkout):
    """Change only names/ports for isolation; retain builds and validation gates."""
    config = json.loads(json.dumps(config))
    checkout = checkout.resolve()
    require(set(config["services"]) == {"db", "server", "frontend", "nginx"}, "Production service inventory changed; review isolation")
    config["name"] = project
    for name, volume in config.get("volumes", {}).items():
        require(not volume.get("external"), f"External volume is unsafe in acceptance test: {name}")
        volume["name"] = f"{project}_{name}"
    for name, network in config.get("networks", {}).items():
        require(not network.get("external"), f"External network is unsafe in acceptance test: {name}")
        network["name"] = f"{project}_{name}"
    for name, service in config["services"].items():
        require(not service.get("container_name"), f"Fixed container name is unsafe: {name}")
        require(not service.get("network_mode"), f"Shared network mode is unsafe: {name}")
        if service.get("build"):
            context = Path(service["build"]["context"]).resolve()
            require(context.is_relative_to(checkout), f"Build context escapes fresh checkout: {context}")
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                require(Path(mount["source"]).resolve().is_relative_to(checkout), "Bind mount escapes test checkout")
            else:
                require(mount["type"] == "volume" and mount["source"] in config["volumes"], "Unmanaged service volume")
        for port in service.get("ports", []):
            port.update({"host_ip": "127.0.0.1", "published": "0"})
    return config


def build_test_environment(example, project):
    values = {}
    for line in example.splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    values.update({
        "POSTGRES_USER": "acceptance", "POSTGRES_PASSWORD": secrets.token_hex(24),
        "POSTGRES_DB": "acceptance", "DATABASE_URL": "", "ARTIFACT_UPLOAD_SECRET": secrets.token_hex(32),
        "ARTIFACT_VOLUME_NAME": f"{project}_artifact_data", "CORS_ORIGIN": "https://127.0.0.1",
        "APP_URL": "https://127.0.0.1", "NEXT_PUBLIC_APP_URL": "https://127.0.0.1",
        "INTERNAL_API_BASE_URL": "http://server:3001", "ALLOW_TEST_ONLY_REFERENCE_CONTEXTS": "0",
        **{key: "" for key in PL_KEYS},
    })
    return values


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.project = "encodingdb-acceptance-" + secrets.token_hex(6)
        self.output = args.output_dir.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.temp = Path(tempfile.mkdtemp(prefix=self.project + "-")).resolve()
        self.checkout = self.temp / "checkout"
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith(("COMPOSE_", "DEPLOY_", "ENCODINGDB_SUITE_", "PL_V7_")) or key in {"ALLOW_TEST_ONLY_REFERENCE_CONTEXTS", "NGINX_CERTS_DIR", "CERT_DIR", "CERT_FILE", "KEY_FILE", "SUBJECT", "DAYS"}:
                del self.env[key]
        self.env.update({"COMPOSE_PROJECT_NAME": self.project, "DEPLOY_COMPOSE_FILE": "acceptance.compose.json"})
        self.summary = {"schemaVersion": 1, "startedAt": now(), "project": self.project, "status": "running", "commands": [], "failureCases": []}
        self.compose_ready = False

    def write_summary(self):
        (self.output / "summary.json").write_text(json.dumps(self.summary, indent=2) + "\n")

    def run(self, args, log, *, env=None, check=True, cwd=None):
        path = self.output / (log + ".log")
        started = now()
        with path.open("w") as stream:
            result = subprocess.run(args, cwd=cwd or self.checkout, env=env or self.env, stdout=stream, stderr=subprocess.STDOUT, text=True)
        self.summary["commands"].append({"argv": args, "log": path.name, "exitCode": result.returncode, "startedAt": started, "finishedAt": now()})
        self.write_summary()
        require(not check or result.returncode == 0, f"Command failed ({result.returncode}); see {path}")
        return result.returncode, path.read_text()

    def compose(self, *args):
        return ["docker", "compose", "-p", self.project, "-f", "acceptance.compose.json", *args]

    def snapshot(self, log):
        _, raw = self.run(self.compose("ps", "-aq"), log + "-ids")
        ids = raw.split()
        require(len(ids) == 4, f"Expected four isolated services, got {len(ids)}")
        _, raw = self.run(["docker", "inspect", *ids], log + "-inspect")
        entries = json.loads(raw)
        snapshot = {}
        # Do not retain full inspect output: Config.Env contains test credentials.
        (self.output / (log + "-inspect.log")).unlink()
        for item in entries:
            labels = item["Config"]["Labels"]
            require(labels["com.docker.compose.project"] == self.project, "Container belongs to another project")
            service = labels["com.docker.compose.service"]
            state = item["State"]
            snapshot[service] = {"id": item["Id"], "image": item["Image"], "startedAt": state["StartedAt"], "status": state["Status"], "health": state.get("Health", {}).get("Status"), "restartCount": item["RestartCount"]}
            if service == "server":
                env = dict(value.split("=", 1) for value in item["Config"]["Env"] if "=" in value)
                require(all(not env.get(key) for key in PL_KEYS), "PL calibration unexpectedly configured")
                require(env.get("ALLOW_TEST_ONLY_REFERENCE_CONTEXTS") == "0", "Test reference contexts unexpectedly enabled")
                self.summary["plConfiguration"] = {key: env.get(key, "") for key in (*PL_KEYS, "ALLOW_TEST_ONLY_REFERENCE_CONTEXTS")}
        (self.output / (log + "-inspect.log")).write_text(json.dumps(snapshot, indent=2) + "\n")
        return snapshot

    def empty_inputs(self, cache):
        paths = [self.checkout / tree / "resources/test_suite_v1/canonical" for tree in ("client", "server")]
        require(all(not path.exists() for path in paths), "Canonical directories must be absent before deployment")
        require(not cache.exists() or not any(cache.iterdir()), "Acquisition cache must start empty")
        require(not (self.checkout / "encodingdb-test-suite-v1.tar.gz").exists(), "Fresh checkout contains adjacent suite pack")
        return {"canonicalDirectoriesAbsent": True, "cacheEmpty": True, "adjacentPackAbsent": True}

    def execute(self):
        self.run(["git", "clone", "--no-local", str(self.args.repository.resolve()), str(self.checkout)], "clone", cwd=self.temp)
        self.run(["git", "checkout", "--detach", self.args.ref], "checkout")
        _, sha = self.run(["git", "rev-parse", "HEAD"], "tested-sha")
        self.summary["testedSha"] = sha.strip()
        _, status = self.run(["git", "status", "--porcelain", "--untracked-files=all"], "initial-git-status")
        require(not status.strip(), "Checkout is not pristine")
        values = build_test_environment((self.checkout / "env.example").read_text(), self.project)
        for key in values:
            self.env.pop(key, None)
        (self.checkout / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        self.run(["bash", "scripts/generate-dev-cert.sh"], "generate-test-tls")
        # Resolve the committed production compose first, then change only isolation.
        # Capture privately because Compose expands the disposable test secrets.
        result = subprocess.run(["docker", "compose", "-p", self.project, "-f", "docker-compose.prod.yml", "config", "--format", "json"], cwd=self.checkout, env=self.env, capture_output=True, text=True, check=True)
        config = isolated_config(json.loads(result.stdout), self.project, self.checkout)
        (self.checkout / "acceptance.compose.json").write_text(json.dumps(config, indent=2) + "\n")
        self.compose_ready = True
        self.summary["isolation"] = {"productionCompose": "docker-compose.prod.yml", "volumes": {key: value["name"] for key, value in config["volumes"].items()}, "networks": {key: value["name"] for key, value in config["networks"].items()}, "nginxPorts": config["services"]["nginx"]["ports"], "configurationChanges": ["unique project, volume and network names", "ephemeral ports bound to 127.0.0.1"], "testEnvSource": "env.example with disposable test secrets and HTTPS loopback URLs"}
        self.summary["initialInputs"] = self.empty_inputs(self.checkout / ".build/final-suite-cache")
        self.run(["bash", "deploy.sh", "--skip-pull"], "deploy-public-empty-cache")
        initial = self.snapshot("successful-stack")
        require(all(item["status"] == "running" and item["health"] == "healthy" for item in initial.values()), "Isolated production stack is not healthy")
        self.summary["successfulStack"] = initial
        self.verify_image(initial["server"]["image"])
        self.verify_api()
        for case in ("missing-pack", "unavailable-pack", "corrupt-pack"):
            self.failure_case(case)
        self.summary["status"] = "passed"

    def verify_image(self, image_id):
        script = r'''const fs=require('fs'),crypto=require('crypto'),path=require('path');
const root='/app/resources/test_suite_v1';
const hash=p=>{const bytes=fs.readFileSync(p);return {sha256:crypto.createHash('sha256').update(bytes).digest('hex'),byteSize:bytes.length}};
const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json')));
console.log(JSON.stringify({metadata:Object.fromEntries(['manifest.json','suite-lock.json','finalization-status.json','suite-pack.json'].map(n=>[n,hash(path.join(root,n))])),sources:manifest.clips.map(c=>({clipId:c.id,fileName:c.fileName,...hash(path.join(root,'canonical',c.fileName))}))}));'''
        _, raw = self.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "node", image_id, "-e", script], "server-image-seven-hashes")
        evidence = json.loads(raw)
        root = self.checkout / "server/resources/test_suite_v1"
        manifest = json.loads((root / "manifest.json").read_text())
        metadata = json.loads((root / "suite-pack.json").read_text())
        require(len(manifest["clips"]) == 7 and len(evidence["sources"]) == 7, "Expected exactly seven canonical sources")
        expected = [{"clipId": clip["id"], "fileName": clip["fileName"], "sha256": clip["sha256"], "byteSize": clip["byteSize"]} for clip in manifest["clips"]]
        require(evidence["sources"] == expected == metadata["contents"]["canonical"], "Image sources disagree with committed manifest/pack identities")
        for name, identity in evidence["metadata"].items():
            data = (root / name).read_bytes()
            require(identity == {"sha256": hashlib.sha256(data).hexdigest(), "byteSize": len(data)}, f"Image metadata differs from tested checkout: {name}")
        self.summary["serverImage"] = {"id": image_id, "verification": "independent docker run, network disabled, no bind mounts", "suiteFingerprint": metadata["suiteFingerprint"], **evidence}

    def verify_api(self):
        script = r'''(async()=>{const http=require('http');const results=[];for(const target of ['/health/live','/health/ready','/health/v7-evidence','/query?limit=1','/test-videos','/corpus?limit=1']){const result=await new Promise((resolve,reject)=>{http.get('http://127.0.0.1:3001'+target,r=>{let body='';r.on('data',c=>body+=c);r.on('end',()=>resolve({path:target,status:r.statusCode,body:JSON.parse(body)}))}).on('error',reject)});if(result.status!==200)throw Error(target+' failed');results.push(result)}console.log(JSON.stringify(results))})().catch(e=>{console.error(e);process.exit(1)})'''
        _, raw = self.run(self.compose("exec", "-T", "server", "node", "-e", script), "api-smoke")
        results = json.loads(raw)
        require(next(item["body"] for item in results if item["path"] == "/health/v7-evidence")["status"] == "ok", "Evidence health is not ok")
        require(all(isinstance(item["body"], list) for item in results if item["path"] in ("/query?limit=1", "/test-videos", "/corpus?limit=1")), "API collection response shape regressed")
        self.summary["apiChecks"] = results

    def failure_case(self, case):
        for tree in ("client", "server"):
            shutil.rmtree(self.checkout / tree / "resources/test_suite_v1/canonical", ignore_errors=True)
        cache = self.checkout / ".build" / (case + "-cache")
        before = self.snapshot(case + "-before")
        inputs = self.empty_inputs(cache)
        env = {**self.env, "DEPLOY_SUITE_CACHE_DIR": str(cache)}
        if case == "missing-pack":
            env["DEPLOY_SUITE_PACK_PATH"] = str(self.checkout / "missing-suite.tar.gz")
            reason = r"(?i)(suite pack not found|suite pack.*(?:does not exist|missing)|(?:does not exist|not found).*missing-suite)"
        elif case == "unavailable-pack":
            env["DEPLOY_SUITE_PACK_URL"] = "http://127.0.0.1:9/unavailable-suite.tar.gz"
            reason = r"(?i)(connection.*refused|failed to establish|unable to acquire|failed to download|could not.*download)"
        else:
            corrupt = self.checkout / ".build/corrupt-suite.tar.gz"
            corrupt.parent.mkdir(exist_ok=True)
            size = json.loads((self.checkout / "server/resources/test_suite_v1/suite-pack.json").read_text())["distribution"]["byteSize"]
            with corrupt.open("wb") as stream:
                stream.truncate(size)
            env["DEPLOY_SUITE_PACK_PATH"] = str(corrupt)
            reason = r"suite pack checksum mismatch"
        started = now()
        code, output = self.run(["bash", "deploy.sh", "--skip-pull"], case, env=env, check=False)
        finished = now()
        after = self.snapshot(case + "-after")
        _, raw = self.run(["docker", "events", "--since", started, "--until", finished, "--filter", f"label=com.docker.compose.project={self.project}", "--filter", "type=container", "--format", "{{json .}}"], case + "-events")
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        rollout_actions = {"create", "destroy", "start", "stop", "kill", "die", "restart", "pause", "unpause", "rename", "update"}
        lifecycle = [event for event in events if event.get("Action", event.get("status")) in rollout_actions]
        evidence = {"case": case, "initialInputs": inputs, "exitCode": code, "expectedDiagnostic": reason, "diagnosticMatched": bool(re.search(reason, output)), "containersUnchanged": before == after, "lifecycleEvents": lifecycle, "log": case + ".log"}
        self.summary["failureCases"].append(evidence)
        self.write_summary()
        require(code != 0, f"{case} unexpectedly succeeded")
        require(evidence["diagnosticMatched"], f"{case} did not fail for the expected acquisition/integrity reason")
        require(before == after and not lifecycle, f"{case} touched the running isolated stack before preparation completed")
        require(all(not (self.checkout / tree / "resources/test_suite_v1/canonical").exists() for tree in ("client", "server")), f"{case} installed unverified sources")

    def cleanup(self):
        if self.compose_ready:
            self.run(self.compose("logs", "--no-color", "--tail", "150"), "stack-logs", check=False)
            code, _ = self.run(self.compose("down", "--volumes", "--remove-orphans"), "isolated-stack-cleanup", check=False)
            self.summary["cleanupSucceeded"] = code == 0
            if code:
                self.summary["status"] = "failed"
                self.summary["cleanupError"] = "Isolated stack cleanup failed; use its recorded unique project name"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.summary["finishedAt"] = now()
        self.write_summary()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=ROOT, help="Local repository to clone without local object shortcuts")
    parser.add_argument("--ref", default="HEAD", help="Committed ref/SHA to test in the fresh clone (default: HEAD)")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".test-reports" / ("clean-deployment-" + time.strftime("%Y%m%dT%H%M%S")), help="New directory for retained logs and summary.json")
    args = parser.parse_args()
    test = Acceptance(args)
    try:
        test.execute()
    except BaseException as error:
        test.summary.update({"status": "failed", "error": str(error)})
        print(f"Clean deployment regression failed: {error}", file=sys.stderr)
    finally:
        test.cleanup()
    print(f"Clean deployment regression {test.summary['status']}: {test.output / 'summary.json'}")
    return 0 if test.summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
