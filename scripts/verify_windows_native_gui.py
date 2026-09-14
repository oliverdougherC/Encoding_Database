"""Fail-closed verification of Windows CI GUI/console journal and helper evidence.

No GUI is simulated here. The PowerShell harness must produce real Windows
screenshots, observations, helper attestations and completed attempt journals.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_embedded(payload, locked):
    require(payload.get("frozen") is True and payload.get("platform") == "win", "Missing frozen Windows helper attestation")
    root = str(payload.get("extractionRoot", "")).replace("\\", "/").rstrip("/").casefold()
    require("_mei" in root and root, "Missing PyInstaller extraction root")
    for name in ("ffmpeg", "ffprobe"):
        actual = str(payload.get(name + "Path", "")).replace("\\", "/").casefold()
        require(actual.startswith(root + "/"), f"{name} was selected outside the package")
        require(payload["identity"][name]["sha256"] == locked[name]["sha256"], f"{name} embedded hash mismatch")
    lock_path = str(payload.get("lockPath", "")).replace("\\", "/").casefold()
    require(lock_path.startswith(root + "/"), "Runtime lock was selected outside the package")


def inspect_campaigns(queue, expected_clips, completed):
    manifests = list(Path(queue).glob("campaigns/*/manifest.json"))
    require(manifests, "No retained campaign manifest")
    clips = set()
    measured_count = 0
    warmup_count = 0
    artifacts = []
    for path in manifests:
        manifest = load(path)
        require(manifest["protocolVersion"] == "7.1", "Wrong measurement protocol")
        require(manifest.get("physicalSourceId"), "Missing physical-source identity")
        require(manifest["runtime"]["clientExecutionArchitecture"] == "x86_64", "Unexpected Windows execution architecture")
        for name in ("ffmpeg", "ffprobe"):
            require(manifest["runtime"][name]["architectures"] == ["x86_64"], f"Unexpected {name} architecture")
        tasks = manifest["tasks"]
        require(all(task["encoder"] == "libx264" and task["preset"] == "fast" for task in tasks), "GUI did not execute the selected software recipe")
        clips.update(task["clipId"] for task in tasks)
        marker = path.parent / "campaign-complete.json"
        if completed:
            require(marker.exists(), "Missing complete campaign marker")
            result = load(marker)
            require(result.get("failed") == 0 and result.get("skipped") == 0, "Campaign failed or skipped work")
        else:
            require(not marker.exists(), "Cancellation happened after campaign completion")
        per_recipe = {}
        warmed_recipes = set()
        for attempt_path in path.parent.glob("attempt-*.json"):
            attempt = load(attempt_path)
            schedule = attempt["schedule"]
            require(schedule["campaign_id"] == path.parent.name, "Attempt campaign identity changed")
            if schedule["phase"] == "warmup":
                warmup_count += 1
                warmed_recipes.add(schedule["recipe_id"])
            if schedule["phase"] != "measured":
                continue
            info = attempt.get("metadata", {}).get("info", {})
            if not completed and attempt.get("timing") is None and not attempt.get("countedForStability"):
                # An interrupted attempt may be recorded without completed media.
                continue
            artifact = Path(info.get("artifactPath", ""))
            require(artifact.is_file(), "Completed measured artifact was lost")
            require(digest(artifact) == info.get("artifactSha256"), "Retained artifact bytes changed")
            timing = attempt.get("timing") or {}
            elapsed = timing.get("elapsed_s", 0)
            require(math.isfinite(elapsed) and elapsed > 0, "Measured attempt has no valid process timing")
            require(timing.get("encoded_frame_count") == timing.get("source_frame_count") and timing.get("source_frame_count") in (192, 240), "Measured attempt did not cover a full canonical clip")
            require(timing.get("source_fps") == 24, "Noncanonical source cadence")
            if completed:
                require(attempt.get("structuralValidity", {}).get("state") != "invalid", "Completed campaign contains invalid media")
            measured_count += 1
            per_recipe[schedule["recipe_id"]] = per_recipe.get(schedule["recipe_id"], 0) + 1
            artifacts.append({"sha256": info["artifactSha256"], "bytes": artifact.stat().st_size})
        if completed:
            require(len(per_recipe) == len(tasks) and all(count >= 2 for count in per_recipe.values()), "A recipe lacks two measured attempts")
            require(set(per_recipe).issubset(warmed_recipes), "A recipe lacks its warmup")
    require(measured_count > 0 and warmup_count > 0, "No completed measurement/warmup preserved")
    if expected_clips is not None:
        require(clips == set(expected_clips), "Seven-clip campaign coverage differs from the frozen suite")
    return {"clips": sorted(clips), "measuredAttempts": measured_count, "warmupAttempts": warmup_count, "artifacts": artifacts}


def verify_receipt(receipt_path, suite, locked):
    receipt_path = Path(receipt_path)
    receipt = load(receipt_path)
    require(receipt["status"] == "PENDING_EVIDENCE_VALIDATION", "Harness did not complete its required phases")
    require(not receipt["cleanupForced"], "Harness required forced process cleanup")
    require("Windows" in receipt["os"]["Caption"], "No actual Windows OS receipt")
    gui = receipt["mode"] == "Gui"
    require([phase["name"] for phase in receipt["phases"]] == (["complete", "stop", "close"] if gui else ["seven-clips"]), "Required native acceptance phases are missing")
    summaries = []
    for phase in receipt["phases"]:
        require(phase["status"] == "PASSED" and not phase["survivors"], "Native phase failed or left owned processes")
        require(phase["exitCode"] == 0, "Packaged process returned nonzero")
        require(phase["encoderObserved"] and phase["helpers"], "No actual packaged encoder process observed")
        require("--no-submit" in phase["command"] and "--submit" not in phase["command"], "Unexpected publication command")
        verify_embedded(load(Path(phase["path"]) / "embedded-runtime.json"), locked)
        for helper in phase["helpers"].values():
            require(helper["sha256"] == locked["ffmpeg"]["sha256"], "Observed encoder differs from the reviewed helper")
            require("_mei" in helper["path"].casefold(), "Observed encoder was not extracted from the package")
        if gui:
            require((Path(phase["path"]) / "launch.png").is_file(), "Missing genuine GUI screenshot")
            require((Path(phase["path"]) / "launch.uia.json").is_file(), "Missing initial accessible-control capture")
            if phase["name"] in ("stop", "close"):
                require(phase["action"] == ("Stop" if phase["name"] == "stop" else "Close confirmed"), "Required GUI cancellation action not observed")
        completed = phase["name"] in ("complete", "seven-clips")
        expected = [clip["id"] for clip in suite["clips"]] if not gui else None
        summaries.append(inspect_campaigns(phase["queue"], expected, completed))
    receipt["journalVerification"] = summaries
    receipt["status"] = "PASSED_VIRTUALIZED_WINDOWS_SOFTWARE_ONLY"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--suite-manifest", required=True)
    parser.add_argument("--runtime-lock", required=True)
    args = parser.parse_args()
    try:
        result = verify_receipt(args.receipt, load(args.suite_manifest), load(args.runtime_lock)["platforms"]["win"])
        print(json.dumps({"status": result["status"], "mode": result["mode"], "phaseCount": len(result["phases"])}))
    except (KeyError, ValueError, OSError, TypeError) as error:
        receipt = load(args.receipt)
        receipt.update(status="FAILED_EVIDENCE_VALIDATION", error=str(error))
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(f"Native Windows evidence failed: {error}")
