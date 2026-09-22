import json
from types import SimpleNamespace
from unittest import mock

import pytest

from client import main
from client.campaign import CampaignJournal, atomic_json, journal_path


@pytest.mark.parametrize("requested,explicit,expected", [(2048, False, 6144), (512, True, 512), (8192, True, 8192)])
def test_direct_resume_resolves_policy_and_journal_obeys_it(tmp_path, requested, explicit, expected):
    campaign_id = "campaign-1234567890abcdef"
    saved = {"seed": 17, "tasks": []}
    original = CampaignJournal(str(tmp_path), campaign_id, saved, 6144)
    args = SimpleNamespace(queue_dir=str(tmp_path), resume_campaign=campaign_id,
                           max_storage_mb=requested, max_storage_mb_explicit=explicit,
                           base_url="https://example.invalid")

    def reopen(**kwargs):
        journal = CampaignJournal(str(tmp_path), campaign_id, saved, kwargs["args"].max_storage_mb)
        assert journal.max_bytes == expected * 1024 * 1024
        return 0

    with mock.patch.object(main, "_apply_submission_policy", side_effect=lambda args, **kw: args), \
         mock.patch.object(main, "_preparation_preflight", return_value=0), \
         mock.patch.object(main, "detect_hardware", return_value={}), \
         mock.patch.object(main, "run_benchmark_batch", side_effect=reopen):
        assert main._resume_campaign(args) == 0
    assert json.loads((original.root / "budget.json").read_text())["maxStorageMb"] == expected
    assert json.loads((original.root / "manifest.json").read_text()) == saved


def test_direct_legacy_resume_allows_existing_retained_bytes(tmp_path):
    campaign_id = "campaign-1234567890abcdef"
    root = journal_path(str(tmp_path), campaign_id)
    atomic_json(root / "manifest.json", {"seed": 17, "tasks": []})
    args = SimpleNamespace(queue_dir=str(tmp_path), resume_campaign=campaign_id,
                           max_storage_mb=2048, max_storage_mb_explicit=False,
                           base_url="https://example.invalid")
    with mock.patch.object(main, "_apply_submission_policy", side_effect=lambda args, **kw: args), \
         mock.patch.object(main, "_preparation_preflight", return_value=0), \
         mock.patch.object(main, "detect_hardware", return_value={}), \
         mock.patch.object(main, "directory_bytes", return_value=2100 * 1024 * 1024), \
         mock.patch.object(main, "run_benchmark_batch", return_value=0) as run:
        assert main._resume_campaign(args) == 0
    assert run.call_args.kwargs["args"].max_storage_mb == 3124


def test_resume_prepares_each_clip_once_across_recipes(tmp_path):
    campaign_id = "campaign-1234567890abcdef"
    task = {"encoder": "libx264", "preset": "fast", "crf": 24, "rateControl": None, "clipId": "clip-a"}
    atomic_json(journal_path(str(tmp_path), campaign_id) / "manifest.json",
                {"seed": 17, "tasks": [task, dict(task, preset="slow"), dict(task, clipId="clip-b")]})
    args = SimpleNamespace(queue_dir=str(tmp_path), resume_campaign=campaign_id,
                           max_storage_mb=2048, max_storage_mb_explicit=False, base_url="https://example.invalid")
    with mock.patch.object(main, "_apply_submission_policy", side_effect=lambda args, **kw: args), \
         mock.patch.object(main, "_preparation_preflight", return_value=0), \
         mock.patch.object(main, "detect_hardware", return_value={}), \
         mock.patch.object(main, "_prepare_named_suite_clip", side_effect=lambda clip: object()) as prepare, \
         mock.patch.object(main, "run_benchmark_batch", return_value=0) as run:
        assert main._resume_campaign(args) == 0
    assert [call.args[0] for call in prepare.call_args_list] == ["clip-a", "clip-b"]
    tasks = run.call_args.kwargs["tasks"]
    assert tasks[0]["suiteClip"] is tasks[1]["suiteClip"]


@pytest.mark.parametrize("explicit_duration,calls", [(False, 2), (True, 1)])
def test_saved_sweep_restores_plan_attempt_cap_and_continues_checkpoints(tmp_path, explicit_duration, calls):
    campaign_id = "campaign-1234567890abcdef"
    tasks = [{"encoder": "libx264", "preset": str(i), "crf": 24, "rateControl": None, "clipId": "clip-a"}
             for i in range(40)]
    atomic_json(journal_path(str(tmp_path), campaign_id) / "manifest.json",
                {"seed": 17, "sweepMode": "large", "tasks": tasks})
    argv = ["--cli", "--resume-campaign", campaign_id, "--queue-dir", str(tmp_path)]
    if explicit_duration:
        argv += ["--max-duration-minutes", "1"]
    args = main.build_arg_parser().parse_args(argv)
    invoked = []

    def batch(**kwargs):
        invoked.append(kwargs)
        main.config._BATCH_ATTEMPTS_RECORDED = 1
        return 11 if len(invoked) == 1 else 0

    with mock.patch.object(main, "_apply_submission_policy", side_effect=lambda args, **kw: args), \
         mock.patch.object(main, "_preparation_preflight", return_value=0), \
         mock.patch.object(main, "detect_hardware", return_value={}), \
         mock.patch.object(main, "_prepare_named_suite_clip", return_value=object()) as prepare, \
         mock.patch.object(main, "run_benchmark_batch", side_effect=batch):
        assert main._resume_campaign(args) == (11 if explicit_duration else 0)
    assert len(invoked) == calls
    assert prepare.call_count == 1
    assert args.max_storage_mb == 6144
    protocol = main._build_protocol_config()
    assert args.max_attempts == 40 * (protocol.warmup_runs + protocol.minimum_measured_runs + protocol.max_adaptive_repeats)
