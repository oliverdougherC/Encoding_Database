#!/usr/bin/env python3
"""Read an owned queue without importing mutation-capable client maintenance code.

Run on the native host; stdout is a portable evidence snapshot, not a certificate.
No API keys, configuration files, environment variables or transport are read.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def capture(queue):
    queue = Path(queue).resolve(strict=True)
    files, errors, artifacts = {}, [], {}
    paths = list(queue.glob("*.json"))
    for directory in ("campaigns", "receipts", "terminal", "dead-letter"):
        paths.extend((queue / directory).rglob("*.json"))
    for path in sorted(paths):
        relative = path.relative_to(queue).as_posix()
        try:
            if queue not in path.resolve(strict=True).parents:
                raise ValueError("evidence leaves owned queue")
            raw = path.read_bytes()
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("JSON evidence is not an object")
            files[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "value": value}
        except (OSError, ValueError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    for item in files.values():
        value = item["value"]
        metadata = value.get("metadata")
        candidates = [value, value.get("payload"), metadata.get("info") if isinstance(metadata, dict) else None]
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("artifactPath"), str):
                continue
            name = candidate["artifactPath"]
            if name in artifacts:
                continue
            path = Path(name)
            try:
                if queue not in path.resolve().parents:
                    artifacts[name] = {"state": "outside-owned-queue"}
                elif not path.is_file():
                    artifacts[name] = {"state": "absent"}
                else:
                    artifacts[name] = {"state": "present", "byteSize": path.stat().st_size,
                                       "sha256": digest(path)}
            except OSError as exc:
                artifacts[name] = {"state": "unreadable", "error": str(exc)}
    return {"kind": "native-queue-snapshot-v1", "queue": str(queue),
            "capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "directories": {name: (queue / name).is_dir()
                            for name in ("campaigns", "receipts", "terminal", "dead-letter")},
            "files": files, "artifacts": artifacts, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", required=True)
    print(json.dumps(capture(parser.parse_args().queue)))
