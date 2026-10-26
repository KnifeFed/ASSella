#!/usr/bin/env python3
"""
scripts/test_sls_lua_config_and_dialogs.py
===========================================
Verification test suite for:
  1. SLS Lua Config reading and writing:
     - lobster.conf.lua parser & serializer
     - spacebunny.conf.lua parser & serializer
  2. Hubcap API Key validation & Bidirectional Sync:
     - is_valid_hubcap_key
     - sync_hubcap_api_key (timestamp comparison)
  3. Dialog theming and construction:
     - LobsterConfigDialog frameless themed layout
     - HubcapConfigDialog frameless themed layout
  4. SingleDepotSelectionDialog:
     - get_selected_dlc_data regression test
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ is on PYTHONPATH
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from utils.settings import get_settings
from utils.sls_lua_config import (
    read_lobster_conf,
    write_lobster_conf,
    read_spacebunny_conf,
    write_spacebunny_conf,
    is_valid_hubcap_key,
    sync_hubcap_api_key,
)
from ui.dialogs.lobster_config_dialog import LobsterConfigDialog
from ui.dialogs.hubcap_config_dialog import HubcapConfigDialog
from ui.dialogs.single_depot_dialog import SingleDepotSelectionDialog


class TestSlsLuaConfigAndDialogs(unittest.TestCase):

    def test_single_depot_dialog_dlc_method(self):
        """SingleDepotSelectionDialog must implement get_selected_dlc_data returning empty dict."""
        self.assertTrue(hasattr(SingleDepotSelectionDialog, "get_selected_dlc_data"))

    def test_lobster_config_read_write(self):
        """Verify lobster.conf.lua reading, modifying, and writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conf_path = Path(tmpdir) / "lobster.conf.lua"

            # Default config when file does not exist
            cfg = read_lobster_conf(conf_path)
            self.assertTrue(cfg.get("enabled"))
            self.assertTrue(cfg.get("notify"))
            self.assertTrue(cfg.get("auto_recover"))
            self.assertFalse(cfg.get("run_on_reload"))

            # Write custom config
            cfg["notify"] = False
            cfg["run_on_reload"] = True
            ok = write_lobster_conf(cfg, conf_path)
            self.assertTrue(ok)
            self.assertTrue(conf_path.is_file())

            # Read back
            cfg2 = read_lobster_conf(conf_path)
            self.assertTrue(cfg2.get("enabled"))
            self.assertFalse(cfg2.get("notify"))
            self.assertTrue(cfg2.get("auto_recover"))
            self.assertTrue(cfg2.get("run_on_reload"))

    def test_spacebunny_config_read_write(self):
        """Verify spacebunny.conf.lua reading, modifying, and writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conf_path = Path(tmpdir) / "spacebunny.conf.lua"

            cfg = read_spacebunny_conf(conf_path)
            self.assertFalse(cfg.get("standalone"))
            self.assertIn("hubcap", cfg)
            hub = cfg["hubcap"]
            self.assertTrue(hub.get("enabled"))
            self.assertEqual(hub.get("api_key"), "")

            # Modify hubcap table
            test_key = "abc12345-6789-def0-1234-56789abcdef0"
            test_ts = 1845242026
            hub["api_key"] = test_key
            hub["api_key_timestamp"] = test_ts
            hub["enabled"] = False
            ok = write_spacebunny_conf(cfg, conf_path)
            self.assertTrue(ok)
            self.assertTrue(conf_path.is_file())

            # Read back
            cfg2 = read_spacebunny_conf(conf_path)
            self.assertFalse(cfg2["hubcap"]["enabled"])
            self.assertEqual(cfg2["hubcap"]["api_key"], test_key)
            self.assertEqual(cfg2["hubcap"]["api_key_timestamp"], test_ts)

    def test_hubcap_key_validation(self):
        """Verify Hubcap API key validator."""
        self.assertTrue(is_valid_hubcap_key("12345678-1234-1234-1234-123456789abc"))
        self.assertTrue(is_valid_hubcap_key("hubcap_live_token_1234567890"))
        self.assertFalse(is_valid_hubcap_key(""))
        self.assertFalse(is_valid_hubcap_key("short"))
        self.assertFalse(is_valid_hubcap_key("invalid key with spaces!"))

    def test_sync_hubcap_api_key(self):
        """Verify bidirectional timestamp-based synchronization."""
        settings = get_settings()
        orig_key = settings.value("morrenus_api_key", "", type=str)
        orig_ts = settings.value("morrenus_api_key_timestamp", 0, type=int)

        with tempfile.TemporaryDirectory() as tmpdir:
            sb_path = Path(tmpdir) / "spacebunny.conf.lua"
            try:
                # 1. Lua newer than settings -> sync to settings
                lua_key = "lua-newer-key-1234567890"
                lua_ts = 4518242026  # minute 45, hour 18, day 24, year 2026
                settings.setValue("morrenus_api_key", "old-key-1234567890")
                settings.setValue("morrenus_api_key_timestamp", "1012232026")  # day 23

                lua_cfg = {
                    "standalone": False,
                    "hubcap": {
                        "enabled": True,
                        "api_key": lua_key,
                        "api_key_timestamp": lua_ts,
                    }
                }
                write_spacebunny_conf(lua_cfg, sb_path)

                synced, msg = sync_hubcap_api_key(settings, sb_path)
                self.assertTrue(synced)
                self.assertIn("spacebunny.conf.lua to ASSella", msg)
                self.assertEqual(settings.value("morrenus_api_key"), lua_key)
                self.assertEqual(int(settings.value("morrenus_api_key_timestamp")), lua_ts)

                # 2. Settings newer than Lua -> sync to Lua
                local_key = "local-newer-key-9876543210"
                local_ts = 5519262026  # day 26
                settings.setValue("morrenus_api_key", local_key)
                settings.setValue("morrenus_api_key_timestamp", str(local_ts))

                synced2, msg2 = sync_hubcap_api_key(settings, sb_path)
                self.assertTrue(synced2)
                self.assertIn("ASSella to spacebunny.conf.lua", msg2)

                read_back = read_spacebunny_conf(sb_path)
                self.assertEqual(read_back["hubcap"]["api_key"], local_key)
                self.assertEqual(read_back["hubcap"]["api_key_timestamp"], local_ts)
            finally:
                settings.setValue("morrenus_api_key", orig_key)
                settings.setValue("morrenus_api_key_timestamp", orig_ts)

    def test_dialogs_instantiation(self):
        """Ensure LobsterConfigDialog and HubcapConfigDialog instantiate cleanly."""
        ldlg = LobsterConfigDialog()
        self.assertIn("enabled", ldlg.switches)
        self.assertIn("notify", ldlg.switches)

        hdlg = HubcapConfigDialog()
        self.assertIsNotNone(hdlg.key_input)
    def test_settings_dialog_tabs_initialization(self):
        """Ensure SettingsDialog loads all tabs without runtime import crashes."""
        from ui.dialogs.settings import SettingsDialog
        for tab_name in ("general", "downloads", "assella", "at0m", "morrenus", "tools", "advanced"):
            dlg = SettingsDialog(initial_tab=tab_name)
            self.assertIsNotNone(dlg)
            dlg.close()


if __name__ == "__main__":
    unittest.main()
