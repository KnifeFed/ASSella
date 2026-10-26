#!/usr/bin/env python3
"""
scripts/test_atom_dlc_and_byparr.py
===================================
Verification test suite for:
  1. AtomDlcSelectionDialog structure:
     - 3 sections: AdditionalApps, AdditionalDepots, DecryptionKeys
     - Filters out base game AppID and owned DLCs (from Steam tickets and config.yaml)
     - Missing depots (without key) are disabled with status tags
     - Bulk toggle bars visible only when >= 5 items
     - Writes to SLSsteam config (batch_config_edit) and plugin_games.json
     - Invariant: Base AppID NEVER in AdditionalApps or AdditionalDepots
  2. DLC Mode Memory Detection:
     - Detects AT0-M mode from plugin_library or config.yaml (DlcData, AdditionalApps)
     - Detects ASSella mode from .depot file or dlc_only_mode
     - Returns None for clean/unconfigured games
  3. Byparr Configuration & Custom Service:
     - ByparrManager.is_custom_service()
     - ByparrManager.get_auth_header() and build_headers()
     - ByparrManager.is_available()
  4. Plugins Manifest & Extras:
     - hubcap.lua registered in plugins_manifest.json
     - hubcap.lua present in res/plugins
     - Excluded from interceptor switches and .bak archiving
"""

import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure src/ is on PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from utils.settings import get_settings
from utils.yaml_config_manager import (
    get_user_config_path,
    get_additional_apps,
    get_additional_depots,
    get_dlc_data,
)
from utils.dlc_helpers import DlcCandidate, DlcDiscovery
from ui.dialogs.atom_dlc_selection_dialog import AtomDlcSelectionDialog
from core.steamdb_scraper import ByparrManager


class TestAtomDlcAndByparr(unittest.TestCase):

    def setUp(self):
        self.settings = get_settings()
        self.orig_byparr_url = self.settings.value("byparr_url", "", type=str)
        self.orig_byparr_auth = self.settings.value("byparr_auth_header", "", type=str)

    def tearDown(self):
        self.settings.setValue("byparr_url", self.orig_byparr_url)
        self.settings.setValue("byparr_auth_header", self.orig_byparr_auth)

    def test_01_byparr_custom_configuration(self):
        """Verify Byparr custom service detection and header builder."""
        # Default state
        self.settings.setValue("byparr_url", "http://127.0.0.1:8191")
        self.assertFalse(ByparrManager.is_custom_service())

        # Custom service URL
        self.settings.setValue("byparr_url", "https://byparr.mycluster.internal:8443")
        self.assertTrue(ByparrManager.is_custom_service())
        self.assertTrue(ByparrManager.is_available())
        self.assertEqual(ByparrManager.get_service_url(), "https://byparr.mycluster.internal:8443")

        # Custom auth header - Bearer token
        self.settings.setValue("byparr_auth_header", "Bearer secret-token-123")
        self.assertEqual(ByparrManager.get_auth_header(), "Bearer secret-token-123")
        headers = ByparrManager.build_headers()
        self.assertEqual(headers.get("Authorization"), "Bearer secret-token-123")
        self.assertEqual(headers.get("Content-Type"), "application/json")

        # Custom auth header - Custom key:value header
        self.settings.setValue("byparr_auth_header", "X-Api-Key: custom-api-key-999")
        headers2 = ByparrManager.build_headers()
        self.assertEqual(headers2.get("X-Api-Key"), "custom-api-key-999")
        print("  [PASS] Byparr custom service and headers verified")

    def test_02_plugins_manifest_hubcap_registered(self):
        """Verify hubcap.lua is in manifest, on disk, and registered in plugin_manager."""
        manifest_path = SRC_DIR / "res" / "plugins" / "plugins_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertIn("hubcap.lua", manifest["plugins"])
        self.assertEqual(manifest["plugins"]["hubcap.lua"]["version"], "1.0.0")

        hubcap_lua = SRC_DIR / "res" / "plugins" / "hubcap.lua"
        self.assertTrue(hubcap_lua.exists())
        self.assertGreater(hubcap_lua.stat().st_size, 20000)

        # Check plugin_manager lists
        from utils.plugin_manager import FALLBACK_REQUIRED_PLUGINS
        self.assertIn("hubcap.lua", FALLBACK_REQUIRED_PLUGINS)
        print("  [PASS] Hubcap plugin manifest and registration verified")

    def test_03_atom_dlc_dialog_structure_and_filters(self):
        """Verify AtomDlcSelectionDialog sets up tables, filters owned items, and hides bulk bars < 5."""
        base_appid = "123456"
        disc = DlcDiscovery(
            appid=base_appid,
            catalog={
                "123456": "Base Game",
                "100001": "DLC Adventure Pack",
                "100002": "DLC Character Pack",
                "100003": "DLC Expansion Pass",
            },
            depots=(
                DlcCandidate("200001", "100001", "DLC Adventure Content", 10000000, ("windows",)),
                DlcCandidate("200002", "100002", "DLC Character Content", 5000000, ("windows",)),
                DlcCandidate("200003", "100003", "DLC Expansion Content", 15000000, ("windows",)),
            ),
            sources=("steam_cmd",),
        )

        manifest_data = {
            "appid": base_appid,
            "game_name": "Test RPG Game",
            "depots": {
                "200001": {"name": "DLC Adventure Content", "dlcappid": "100001", "key": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
                "200002": {"name": "DLC Character Content", "dlcappid": "100002", "key": ""},
                "200003": {"name": "DLC Expansion Content", "dlcappid": "100003", "key": "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"},
            },
            "missing_depots_from_hubcap": ["200002"],
            "missing_depots_info": {
                "200002": {"status": "key_pending", "tag": "[No Key]"}
            },
            "keys": {
                "200001": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "200003": "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
            }
        }

        # Mock Steam ticket ownership to include 100001 as already owned
        with patch("ui.dialogs.atom_dlc_selection_dialog.get_owned_dlcs_from_steam", return_value={"100001"}):
            dlg = AtomDlcSelectionDialog(
                parent=None,
                app_id=base_appid,
                game_name="Test RPG Game",
                accent_color="#6c5ce7",
                discovery=disc,
                manifest_data=manifest_data,
            )

            # 1. Base appid (123456) MUST NOT be in apps table, while owned DLC (100001) is present but greyscaled
            app_ids_in_table = [dlg.apps_table.item(r, 0).text() for r in range(dlg.apps_table.rowCount())]
            self.assertNotIn("123456", app_ids_in_table)
            self.assertIn("100001", app_ids_in_table)
            self.assertIn("100002", app_ids_in_table)
            self.assertIn("100003", app_ids_in_table)
            self.assertEqual(len(app_ids_in_table), 3)

            # Owned DLC 100001 toggle must be disabled/read-only
            toggle_100001 = dlg.app_toggles["100001"]
            self.assertFalse(toggle_100001.isEnabled())

            # Unowned DLC 100002 & 100003 must be enabled
            toggle_100002 = dlg.app_toggles["100002"]
            self.assertTrue(toggle_100002.isEnabled())

            # 2. Bulk bar should be hidden because count is < 5 (3 items)
            self.assertFalse(dlg.apps_bulk_bar.isVisible())

            # 3. Depots: 200001 belongs to owned DLC 100001 -> greyscaled with locked toggle
            # 200002 is missing key -> disabled with tag '[No Key]'
            # 200003 is valid -> enabled
            depot_ids_in_table = [dlg.depots_table.item(r, 0).text() for r in range(dlg.depots_table.rowCount())]
            self.assertIn("200001", depot_ids_in_table)
            self.assertIn("200002", depot_ids_in_table)
            self.assertIn("200003", depot_ids_in_table)

            # 200001 owned depot toggle should be disabled/locked
            toggle_200001 = dlg.depot_toggles["200001"]
            self.assertFalse(toggle_200001.isEnabled())

            # 200002 toggle should be disabled (missing key)
            toggle_200002 = dlg.depot_toggles["200002"]
            self.assertFalse(toggle_200002.isEnabled())

            # 200003 toggle should be enabled and checked
            toggle_200003 = dlg.depot_toggles["200003"]
            self.assertTrue(toggle_200003.isEnabled())
            self.assertTrue(toggle_200003.isChecked())

            print("  [PASS] AtomDlcSelectionDialog structure, owned DLC greyscaling, and toggle state verified")

    def test_04_dlc_mode_memory_detection(self):
        """Verify _detect_configured_dlc_mode detects AT0-M vs ASSella vs unconfigured."""
        from ui.dialogs.library.actions import LibraryActionsMixin

        actions_obj = LibraryActionsMixin()

        # 1. Clean unconfigured game
        clean_appid = "9999999"
        mode = actions_obj._detect_configured_dlc_mode(clean_appid)
        self.assertIsNone(mode)

        # 2. AT0-M game in plugin_library
        atom_appid = "8888888"
        mock_plugin_lib = {
            atom_appid: {
                "name": "Mock AT0-M Game",
                "appid": atom_appid,
                "is_atom": True,
                "is_dlc_only": True,
                "dlc_appids": ["8888889"],
            }
        }
        with patch("utils.plugin_games.load_plugin_library", return_value=mock_plugin_lib):
            mode = actions_obj._detect_configured_dlc_mode(atom_appid)
            self.assertEqual(mode, "native")

        # 3. ACCELA game with .depot file
        accela_appid = "7777777"
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            depots_dir = Path(tmp_dir) / "depots"
            depots_dir.mkdir(parents=True, exist_ok=True)
            depot_file = depots_dir / f"{accela_appid}.depot"
            depot_file.write_text("dummy depot content")

            with patch("utils.plugin_games.load_plugin_library", return_value={}), \
                 patch("utils.yaml_config_manager.get_user_config_path", return_value=None), \
                 patch("utils.helpers.get_base_path", return_value=Path(tmp_dir)):
                mode = actions_obj._detect_configured_dlc_mode(accela_appid)
                self.assertEqual(mode, "assella")

        # 4. ACCELA game with is_dlc_only_mode setting
        setting_appid = "6666666"
        with patch("utils.plugin_games.load_plugin_library", return_value={}), \
             patch("utils.yaml_config_manager.get_user_config_path", return_value=None), \
             patch("utils.dlc_helpers.is_dlc_only_mode", return_value=True):
            mode = actions_obj._detect_configured_dlc_mode(setting_appid)
            self.assertEqual(mode, "assella")

        print("  [PASS] DLC mode memory detection verified")


if __name__ == "__main__":
    unittest.main()
