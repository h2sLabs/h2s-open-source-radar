import sys
import subprocess
import webbrowser
import plistlib
import os
import time
import html
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QTextBrowser, QDialog, QFormLayout, QSpinBox, QCheckBox,
    QPlainTextEdit, QMessageBox, QSystemTrayIcon, QMenu, QProgressBar
)
from PySide6.QtGui import QAction, QIcon, QPixmap

from db import (
    init_db, load_settings, save_settings, query_repos, repo_by_id, mark_read,
    set_favorite, set_hidden, stats
)
from engine import (
    DiscoveryEngine, sample_activity, scan_recent_project_signals, rescore_cached
)

APP_NAME = "H2S Open Source Radar"
APP_VERSION = "0.1.0"
WEBSITE = "https://h2sstudio.com"
CATEGORIES = [
    "작곡·음악 생성", "DAW 자동화", "Audio→MIDI·채보", "Stem·오디오 분리",
    "보컬·가창 합성", "Agent·MCP", "로컬 LLM", "영상·이미지 AI",
    "3D·비전", "기타 AI"
]

FILTER_TITLES = {
    ("all", ""): ("For You", "인기·신선도·관심분야·현재 작업 맥락을 함께 반영한 추천입니다."),
    ("hot", ""): ("Trending", "추천 점수와 최근 활동성이 높은 프로젝트를 모았습니다."),
    ("context", ""): ("In Your Flow", "지금 Mac에서 실행 중인 작업과 연관성이 높은 프로젝트입니다."),
    ("new", ""): ("New Discoveries", "아직 확인하지 않은 새 프로젝트입니다."),
    ("favorite", ""): ("Saved", "나중에 다시 볼 프로젝트를 모아둡니다."),
}


def asset_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def app_icon():
    p = asset_path("h2s-radar.png")
    return QIcon(str(p)) if p.exists() else QIcon()


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


class SettingsDialog(QDialog):
    saved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = load_settings()
        self.setWindowTitle("Open Source Radar 설정")
        self.resize(690, 650)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 26)
        root.setSpacing(14)

        eyebrow = QLabel("PERSONAL RADAR")
        eyebrow.setObjectName("eyebrow")
        root.addWidget(eyebrow)

        title = QLabel("관심분야와 자동 추천")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        note = QLabel(
            "한 줄에 하나씩 관심분야를 적어주세요. 입력값은 단순 필터가 아니라 "
            "GitHub 검색 쿼리와 추천 점수에 실제로 반영됩니다."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        self.interests = QPlainTextEdit()
        self.interests.setPlainText("\n".join(self.settings.get("interests", [])))
        self.interests.setPlaceholderText(
            "예: Logic Pro automation\nAudio to MIDI\nSinging voice synthesis"
        )
        root.addWidget(self.interests, 1)

        form = QFormLayout()
        form.setSpacing(12)

        self.hours = QSpinBox()
        self.hours.setRange(1, 24)
        self.hours.setSuffix("시간")
        self.hours.setValue(int(self.settings.get("auto_refresh_hours", 6)))
        form.addRow("자동 탐색 주기", self.hours)

        self.score = QSpinBox()
        self.score.setRange(50, 100)
        self.score.setValue(int(self.settings.get("notify_score", 82)))
        form.addRow("알림 기준 점수", self.score)

        self.monitor = QCheckBox("현재 작업 맥락을 사용해 추천 순위를 자동 조정")
        self.monitor.setChecked(bool(self.settings.get("context_monitoring", True)))
        form.addRow("", self.monitor)

        self.login = QCheckBox("Mac 로그인 시 백그라운드 자동 실행")
        self.login.setChecked(bool(self.settings.get("start_at_login", True)))
        form.addRow("", self.login)

        root.addLayout(form)

        privacy = QLabel(
            "Privacy by default  ·  앱 이름과 최근 프로젝트 파일의 이름·확장자만 로컬에서 사용합니다. "
            "키 입력, 화면 캡처, 클립보드, 파일 본문은 수집하지 않습니다."
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("privacy")
        root.addWidget(privacy)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("취소")
        save = QPushButton("저장")
        save.setObjectName("primary")
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.do_save)

    def do_save(self):
        vals = [x.strip() for x in self.interests.toPlainText().splitlines() if x.strip()]
        data = dict(self.settings)
        data.update({
            "interests": vals,
            "auto_refresh_hours": self.hours.value(),
            "notify_score": self.score.value(),
            "context_monitoring": self.monitor.isChecked(),
            "start_at_login": self.login.isChecked(),
        })
        save_settings(data)
        self.saved.emit(data)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_db()
        self.settings = load_settings()
        self.worker = None
        self.row_ids = {}
        self.mode = "all"
        self.category = ""

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

    def section_label(self, text):
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

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
        pix = QPixmap(str(asset_path("h2s-radar.png")))
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

        sub = QLabel("Find what matters before you search.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sl.addWidget(sub)
        sl.addSpacing(14)

        sl.addWidget(self.section_label("DISCOVER"))

        self.nav = []
        specs = [
            ("⌂  For You", "all", ""),
            ("↗  Trending", "hot", ""),
            ("◎  In Your Flow", "context", ""),
            ("✦  New Discoveries", "new", ""),
            ("★  Saved", "favorite", ""),
        ]
        for label, mode, cat in specs:
            self.add_nav(sl, label, mode, cat)

        sl.addSpacing(12)
        sl.addWidget(self.section_label("CATEGORIES"))

        category_labels = {
            "작곡·음악 생성": "Music Generation",
            "DAW 자동화": "DAW Automation",
            "Audio→MIDI·채보": "Audio → MIDI",
            "Stem·오디오 분리": "Stem Separation",
            "보컬·가창 합성": "Vocal Synthesis",
            "Agent·MCP": "Agents · MCP",
            "로컬 LLM": "Local LLM",
            "영상·이미지 AI": "Video · Image",
            "3D·비전": "3D · Vision",
            "기타 AI": "Other AI",
        }
        for cat in CATEGORIES:
            self.add_nav(sl, category_labels.get(cat, cat), "all", cat)

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
        cap = QLabel("LIVE CONTEXT")
        cap.setObjectName("sectionLabel")
        context_head.addWidget(dot)
        context_head.addWidget(cap)
        context_head.addStretch()
        cc.addLayout(context_head)

        self.context_side = QLabel("작업 맥락을 확인하는 중…")
        self.context_side.setObjectName("contextText")
        self.context_side.setWordWrap(True)
        cc.addWidget(self.context_side)

        privacy = QLabel("Local only · no screen / keys")
        privacy.setObjectName("privacyMini")
        cc.addWidget(privacy)
        sl.addWidget(context_card)

        website = QPushButton("h2sstudio.com  ↗")
        website.setObjectName("website")
        website.clicked.connect(lambda: webbrowser.open(WEBSITE))
        sl.addWidget(website)

        settings = QPushButton("⚙  Settings")
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
        eyebrow = QLabel("H2S PERSONAL OPEN-SOURCE INTELLIGENCE")
        eyebrow.setObjectName("eyebrow")
        head.addWidget(eyebrow)

        self.page_title = QLabel("For You")
        self.page_title.setObjectName("pageTitle")
        head.addWidget(self.page_title)

        self.page_subtitle = QLabel(FILTER_TITLES[("all", "")][1])
        self.page_subtitle.setObjectName("muted")
        head.addWidget(self.page_subtitle)
        hero.addLayout(head, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        top_actions = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects, tech, topics…")
        self.search.setMinimumWidth(360)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.load_items)
        top_actions.addWidget(self.search)

        self.refresh_btn = QPushButton("Refresh radar")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(lambda: self.refresh(False))
        top_actions.addWidget(self.refresh_btn)
        actions.addLayout(top_actions)

        self.status = QLabel("Cached recommendations are ready.")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignRight)
        actions.addWidget(self.status)
        hero.addLayout(actions)
        main.addLayout(hero)

        # Stats
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.stats_labels = {}
        for key, label, hint in [
            ("new_count", "New", "unread"),
            ("hot_count", "Hot", "score 78+"),
            ("context_count", "Context", "in your flow"),
            ("favorite_count", "Saved", "bookmarked"),
        ]:
            card = QFrame()
            card.setObjectName("statCard")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(15, 11, 15, 11)
            lay.setSpacing(1)

            top = QHBoxLayout()
            cap = QLabel(label)
            cap.setObjectName("statLabel")
            num = QLabel("0")
            num.setObjectName("stat")
            top.addWidget(cap)
            top.addStretch()
            top.addWidget(num)
            lay.addLayout(top)

            small = QLabel(hint)
            small.setObjectName("tiny")
            lay.addWidget(small)

            cards.addWidget(card)
            self.stats_labels[key] = num

        main.addLayout(cards)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        main.addWidget(self.progress)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "SCORE", "CATEGORY", "PROJECT", "★ STARS", "LANG", "UPDATED", "WHY IT FITS"
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
        for i in [0, 1, 3, 4, 5]:
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)

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
        self.detail_meta = QLabel("Select a project")
        self.detail_meta.setObjectName("tiny")
        meta_row.addWidget(self.detail_meta)
        meta_row.addStretch()

        self.score_badge = QLabel("—")
        self.score_badge.setObjectName("scoreBadge")
        meta_row.addWidget(self.score_badge)
        dl.addLayout(meta_row)

        self.detail_title = QLabel("추천 프로젝트를 선택하세요")
        self.detail_title.setObjectName("detailTitle")
        self.detail_title.setWordWrap(True)
        dl.addWidget(self.detail_title)

        self.detail = QTextBrowser()
        self.detail.setMaximumHeight(100)
        self.detail.setOpenExternalLinks(True)
        dl.addWidget(self.detail)

        ar = QHBoxLayout()
        self.open_btn = QPushButton("Open on GitHub  ↗")
        self.open_btn.setObjectName("primary")
        self.save_btn = QPushButton("☆ Save")
        self.hide_btn = QPushButton("Hide")
        ar.addWidget(self.open_btn)
        ar.addWidget(self.save_btn)
        ar.addWidget(self.hide_btn)
        ar.addStretch()

        footer = QLabel(f"v{APP_VERSION}  ·  H2S Labs  ·  Privacy-first")
        footer.setObjectName("tiny")
        ar.addWidget(footer)
        dl.addLayout(ar)

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
            self.page_title.setText(cat)
            self.page_subtitle.setText("선택한 분야의 프로젝트를 추천 점수 순으로 보여줍니다.")
        else:
            title, sub = FILTER_TITLES.get((mode, ""), FILTER_TITLES[("all", "")])
            self.page_title.setText(title)
            self.page_subtitle.setText(sub)
        self.load_items()

    def load_items(self):
        rows = query_repos(
            self.category, self.mode, self.search.text().strip(), limit=500
        )
        self.table.setRowCount(len(rows))
        self.row_ids = {}

        for r, d in enumerate(rows):
            self.row_ids[r] = d["id"]
            project = d["full_name"]
            if d["is_new"]:
                project = "✦ " + project
            if d["favorite"]:
                project = "★ " + project

            vals = [
                str(d["score"]),
                d["category"],
                project,
                f'{int(d["stars"] or 0):,}',
                d["language"] or "—",
                (d["pushed_at"] or "")[:10],
                d["why"] or "관심분야 기반",
            ]
            for col, value in enumerate(vals):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, d["id"])
                if col == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, col, item)

        s = stats()
        for key, label in self.stats_labels.items():
            label.setText(str(s.get(key, 0)))

        if rows and self.table.currentRow() < 0:
            self.table.selectRow(0)
        if not rows:
            self.detail_meta.setText("No results")
            self.detail_title.setText("조건에 맞는 프로젝트가 없습니다")
            self.score_badge.setText("—")
            self.detail.clear()

    def current_id(self):
        return self.row_ids.get(self.table.currentRow())

    def show_selected(self):
        repo_id = self.current_id()
        if not repo_id:
            return
        d = repo_by_id(repo_id)
        if not d:
            return

        mark_read(repo_id)

        license_text = d["license"] or "license not declared"
        self.detail_meta.setText(
            f'{d["category"]}  ·  {d["language"] or "language n/a"}  ·  '
            f'{license_text}  ·  ★ {int(d["stars"] or 0):,}'
        )
        self.score_badge.setText(f'{d["score"]}/100')
        self.detail_title.setText(d["full_name"])

        topics = " · ".join((d.get("topics") or [])[:10])
        why = html.escape(d["why"] or "관심분야 기반")
        desc = html.escape(d["description"] or "설명 없음")
        topics_html = html.escape(topics)
        self.detail.setHtml(
            f'<b style="color:#DCE6FF">Why it fits</b>  {why}'
            f'<br><span style="color:#BAC6D8">{desc}</span>'
            f'<br><span style="color:#77849A">{topics_html}</span>'
        )
        self.save_btn.setText("★ Saved" if d["favorite"] else "☆ Save")

    def open_selected(self, *_):
        repo_id = self.current_id()
        if repo_id:
            d = repo_by_id(repo_id)
            if d:
                webbrowser.open(d["html_url"])

    def toggle_save(self):
        repo_id = self.current_id()
        if not repo_id:
            return
        d = repo_by_id(repo_id)
        set_favorite(repo_id, not bool(d["favorite"]))
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
            mins = max(1, int(remaining / 60))
            self.status.setText(f"Using cache · next scan in ~{mins} min")

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
        self.refresh_btn.setText("Scanning…")
        self.worker.start()

    def on_progress(self, current, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.status.setText(f"Scanning {current}/{total} · {message}")

    def on_done(self, result, silent):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh radar")
        errors = result.get("errors") or []

        self.status.setText(
            f'Updated · {result.get("found", 0)} analyzed · '
            f'{result.get("new", 0)} new'
            + (f' · {len(errors)} warning(s)' if errors else "")
        )

        if int(result.get("found", 0) or 0) > 0:
            self.settings["last_scan_epoch"] = time.time()
            save_settings(self.settings)

        rescore_cached()
        self.load_items()

        top = result.get("top_new") or []
        if top:
            first = top[0]
            self.notify(
                "새 AI 오픈소스 추천",
                f'{first["name"]} · 추천 {first["score"]} · {first["why"]}'
            )

        if errors and not silent:
            QMessageBox.warning(self, "탐색 일부 실패", "\n".join(errors[:3]))

    def on_failed(self, message):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh radar")
        self.status.setText("Scan failed")
        QMessageBox.warning(self, APP_NAME, message)

    def notify(self, title, message):
        try:
            title = title.replace('"', "'")
            message = message.replace('"', "'")
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                timeout=4
            )
        except Exception:
            pass

    def sample_context(self):
        if not self.settings.get("context_monitoring", True):
            self.context_side.setText("Context monitoring is off")
            return
        name = sample_activity()
        self.context_side.setText(name or "No matching creative app detected")

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
        self.settings = data
        self.refresh_timer.start(
            max(1, int(data.get("auto_refresh_hours", 6))) * 60 * 60 * 1000
        )
        sync_login_item(bool(data.get("start_at_login", True)))
        self.sample_context()
        rescore_cached()
        self.load_items()
        self.status.setText("Preferences saved · scores recalculated")

    def setup_tray(self):
        icon = app_icon()
        self.tray = QSystemTrayIcon(icon, self)

        menu = QMenu()
        show = QAction("Open Source Radar 열기", self)
        refresh = QAction("지금 추천 갱신", self)
        site = QAction("H2S Studio 열기", self)
        quit_action = QAction("종료", self)

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
            "백그라운드에서 추천을 계속 확인합니다.",
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
        #liveDot {
            color: #67D8A5;
            font-size: 10px;
        }
        #contextText {
            color: #C6D1E1;
            font-size: 11px;
            line-height: 1.3;
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
        QPushButton#primary:hover {
            background: #6985FA;
        }
        QPushButton#website {
            text-align: left;
            border: 1px solid #223149;
            background: #111A27;
            color: #8AA5FF;
        }
        QLineEdit, QPlainTextEdit {
            background: #101824;
            border: 1px solid #27364C;
            border-radius: 9px;
            padding: 8px;
            selection-background-color: #536FE8;
        }
        QLineEdit:focus, QPlainTextEdit:focus {
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
