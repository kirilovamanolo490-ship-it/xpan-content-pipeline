import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xpan_auto.deployment import setting, verified_social_set_id

class DeploymentTests(unittest.TestCase):
    def test_local_settings_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            root=Path(d)
            (root / ".env").write_text("# example\nDEMO='file value'\n")
            self.assertEqual(setting("DEMO", root=root), "file value")
            os.environ["DEMO"]="environment value"
            self.assertEqual(setting("DEMO", root=root), "environment value")
            self.assertEqual(setting("MISSING", "fallback", root=root), "fallback")
    def test_social_set_configuration_is_required(self):
        for value in ("", "0", "invalid", "-1"):
            with patch.dict(os.environ, {"XPAN_TYPEFULLY_SOCIAL_SET_ID": value}):
                with self.assertRaises(ValueError): verified_social_set_id()
    def test_social_set_configuration_uses_verified_value(self):
        with patch.dict(os.environ, {"XPAN_TYPEFULLY_SOCIAL_SET_ID": "123456"}):
            self.assertEqual(verified_social_set_id(), 123456)
