"""
atom_dlc_selection_dialog.py - Dedicated modal DLC selection dialog for AT0-M mode.

Presents the 3-section layout (AdditionalApps, AdditionalDepots, DecryptionKeys)
specifically tailored for DLC-only configuration:
- Base game OS depots and already-owned DLCs are hidden.
- Unowned DLCs are auto-selected by default.
- Select All / None toggles appear under each section only if >= 5 entries.
- Directly syncs selected DLCs, depots, and decryption keys into SLSsteam config.yaml
  and registers to plugin_games.json while enforcing all AT0-M DLC invariants.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.dialog_titlebar import DialogTitleBar
from ui.dialogs.game_details.depots_tab import (
    MiniSwitchToggle,
    _ToggleContainer,
    _make_bulk_toggle_bar,
    _make_table,
    section_title,
    _set_table_height,
)
from ui.dialogs.themed_message_box import ThemedMessageBox
from utils.dlc_helpers import (
    get_owned_dlcs_from_steam,
    is_base_game_main_depot,
)
from utils.plugin_games import (
    build_depot_comment,
    build_key_comment,
    load_plugin_library,
    save_plugin_library,
)
from utils.settings import get_settings
from utils.yaml_config_manager import (
    add_dlc_data_batch,
    batch_config_edit,
    ensure_sls_plugin_config_sections,
    get_additional_apps,
    get_additional_depots,
    get_dlc_data,
    get_user_config_path,
    remove_additional_app,
    remove_dlc_data,
)

logger = logging.getLogger(__name__)


class AtomDlcSelectionDialog(QDialog):
    """Dedicated modal dialog for selecting and registering DLCs into SLSsteam AT0-M mode."""

    def __init__(
        self,
        parent: Optional[QWidget],
        app_id: str,
        game_name: str,
        accent_color: str,
        discovery: Any,
        manifest_data: Optional[Dict[str, Any]] = None,
        cached_selected_depots: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.app_id = str(app_id).strip()
        self.game_name = game_name or f"App {self.app_id}"
        self.accent_color = accent_color or "#6c5ce7"
        self.discovery = discovery
        self.manifest_data = manifest_data or {}
        self.cached_selected_depots = cached_selected_depots or []
        self.settings = get_settings()

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(720)
        self.resize(760, 680)

        # State tracking
        self.desired_apps: Dict[str, bool] = {}
        self.desired_depots: Dict[str, bool] = {}
        self.desired_keys: Dict[str, bool] = {}

        self.app_toggles: Dict[str, MiniSwitchToggle] = {}
        self.depot_toggles: Dict[str, MiniSwitchToggle] = {}
        self.key_toggles: Dict[str, MiniSwitchToggle] = {}

        self._internal_bulk_update = False
        self._registered_success = False

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        card = QFrame()
        card.setObjectName("dialogCard")
        card.setStyleSheet("""
            QFrame#dialogCard {
                background-color: #16181f;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 10px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        titlebar = DialogTitleBar(self, f"AT0-M DLC Setup — {self.game_name}", can_minimize=False, can_maximize=False)
        card_layout.addWidget(titlebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0px; }
            QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.14); border-radius: 3px; min-height: 24px; }
            QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.25); }
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        self.layout = QVBoxLayout(content_widget)
        self.layout.setContentsMargins(20, 14, 20, 16)
        self.layout.setSpacing(12)

        # Subtitle banner
        sub_lbl = QLabel(
            f"Select which DLCs to unlock and register for <b>{self.game_name}</b> ({self.app_id}) in AT0-M.<br/>"
            "<span style='color: rgba(255, 255, 255, 0.55); font-size: 8pt;'>"
            "Owned DLCs and base game content files are hidden to prevent accidental clobbering.</span>"
        )
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.85); font-size: 8.5pt; line-height: 1.4;")
        self.layout.addWidget(sub_lbl)

        ac = self.accent_color

        # ── Section 1: AdditionalApps (DLC AppIDs & Names) ──
        self.layout.addWidget(section_title("AppIDs & Licenses (AdditionalApps)", ac))
        self.apps_table = _make_table(["AppID", "DLC Name", "Register"], ac)
        self.apps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.apps_table.setColumnWidth(0, 110)
        self.apps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.apps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.apps_table.setColumnWidth(2, 85)
        self.layout.addWidget(self.apps_table)

        self.apps_bulk_bar, self.apps_bulk_toggle, self.apps_btn_all, self.apps_btn_none = _make_bulk_toggle_bar(
            "DLC AppIDs", lambda chk: self._on_bulk_toggle_apps(chk)
        )
        self.layout.addWidget(self.apps_bulk_bar)

        # ── Section 2: AdditionalDepots (DLC Depots) ──
        self.layout.addWidget(section_title("Depots Registered (AdditionalDepots)", ac))
        self.depots_table = _make_table(["Depot ID", "Depot Name", "Register"], ac)
        self.depots_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.depots_table.setColumnWidth(0, 110)
        self.depots_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.depots_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.depots_table.setColumnWidth(2, 85)
        self.layout.addWidget(self.depots_table)

        self.depots_bulk_bar, self.depots_bulk_toggle, self.depots_btn_all, self.depots_btn_none = _make_bulk_toggle_bar(
            "Depots", lambda chk: self._on_bulk_toggle_depots(chk)
        )
        self.layout.addWidget(self.depots_bulk_bar)

        # ── Section 3: DecryptionKeys (Keys) ──
        self.layout.addWidget(section_title("AES Decryption Keys (DecryptionKeys)", ac))
        self.keys_table = _make_table(["Target ID", "AES Key", "Register"], ac)
        self.keys_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.keys_table.setColumnWidth(0, 110)
        self.keys_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.keys_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.keys_table.setColumnWidth(2, 85)
        self.layout.addWidget(self.keys_table)

        self.keys_bulk_bar, self.keys_bulk_toggle, self.keys_btn_all, self.keys_btn_none = _make_bulk_toggle_bar(
            "Keys", lambda chk: self._on_bulk_toggle_keys(chk)
        )
        self.layout.addWidget(self.keys_bulk_bar)

        scroll.setWidget(content_widget)
        card_layout.addWidget(scroll, 1)

        # ── Bottom Action Bar ──
        btn_bar = QFrame()
        btn_bar.setStyleSheet("background: rgba(0, 0, 0, 0.25); border-top: 1px solid rgba(255, 255, 255, 0.08);")
        bar_lay = QHBoxLayout(btn_bar)
        bar_lay.setContentsMargins(18, 12, 18, 12)
        bar_lay.setSpacing(10)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 8.5pt;")
        bar_lay.addWidget(self.summary_lbl)
        bar_lay.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setFixedSize(80, 32)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.07);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 5px;
                color: rgba(255, 255, 255, 0.85);
                font-size: 8.5pt;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.14);
                color: #FFFFFF;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        bar_lay.addWidget(btn_cancel)

        from utils.color_utils import get_best_foreground_color
        btn_fg = get_best_foreground_color(self.accent_color)
        self.register_btn = QPushButton("Register to AT0-M")
        self.register_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.register_btn.setFixedHeight(32)
        self.register_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.accent_color};
                border: none;
                border-radius: 5px;
                color: {btn_fg};
                font-size: 8.5pt;
                font-weight: 600;
                padding: 0 16px;
            }}
            QPushButton:hover:!disabled {{
                background-color: #FFFFFF;
                color: #000000;
            }}
            QPushButton:disabled {{
                background-color: rgba(255, 255, 255, 0.05);
                color: rgba(255, 255, 255, 0.25);
            }}
        """)
        self.register_btn.clicked.connect(self._on_register_clicked)
        bar_lay.addWidget(self.register_btn)

        card_layout.addWidget(btn_bar)
        root_layout.addWidget(card)

        # Collect data and populate
        self._populate()

    def _collect_dlc_data(self) -> Dict[str, Any]:
        """Cross-reference DLCs, depots, and keys, hiding base game and owned items."""
        cfg_path = get_user_config_path()
        live_apps = set(get_additional_apps(cfg_path)) if cfg_path and cfg_path.exists() else set()
        live_depots = set(get_additional_depots(cfg_path)) if cfg_path and cfg_path.exists() else set()
        live_dlc_data = set(get_dlc_data(cfg_path, self.app_id).keys()) if cfg_path and cfg_path.exists() else set()
        try:
            steam_owned = get_owned_dlcs_from_steam(self.app_id)
        except Exception as e:
            logger.debug(f"[AtomDLC] Could not read Steam ticket ownership: {e}")
            steam_owned = set()

        # All catalog DLCs
        raw_catalog: Dict[str, str] = {}
        if self.discovery and getattr(self.discovery, "catalog", None):
            raw_catalog.update({str(k): str(v) for k, v in self.discovery.catalog.items()})
        if self.manifest_data.get("dlcs"):
            raw_catalog.update({str(k): str(v) for k, v in self.manifest_data["dlcs"].items()})

        # Exclude base game AppID
        raw_catalog.pop(self.app_id, None)

        # Exclude already owned DLCs (in Steam tickets, AdditionalApps, or DlcData)
        unowned_dlcs = {
            k: v for k, v in raw_catalog.items()
            if k not in live_apps and k not in live_dlc_data and k not in steam_owned
        }

        # Depots mapping
        manifest_depots = self.manifest_data.get("depots") or {}
        candidate_depots = getattr(self.discovery, "depots", []) or []
        missing_depot_ids = set(self.manifest_data.get("missing_depots_from_hubcap") or [])
        missing_info = self.manifest_data.get("missing_depots_info") or {}

        depots_map: Dict[str, Dict[str, Any]] = {}
        for cd in candidate_depots:
            did = str(cd.depot_id).strip()
            dlc_id = str(cd.dlc_appid).strip() if cd.dlc_appid else ""
            if did == self.app_id or is_base_game_main_depot(did, cd.name, self.app_id):
                continue
            if dlc_id and dlc_id not in unowned_dlcs:
                continue  # Skip depot if its DLC is already owned
            depots_map[did] = {
                "id": did,
                "name": cd.name or f"Depot {did}",
                "dlc_appid": dlc_id,
                "is_missing": did in missing_depot_ids,
                "missing_status": missing_info.get(did, {}).get("status", "unknown") if did in missing_depot_ids else None,
                "missing_tag": missing_info.get(did, {}).get("tag", "[No Key]") if did in missing_depot_ids else None,
                "key": self.manifest_data.get("keys", {}).get(did, ""),
            }

        for did, dinfo in manifest_depots.items():
            did_str = str(did).strip()
            if did_str == self.app_id or is_base_game_main_depot(did_str, "", self.app_id):
                continue
            dlc_id = str(dinfo.get("dlcappid") or "").strip()
            if dlc_id and dlc_id not in unowned_dlcs:
                continue
            dname = dinfo.get("name") or dinfo.get("desc") or f"Depot {did_str}"
            is_miss = did_str in missing_depot_ids
            m_stat = missing_info.get(did_str, {}).get("status", "unknown") if is_miss else None
            m_tag = missing_info.get(did_str, {}).get("tag", "[No Key]") if is_miss else None
            k_val = dinfo.get("key") or self.manifest_data.get("keys", {}).get(did_str, "")
            depots_map.setdefault(did_str, {
                "id": did_str,
                "name": dname,
                "dlc_appid": dlc_id,
                "is_missing": is_miss,
                "missing_status": m_stat,
                "missing_tag": m_tag,
                "key": k_val,
            })

        # Keys mapping
        manifest_keys = self.manifest_data.get("keys") or {}
        keys_map: Dict[str, Dict[str, Any]] = {}
        for did, dinfo in depots_map.items():
            k_val = dinfo.get("key") or manifest_keys.get(did, "")
            is_miss = dinfo.get("is_missing", False) or not k_val
            keys_map[did] = {
                "id": did,
                "key": k_val,
                "desc": dinfo.get("name", ""),
                "is_missing": is_miss,
                "missing_status": dinfo.get("missing_status"),
                "missing_tag": dinfo.get("missing_tag", "[No Key]"),
            }

        return {
            "unowned_dlcs": unowned_dlcs,
            "depots": depots_map,
            "keys": keys_map,
        }

    def _populate(self):
        data = self._collect_dlc_data()
        self._data = data

        # 1. Populate AdditionalApps Table
        dlcs = data["unowned_dlcs"]
        sorted_dlc_ids = sorted(dlcs.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        self.apps_table.setRowCount(len(sorted_dlc_ids))

        for row, dlc_id in enumerate(sorted_dlc_ids):
            dlc_name = dlcs[dlc_id]
            id_item = QTableWidgetItem(dlc_id)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.apps_table.setItem(row, 0, id_item)

            name_item = QTableWidgetItem(dlc_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            name_item.setToolTip(f"{dlc_name} ({dlc_id})")
            self.apps_table.setItem(row, 1, name_item)

            toggle = MiniSwitchToggle(checked=True)
            self.desired_apps[dlc_id] = True
            self.app_toggles[dlc_id] = toggle

            def _make_app_cb(aid: str):
                def _cb(checked: bool):
                    self.desired_apps[aid] = checked
                    self._cascade_app_toggle(aid, checked)
                    self._update_summary()
                    self._sync_bulk_bars()
                return _cb

            toggle.toggled.connect(_make_app_cb(dlc_id))
            self.apps_table.setCellWidget(row, 2, _ToggleContainer(toggle))

        _set_table_height(self.apps_table, len(sorted_dlc_ids))
        self.apps_bulk_bar.setVisible(len(sorted_dlc_ids) >= 5)

        # 2. Populate AdditionalDepots Table
        depots = data["depots"]
        sorted_depot_ids = sorted(depots.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        self.depots_table.setRowCount(len(sorted_depot_ids))

        for row, did in enumerate(sorted_depot_ids):
            dinfo = depots[did]
            id_item = QTableWidgetItem(did)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if dinfo.get("is_missing"):
                id_item.setForeground(QColor(130, 130, 130))
                font = id_item.font()
                font.setItalic(True)
                id_item.setFont(font)
            self.depots_table.setItem(row, 0, id_item)

            desc_text = dinfo["name"]
            if dinfo.get("is_missing") and dinfo.get("missing_tag"):
                desc_text = f"{dinfo['missing_tag']}  {desc_text}"

            desc_item = QTableWidgetItem(desc_text)
            desc_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if dinfo.get("is_missing"):
                m_stat = dinfo.get("missing_status")
                if m_stat == "ready_on_hubcap":
                    desc_item.setForeground(QColor("#4DD0E1"))
                elif m_stat == "key_pending":
                    desc_item.setForeground(QColor("#FFB74D"))
                else:
                    desc_item.setForeground(QColor(130, 130, 130))
                font = desc_item.font()
                font.setItalic(True)
                desc_item.setFont(font)
            desc_item.setToolTip(dinfo["name"])
            self.depots_table.setItem(row, 1, desc_item)

            if dinfo.get("is_missing"):
                toggle = MiniSwitchToggle(checked=False, read_only=True)
                toggle.setEnabled(False)
                toggle.setToolTip("Depot decryption key is missing from Hubcap — cannot enable.")
            else:
                toggle = MiniSwitchToggle(checked=True)
                self.desired_depots[did] = True

                def _make_depot_cb(depot_id: str):
                    def _cb(checked: bool):
                        self.desired_depots[depot_id] = checked
                        self._update_summary()
                        self._sync_bulk_bars()
                    return _cb

                toggle.toggled.connect(_make_depot_cb(did))

            self.depot_toggles[did] = toggle
            self.depots_table.setCellWidget(row, 2, _ToggleContainer(toggle))

        _set_table_height(self.depots_table, len(sorted_depot_ids))
        self.depots_bulk_bar.setVisible(len(sorted_depot_ids) >= 5)

        # 3. Populate DecryptionKeys Table
        keys = data["keys"]
        sorted_key_ids = sorted(keys.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        self.keys_table.setRowCount(len(sorted_key_ids))

        for row, kid in enumerate(sorted_key_ids):
            kinfo = keys[kid]
            id_item = QTableWidgetItem(kid)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if kinfo.get("is_missing"):
                id_item.setForeground(QColor(130, 130, 130))
                font = id_item.font()
                font.setItalic(True)
                id_item.setFont(font)
            self.keys_table.setItem(row, 0, id_item)

            if kinfo.get("is_missing"):
                key_text = kinfo.get("missing_tag", "[No Key]")
                key_item = QTableWidgetItem(key_text)
                key_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                key_item.setForeground(QColor(130, 130, 130))
                font_k = key_item.font()
                font_k.setItalic(True)
                key_item.setFont(font_k)
                key_item.setToolTip("No AES decryption key available.")
                self.keys_table.setItem(row, 1, key_item)

                toggle = MiniSwitchToggle(checked=False, read_only=True)
                toggle.setEnabled(False)
            else:
                raw_key = kinfo["key"]
                short_key = f"{raw_key[:15]}..." if len(raw_key) > 15 else (raw_key or "N/A")
                key_item = QTableWidgetItem(short_key)
                key_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                key_item.setToolTip(f"AES Key for {kinfo.get('desc', kid)}")
                self.keys_table.setItem(row, 1, key_item)

                toggle = MiniSwitchToggle(checked=True)
                self.desired_keys[kid] = True

                def _make_key_cb(key_id: str):
                    def _cb(checked: bool):
                        self.desired_keys[key_id] = checked
                        self._sync_bulk_bars()
                    return _cb

                toggle.toggled.connect(_make_key_cb(kid))

            self.key_toggles[kid] = toggle
            self.keys_table.setCellWidget(row, 2, _ToggleContainer(toggle))

        _set_table_height(self.keys_table, len(sorted_key_ids))
        self.keys_bulk_bar.setVisible(len(sorted_key_ids) >= 5)

        self._update_summary()
        self._sync_bulk_bars()

    def _cascade_app_toggle(self, aid: str, checked: bool):
        """When a DLC AppID is toggled, update its mapped depots and keys."""
        depots = self._data.get("depots", {})
        for did, dinfo in depots.items():
            if str(dinfo.get("dlc_appid")) == str(aid):
                if did in self.depot_toggles and self.depot_toggles[did].isEnabled():
                    self.depot_toggles[did].setChecked(checked, animate=True)
                    self.desired_depots[did] = checked
                if did in self.key_toggles and self.key_toggles[did].isEnabled():
                    self.key_toggles[did].setChecked(checked, animate=True)
                    self.desired_keys[did] = checked

    def _update_summary(self):
        sel_dlcs = sum(1 for v in self.desired_apps.values() if v)
        tot_dlcs = len(self.desired_apps)
        sel_depots = sum(1 for v in self.desired_depots.values() if v)
        self.summary_lbl.setText(f"Selected: <b>{sel_dlcs}/{tot_dlcs}</b> DLC(s), <b>{sel_depots}</b> depot(s)")
        self.register_btn.setText(f"Register to AT0-M ({sel_dlcs} DLCs)")
        self.register_btn.setEnabled(sel_dlcs > 0 or sel_depots > 0)

    def _sync_bulk_bars(self):
        if self._internal_bulk_update:
            return
        self._internal_bulk_update = True
        try:
            if len(self.desired_apps) >= 5:
                all_apps_on = bool(self.desired_apps) and all(self.desired_apps.values())
                self.apps_bulk_toggle.setChecked(all_apps_on, animate=False)

            valid_depot_ids = [d for d, info in self._data.get("depots", {}).items() if not info.get("is_missing")]
            if len(self._data.get("depots", {})) >= 5 and valid_depot_ids:
                all_depots_on = all(self.desired_depots.get(d, False) for d in valid_depot_ids)
                self.depots_bulk_toggle.setChecked(all_depots_on, animate=False)

            valid_key_ids = [k for k, info in self._data.get("keys", {}).items() if not info.get("is_missing") and info.get("key")]
            if len(self._data.get("keys", {})) >= 5 and valid_key_ids:
                all_keys_on = all(self.desired_keys.get(k, False) for k in valid_key_ids)
                self.keys_bulk_toggle.setChecked(all_keys_on, animate=False)
        finally:
            self._internal_bulk_update = False

    def _on_bulk_toggle_apps(self, checked: bool):
        if self._internal_bulk_update:
            return
        for aid, toggle in self.app_toggles.items():
            if toggle.isEnabled():
                toggle.setChecked(checked, animate=True)
        self._update_summary()

    def _on_bulk_toggle_depots(self, checked: bool):
        if self._internal_bulk_update:
            return
        for did, toggle in self.depot_toggles.items():
            if toggle.isEnabled():
                toggle.setChecked(checked, animate=True)
        self._update_summary()

    def _on_bulk_toggle_keys(self, checked: bool):
        if self._internal_bulk_update:
            return
        for kid, toggle in self.key_toggles.items():
            if toggle.isEnabled():
                toggle.setChecked(checked, animate=True)
        self._update_summary()

    def _on_register_clicked(self):
        """Write configuration to SLSsteam config.yaml and register in plugin_games.json."""
        selected_dlcs = {aid: self._data["unowned_dlcs"][aid] for aid, v in self.desired_apps.items() if v}
        selected_depots = {did: self._data["depots"][did]["name"] for did, v in self.desired_depots.items() if v}
        selected_keys = {
            kid: self._data["keys"][kid]["key"]
            for kid, v in self.desired_keys.items()
            if v and self._data["keys"][kid].get("key")
        }

        if not selected_dlcs and not selected_depots:
            ThemedMessageBox.information(self, "Nothing Selected", "No DLCs or depots are selected.")
            return

        cfg_path = get_user_config_path()
        if not cfg_path:
            ThemedMessageBox.critical(self, "Error", "SLSsteam configuration path could not be found.")
            return

        try:
            ensure_sls_plugin_config_sections(cfg_path)

            dlc_count = len(selected_dlcs)
            with batch_config_edit(cfg_path) as editor:
                # Invariant: Base AppID must NEVER be in AdditionalApps for DLC-only game
                editor.remove_app(self.app_id)

                if dlc_count >= 64:
                    # High DLC counts: use DlcData
                    add_dlc_data_batch(cfg_path, self.app_id, selected_dlcs)
                else:
                    for dlc_id, dlc_name in selected_dlcs.items():
                        editor.add_app(dlc_id, comment=f"[DLC] {dlc_name}")

                for did, dname in selected_depots.items():
                    comment = build_depot_comment(self.game_name, did, dname, self.app_id)
                    editor.add_depot(did, comment=comment, app_id=self.app_id)

                for kid, kval in selected_keys.items():
                    dname = selected_depots.get(kid, "")
                    comment = build_key_comment(self.game_name, kid, dname, self.app_id)
                    editor.add_key(kid, kval, comment=comment)

            # Update plugin_games.json
            plugin_lib = load_plugin_library()
            existing_rec = plugin_lib.get(self.app_id, {})
            existing_dlcs = set(existing_rec.get("dlc_appids", [])) | set(selected_dlcs.keys())
            existing_depots = set(existing_rec.get("depots", [])) | set(selected_depots.keys())
            existing_keys = dict(existing_rec.get("keys", {}))
            existing_keys.update(selected_keys)
            existing_names = dict(existing_rec.get("depot_names", {}))
            existing_names.update(selected_depots)

            plugin_lib[self.app_id] = {
                "name": self.game_name,
                "appid": self.app_id,
                "is_atom": True,
                "is_dlc_only": True,
                "dlc_appids": sorted(existing_dlcs, key=lambda x: int(x) if x.isdigit() else 0),
                "depots": sorted(existing_depots, key=lambda x: int(x) if x.isdigit() else 0),
                "keys": existing_keys,
                "depot_names": existing_names,
            }
            save_plugin_library(plugin_lib)

            # Save setting
            self.settings.setValue(f"dlc_only_mode/{self.app_id}", True)

            ThemedMessageBox.information(
                self,
                "DLC Registration Complete",
                f"✓ Successfully registered <b>{dlc_count}</b> DLC(s) and <b>{len(selected_depots)}</b> depot(s) "
                f"for '{self.game_name}' into SLSsteam!<br/><br/>"
                "Please restart Steam client so Steam natively recognizes and unlocks your new DLCs.",
            )
            self._registered_success = True
            self.accept()
        except Exception as exc:
            logger.error(f"[AtomDlcSelection] Failed to register DLCs: {exc}", exc_info=True)
            ThemedMessageBox.critical(self, "Registration Error", f"Failed writing to SLSsteam config:\n\n{exc}")
