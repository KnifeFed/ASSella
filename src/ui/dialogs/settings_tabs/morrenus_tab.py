import time
import logging
from typing import Optional, Tuple

import requests
from PyQt6.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QApplication,
    QScrollArea,
)

from ui.dialogs.settings_tabs.morrenus_stats_widget import MorrenusStatsWidget

logger = logging.getLogger(__name__)


def benchmark_mrc_provider(provider: str) -> Tuple[bool, int, str]:
    """Background helper to benchmark Manifest / MRC provider connectivity and latency."""
    start = time.perf_counter()
    ok = False
    err = ""
    prov = (provider or "auto").lower()
    try:
        if prov == "wudrm":
            url = "http://gmrc.wudrm.com/manifest/"
            r = requests.get(url, headers={"User-Agent": "Valve/Steam HTTP Client 1.0"}, timeout=4.0)
            ok = r.status_code in (200, 400, 404, 405)
            if not ok:
                err = f"HTTP {r.status_code}"
        elif prov == "manifestdex":
            url = "https://manifest.manifestdex.com/"
            headers = {"User-Agent": "ManifestDeX/1.0", "Accept": "*/*"}
            r = requests.get(url, headers=headers, timeout=4.0)
            ok = r.status_code < 500
            if not ok:
                err = f"HTTP {r.status_code}"
        elif prov == "hubcap":
            url = "https://hubcapmanifest.com/api/v1/health"
            r = requests.get(url, timeout=4.0)
            ok = r.status_code == 200
            if not ok:
                err = f"HTTP {r.status_code}"
        elif prov == "steamrun":
            url = "https://manifest.steam.run/api/manifest/2716668420228619833"
            r = requests.get(url, headers={"User-Agent": "Valve/Steam HTTP Client 1.0"}, timeout=4.0)
            ok = r.status_code in (200, 400, 404)
            if not ok:
                err = f"HTTP {r.status_code}"
        elif prov == "opensteamtool":
            url = "https://manifest.opensteamtool.com/manifest/2716668420228619833"
            r = requests.get(url, headers={"User-Agent": "Valve/Steam HTTP Client 1.0"}, timeout=4.0)
            ok = r.status_code in (200, 400, 404)
            if not ok:
                err = f"HTTP {r.status_code}"
        else:  # auto / race
            try:
                r1 = requests.get(
                    "http://gmrc.wudrm.com/manifest/",
                    headers={"User-Agent": "Valve/Steam HTTP Client 1.0"},
                    timeout=3.0,
                )
                if r1.status_code in (200, 400, 404, 405):
                    ok = True
            except Exception:
                pass

            if not ok:
                try:
                    r2 = requests.get(
                        "https://manifest.manifestdex.com/",
                        headers={"User-Agent": "ManifestDeX/1.0"},
                        timeout=3.0,
                    )
                    ok = r2.status_code < 500
                    if not ok:
                        err = f"HTTP {r2.status_code}"
                except Exception as e2:
                    err = str(e2)[:25]
    except requests.exceptions.Timeout:
        err = "Timeout"
    except requests.exceptions.ConnectionError:
        err = "Connection Refused"
    except Exception as exc:
        err = str(exc)[:25]

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return (ok, elapsed_ms, err)


def create_api_key_setting(
    dialog,
    label: str,
    placeholder: str,
    setting_key: str,
    help_url: Optional[str] = None,
    help_text: Optional[str] = None,
) -> Tuple[QVBoxLayout, QLineEdit]:
    """Create an API key input field with Get API Key, Show, and Paste buttons in a row below."""
    layout = QVBoxLayout()
    layout.setSpacing(6)

    lbl = QLabel(label)
    lbl.setStyleSheet("color: #FFFFFF; font-size: 9.5pt; font-weight: 500; border: none; background: transparent;")
    layout.addWidget(lbl)

    api_key_input = QLineEdit()
    api_key_input.setPlaceholderText(placeholder)
    api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
    current_key = dialog.settings.value(setting_key, "", type=str)
    api_key_input.setText(current_key)
    layout.addWidget(api_key_input)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)

    if help_url:
        get_key_btn = QPushButton("Get API Key")
        get_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        get_key_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(help_url)))
        btn_row.addWidget(get_key_btn)

    toggle_btn = QPushButton("Show")
    toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    toggle_btn.clicked.connect(lambda: toggle_api_key_visibility(api_key_input, toggle_btn))
    btn_row.addWidget(toggle_btn)

    paste_btn = QPushButton("Paste")
    paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_paste():
        clip_text = QApplication.clipboard().text()
        if clip_text:
            api_key_input.setText(clip_text.strip())

    paste_btn.clicked.connect(_on_paste)
    btn_row.addWidget(paste_btn)

    btn_row.addStretch()
    layout.addLayout(btn_row)

    return layout, api_key_input


def toggle_api_key_visibility(input_field: QLineEdit, toggle_btn: QPushButton) -> None:
    """Toggle API key visibility."""
    if input_field.echoMode() == QLineEdit.EchoMode.Password:
        input_field.setEchoMode(QLineEdit.EchoMode.Normal)
        toggle_btn.setText("Hide")
    else:
        input_field.setEchoMode(QLineEdit.EchoMode.Password)
        toggle_btn.setText("Show")


def create_morrenus_tab(dialog) -> QWidget:
    """Create the Morrenus / Hubcap Integrations settings tab with scrollable container."""
    tab = QWidget()
    outer_layout = QVBoxLayout(tab)
    outer_layout.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)

    # 1. API Keys Card
    key_card, key_layout = dialog._create_card_frame("API Keys")
    key_layout.setSpacing(8)

    morrenus_layout, dialog.api_key_input = create_api_key_setting(
        dialog,
        "Hubcap API Key:",
        "Paste your Hubcap API key",
        "morrenus_api_key",
        help_url="https://hubcapmanifest.com/",
    )
    key_layout.addLayout(morrenus_layout)
    layout.addWidget(key_card)

    # 2. Stats Card
    stats_card, stats_layout = dialog._create_card_frame("Hubcap Stats")
    stats_layout.setContentsMargins(10, 8, 10, 8)

    dialog.morrenus_stats_widget = MorrenusStatsWidget()
    stats_layout.addWidget(dialog.morrenus_stats_widget)
    layout.addWidget(stats_card)

    # 3. Byparr Cloudflare Solver Card
    from PyQt6.QtWidgets import QCheckBox
    from core.steamdb_scraper import ByparrManager

    byparr_card, byparr_layout = dialog._create_card_frame("Cloudflare Solver (Byparr)")
    byparr_layout.setContentsMargins(10, 8, 10, 10)
    byparr_layout.setSpacing(8)

    byparr_desc = QLabel(
        "Bypasses Cloudflare Turnstile protection on SteamDB to discover build history, "
        "patch metadata, and depot manifests."
    )
    byparr_desc.setWordWrap(True)
    byparr_desc.setStyleSheet("color: rgba(255, 255, 255, 0.65); font-size: 8.5pt; line-height: 1.3;")
    byparr_layout.addWidget(byparr_desc)

    byparr_enable_cb = QCheckBox("Enable Byparr / SteamDB Integration")
    is_scraping_disabled = dialog.settings.value("disable_steamdb_scraping", False, type=bool)
    byparr_enable_cb.setChecked(not is_scraping_disabled)
    byparr_enable_cb.setCursor(Qt.CursorShape.PointingHandCursor)
    byparr_enable_cb.setStyleSheet("color: #FFFFFF; font-size: 8.5pt; font-weight: 500;")
    byparr_layout.addWidget(byparr_enable_cb)

    status_row = QHBoxLayout()
    status_row.setSpacing(8)
    status_tag = QLabel("Status:")
    status_tag.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 8.5pt; font-weight: 600;")
    status_row.addWidget(status_tag)

    byparr_status_badge = QLabel("")
    status_row.addWidget(byparr_status_badge)
    status_row.addStretch()
    byparr_layout.addLayout(status_row)

    def _update_byparr_status():
        enabled = byparr_enable_cb.isChecked()
        if not enabled:
            byparr_status_badge.setText("Disabled in Settings")
            byparr_status_badge.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 8.5pt; font-weight: bold;")
        elif ByparrManager.is_custom_service():
            url = ByparrManager.get_service_url()
            running = ByparrManager.is_running()
            stat_text = "Online" if running else "Configured"
            color = "#81C784" if running else "#FFB74D"
            byparr_status_badge.setText(f"Custom Bypasser ({stat_text}: {url})")
            byparr_status_badge.setStyleSheet(f"color: {color}; font-size: 8.5pt; font-weight: bold;")
        elif ByparrManager.find_byparr_dir():
            running = ByparrManager.is_running()
            stat_text = "Online" if running else "Ready on Demand"
            byparr_status_badge.setText(f"Local Managed ({stat_text})")
            byparr_status_badge.setStyleSheet("color: #81C784; font-size: 8.5pt; font-weight: bold;")
        else:
            byparr_status_badge.setText("Not Configured / Missing")
            byparr_status_badge.setStyleSheet("color: #FFB74D; font-size: 8.5pt; font-weight: bold;")

    def _on_byparr_toggled(checked: bool):
        dialog.settings.setValue("disable_steamdb_scraping", not checked)
        _update_byparr_status()

    byparr_enable_cb.toggled.connect(_on_byparr_toggled)
    _update_byparr_status()

    # Buttons Row
    byparr_btn_row = QHBoxLayout()
    byparr_btn_row.setSpacing(8)

    btn_setup_local = QPushButton("⚡ Setup Local Byparr")
    btn_setup_local.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_setup_local.setStyleSheet("""
        QPushButton {
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 6px;
            color: #FFFFFF;
            font-size: 8.5pt;
            font-weight: 500;
            padding: 6px 14px;
        }
        QPushButton:hover {
            background-color: rgba(255, 255, 255, 0.16);
            border-color: rgba(255, 255, 255, 0.3);
        }
    """)

    def _on_setup_local():
        try:
            from managers.cli_manager import open_cli_terminal
            open_cli_terminal(
                "curl -sSL https://raw.githubusercontent.com/niwia/ASSella/beta/scripts/setup_byparr.sh | bash; "
                "echo ''; echo 'Setup finished. Press Enter to close...'; read _"
            )
        except Exception as _ex:
            logger.warning(f"Could not launch local byparr setup: {_ex}")

    btn_setup_local.clicked.connect(_on_setup_local)
    byparr_btn_row.addWidget(btn_setup_local)

    btn_configure_custom = QPushButton("🌐 Configure Custom Bypasser")
    btn_configure_custom.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_configure_custom.setStyleSheet("""
        QPushButton {
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 6px;
            color: #FFFFFF;
            font-size: 8.5pt;
            font-weight: 500;
            padding: 6px 14px;
        }
        QPushButton:hover {
            background-color: rgba(255, 255, 255, 0.16);
            border-color: rgba(255, 255, 255, 0.3);
        }
    """)

    def _on_configure_custom():
        from ui.dialogs.custom_byparr_dialog import CustomByparrDialog
        dlg = CustomByparrDialog(dialog, accent_color=dialog.accent_color)
        if dlg.exec():
            byparr_enable_cb.setChecked(True)
            _update_byparr_status()

    btn_configure_custom.clicked.connect(_on_configure_custom)
    byparr_btn_row.addWidget(btn_configure_custom)

    byparr_btn_row.addStretch()
    byparr_layout.addLayout(byparr_btn_row)

    layout.addWidget(byparr_card)

    layout.addStretch()

    scroll.setWidget(container)
    outer_layout.addWidget(scroll)

    # Connect tab change for lazy loading stats
    dialog.morrenus_tab_initialized = False

    dialog.tab_widget.addTab(tab, "Integrations")
    return tab
