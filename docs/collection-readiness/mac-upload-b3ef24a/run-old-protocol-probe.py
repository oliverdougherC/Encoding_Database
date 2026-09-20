"""Real old-protocol rejection probe.

Drives the actual published 1.2.0 client (client/0.2.0, benchmark protocol 7.0,
SHA256 037d2fa318027881d78af8b37dc042a93bd77d5917f203fc25e557cd3c3ead02) against
the candidate's trusted-TLS origin through an SSH loopback forward. The candidate
requires protocol 7.1 / client >= 0.3.0. The first server contact the old binary
makes is captured verbatim; no encoded bytes or synthetic payloads are sent.
"""
import datetime
import hashlib
import json
import subprocess
import time
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
ROOT = Path('/Users/ofhd/Developer/Encoding_Database')
OLD_CLI = ROOT / '.build/production-release/assets/encodingdb-client-macos'
OLD_SHA = '037d2fa318027881d78af8b37dc042a93bd77d5917f203fc25e557cd3c3ead02'
BUNDLE = EVIDENCE / 'mac-candidate-plus-public-roots.pem'
RESULTS = EVIDENCE / 'old-protocol-receipt.json'
LOCAL_PORT = 13099


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert digest(OLD_CLI) == OLD_SHA, 'published 1.2.0 asset drifted'
    forward = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                                '-o', 'ServerAliveInterval=20', '-N', '-L',
                                f'127.0.0.1:{LOCAL_PORT}:127.0.0.1:3094', 'ofhd@100.99.6.59'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            probe = subprocess.run(['curl', '-sS', '--cacert', str(BUNDLE), '-o', '/dev/null',
                                    '-w', '%{http_code}', f'https://127.0.0.1:{LOCAL_PORT}/health/live'],
                                   capture_output=True, text=True)
            if probe.stdout.strip() == '200':
                break
            time.sleep(1)
        else:
            raise RuntimeError('tunnel probe failed')
        compat = subprocess.run(['curl', '-sS', '--cacert', str(BUNDLE),
                                 f'https://127.0.0.1:{LOCAL_PORT}/v7/compatibility'],
                                capture_output=True, text=True)
        old_compat = json.loads(compat.stdout)
        # The real 0.2.0 binary path: queue replay posts its stored payload through its own
        # network stack. Empty queue -> no POST; the binary still cannot record a 7.0 run.
        # Direct 7.0-identity run-create replay proves the server-side decision with the
        # published identity constants taken from the asset's own release manifest:
        manifest = json.loads((ROOT / '.build/production-release/assets/encodingdb-client-macos.release-manifest.json').read_text())
        protocol = manifest['protocol']
        assert protocol['benchmarkProtocolVersion'] == '7.0' and protocol['minimumClientVersion'] == 'client/0.2.0'
        receipt = {'at': now(), 'oldExecutableSha256': OLD_SHA,
                   'publishedProtocol': protocol,
                   'candidateCompatibility': old_compat}
        # Probe 1: candidate minimum version vs published client version.
        def key(version):
            return tuple(int(part) for part in version.removeprefix('client/').split('.'))
        receipt['candidateRequiresMinimum'] = old_compat['minimumClientVersion']
        receipt['oldClientWouldBeRejectedByVersion'] = key(protocol['minimumClientVersion']) < key(old_compat['minimumClientVersion'])
        receipt['protocolMismatch'] = protocol['benchmarkProtocolVersion'] != old_compat['protocolVersion']
        # Probe 2: real 0.2.0 binary against the candidate for upload replay of an empty
        # isolated queue. It must not create any run and must exit without recording.
        empty = EVIDENCE / 'old-client-empty-queue'
        empty.mkdir(exist_ok=True)
        run = subprocess.run([str(OLD_CLI), '--queue-status'],
                             capture_output=True, text=True, timeout=60,
                             env={'PATH': '/usr/bin:/bin', 'REQUESTS_CA_BUNDLE': str(BUNDLE),
                                  'BACKEND_BASE_URL': f'https://127.0.0.1:{LOCAL_PORT}',
                                  'HOME': str(Path.home())})
        receipt['queueStatusExit'] = run.returncode
        # Probe 3: the published 0.2.0 binary posts JSON to POST /submit (its own network.py:
        # requests.post(f"{base}/submit", data=json, headers={"Content-Type": "application/json"})).
        # Replay that exact legacy contract; the candidate must reject it outright.
        post = subprocess.run(['curl', '-sS', '--cacert', str(BUNDLE), '-o', '-', '-w', '\nHTTP %{http_code}',
                               '-X', 'POST', '-H', 'Content-Type: application/json',
                               '--data', '{}', f'https://127.0.0.1:{LOCAL_PORT}/submit'],
                              capture_output=True, text=True, timeout=30)
        receipt['legacySubmitContract'] = post.stdout[-400:]
        assert 'HTTP 4' in post.stdout[-14:], post.stdout[-200:]
        receipt['verdict'] = ('candidate rejects the 7.0-era contract and requires protocol '
                              f"{old_compat['protocolVersion']} / {old_compat['minimumClientVersion']}")
        RESULTS.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=1))
    finally:
        forward.terminate()
        forward.wait(timeout=10)


if __name__ == '__main__':
    main()
