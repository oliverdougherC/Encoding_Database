"""R06/R07: the real run_benchmark_batch producer and the real GUI consumer.

Every assertion here compares the GUI's observable bar state against durable
attempts written by the producer, while publication and receipt state stay in
the separate ledger. A mock that agreed with itself could not catch a unit
mismatch between producer and consumer.
"""
import argparse
import json
import sys
import threading
from dataclasses import replace
from pathlib import Path
from unittest import mock

from client import main, protocol, spool
from client import windows_gui as gui
from client.network import SubmitError
from test_spool import server_bundle


def _build_gui_app():
    from test_windows_gui import Variable, Widget, cached_estimate, cached_recovery_state
    root = mock.MagicMock()
    bindings = {}
    root.bind.side_effect = lambda key, callback: bindings.__setitem__(key, callback)
    tk = mock.MagicMock()
    tk.Tk.return_value = root
    tk.StringVar = tk.IntVar = tk.BooleanVar = Variable
    for name in ("Frame", "LabelFrame", "Label", "Combobox", "Checkbutton", "Spinbox",
                 "Entry", "Button", "Progressbar"):
        setattr(tk.ttk, name, Widget)
    tk.scrolledtext.ScrolledText = Widget
    base_args = argparse.Namespace(codec="libx264", presets="fast", crf=0, no_submit=True,
                                   queue_dir="test-only", base_url="http://127.0.0.1:9")
    with mock.patch.dict(sys.modules, {"tkinter": tk}), mock.patch.object(gui.os, "name", "nt"), \
         mock.patch.object(gui, "list_all_available_encoders", return_value=["libx264"]), \
         mock.patch.object(gui, "desktop_work_area", return_value=(0, 0, 1024, 720)), \
         mock.patch.object(gui.client_main, "recovery_state", side_effect=cached_recovery_state), \
         mock.patch.object(gui.threading, "Thread"):
        gui.launch_windows_gui(base_args)
    app = bindings["<Alt-b>"].__self__
    app._estimate_acquisition = cached_estimate
    app._load_recovery_state = cached_recovery_state
    return app


def _drive_gui(app, events):
    """Feed every producer event through the real consumer handler."""
    for event in events:
        app._handle_event(event)
    return app


def _encode(**kwargs):
    artifact = Path(kwargs['out_dir']) / kwargs['artifact_name']
    artifact.write_bytes(b'encoded')
    return {'artifactPath': str(artifact), 'encoderUsed': 'libx264', 'presetUsed': 'fast',
            'fileSizeBytes': 7, 'encodeStartMonotonicNs': 1_000_000_000,
            'encodeEndMonotonicNs': 2_000_000_000, 'elapsedMs': 1000, 'error': None}


def _producer_patches(fixture, tmp_path, *, transport=None):
    from test_main_routing import _DummyDashboard
    stack = [
        mock.patch.object(main, 'ensure_ffmpeg_and_ffprobe', return_value=(True, 'ffmpeg test')),
        mock.patch.object(main, '_build_protocol_config',
                          return_value=protocol.ProtocolConfig.for_version('7.1', max_adaptive_repeats=0)),
        mock.patch.object(main, 'probe_video_stream_metrics',
                          return_value={'sourceFps': 24, 'sourceDurationSeconds': 5, 'containerFormat': 'mp4'}),
        mock.patch.object(main, '_probe_artifact_contract',
                          side_effect=lambda path: fixture._artifact_contract()),
        mock.patch.object(main, '_capture_protocol_environment_snapshot',
                          return_value=protocol.EnvironmentSnapshot(selected_accelerator='software')),
        mock.patch.object(main, 'encode_to_artifact', side_effect=_encode),
        mock.patch.object(main, 'BatchRunDashboard', _DummyDashboard),
    ]
    if transport is not None:
        stack.append(mock.patch.object(spool, 'submit_artifact_submission', side_effect=transport))
        stack.append(mock.patch.object(main, 'fetch_baseline_rows', return_value=[]))
    return stack


def _run_batch(tmp_path, *, seed, events, transport=None, tasks=None, no_submit=True,
               cancel_event=None, encode_side_effect=None):
    from test_main_routing import MainRoutingTests
    fixture = MainRoutingTests()
    clip = fixture._quick_clip()
    args = fixture._batch_args(str(tmp_path), no_submit=no_submit)
    args.local_metrics = False
    args.campaign_seed = seed
    args.max_duration_minutes = 60
    hardware = main.HardwareInfo('CPU', None, 16, 'OS')
    if tasks is None:
        tasks = [{'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': clip}]
    with mock.patch.object(main, 'detect_hardware', return_value=hardware), \
         mock.patch.object(main, 'check_compatibility', return_value={}):
        stack = _producer_patches(fixture, tmp_path, transport=transport)
        if encode_side_effect is not None:
            stack = [p for p in stack if p.attribute != 'encode_to_artifact']
            stack.append(mock.patch.object(main, 'encode_to_artifact', side_effect=encode_side_effect))
        for patcher in stack:
            patcher.start()
        try:
            rc = main.run_benchmark_batch(
                hardware=hardware, base_url='https://example.invalid', args=args,
                event_sink=events.append, cancel_event=cancel_event, tasks=tasks)
        finally:
            for patcher in stack:
                patcher.stop()
    return rc


def _campaign_root(tmp_path):
    return next((tmp_path / 'campaigns').iterdir())


def _journal_for(tmp_path, root):
    return main.CampaignJournal(str(tmp_path), root.name,
                                json.loads((root / 'manifest.json').read_text()), 2048)


def test_local_only_success_bars_match_durable_saves(tmp_path):
    events = []
    rc = _run_batch(tmp_path, seed=41, events=events)
    assert rc == 0
    root = _campaign_root(tmp_path)
    saved = list(root.glob('submission-*.json'))
    attempts = list(root.glob('attempt-*.json'))
    progress = [e for e in events if e.get('type') == 'campaign_progress']
    assert progress, "producer must emit campaign_progress"
    final = progress[-1]
    # Progress counts every durable encode attempt. Publication is a separate
    # ledger, so the two measured envelopes must not drive the bars.
    assert len(attempts) == 3  # 1 warmup + 2 measured
    assert len(saved) == 2
    assert final['total'] == len(attempts) == 3
    assert final['done'] == final['total']
    assert final['batchDone'] == final['batchTotal'] == 3
    assert final['unit'] == 'durable-attempt'
    # Monotonic: both fractions never decrease across the whole event stream.
    overall = [(e['done'], e['total']) for e in progress]
    batch = [(e['batchDone'], e['batchTotal']) for e in progress]
    assert all(a[0] / a[1] <= b[0] / b[1] + 1e-9 for a, b in zip(overall, overall[1:]))
    assert all(a[0] / a[1] <= b[0] / b[1] + 1e-9 for a, b in zip(batch, batch[1:]))
    # The real GUI consumer ends at 100% with matching options.
    app = _drive_gui(_build_gui_app(), events)
    assert app.overall_pb.options['maximum'] == 3
    assert app.overall_pb.options['value'] == 3
    assert app.batch_pb.options['value'] == 3
    # task_complete after the final progress must not push past the maximum.
    app._handle_event({'type': 'task_complete', 'scope': 'batch', 'processed': 99, 'total': 9})
    assert app.overall_pb.options['value'] == 3
    # Durable ledger for the end screen: saved, nothing uploaded.
    ledger = main._durable_campaign_ledger(str(tmp_path), root.name, _journal_for(tmp_path, root), True)
    assert ledger['savedLocal'] == 2
    assert ledger['uploaded'] == 0
    assert ledger['queued'] == 0


def test_warmup_and_measured_attempts_advance_bars_before_publication(tmp_path, monkeypatch):
    monkeypatch.setenv('ENCODINGDB_HOST_PHASE_DIR', str(tmp_path / 'host-phase'))
    events = []
    assert _run_batch(tmp_path, seed=405, events=events) == 0
    app = _build_gui_app()
    progress_before_next_encode = {}
    for event in events:
        app._handle_event(event)
        if event.get('type') == 'encode_start':
            progress_before_next_encode[event['index']] = (
                app.overall_pb.options['value'], app.batch_pb.options['value'])
    # The first warmup and first measured attempt are durably recorded before
    # the following encode starts; a publication-only bar stayed at (0, 0).
    assert progress_before_next_encode[2] == (1, 1)
    assert progress_before_next_encode[3] == (2, 2)
    assert app.overall_pb.options['maximum'] == 3
    assert app.overall_pb.options['value'] == 3
    assert app.batch_pb.options['maximum'] == 3
    assert app.batch_pb.options['value'] == 3


def test_local_only_resume_baseline_never_rewinds_or_double_counts(tmp_path):
    first = []
    assert _run_batch(tmp_path, seed=42, events=first) == 0
    root = _campaign_root(tmp_path)
    resume_events = []
    assert _run_batch(tmp_path, seed=42, events=resume_events) == 0
    recorded = len(list(root.glob('attempt-*.json')))
    progress = [e for e in resume_events if e.get('type') == 'campaign_progress']
    assert progress[0]['done'] == 3, "resume must start from the durable baseline"
    assert progress[-1]['done'] == progress[-1]['total'] == recorded == 3
    # GUI consumer: overall starts at the durable baseline and never drops.
    values = []
    app = _build_gui_app()
    for event in resume_events:
        app._handle_event(event)
        if event.get('type') in ('run_start', 'campaign_progress'):
            values.append(app.overall_pb.options['value'])
    assert values and values[0] == 3
    assert all(a <= b for a, b in zip(values, values[1:]))


def test_interrupted_resume_keeps_overall_baseline_and_restarts_batch(tmp_path, monkeypatch):
    monkeypatch.setenv('ENCODINGDB_HOST_PHASE_DIR', str(tmp_path / 'host-phase'))
    cancel = threading.Event()

    class StopAfterFirstSave(list):
        def append(self, event):
            super().append(event)
            if event.get('type') == 'campaign_progress' and event.get('done') == 1:
                cancel.set()

    first = StopAfterFirstSave()
    assert _run_batch(tmp_path, seed=404, events=first, cancel_event=cancel) == 130
    root = _campaign_root(tmp_path)
    assert len(list(root.glob('attempt-*.json'))) == 1

    resumed = []
    assert _run_batch(tmp_path, seed=404, events=resumed) == 0
    progress = [event for event in resumed if event.get('type') == 'campaign_progress']
    assert (progress[0]['done'], progress[0]['batchDone']) == (1, 0)
    assert any((event['done'], event['batchDone']) == (2, 1) for event in progress)
    assert (progress[-1]['done'], progress[-1]['total']) == (3, 3)
    assert (progress[-1]['batchDone'], progress[-1]['batchTotal']) == (2, 2)
    app = _drive_gui(_build_gui_app(), resumed)
    assert app.overall_pb.options['value'] == 3
    assert app.batch_pb.options['value'] == 2


def test_partial_upload_run_measurement_bars_finish_but_publication_does_not(tmp_path):
    from test_main_routing import MainRoutingTests
    fixture = MainRoutingTests()
    clip_a = fixture._quick_clip()
    clip_b = replace(clip_a, clip_id="film-grain-1080p24-final",
                     workload_id="film-grain-1080p24-final")

    def transport(base_url, submission, **kwargs):
        run_create = submission['runCreate']
        group = str(run_create['repetitionGroupId'])
        index = int(run_create['repetitionIndex'])
        if 'athletic' in group:
            return server_bundle(submission, 'run-progress-ok')
        if index == 1:
            raise SubmitError('submit failed (503)', retryable=True)
        raise SubmitError('server rejected the evidence (400)', retryable=False)

    events = []
    rc = _run_batch(tmp_path, seed=29, events=events, transport=transport, no_submit=False,
                    tasks=[{'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': clip_a},
                           {'encoder': 'libx264', 'preset': 'fast', 'crf': 24, 'suiteClip': clip_b}])
    assert rc == 1
    root = _campaign_root(tmp_path)
    accepted = list(root.glob('submission-*.accepted.json'))
    assert len(accepted) == 2  # only the athletic group confirmed
    progress = [e for e in events if e.get('type') == 'campaign_progress']
    final = progress[-1]
    # Six warmup/measured attempts are recorded even though only two uploads
    # are acknowledged. The GUI separates measurement progress from delivery.
    assert final['total'] == final['done'] == 6
    app = _drive_gui(_build_gui_app(), events)
    assert app.overall_pb.options['maximum'] == 6
    assert app.overall_pb.options['value'] == 6
    assert app.batch_pb.options['value'] == app.batch_pb.options['maximum'] == 6
    assert app.stage_var.get() == 'Finished with issues'
    overall = [(e['done'], e['total']) for e in progress]
    assert all(a[0] / a[1] <= b[0] / b[1] + 1e-9 for a, b in zip(overall, overall[1:]))
    ledger = main._durable_campaign_ledger(str(tmp_path), root.name, _journal_for(tmp_path, root), False)
    assert ledger['uploaded'] == 2
    assert ledger['queued'] == 1
    assert ledger['terminalFailures'] == 1


def test_terminal_cancellation_bars_match_durable_attempts(tmp_path):
    # The GUI Stop path: cancel_event set mid-run; the producer exits 130 and
    # the bars must reflect only durably saved work.
    calls = []

    def encode_then_cancel(**kwargs):
        result = _encode(**kwargs)
        calls.append(kwargs['artifact_name'])
        if kwargs['artifact_name'].endswith('measured-r1.mp4'):
            cancel.set()
        return result

    cancel = threading.Event()
    events = []
    rc = _run_batch(tmp_path, seed=43, events=events, cancel_event=cancel,
                    encode_side_effect=encode_then_cancel)
    assert rc == 130
    assert events[-1]['type'] == 'run_interrupted'
    progress = [e for e in events if e.get('type') == 'campaign_progress']
    final = progress[-1]
    root = _campaign_root(tmp_path)
    recorded = len(list(root.glob('attempt-*.json')))
    # The first warmup is durable; the interrupted measured output is not.
    assert final['done'] == recorded == 1
    assert final['warmupsDone'] == 1
    assert final['measuredDone'] == 0
    app = _drive_gui(_build_gui_app(), events)
    assert app.overall_pb.options['value'] == recorded
    if recorded < final['total']:
        assert app.overall_pb.options['value'] < app.overall_pb.options['maximum']


def test_end_screen_ledger_separates_saved_from_confirmed(tmp_path):
    # R06 end screen: the rendered text must separate saved / uploaded /
    # queued / confirmed and never call saved work "submitted".
    events = []
    assert _run_batch(tmp_path, seed=44, events=events) == 0
    root = _campaign_root(tmp_path)
    ledger = main._durable_campaign_ledger(str(tmp_path), root.name, _journal_for(tmp_path, root), True)
    assert ledger['savedLocal'] == 2
    assert ledger['uploaded'] == 0
    from client import ui
    lines = []
    with mock.patch.object(ui, '_rich_tty', return_value=False), \
         mock.patch('builtins.print', side_effect=lambda *a, **k: lines.append(' '.join(str(x) for x in a))):
        ui.print_end_screen(0, 12.0, status='complete', ledger=ledger)
    text = '\n'.join(lines)
    assert 'Saved locally: 2' in text
    assert 'Server-confirmed: 0' in text
    assert 'analysis pending' in text
    assert 'Submitted' not in text
