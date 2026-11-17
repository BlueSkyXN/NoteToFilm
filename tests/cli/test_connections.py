"""连接来源：环境变量优先，其次项目 .env，生图可即时读取 Codex 配置；不复制、不输出密钥。"""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from notetofilm_local.adapters import get_adapter
from notetofilm_local.config import (_parse_env, codex_provider, connection_status, load_config, load_env_files,
                                     resolve_route)
from notetofilm_local.errors import NTFError
from test_company_protocols import MockHTTP, PNG

ROOT = Path(__file__).resolve().parents[2]
CODEX = """model_provider = "relay"

[model_providers.relay]
name = "relay"
base_url = "https://relay.example/v1/"
experimental_bearer_token = "codex-fixture-token"

[model_providers.keyed]
base_url = "https://keyed.example/api"
env_key = "FIXTURE_KEYED_TOKEN"
"""


class ConnectionSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ntf-conn-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'codex').mkdir()
        (self.root / 'codex/config.toml').write_text(CODEX)
        (self.root / 'a.png').write_bytes(PNG)
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('NTF_CPA_', 'NTF_UNIAPI_', 'FIXTURE_'))}
        clean['CODEX_HOME'] = str(self.root / 'codex')
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = load_config(ROOT / 'configs/cpa-uniapi.example.json')

    def test_env_file_parsing_and_environment_priority(self):
        self.assertEqual(_parse_env('# note\nexport A=1\nB = "two words"\nC=\'x=y\'\nbad line\n9X=no\n'),
                         {'A': '1', 'B': 'two words', 'C': 'x=y'})
        env = self.root / 'project.env'
        env.write_text('NTF_UNIAPI_BASE_URL=https://video.example\nNTF_UNIAPI_API_KEY=from-file\n')
        with mock.patch.dict(os.environ, {'NTF_ENV_FILE': str(env), 'NTF_UNIAPI_API_KEY': 'from-shell'}):
            self.assertEqual(load_env_files(), [str(env.resolve())])
            self.assertEqual(os.environ['NTF_UNIAPI_BASE_URL'], 'https://video.example')
            self.assertEqual(os.environ['NTF_UNIAPI_API_KEY'], 'from-shell')

    def test_codex_provider_is_read_from_the_selected_or_named_provider(self):
        self.assertEqual(codex_provider('selected'), {'name': 'relay', 'base_url': 'https://relay.example/v1', 'token': 'codex-fixture-token'})
        self.assertIsNone(codex_provider('keyed')['token'])
        with mock.patch.dict(os.environ, {'FIXTURE_KEYED_TOKEN': 'keyed-token'}):
            self.assertEqual(codex_provider('keyed')['token'], 'keyed-token')
        with self.assertRaises(NTFError) as error:
            codex_provider('absent')
        self.assertEqual(error.exception.code, 'codex_provider_missing')

    def test_image_route_uses_codex_at_request_time_and_environment_overrides_it(self):
        route = resolve_route(self.config, None, 'image')
        self.assertEqual((route['connection']['base_url'], route['connection']['connection_source']),
                         ('https://relay.example/v1', 'codex:relay'))
        self.assertNotIn('codex-fixture-token', json.dumps(route))
        image = get_adapter(route)
        image.opener = MockHTTP({'data': [{'b64_json': base64.b64encode(PNG).decode()}]})
        image.submit({'prompt': 'frame'}, self.root)
        sent = image.opener.requests[0]
        self.assertEqual(sent.full_url, 'https://relay.example/v1/images/generations')
        self.assertEqual(sent.get_header('Authorization'), 'Bearer codex-fixture-token')
        self.assertEqual(connection_status(self.config, 'cpa-image-2-6-sunburst'),
                         {'connection_source': 'codex:relay', 'credential': 'codex'})
        with mock.patch.dict(os.environ, {'NTF_CPA_BASE_URL': 'https://override.example/v1', 'NTF_CPA_API_KEY': 'env-token'}):
            route = resolve_route(self.config, None, 'image')
            self.assertEqual(route['connection']['connection_source'], 'environment')
            image = get_adapter(route)
            image.opener = MockHTTP({'data': [{'b64_json': base64.b64encode(PNG).decode()}]})
            image.submit({'prompt': 'frame'}, self.root)
            self.assertEqual(image.opener.requests[0].get_header('Authorization'), 'Bearer env-token')
            self.assertEqual(connection_status(self.config, 'cpa-image-2-6-sunburst')['credential'], 'environment')

    def test_video_route_without_environment_reports_missing(self):
        self.assertEqual(connection_status(self.config, 'company-seedance-2-5'),
                         {'connection_source': 'missing', 'credential': 'missing'})


if __name__ == '__main__':
    unittest.main()
