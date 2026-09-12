"""Safety boundaries for the real clean-deployment acceptance harness."""
import copy
from pathlib import Path
import subprocess
import unittest

from scripts.test_clean_deployment import isolated_config, build_test_environment

ROOT = Path(__file__).resolve().parents[2]


class DeploymentIsolationTests(unittest.TestCase):
    def setUp(self):
        self.checkout = Path('/tmp/encodingdb-acceptance-test/checkout')
        self.config = {
            'name': 'encodingdb',
            'services': {
                'db': {'image': 'postgres:16-alpine', 'volumes': [{'type': 'volume', 'source': 'db_data', 'target': '/data'}], 'healthcheck': {'test': ['CMD', 'pg_isready']}},
                'server': {'build': {'context': str(self.checkout / 'server')}, 'environment': {'ALLOW_TEST_ONLY_REFERENCE_CONTEXTS': '0'}},
                'frontend': {'build': {'context': str(self.checkout / 'frontend')}},
                'nginx': {'ports': [{'target': 443, 'published': '443', 'protocol': 'tcp'}], 'volumes': [{'type': 'bind', 'source': str(self.checkout / 'nginx/conf.d'), 'target': '/etc/nginx/conf.d', 'read_only': True}]},
            },
            'volumes': {'db_data': {'name': 'encodingdb_prod_db_data'}},
            'networks': {'app': {'name': 'encodingdb_app'}},
        }

    def test_isolation_preserves_builds_healthchecks_and_mount_targets(self):
        original = copy.deepcopy(self.config)
        result = isolated_config(self.config, 'encodingdb-acceptance-123', self.checkout)
        self.assertEqual(self.config, original)
        self.assertEqual(result['services']['server'], original['services']['server'])
        self.assertEqual(result['services']['db'], original['services']['db'])
        self.assertEqual(result['services']['nginx']['volumes'], original['services']['nginx']['volumes'])
        self.assertEqual(result['volumes']['db_data']['name'], 'encodingdb-acceptance-123_db_data')
        self.assertEqual(result['networks']['app']['name'], 'encodingdb-acceptance-123_app')
        self.assertEqual(result['services']['nginx']['ports'][0], {'target': 443, 'published': '0', 'host_ip': '127.0.0.1', 'protocol': 'tcp'})

    def test_refuses_external_resources_and_paths_outside_fresh_checkout(self):
        for kind in ('volume', 'network', 'container', 'host_network', 'build', 'mount'):
            with self.subTest(kind=kind):
                config = copy.deepcopy(self.config)
                if kind == 'volume':
                    config['volumes']['db_data']['external'] = True
                elif kind == 'network':
                    config['networks']['app']['external'] = True
                elif kind == 'container':
                    config['services']['server']['container_name'] = 'production-server'
                elif kind == 'host_network':
                    config['services']['server']['network_mode'] = 'host'
                elif kind == 'build':
                    config['services']['server']['build']['context'] = '/production/server'
                else:
                    config['services']['nginx']['volumes'][0]['source'] = '/production/nginx'
                with self.assertRaises(RuntimeError):
                    isolated_config(config, 'encodingdb-acceptance-123', self.checkout)

    def test_test_environment_passes_real_production_gate_with_pl_absent(self):
        values = build_test_environment((ROOT / 'env.example').read_text(), 'encodingdb-acceptance-123')
        import json
        script = "import {validateProductionEnv} from './scripts/validate-production-env.mjs'; const result=validateProductionEnv({env:JSON.parse(process.argv[1])}); console.log(JSON.stringify(result)); process.exitCode=result.ok?0:1;"
        result = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(values)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(all(not values[key] for key in ('PL_V7_REFERENCE_CONTEXT_PATH', 'PL_V7_REFERENCE_CONTEXT_VERSION', 'PL_V7_REFERENCE_BITRATES_JSON')))
        self.assertEqual(values['ALLOW_TEST_ONLY_REFERENCE_CONTEXTS'], '0')
        self.assertEqual(values['ARTIFACT_VALIDATE_MEDIA_BEFORE_PUBLISH'], '1')


if __name__ == '__main__':
    unittest.main()
