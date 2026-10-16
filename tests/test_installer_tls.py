import importlib.util
from pathlib import Path
import ssl
import unittest
from unittest.mock import patch, Mock

SPEC = importlib.util.spec_from_file_location('install_cli_tools', Path(__file__).resolve().parents[1] / 'packaging/install_cli_tools.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTLSTests(unittest.TestCase):
    def test_public_bundle_adds_to_system_trust_and_keeps_verification(self):
        context = installer.download_tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 100)

    def test_existing_windows_trust_is_not_replaced(self):
        import certifi
        context = Mock()
        with patch.object(installer.ssl, 'create_default_context', return_value=context) as default:
            self.assertIs(installer.download_tls_context(), context)
        default.assert_called_once_with()
        context.load_verify_locations.assert_called_once_with(cafile=certifi.where())
