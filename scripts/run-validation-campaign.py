#!/usr/bin/env python3
"""Run a registered validation-only scene through the corrected client protocol.

No HTTP submission or operator credential is used here. The companion operator
importer consumes the completed journal only after all timing work has finished.
"""
import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
import platform
import secrets
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--workload', required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--encoder', choices=['libx264', 'libx265', 'libsvtav1'], default='libx264')
    parser.add_argument('--preset', default='fast')
    parser.add_argument('--crf', type=int, default=23)
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    from client import config
    from client.campaign import CampaignJournal, atomic_json, physical_source_id
    from client.ffmpeg import encode_to_artifact
    from client.runtime_lock import verify_runtime_lock
    from client.hardware import detect_hardware
    from client.identity import runtime_identity, execution_provenance
    from client.main import CLIENT_VERSION, _capture_protocol_environment_snapshot, _probe_artifact_contract
    from client.protocol import ProtocolConfig, StructuralExpectation, RecipeSpec, EncodeTiming, EncodeOutcome, ArtifactProbe, execute_protocol_campaign, generate_campaign_id
    registry = json.loads(args.registry.read_text())
    claimed = registry.pop('registryHash')
    if canonical_hash(registry) != claimed: raise ValueError('Source registry hash mismatch')
    source = next(entry for entry in registry['sources'] if entry['workloadId'] == args.workload)
    if source['sourceSuiteVersion'] != 'encodingdb-validation-holdouts-v1' or not args.workload.startswith('validation-'):
        raise ValueError('Only registered validation-only workloads are allowed')
    if digest(args.reference) != source['sourceSha256'] or args.reference.stat().st_size != source['byteSize']:
        raise ValueError('Registered reference bytes differ')
    runtime_verification = verify_runtime_lock(ffmpeg_path=config.ffmpeg_exe(), ffprobe_path=config.ffprobe_exe())
    hardware = detect_hardware()
    protocol = ProtocolConfig.for_version('7.1')
    seed = args.seed if args.seed is not None else secrets.randbits(63)
    recipe_data = {'encoder': args.encoder, 'preset': args.preset, 'crf': args.crf, 'sourceRegistrationHash': canonical_hash(source)}
    recipe_id = canonical_hash(recipe_data)
    spec = RecipeSpec(recipe_id, StructuralExpectation(duration_s=source['durationSeconds'], frame_count=source['frameCount'], width=1920, height=1080,
        codec={'libx264': 'h264', 'libx265': 'hevc', 'libsvtav1': 'av1'}[args.encoder], pix_fmt='yuv420p', bit_depth=8, chroma_subsampling='4:2:0',
        color_range='tv', color_space='bt709', color_transfer='bt709', color_primaries='bt709', avg_frame_rate=24, no_audio=True), recipe_data)
    campaign_id = generate_campaign_id('7.1', [recipe_id], seed)
    manifest = {'schemaVersion': 'encodingdb-controlled-validation-campaign/v1', 'validationOnly': True, 'protocolVersion': '7.1',
        'source': source, 'sourceRegistrationHash': canonical_hash(source), 'referencePath': str(args.reference.resolve()), 'seed': seed,
        'recipe': recipe_data, 'physicalSourceId': physical_source_id(), 'hardware': dataclasses.asdict(hardware), 'runtime': runtime_identity(),
        'clientVersion': CLIENT_VERSION, 'runnerSha256': digest(__file__), 'ffmpegVersion': subprocess.check_output([config.ffmpeg_exe(), '-version'], text=True).splitlines()[0],
        'runtimeVerification': runtime_verification, 'execution': execution_provenance(), 'osName': platform.system(), 'osVersion': platform.version(), 'protocolConfig': dataclasses.asdict(protocol)}
    journal = CampaignJournal(str(args.output), campaign_id, manifest, 2048)
    def encode(schedule, recipe):
        name = f'{schedule.execution_order:03d}-{schedule.phase}.mp4'
        info = encode_to_artifact(input_path=str(args.reference), encoder=args.encoder, preset=args.preset, crf=args.crf,
            out_dir=str(journal.root), artifact_name=name, host_gpu_vendors=hardware.gpuVendors,
            checkpoint_path=str(journal.root / (name + '.process.json')), max_output_bytes=journal.check_budget())
        if info.get('error') or info.get('encodeTimerBoundary') != 'ffmpeg-process-v1':
            return EncodeOutcome(None, ArtifactProbe(decodable=False, decode_error=info.get('error') or 'Missing corrected interval'), metadata={'info': info})
        if info.get('encoderUsed') != args.encoder or str(info.get('presetUsed')) != args.preset: raise ValueError('Unexpected encoder/preset substitution')
        probe = _probe_artifact_contract(info['artifactPath'])
        timing = EncodeTiming.from_measurement(start_monotonic_ns=info['encodeStartMonotonicNs'], end_monotonic_ns=info['encodeEndMonotonicNs'],
            source_frame_count=source['frameCount'], encoded_frame_count=probe.frame_count or 0, source_fps=24)
        return EncodeOutcome(timing, probe, artifact_path=info['artifactPath'], metadata={'info': info})
    with journal.measurement_lock():
        campaign = execute_protocol_campaign(recipes=[spec], config=protocol, encode_runner=encode,
            environment_sampler=lambda schedule, recipe: _capture_protocol_environment_snapshot(hardware=hardware, encoder=args.encoder),
            seed=seed, record_sink=journal.save, resumed_records=journal.records)
    receipt = {**manifest, 'campaign': campaign.to_dict(), 'journalPath': str(journal.root.resolve())}
    atomic_json(journal.root / 'validation-campaign.json', receipt)
    print(journal.root / 'validation-campaign.json')
    if not campaign.recipe_results[0].stability.stable:
        print('Timing unstable: retained journal remains ineligible; no analysis or submission performed.', file=sys.stderr)
        return 4
    return 0

if __name__ == '__main__': sys.exit(main())
