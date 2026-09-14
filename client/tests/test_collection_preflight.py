from unittest import mock

import pytest

from client import network
from client.suite import load_suite_pack_metadata


def test_preflight_rejects_wrong_suite_before_encoding():
    contract = {
        "protocolVersion": "7.1", "minimumClientVersion": "client/0.3.0",
        "encodeTimerBoundary": "ffmpeg-process-v1", "sourceSuiteVersion": "encodingdb-test-suite-v1",
        "suiteFingerprint": load_suite_pack_metadata()["suiteFingerprint"],
    }
    response = mock.Mock(status_code=200)
    response.json.return_value = contract
    with mock.patch.object(network, "_load_requests") as requests:
        requests.return_value.get.return_value = response
        assert network.check_compatibility("https://example.invalid", "client/0.3.0") == contract
        response.json.return_value = {**contract, "suiteFingerprint": "0" * 64}
        with pytest.raises(network.SubmitError):
            network.check_compatibility("https://example.invalid", "client/0.3.0")
        response.status_code = 409
        with pytest.raises(network.SubmitError):
            network.check_compatibility("https://example.invalid", "client/0.3.0")
