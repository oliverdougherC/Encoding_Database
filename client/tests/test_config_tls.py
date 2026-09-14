"""Custom trust roots remain opt-in and never disable certificate verification."""
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('values, expected', [
    ({'REQUESTS_CA_BUNDLE': '/tmp/reviewed-ca.pem', 'CURL_CA_BUNDLE': '/tmp/fallback.pem'}, '/tmp/reviewed-ca.pem'),
    ({'CURL_CA_BUNDLE': '/tmp/fallback.pem'}, '/tmp/fallback.pem'),
    ({'REQUESTS_CA_BUNDLE': '0'}, '0'),
    ({}, None),
])
def test_requests_trust_bundle_preserves_standard_precedence(values, expected):
    env = {key: value for key, value in os.environ.items() if key not in {'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'}}
    env.update(values)
    result = subprocess.run([sys.executable, '-c',
        'import json, certifi; from client import config; print(json.dumps([config.REQUESTS_VERIFY, certifi.where()]))'],
        env=env, capture_output=True, text=True, check=True, timeout=20)
    actual, default = json.loads(result.stdout)
    assert actual == (default if expected is None else expected)
    assert actual is not False
