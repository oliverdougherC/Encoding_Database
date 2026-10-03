"""Seeded state exercises for the independent campaign conservation oracle."""

import hashlib
import importlib.util
import json
import random
from pathlib import Path


MODULE = Path(__file__).with_name("campaign_conservation.py")
SPEC = importlib.util.spec_from_file_location("campaign_conservation", MODULE)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path, seed):
    rng = random.Random(seed)
    campaign_id = f"campaign-{seed:016x}"
    queue = tmp_path / "queue"
    root = queue / "campaigns" / campaign_id
    _write(root / "manifest.json", {
        "tasks": [{"recipe": "a"}, {"recipe": "b"}],
        "protocolConfig": {
            "warmup_runs": 1, "minimum_measured_runs": 2,
            "max_adaptive_repeats": 2, "stability_threshold_ratio": 0.03,
        },
    })
    order = 0
    expected = []
    for recipe in ("a", "b"):
        state = rng.choice(("unstarted", "partial", "stable", "adaptive"))
        if state == "unstarted":
            continue
        phases = ["warmup"] + (["measured"] if state == "partial" else ["measured"] * (4 if state == "adaptive" else 2))
        for index, phase in enumerate(phases):
            order += 1
            sha = hashlib.sha256(f"{recipe}:{index}".encode()).hexdigest()
            record = {
                "schedule": {"campaign_id": campaign_id, "recipe_id": recipe,
                             "phase": phase, "execution_order": order,
                             "repetition_index": index if phase == "measured" else 1},
                "timing": {"elapsed_s": float(index + 1) if state == "adaptive" else 1.0},
                "countedForStability": phase == "measured",
                "overallValidity": {"state": "valid"},
                "metadata": {"info": {"artifactSha256": sha, "error": None}},
                "skippedBeforeEncode": False,
            }
            _write(root / f"attempt-{order:06d}.json", record)
            if phase != "measured" or state == "partial":
                continue
            expected.append(order)
            verdict = rng.choice(("confirmed", "queued", "terminal", "unstaged", "journal_only"))
            if verdict != "journal_only":
                payload = {"runCreate": {"campaignId": campaign_id, "payloadHash": sha},
                           "artifactSha256": sha}
                _write(root / f"submission-{order:06d}.json", payload)
                local_hash = oracle._payload_hash(payload)
                if verdict == "queued":
                    _write(queue / f"{local_hash}.json", {"payload": payload})
                if verdict == "terminal":
                    _write(queue / "terminal" / f"{local_hash}.json", {"payload": payload})
            if verdict == "confirmed":
                _write(root / f"submission-{order:06d}.accepted.json", {
                    "executionOrder": order, "benchmarkRunId": f"run-{seed}-{order}",
                    "artifactSha256": sha,
                })
    return queue, campaign_id, expected


def test_seeded_conservation_states(tmp_path):
    for seed in range(1, 25):
        queue, campaign_id, expected = _fixture(tmp_path / str(seed), seed)
        result = oracle.audit(queue, campaign_id)
        assert result["issues"] == [], (seed, result)
        assert result["frozenGroups"] == sum(result["groups"].values())
        assert result["attempts"]["total"] == sum(result["attempts"]["validity"].values())
        assert result["eligibleFinalized"] == len(expected)
        assert result["eligibleFinalized"] == sum(result["publication"].values())


def test_duplicate_acknowledged_server_identity_is_detected(tmp_path):
    queue, campaign_id, eligible = _fixture(tmp_path, 49)
    root = queue / "campaigns" / campaign_id
    assert len(eligible) >= 2
    for order in eligible[:2]:
        record = json.loads((root / f"attempt-{order:06d}.json").read_text())
        _write(root / f"submission-{order:06d}.accepted.json", {
            "executionOrder": order, "benchmarkRunId": "same-server-run",
            "artifactSha256": record["metadata"]["info"]["artifactSha256"],
        })
    result = oracle.audit(queue, campaign_id)
    assert "duplicate server run ID in accepted markers" in result["issues"]


def test_oracle_identifies_staged_copy_by_immutable_payload():
    payload = {
        "submissionKind": "authoritative-artifact-run-v1",
        "artifactPath": "/journal/original.mp4",
        "artifactSha256": "a" * 64,
        "runCreate": {"payloadHash": "b" * 64},
    }
    staged = dict(payload, artifactPath="/queue/artifacts/copy.mp4", artifactManaged=True)
    assert oracle._payload_hash(payload) == oracle._payload_hash(staged)


def test_persistence_and_acknowledgment_boundaries_conserve_identity(tmp_path):
    queue = tmp_path / "queue"
    campaign_id = "campaign-0000000000000001"
    root = queue / "campaigns" / campaign_id
    _write(root / "manifest.json", {
        "tasks": [{"recipe": "r"}],
        "protocolConfig": {"warmup_runs": 1, "minimum_measured_runs": 2,
                           "max_adaptive_repeats": 0, "stability_threshold_ratio": 0.03},
    })
    for order, phase in ((1, "warmup"), (2, "measured"), (3, "measured")):
        _write(root / f"attempt-{order:06d}.json", {
            "schedule": {"campaign_id": campaign_id, "recipe_id": "r",
                         "phase": phase, "execution_order": order},
            "timing": {"elapsed_s": 1.0},
            "countedForStability": phase == "measured",
            "overallValidity": {"state": "valid"},
            "metadata": {"info": {"artifactSha256": f"{order:064x}"}},
            "skippedBeforeEncode": False,
        })

    def state():
        result = oracle.audit(queue, campaign_id)
        assert result["issues"] == []
        assert result["eligibleFinalized"] == sum(result["publication"].values()) == 2
        return result["publication"]

    assert state() == {"journal_only": 2}
    payload = {"submissionKind": "authoritative-artifact-run-v1",
               "artifactPath": str(root / "measured.mp4"),
               "artifactSha256": f"{2:064x}",
               "runCreate": {"campaignId": campaign_id, "payloadHash": "b" * 64}}
    _write(root / "submission-000002.json", payload)
    assert state() == {"unstaged_envelope": 1, "journal_only": 1}
    local_hash = oracle._payload_hash(payload)
    queued = queue / f"{local_hash}.json"
    _write(queued, {"payload": dict(payload, artifactPath="/managed/copy.mp4")})
    assert state() == {"queued": 1, "journal_only": 1}
    queued.unlink()
    _write(queue / "receipts" / f"{local_hash}.json", {
        "localHash": local_hash, "response": {"benchmarkRun": {"id": "run-original"}},
    })
    assert state() == {"receipted_without_journal_marker": 1, "journal_only": 1}
    _write(root / "submission-000002.accepted.json", {
        "executionOrder": 2, "benchmarkRunId": "run-original",
        "artifactSha256": f"{2:064x}",
    })
    assert state() == {"confirmed": 1, "journal_only": 1}
