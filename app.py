import sys
import subprocess
import webbrowser
import plistlib
import os
import time
import html
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QTextBrowser, QDialog, QFormLayout, QSpinBox, QCheckBox,
    QPlainTextEdit, QMessageBox, QSystemTrayIcon, QMenu, QProgressBar, QComboBox,
    QFileDialog
)
from PySide6.QtGui import QAction, QIcon, QPixmap

from db import (
    init_db, load_settings, save_settings, query_repos, repo_by_id, mark_read,
    set_favorite, set_hidden, stats, update_release_info, set_managed_install,
    update_description_translation
)
from engine import (
    DiscoveryEngine, sample_activity, scan_recent_project_signals, rescore_cached
)
from i18n import tr, category_name, normalize_language
from installer import (
    mac_profile, assess_repo, format_bytes, probe_release, install_release,
    license_group
)
from translator import translate_description, TRANSLATION_SOURCE

APP_NAME = "H2S Open Source Radar"
APP_VERSION = "0.1.0"
WEBSITE = "https://h2sstudio.com"

CATEGORIES = [
    "작곡·음악 생성", "DAW 자동화", "Audio→MIDI·채보", "Stem·오디오 분리",
    "보컬·가창 합성", "Agent·MCP", "로컬 LLM", "영상·이미지 AI",
    "3D·비전", "기타 AI",
]

FILTER_KEYS = {
    "all": ("for_you_title", "for_you_sub"),
    "hot": ("trending_title", "trending_sub"),
    "context": ("context_title", "context_sub"),
    "new": ("new_title", "new_sub"),
    "favorite": ("saved_title", "saved_sub"),
}


def asset_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def app_icon():
    path = asset_path("h2s-app-icon.png")
    return QIcon(str(path)) if path.exists() else QIcon()


def sync_login_item(enabled):
    path = Path.home() / "Library" / "LaunchAgents" / "com.h2s.opensource-radar.plist"
    uid = str(os.getuid())
    try:
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(path)],
            capture_output=True, timeout=4
        )
    except Exception:
        pass

    if not enabled:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return

    bundle = Path.home() / "Applications" / "H2S Open Source Radar.app"
    if getattr(sys, "frozen", False):
        try:
            bundle = Path(sys.executable).resolve().parents[2]
        except Exception:
            pass

    payload = {
        "Label": "com.h2s.opensource-radar",
        "ProgramArguments": ["/usr/bin/open", "-g", str(bundle), "--args", "--background"],
        "RunAtLoad": True,
        "ProcessType": "Background",
        "ThrottleInterval": 60,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(payload, f)

    try:
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(path)],
            capture_output=True, timeout=5
        )
    except Exception:
        pass


class ScanWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            result = DiscoveryEngine(
                lambda a, b, c: self.progress.emit(a, b, c)
            ).run()
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ReleaseProbeWorker(QThread):
    done = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, repo_id, repo_data, profile, parent=None):
        super().__init__(parent)
        self.repo_id = repo_id
        self.repo_data = repo_data
        self.profile = profile

    def run(self):
        try:
            info = probe_release(self.repo_data, self.profile)
            self.done.emit(self.repo_id, info)
        except Exception as exc:
            self.failed.emit(self.repo_id, str(exc))


class TranslationWorker(QThread):
    done = Signal(int, str, str, str)
    failed = Signal(int, str)

    def __init__(self, repo_id, original, category, parent=None):
        super().__init__(parent)
        self.repo_id = repo_id
        self.original = original
        self.category = category

    def run(self):
        try:
            translated, source = translate_description(
                self.original, self.category
            )
            self.done.emit(
                self.repo_id, self.original, translated, source
            )
        except Exception as exc:
            self.failed.emit(self.repo_id, str(exc))


class InstallWorker(QThread):
    progress = Signal(int)
    done = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, repo_id, repo_data, release_info, parent=None):
        super().__init__(parent)
        self.repo_id = repo_id
        self.repo_data = repo_data
        self.release_info = release_info

    def run(self):
        try:
            result = install_release(
                self.repo_data,
                self.release_info,
                progress=lambda value: self.progress.emit(value),
            )
            self.done.emit(self.repo_id, result)
        except Exception as exc:
            self.failed.emit(self.repo_id, str(exc))


class SettingsDialog(QDialog):
    saved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = load_settings()
        self.lang = normalize_language(self.settings.get("language", "en"))

        self.setWindowTitle(tr(self.lang, "settings_title"))
        self.resize(700, 690)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 26)
        root.setSpacing(14)

        eyebrow = QLabel(tr(self.lang, "personal_radar"))
        eyebrow.setObjectName("eyebrow")
        root.addWidget(eyebrow)

        title = QLabel(tr(self.lang, "settings_heading"))
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        note = QLabel(tr(self.lang, "settings_note"))
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        self.interests = QPlainTextEdit()
        self.interests.setPlainText("\n".join(self.settings.get("interests", [])))
        self.interests.setPlaceholderText(tr(self.lang, "interests_placeholder"))
        root.addWidget(self.interests, 1)

        form = QFormLayout()
        form.setSpacing(12)

        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("한국어", "ko")
        idx = self.language.findData(self.lang)
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        form.addRow(tr(self.lang, "language"), self.language)

        self.hours = QSpinBox()
        self.hours.setRange(1, 24)
        self.hours.setSuffix(tr(self.lang, "hours_suffix"))
        self.hours.setValue(int(self.settings.get("auto_refresh_hours", 6)))
        form.addRow(tr(self.lang, "refresh_interval"), self.hours)

        self.score = QSpinBox()
        self.score.setRange(50, 100)
        self.score.setValue(int(self.settings.get("notify_score", 82)))
        form.addRow(tr(self.lang, "notification_score"), self.score)

        self.monitor = QCheckBox(tr(self.lang, "context_monitor"))
        self.monitor.setChecked(bool(self.settings.get("context_monitoring", True)))
        form.addRow("", self.monitor)

        self.login = QCheckBox(tr(self.lang, "start_login"))
        self.login.setChecked(bool(self.settings.get("start_at_login", True)))
        form.addRow("", self.login)

        install_row = QHBoxLayout()
        self.install_root = QLineEdit(
            os.path.expanduser(self.settings.get("install_root") or "~/Applications/H2S Tools")
        )
        browse = QPushButton(tr(self.lang, "browse"))
        browse.clicked.connect(self.choose_install_root)
        install_row.addWidget(self.install_root, 1)
        install_row.addWidget(browse)
        form.addRow(tr(self.lang, "install_location"), install_row)

        root.addLayout(form)

        privacy = QLabel(tr(self.lang, "privacy_settings"))
        privacy.setWordWrap(True)
        privacy.setObjectName("privacy")
        root.addWidget(privacy)

        row = QHBoxLayout()
        row.addStretch()

        cancel = QPushButton(tr(self.lang, "cancel"))
        save = QPushButton(tr(self.lang, "save"))
        save.setObjectName("primary")
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.do_save)

    def choose_install_root(self):
        selected = QFileDialog.getExistingDirectory(
            self,
            tr(self.lang, "choose_install_location"),
            self.install_root.text().strip() or str(Path.home() / "Applications"),
        )
        if selected:
            self.install_root.setText(selected)

    def do_save(self):
        vals = [x.strip() for x in self.interests.toPlainText().splitlines() if x.strip()]
        data = dict(self.settings)
        data.update({
            "interests": vals,
            "language": self.language.currentData(),
            "auto_refresh_hours": self.hours.value(),
            "notify_score": self.score.value(),
            "context_monitoring": self.monitor.isChecked(),
            "start_at_login": self.login.isChecked(),
            "install_root": os.path.expanduser(
                self.install_root.text().strip() or "~/Applications/H2S Tools"
            ),
        })
        save_settings(data)
        self.saved.emit(data)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_db()
        self.settings = load_settings()
        self.lang = normalize_language(self.settings.get("language", "en"))
        self.worker = None
        self.probe_worker = None
        self.install_worker = None
        self.translation_worker = None
        self.pending_translation = None
        self.translation_cooldown = {}
        self.translation_debounce = QTimer(self)
        self.translation_debounce.setSingleShot(True)
        self.translation_debounce.setInterval(120)
        self.translation_debounce.timeout.connect(self._launch_pending_translation)
        self.row_ids = {}
        self.repo_cache = {}
        self.pending_probe = None
        self.probe_cooldown = {}
        self.probe_debounce = QTimer(self)
        self.probe_debounce.setSingleShot(True)
        self.probe_debounce.setInterval(180)
        self.probe_debounce.timeout.connect(self._launch_pending_probe)
        self.mode = "all"
        self.category = ""
        self.profile = mac_profile()
        self.current_release_info = None
        self.current_assessment = None

        # Re-score cached rows so recommendation reasons always match the selected UI language.
        rescore_cached()

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1500, 920)
        self.setMinimumSize(1180, 720)

        self.build_ui()
        self.apply_style()
        self.setup_timers()
        self.setup_tray()
        self.load_items()

        QTimer.singleShot(700, self.sample_context)
        QTimer.singleShot(1400, self.auto_refresh_if_due)

    def t(self, key, **kwargs):
        return tr(self.lang, key, **kwargs)

    def section_label(self, text):
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def filter_title_subtitle(self, mode):
        title_key, sub_key = FILTER_KEYS.get(mode, FILTER_KEYS["all"])
        return self.t(title_key), self.t(sub_key)

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 22, 16, 18)
        sl.setSpacing(5)

        brand_row = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName("logo")
        pix = QPixmap(str(asset_path("h2s-radar-mark.png")))
        if not pix.isNull():
            logo.setPixmap(pix.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo.setText("H2S")
        brand_row.addWidget(logo)

        brand_text = QVBoxLayout()
        brand = QLabel("H2S LABS")
        brand.setObjectName("brand")
        product = QLabel("Open Source Radar")
        product.setObjectName("brandTitle")
        brand_text.addWidget(brand)
        brand_text.addWidget(product)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()
        sl.addLayout(brand_row)

        sub = QLabel(self.t("brand_tagline"))
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sl.addWidget(sub)
        sl.addSpacing(14)

        sl.addWidget(self.section_label(self.t("discover")))

        self.nav = []
        specs = [
            (self.t("nav_for_you"), "all", ""),
            (self.t("nav_trending"), "hot", ""),
            (self.t("nav_context"), "context", ""),
            (self.t("nav_new"), "new", ""),
            (self.t("nav_saved"), "favorite", ""),
        ]
        for label, mode, cat in specs:
            self.add_nav(sl, label, mode, cat)

        sl.addSpacing(12)
        sl.addWidget(self.section_label(self.t("categories")))

        for cat in CATEGORIES:
            self.add_nav(sl, category_name(self.lang, cat), "all", cat)

        self.nav[0].setChecked(True)
        sl.addStretch()

        context_card = QFrame()
        context_card.setObjectName("contextCard")
        cc = QVBoxLayout(context_card)
        cc.setContentsMargins(12, 11, 12, 11)
        cc.setSpacing(5)

        context_head = QHBoxLayout()
        dot = QLabel("●")
        dot.setObjectName("liveDot")
        cap = QLabel(self.t("live_context"))
        cap.setObjectName("sectionLabel")
        context_head.addWidget(dot)
        context_head.addWidget(cap)
        context_head.addStretch()
        cc.addLayout(context_head)

        self.context_side = QLabel(self.t("context_loading"))
        self.context_side.setObjectName("contextText")
        self.context_side.setWordWrap(True)
        cc.addWidget(self.context_side)

        privacy = QLabel(self.t("privacy_mini"))
        privacy.setObjectName("privacyMini")
        cc.addWidget(privacy)
        sl.addWidget(context_card)

        website = QPushButton("h2sstudio.com  ↗")
        website.setObjectName("website")
        website.clicked.connect(lambda: webbrowser.open(WEBSITE))
        sl.addWidget(website)

        settings = QPushButton(self.t("settings"))
        settings.setObjectName("nav")
        settings.clicked.connect(self.open_settings)
        sl.addWidget(settings)

        root.addWidget(side)

        # Main body
        body = QWidget()
        body.setObjectName("body")
        main = QVBoxLayout(body)
        main.setContentsMargins(28, 24, 28, 22)
        main.setSpacing(14)

        hero = QHBoxLayout()
        head = QVBoxLayout()

        eyebrow = QLabel(self.t("hero_eyebrow"))
        eyebrow.setObjectName("eyebrow")
        head.addWidget(eyebrow)

        first_title, first_sub = self.filter_title_subtitle("all")
        self.page_title = QLabel(first_title)
        self.page_title.setObjectName("pageTitle")
        head.addWidget(self.page_title)

        self.page_subtitle = QLabel(first_sub)
        self.page_subtitle.setObjectName("muted")
        head.addWidget(self.page_subtitle)
        hero.addLayout(head, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)

        top_actions = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t("search_placeholder"))
        self.search.setMinimumWidth(360)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.load_items)
        top_actions.addWidget(self.search)

        self.refresh_btn = QPushButton(self.t("refresh"))
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(lambda: self.refresh(False))
        top_actions.addWidget(self.refresh_btn)
        actions.addLayout(top_actions)

        self.status = QLabel(self.t("status_ready"))
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignRight)
        actions.addWidget(self.status)

        hero.addLayout(actions)
        main.addLayout(hero)

        # Stats
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.stats_labels = {}
        stat_specs = [
            ("new_count", "new_stat", "new_hint"),
            ("hot_count", "hot_stat", "hot_hint"),
            ("context_count", "context_stat", "context_hint"),
            ("favorite_count", "saved_stat", "saved_hint"),
        ]
        for key, label_key, hint_key in stat_specs:
            card = QFrame()
            card.setObjectName("statCard")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(15, 11, 15, 11)
            lay.setSpacing(1)

            top = QHBoxLayout()
            cap = QLabel(self.t(label_key))
            cap.setObjectName("statLabel")
            num = QLabel("0")
            num.setObjectName("stat")
            top.addWidget(cap)
            top.addStretch()
            top.addWidget(num)
            lay.addLayout(top)

            small = QLabel(self.t(hint_key))
            small.setObjectName("tiny")
            lay.addWidget(small)

            cards.addWidget(card)
            self.stats_labels[key] = num

        main.addLayout(cards)

        # Advanced filters
        filter_head = QHBoxLayout()
        self.advanced_toggle = QPushButton(self.t("advanced_filters"))
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setObjectName("filterToggle")
        filter_head.addWidget(self.advanced_toggle)
        filter_head.addStretch()

        machine = self.profile
        self.machine_summary = QLabel(
            f'{machine.get("cpu") or "Mac"} · {machine.get("arch")} · '
            f'macOS {machine.get("macos")} · '
            f'{format_bytes(machine.get("ram_bytes"))} RAM · '
            f'{format_bytes(machine.get("free_bytes"))} free'
        )
        self.machine_summary.setObjectName("tiny")
        filter_head.addWidget(self.machine_summary)
        main.addLayout(filter_head)

        self.advanced_panel = QFrame()
        self.advanced_panel.setObjectName("filterPanel")
        fp = QHBoxLayout(self.advanced_panel)
        fp.setContentsMargins(12, 10, 12, 10)
        fp.setSpacing(9)

        def add_filter(label_text, items):
            box = QVBoxLayout()
            cap = QLabel(label_text)
            cap.setObjectName("tiny")
            combo = QComboBox()
            for text_value, data_value in items:
                combo.addItem(text_value, data_value)
            box.addWidget(cap)
            box.addWidget(combo)
            fp.addLayout(box)
            return combo

        self.compat_filter = add_filter(
            self.t("filter_compatibility"),
            [
                (self.t("filter_all"), "all"),
                (self.t("filter_mac_ready"), "ready"),
                (self.t("filter_one_click"), "oneclick"),
                (self.t("filter_review"), "review"),
                (self.t("filter_incompatible"), "blocked"),
            ],
        )
        self.installed_filter = add_filter(
            self.t("filter_installed"),
            [
                (self.t("filter_all"), "all"),
                (self.t("filter_installed_yes"), "installed"),
                (self.t("filter_installed_no"), "not_installed"),
            ],
        )
        self.size_filter = add_filter(
            self.t("filter_size"),
            [
                (self.t("filter_all"), "all"),
                ("< 500 MB", "lt500"),
                ("< 2 GB", "lt2g"),
                ("< 5 GB", "lt5g"),
                ("≥ 5 GB", "gte5g"),
            ],
        )
        self.license_filter = add_filter(
            self.t("filter_license"),
            [
                (self.t("filter_all"), "all"),
                (self.t("filter_permissive"), "permissive"),
                (self.t("filter_copyleft"), "copyleft"),
                (self.t("filter_declared"), "declared"),
                (self.t("filter_undeclared"), "undeclared"),
            ],
        )
        self.updated_filter = add_filter(
            self.t("filter_updated"),
            [
                (self.t("filter_all"), "all"),
                (self.t("filter_30_days"), "30"),
                (self.t("filter_90_days"), "90"),
                (self.t("filter_1_year"), "365"),
            ],
        )

        stars_box = QVBoxLayout()
        stars_cap = QLabel(self.t("filter_min_stars"))
        stars_cap.setObjectName("tiny")
        self.min_stars_filter = QSpinBox()
        self.min_stars_filter.setRange(0, 10000000)
        self.min_stars_filter.setSingleStep(100)
        self.min_stars_filter.setSpecialValueText(self.t("filter_any"))
        stars_box.addWidget(stars_cap)
        stars_box.addWidget(self.min_stars_filter)
        fp.addLayout(stars_box)

        reset_filters = QPushButton(self.t("filter_reset"))
        reset_filters.clicked.connect(self.reset_advanced_filters)
        fp.addWidget(reset_filters)
        fp.addStretch()

        for combo in [
            self.compat_filter, self.installed_filter, self.size_filter,
            self.license_filter, self.updated_filter,
        ]:
            combo.currentIndexChanged.connect(self.load_items)
        self.min_stars_filter.valueChanged.connect(self.load_items)

        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        main.addWidget(self.advanced_panel)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        main.addWidget(self.progress)

        # Table
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            self.t("score"), self.t("project"), self.t("mac_status"),
            self.t("installed_col"), self.t("install_size"), self.t("category"),
            self.t("stars"), self.t("language_col"), self.t("updated"), self.t("why")
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)

        hh = self.table.horizontalHeader()
        for i in [0, 2, 3, 4, 5, 6, 7, 8]:
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(9, QHeaderView.Stretch)

        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.itemDoubleClicked.connect(self.open_selected)
        main.addWidget(self.table, 1)

        # Detail
        detail = QFrame()
        detail.setObjectName("detail")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(18, 14, 18, 14)
        dl.setSpacing(7)

        meta_row = QHBoxLayout()
        self.detail_meta = QLabel(self.t("select_project"))
        self.detail_meta.setObjectName("tiny")
        meta_row.addWidget(self.detail_meta)
        meta_row.addStretch()

        self.mac_badge = QLabel("—")
        self.mac_badge.setObjectName("macBadge")
        meta_row.addWidget(self.mac_badge)

        self.score_badge = QLabel("—")
        self.score_badge.setObjectName("scoreBadge")
        meta_row.addWidget(self.score_badge)
        dl.addLayout(meta_row)

        self.detail_title = QLabel(self.t("select_recommendation"))
        self.detail_title.setObjectName("detailTitle")
        self.detail_title.setWordWrap(True)
        dl.addWidget(self.detail_title)

        self.detail = QTextBrowser()
        self.detail.setMaximumHeight(112)
        self.detail.setOpenExternalLinks(True)
        dl.addWidget(self.detail)

        self.install_info = QLabel(self.t("install_info_waiting"))
        self.install_info.setObjectName("installInfo")
        self.install_info.setWordWrap(True)
        dl.addWidget(self.install_info)

        ar = QHBoxLayout()
        self.install_btn = QPushButton(self.t("install_checking"))
        self.install_btn.setObjectName("installPrimary")
        self.install_btn.setEnabled(False)
        self.guide_btn = QPushButton(self.t("quick_start_button"))
        self.guide_btn.hide()
        self.open_btn = QPushButton(self.t("open_github"))
        self.open_btn.setObjectName("primary")
        self.save_btn = QPushButton(self.t("save_button"))
        self.hide_btn = QPushButton(self.t("hide"))
        ar.addWidget(self.install_btn)
        ar.addWidget(self.guide_btn)
        ar.addWidget(self.open_btn)
        ar.addWidget(self.save_btn)
        ar.addWidget(self.hide_btn)
        ar.addStretch()

        footer = QLabel(f"v{APP_VERSION}  ·  H2S Labs  ·  {self.t('footer_privacy')}")
        footer.setObjectName("tiny")
        ar.addWidget(footer)
        dl.addLayout(ar)

        self.install_btn.clicked.connect(self.install_or_open)
        self.guide_btn.clicked.connect(self.show_quick_start)
        self.open_btn.clicked.connect(self.open_selected)
        self.save_btn.clicked.connect(self.toggle_save)
        self.hide_btn.clicked.connect(self.hide_selected)

        main.addWidget(detail)
        root.addWidget(body, 1)

    def add_nav(self, layout, label, mode, cat):
        button = QPushButton(label)
        button.setObjectName("nav")
        button.setCheckable(True)
        button.clicked.connect(
            lambda checked, m=mode, c=cat, b=button: self.set_filter(m, c, b)
        )
        layout.addWidget(button)
        self.nav.append(button)

    def set_filter(self, mode, cat, button):
        self.mode = mode
        self.category = cat
        for b in self.nav:
            b.setChecked(b is button)

        if cat:
            self.page_title.setText(category_name(self.lang, cat))
            self.page_subtitle.setText(self.t("category_sub"))
        else:
            title, sub = self.filter_title_subtitle(mode)
            self.page_title.setText(title)
            self.page_subtitle.setText(sub)
        self.load_items()

    def reset_advanced_filters(self):
        for combo in [
            self.compat_filter, self.installed_filter, self.size_filter,
            self.license_filter, self.updated_filter,
        ]:
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.min_stars_filter.blockSignals(True)
        self.min_stars_filter.setValue(0)
        self.min_stars_filter.blockSignals(False)
        self.load_items()

    def compatibility_label(self, assessment):
        status = assessment.get("status")
        if status == "ready":
            return self.t("mac_ready_short")
        if status == "blocked":
            return self.t("mac_blocked_short")
        return self.t("mac_review_short")

    def _passes_advanced_filters(self, data, assessment):
        compat = self.compat_filter.currentData()
        if compat == "oneclick" and not assessment.get("one_click_ready"):
            return False
        if compat not in {"all", "oneclick"} and assessment.get("status") != compat:
            return False

        installed = self.installed_filter.currentData()
        if installed == "installed" and not assessment.get("installed"):
            return False
        if installed == "not_installed" and assessment.get("installed"):
            return False

        estimate = int(assessment.get("estimated_bytes") or 0)
        size_mode = self.size_filter.currentData()
        if size_mode == "lt500" and estimate >= 500 * 1024**2:
            return False
        if size_mode == "lt2g" and estimate >= 2 * 1024**3:
            return False
        if size_mode == "lt5g" and estimate >= 5 * 1024**3:
            return False
        if size_mode == "gte5g" and estimate < 5 * 1024**3:
            return False

        group = assessment.get("license_group")
        license_mode = self.license_filter.currentData()
        if license_mode == "declared" and group == "undeclared":
            return False
        if license_mode in {"permissive", "copyleft", "undeclared"} and group != license_mode:
            return False

        if int(data.get("stars") or 0) < int(self.min_stars_filter.value()):
            return False

        updated_mode = self.updated_filter.currentData()
        if updated_mode != "all":
            try:
                pushed = datetime.fromisoformat(
                    (data.get("pushed_at") or "").replace("Z", "+00:00")
                )
                age = (datetime.now(timezone.utc) - pushed).days
                if age > int(updated_mode):
                    return False
            except Exception:
                return False

        return True

    def load_items(self):
        previous_id = self.current_id()
        raw_rows = query_repos(
            self.category, self.mode, self.search.text().strip(), limit=500
        )

        rows = []
        for data in raw_rows:
            assessment = assess_repo(data, self.profile)
            if self._passes_advanced_filters(data, assessment):
                rows.append((data, assessment))

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rows))
            self.row_ids = {}
            self.repo_cache = {}

            for row_index, (data, assessment) in enumerate(rows):
                repo_id = data["id"]
                self.row_ids[row_index] = repo_id
                self.repo_cache[repo_id] = data
                project = data["full_name"]
                if data["is_new"]:
                    project = "✦ " + project
                if data["favorite"]:
                    project = "★ " + project

                mac_text = self.compatibility_label(assessment)
                installed_text = (
                    self.t("installed_yes_short")
                    if assessment.get("installed")
                    else self.t("installed_no_short")
                )
                if int(data.get("installed_size") or 0) > 0:
                    size_text = format_bytes(data.get("installed_size"))
                else:
                    size_text = f'≈ {format_bytes(assessment.get("estimated_bytes"))}+'

                vals = [
                    str(data["score"]),
                    project,
                    mac_text,
                    installed_text,
                    size_text,
                    category_name(self.lang, data["category"]),
                    f'{int(data["stars"] or 0):,}',
                    data["language"] or "—",
                    (data["pushed_at"] or "")[:10],
                    data["why"] or self.t("interest_based"),
                ]
                for col, value in enumerate(vals):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, repo_id)
                    if col in {0, 2, 3, 4}:
                        item.setTextAlignment(Qt.AlignCenter)
                    if col == 2:
                        item.setToolTip(assessment.get("reason") or "")
                    if col == 3 and assessment.get("installed_path"):
                        item.setToolTip(assessment.get("installed_path"))
                    if col == 4:
                        item.setToolTip(self.t("size_estimate_tooltip"))
                    self.table.setItem(row_index, col, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        current_stats = stats()
        for key, label in self.stats_labels.items():
            label.setText(str(current_stats.get(key, 0)))

        if rows:
            selected = False
            if previous_id:
                selected = self.select_repo_id(previous_id)
            if not selected:
                self.table.selectRow(0)
        else:
            self.detail_meta.setText(self.t("no_results_meta"))
            self.detail_title.setText(self.t("no_results"))
            self.score_badge.setText("—")
            self.mac_badge.setText("—")
            self.install_info.setText(self.t("install_info_waiting"))
            self.install_btn.setEnabled(False)
            self.install_btn.setText(self.t("install_unavailable"))
            self.guide_btn.hide()
            self.detail.clear()

    def current_id(self):
        return self.row_ids.get(self.table.currentRow())

    def _cached_release_info(self, data):
        if not data.get("release_checked_at"):
            return None
        return {
            "compatible": bool(data.get("release_compatible")),
            "release_name": data.get("release_name") or "",
            "tag_name": data.get("release_name") or "",
            "asset_name": data.get("release_asset_name") or "",
            "asset_url": data.get("release_asset_url") or "",
            "asset_size": int(data.get("release_asset_size") or 0),
            "install_method": data.get("release_install_method") or "",
            "reason": data.get("release_reason") or "",
        }

    def _release_check_is_fresh(self, data, hours=12):
        value = data.get("release_checked_at") or ""
        if not value:
            return False
        try:
            checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - checked).total_seconds() < hours * 3600
        except Exception:
            return False

    def show_selected(self):
        repo_id = self.current_id()
        if not repo_id:
            return
        data = self.repo_cache.get(repo_id) or repo_by_id(repo_id)
        if not data:
            return

        if data.get("is_new"):
            mark_read(repo_id)
            data["is_new"] = 0
            self.repo_cache[repo_id] = data
        assessment = assess_repo(data, self.profile)
        self.current_assessment = assessment
        self.current_release_info = None
        self.guide_btn.setVisible(bool(assessment.get("installed")))

        license_text = data["license"] or self.t("license_missing")
        language_text = data["language"] or self.t("language_missing")
        self.detail_meta.setText(
            f'{category_name(self.lang, data["category"])}  ·  {language_text}  ·  '
            f'{license_text}  ·  ★ {int(data["stars"] or 0):,}'
        )
        self.score_badge.setText(f'{data["score"]}/100')
        self.mac_badge.setText(self.compatibility_label(assessment))
        self.detail_title.setText(data["full_name"])

        topics = " · ".join((data.get("topics") or [])[:10])
        why = html.escape(data["why"] or self.t("interest_based"))
        original_desc = data["description"] or self.t("description_missing")
        desc_text = original_desc
        translation_note = ""

        if self.lang == "ko" and data.get("description"):
            cached_ko = (data.get("description_ko") or "").strip()
            cached_original = data.get("description_ko_original") or ""
            if (
                cached_ko
                and cached_original == data["description"]
                and data.get("description_ko_source") == TRANSLATION_SOURCE
            ):
                desc_text = cached_ko
                translation_note = self.t("translated_description")
            else:
                desc_text = self.t("translation_pending")
                translation_note = self.t("translation_pending_note")
                self.queue_description_translation(repo_id, data)

        desc = html.escape(desc_text)
        topics_html = html.escape(topics)
        compat_reason = html.escape(assessment.get("reason") or "")
        translation_html = (
            f'<br><span style="color:#6F829F;font-size:10px">'
            f'{html.escape(translation_note)}</span>'
            if translation_note else ""
        )
        self.detail.setHtml(
            f'<b style="color:#DCE6FF">{html.escape(self.t("why_it_fits"))}</b>  {why}'
            f'<br><span style="color:#BAC6D8">{desc}</span>'
            f'{translation_html}'
            f'<br><span style="color:#78A7FF">{html.escape(self.t("mac_check"))}: '
            f'{compat_reason}</span>'
            f'<br><span style="color:#77849A">{topics_html}</span>'
        )

        install_bits = [
            self.t(
                "estimated_usage",
                size=format_bytes(assessment.get("estimated_bytes")),
            ),
            self.t(
                "free_space",
                size=format_bytes(assessment.get("free_bytes")),
            ),
        ]
        if assessment.get("release_size"):
            install_bits.insert(
                0,
                self.t(
                    "download_size",
                    size=format_bytes(assessment.get("release_size")),
                ),
            )
        if assessment.get("installed_path"):
            install_bits.append(
                self.t("installed_path", path=assessment.get("installed_path"))
            )
        else:
            install_bits.append(
                self.t(
                    "install_destination",
                    path=os.path.expanduser(
                        self.settings.get("install_root") or "~/Applications/H2S Tools"
                    ),
                )
            )
        self.install_info.setText("  ·  ".join(install_bits))

        self.save_btn.setText(
            self.t("saved_button") if data["favorite"] else self.t("save_button")
        )

        if assessment.get("installed") and assessment.get("installed_path"):
            self.install_btn.setEnabled(True)
            self.install_btn.setText(self.t("open_installed"))
            self.install_btn.setToolTip(assessment.get("installed_path"))
            return

        if assessment.get("status") == "blocked":
            self.install_btn.setEnabled(False)
            self.install_btn.setText(self.t("install_incompatible"))
            self.install_btn.setToolTip(assessment.get("reason") or "")
            return

        cached = self._cached_release_info(data)
        if cached and cached.get("compatible") and cached.get("asset_url"):
            self.current_release_info = cached
            self.install_btn.setEnabled(True)
            self.install_btn.setText(
                self.t(
                    "easy_install",
                    size=format_bytes(cached.get("asset_size")),
                )
            )
            self.install_btn.setToolTip(cached.get("asset_name") or "")
            return

        if cached and self._release_check_is_fresh(data):
            self.install_btn.setEnabled(False)
            self.install_btn.setText(self.t("install_unavailable"))
            self.install_btn.setToolTip(cached.get("reason") or "")
            return

        self.install_btn.setEnabled(False)
        self.install_btn.setText(self.t("install_checking"))
        self.install_btn.setToolTip(self.t("install_checking_tip"))
        self.queue_release_probe(repo_id, data)

    def queue_description_translation(self, repo_id, data):
        if self.lang != "ko":
            return
        original = (data.get("description") or "").strip()
        if not original:
            return
        cooldown = float(self.translation_cooldown.get(repo_id, 0) or 0)
        if cooldown > time.time():
            return
        self.pending_translation = (
            repo_id,
            original,
            data.get("category") or "",
        )
        self.translation_debounce.start()

    def _launch_pending_translation(self):
        if not self.pending_translation:
            return
        repo_id, original, category = self.pending_translation
        if self.current_id() != repo_id or self.lang != "ko":
            self.pending_translation = None
            return
        if self.translation_worker and self.translation_worker.isRunning():
            return

        self.pending_translation = None
        self.translation_worker = TranslationWorker(
            repo_id, original, category, self
        )
        self.translation_worker.done.connect(self.translation_done)
        self.translation_worker.failed.connect(self.translation_failed)
        self.translation_worker.start()

    def _continue_pending_translation(self):
        if not self.pending_translation:
            return
        if (
            self.current_id() == self.pending_translation[0]
            and self.lang == "ko"
        ):
            self.translation_debounce.start(60)
        else:
            self.pending_translation = None

    def translation_done(self, repo_id, original, translated, source):
        update_description_translation(
            repo_id, original, translated, source
        )
        fresh = repo_by_id(repo_id)
        if fresh:
            self.repo_cache[repo_id] = fresh
        if self.current_id() == repo_id and self.lang == "ko":
            self.show_selected()
        QTimer.singleShot(0, self._continue_pending_translation)

    def translation_failed(self, repo_id, message):
        self.translation_cooldown[repo_id] = time.time() + 120
        if self.current_id() == repo_id and self.lang == "ko":
            data = self.repo_cache.get(repo_id) or repo_by_id(repo_id)
            if data:
                # Fall back to the original description instead of leaving a
                # permanent loading message when translation is unavailable.
                original = html.escape(
                    data.get("description") or self.t("description_missing")
                )
                self.detail.setHtml(
                    f'<b style="color:#DCE6FF">{html.escape(self.t("why_it_fits"))}</b>  '
                    f'{html.escape(data.get("why") or self.t("interest_based"))}'
                    f'<br><span style="color:#BAC6D8">{original}</span>'
                    f'<br><span style="color:#A07A7A;font-size:10px">'
                    f'{html.escape(self.t("translation_failed_short"))}</span>'
                )
        QTimer.singleShot(0, self._continue_pending_translation)

    def queue_release_probe(self, repo_id, data):
        cooldown = float(self.probe_cooldown.get(repo_id, 0) or 0)
        if cooldown > time.time():
            self.install_btn.setEnabled(False)
            self.install_btn.setText(self.t("install_unavailable"))
            return
        self.pending_probe = (repo_id, dict(data))
        self.probe_debounce.start()

    def _launch_pending_probe(self):
        if not self.pending_probe:
            return
        repo_id, data = self.pending_probe
        if self.current_id() != repo_id:
            self.pending_probe = None
            return
        if self.probe_worker and self.probe_worker.isRunning():
            return
        self.pending_probe = None
        self.probe_worker = ReleaseProbeWorker(
            repo_id, data, dict(self.profile), self
        )
        self.probe_worker.done.connect(self.release_probe_done)
        self.probe_worker.failed.connect(self.release_probe_failed)
        self.probe_worker.start()

    def _continue_pending_probe(self):
        if not self.pending_probe:
            return
        if self.current_id() == self.pending_probe[0]:
            self.probe_debounce.start(80)
        else:
            self.pending_probe = None

    def release_probe_done(self, repo_id, info):
        reason = (info.get("reason") or "").lower()
        if "rate limit" in reason:
            self.probe_cooldown[repo_id] = time.time() + 300
        else:
            update_release_info(repo_id, info)
            fresh = repo_by_id(repo_id)
            if fresh:
                self.repo_cache[repo_id] = fresh

        if self.current_id() == repo_id:
            # Update only the detail pane. Rebuilding all 200+ table rows here
            # caused the visible click lag.
            self.show_selected()

        QTimer.singleShot(0, self._continue_pending_probe)

    def release_probe_failed(self, repo_id, message):
        self.probe_cooldown[repo_id] = time.time() + 180
        if self.current_id() == repo_id:
            self.install_btn.setEnabled(False)
            self.install_btn.setText(self.t("install_unavailable"))
            self.install_btn.setToolTip(message)
        QTimer.singleShot(0, self._continue_pending_probe)

    def select_repo_id(self, repo_id):
        for row, value in self.row_ids.items():
            if value == repo_id:
                self.table.selectRow(row)
                return True
        return False

    def install_or_open(self):
        repo_id = self.current_id()
        if not repo_id:
            return
        data = repo_by_id(repo_id)
        if not data:
            return
        assessment = assess_repo(data, self.profile)

        if assessment.get("installed") and assessment.get("installed_path"):
            path = assessment.get("installed_path")
            subprocess.Popen(["/usr/bin/open", path])
            return

        release_info = self.current_release_info or self._cached_release_info(data)
        if (
            assessment.get("status") == "blocked"
            or not release_info
            or not release_info.get("compatible")
            or not release_info.get("asset_url")
        ):
            return

        self.install_btn.setEnabled(False)
        self.install_btn.setText(self.t("installing"))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()

        self.install_worker = InstallWorker(
            repo_id, data, release_info, self
        )
        self.install_worker.progress.connect(self.install_progress)
        self.install_worker.done.connect(self.install_done)
        self.install_worker.failed.connect(self.install_failed)
        self.install_worker.start()

    def install_progress(self, value):
        self.progress.setValue(int(value))
        self.status.setText(self.t("install_progress", percent=int(value)))

    def install_done(self, repo_id, result):
        self.progress.hide()
        if result.get("pending_system_installer"):
            self.status.setText(self.t("system_installer_opened"))
            self.install_btn.setText(self.t("finish_system_installer"))
            self.install_btn.setEnabled(False)
            return

        path = result.get("path") or ""
        set_managed_install(
            repo_id,
            path,
            result.get("version") or "",
            result.get("bytes") or 0,
        )
        self.profile = mac_profile()
        self.status.setText(
            self.t(
                "install_complete",
                size=format_bytes(result.get("bytes")),
            )
        )
        self.load_items()
        self.select_repo_id(repo_id)
        self.show_selected()
        QTimer.singleShot(250, self.show_quick_start)

    def install_failed(self, repo_id, message):
        self.progress.hide()
        self.status.setText(self.t("install_failed"))
        self.install_btn.setEnabled(True)
        self.install_btn.setText(self.t("easy_install", size=""))
        QMessageBox.warning(
            self,
            self.t("install_failed"),
            message,
        )

    def show_quick_start(self):
        repo_id = self.current_id()
        if not repo_id:
            return
        data = repo_by_id(repo_id)
        if not data:
            return
        key = {
            "작곡·음악 생성": "quick_start_music",
            "DAW 자동화": "quick_start_daw",
            "Audio→MIDI·채보": "quick_start_midi",
            "Stem·오디오 분리": "quick_start_stem",
            "보컬·가창 합성": "quick_start_vocal",
            "Agent·MCP": "quick_start_agent",
            "로컬 LLM": "quick_start_agent",
        }.get(data.get("category"), "quick_start_generic")
        QMessageBox.information(
            self,
            self.t("quick_start_title"),
            f'{data.get("name") or data.get("full_name")}\n\n{self.t(key)}',
        )

    def open_selected(self, *_):
        repo_id = self.current_id()
        if repo_id:
            data = repo_by_id(repo_id)
            if data:
                webbrowser.open(data["html_url"])

    def toggle_save(self):
        repo_id = self.current_id()
        if not repo_id:
            return
        data = repo_by_id(repo_id)
        set_favorite(repo_id, not bool(data["favorite"]))
        self.load_items()

    def hide_selected(self):
        repo_id = self.current_id()
        if repo_id:
            set_hidden(repo_id, True)
            self.load_items()

    def auto_refresh_if_due(self):
        last = float(self.settings.get("last_scan_epoch", 0) or 0)
        hours = max(1, int(self.settings.get("auto_refresh_hours", 6)))
        remaining = hours * 3600 - (time.time() - last)
        if remaining <= 0:
            self.refresh(True)
        else:
            minutes = max(1, int(remaining / 60))
            self.status.setText(self.t("using_cache", minutes=minutes))

    def refresh(self, silent=False):
        if self.worker and self.worker.isRunning():
            return
        self.worker = ScanWorker(self)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(lambda x: self.on_done(x, silent))
        self.worker.failed.connect(self.on_failed)
        self.progress.setRange(0, 6)
        self.progress.setValue(0)
        self.progress.show()
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText(self.t("scanning"))
        self.worker.start()

    def on_progress(self, current, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.status.setText(
            self.t("scan_progress", current=current, total=total, message=message)
        )

    def on_done(self, result, silent):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText(self.t("refresh"))

        errors = result.get("errors") or []
        status = self.t(
            "scan_done",
            found=result.get("found", 0),
            new=result.get("new", 0),
        )
        if errors:
            status += self.t("warning_count", count=len(errors))
        self.status.setText(status)

        if int(result.get("found", 0) or 0) > 0:
            self.settings["last_scan_epoch"] = time.time()
            save_settings(self.settings)

        rescore_cached()
        self.load_items()

        top = result.get("top_new") or []
        if top:
            first = top[0]
            self.notify(
                self.t("new_notification"),
                f'{first["name"]} · {self.t("recommendation", score=first["score"])} · {first["why"]}'
            )

        if errors and not silent:
            QMessageBox.warning(
                self, self.t("scan_warning_title"), "\n".join(errors[:3])
            )

    def on_failed(self, message):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText(self.t("refresh"))
        self.status.setText(self.t("scan_failed"))
        QMessageBox.warning(self, APP_NAME, message)

    def notify(self, title, message):
        try:
            title = title.replace('"', "'")
            message = message.replace('"', "'")
            subprocess.run(
                [
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}"'
                ],
                timeout=4
            )
        except Exception:
            pass

    def sample_context(self):
        if not self.settings.get("context_monitoring", True):
            self.context_side.setText(self.t("context_off"))
            return
        name = sample_activity()
        self.context_side.setText(name or self.t("context_none"))

    def scan_files(self):
        if self.settings.get("context_monitoring", True):
            scan_recent_project_signals()
            rescore_cached()
            if self.mode == "context":
                self.load_items()

    def setup_timers(self):
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.sample_context)
        self.activity_timer.start(60 * 1000)

        self.file_timer = QTimer(self)
        self.file_timer.timeout.connect(self.scan_files)
        self.file_timer.start(10 * 60 * 1000)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(lambda: self.refresh(True))
        self.refresh_timer.start(
            max(1, int(self.settings.get("auto_refresh_hours", 6))) * 60 * 60 * 1000
        )

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.saved.connect(self.settings_saved)
        dialog.exec()

    def settings_saved(self, data):
        old_lang = self.lang
        self.settings = data
        self.lang = normalize_language(data.get("language", "en"))

        self.refresh_timer.start(
            max(1, int(data.get("auto_refresh_hours", 6))) * 60 * 60 * 1000
        )
        sync_login_item(bool(data.get("start_at_login", True)))

        rescore_cached()

        if self.lang != old_lang:
            QTimer.singleShot(200, self.restart_app)
            return

        self.sample_context()
        self.load_items()
        self.status.setText(self.t("preferences_saved"))

    def restart_app(self):
        try:
            if getattr(sys, "frozen", False):
                bundle = Path(sys.executable).resolve().parents[2]
                subprocess.Popen(["/usr/bin/open", "-n", str(bundle)])
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
        finally:
            QApplication.quit()

    def setup_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)

        menu = QMenu()
        show = QAction(self.t("tray_open"), self)
        refresh = QAction(self.t("tray_refresh"), self)
        site = QAction(self.t("tray_site"), self)
        quit_action = QAction(self.t("tray_quit"), self)

        show.triggered.connect(self.show_normal)
        refresh.triggered.connect(lambda: self.refresh(False))
        site.triggered.connect(lambda: webbrowser.open(WEBSITE))
        quit_action.triggered.connect(QApplication.quit)

        menu.addAction(show)
        menu.addAction(refresh)
        menu.addAction(site)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_normal()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()

    def show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage(
            APP_NAME,
            self.t("background_message"),
            QSystemTrayIcon.Information,
            1800,
        )

    def apply_style(self):
        self.setStyleSheet("""
        QWidget {
            font-size: 13px;
            color: #EAF0FA;
            background: #0A0F17;
        }
        #sidebar {
            background: #0D141F;
            border-right: 1px solid #1C2838;
        }
        #body { background: #0A0F17; }
        #logo { background: transparent; }
        #brand {
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 1.4px;
            color: #7E9BFF;
        }
        #brandTitle {
            font-size: 17px;
            font-weight: 760;
            color: #F2F6FD;
        }
        #eyebrow, #sectionLabel {
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 1.2px;
            color: #6E7C91;
        }
        #pageTitle {
            font-size: 31px;
            font-weight: 800;
            color: #F6F8FC;
        }
        #dialogTitle {
            font-size: 23px;
            font-weight: 800;
        }
        #muted { color: #8491A6; }
        #status {
            color: #6F7F96;
            font-size: 11px;
        }
        #tiny {
            color: #748198;
            font-size: 10px;
        }
        #contextCard {
            background: #121B29;
            border: 1px solid #223149;
            border-radius: 12px;
        }
        #filterPanel {
            background: #0F1824;
            border: 1px solid #203047;
            border-radius: 11px;
        }
        QPushButton#filterToggle {
            background: transparent;
            border: 1px solid #27364C;
            color: #9AA8BC;
            padding: 6px 10px;
        }
        QPushButton#filterToggle:checked {
            background: #16263F;
            color: #DDE7F8;
            border-color: #385780;
        }
        #liveDot {
            color: #67D8A5;
            font-size: 10px;
        }
        #contextText {
            color: #C6D1E1;
            font-size: 11px;
        }
        #privacyMini {
            color: #66768E;
            font-size: 9px;
        }
        QPushButton {
            background: #151F2E;
            border: 1px solid #293950;
            border-radius: 8px;
            padding: 8px 11px;
        }
        QPushButton:hover {
            background: #1B293C;
            border-color: #36506F;
        }
        QPushButton:checked {
            background: #1D3155;
            border-color: #365E9F;
        }
        QPushButton#nav {
            text-align: left;
            border: none;
            background: transparent;
            color: #A8B4C6;
            padding: 7px 9px;
        }
        QPushButton#nav:hover {
            background: #141F2F;
            color: #E9EEF7;
        }
        QPushButton#nav:checked {
            background: #1A2C4D;
            color: #FFFFFF;
        }
        QPushButton#primary {
            background: #5B78F6;
            border-color: #6B87FF;
            color: white;
            font-weight: 760;
        }
        QPushButton#primary:hover { background: #6985FA; }
        QPushButton#installPrimary {
            background: #356CE8;
            border-color: #5485F2;
            color: white;
            font-weight: 800;
        }
        QPushButton#installPrimary:hover {
            background: #477CF0;
        }
        QPushButton#installPrimary:disabled {
            background: #172131;
            border-color: #27364C;
            color: #66768D;
        }
        QPushButton#website {
            text-align: left;
            border: 1px solid #223149;
            background: #111A27;
            color: #8AA5FF;
        }
        QLineEdit, QPlainTextEdit, QComboBox {
            background: #101824;
            border: 1px solid #27364C;
            border-radius: 9px;
            padding: 8px;
            selection-background-color: #536FE8;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border-color: #5878D9;
        }
        QTableWidget {
            background: #0D141E;
            alternate-background-color: #101923;
            border: 1px solid #1D2A3B;
            border-radius: 12px;
            outline: none;
        }
        QTableWidget::item {
            padding: 7px;
            border-bottom: 1px solid #162131;
        }
        QTableWidget::item:selected {
            background: #1E365F;
            color: #FFFFFF;
        }
        QHeaderView::section {
            background: #111A26;
            color: #718198;
            font-size: 10px;
            font-weight: 800;
            padding: 9px;
            border: none;
            border-bottom: 1px solid #253349;
        }
        #statCard {
            background: #101824;
            border: 1px solid #1E2C40;
            border-radius: 11px;
        }
        #statLabel {
            color: #8997AB;
            font-size: 11px;
            font-weight: 650;
        }
        #stat {
            font-size: 22px;
            font-weight: 820;
            color: #F2F5FB;
        }
        #detail {
            background: #101824;
            border: 1px solid #223047;
            border-radius: 12px;
        }
        #detailTitle {
            font-size: 17px;
            font-weight: 780;
            color: #F1F5FB;
        }
        #scoreBadge {
            background: #1E3155;
            border: 1px solid #365E9F;
            border-radius: 9px;
            padding: 4px 8px;
            color: #BDD0FF;
            font-weight: 800;
        }
        #macBadge {
            background: #132B27;
            border: 1px solid #245B4C;
            border-radius: 9px;
            padding: 4px 8px;
            color: #8FE1C4;
            font-weight: 750;
        }
        #installInfo {
            color: #8FA0B7;
            font-size: 10px;
            background: #0D1520;
            border: 1px solid #1D2B3E;
            border-radius: 8px;
            padding: 7px 9px;
        }
        QTextBrowser {
            background: transparent;
            border: none;
            color: #C9D3E2;
        }
        #privacy {
            background: #111C29;
            border: 1px solid #29405E;
            border-radius: 10px;
            padding: 12px;
            color: #AFC4DE;
        }
        QProgressBar {
            border: none;
            background: #141D2A;
        }
        QProgressBar::chunk { background: #6380F7; }
        QSpinBox {
            background: #101824;
            border: 1px solid #27364C;
            border-radius: 7px;
            padding: 5px;
        }
        QMenu {
            background: #111A26;
            border: 1px solid #26364B;
        }
        QMenu::item:selected { background: #1E365F; }
        """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    background = "--background" in sys.argv
    allow_reopen = {"value": not background}

    def on_state(state):
        if (
            state == Qt.ApplicationActive
            and allow_reopen["value"]
            and not window.isVisible()
        ):
            window.show_normal()

    app.applicationStateChanged.connect(on_state)

    if background:
        QTimer.singleShot(2500, lambda: allow_reopen.__setitem__("value", True))
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
