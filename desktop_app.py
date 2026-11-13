import argparse
import hashlib
import json
import sys
from pathlib import Path
from threading import Event
from zipfile import BadZipFile

from PySide6.QtCore import QObject, QStandardPaths, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from selenium.common.exceptions import TimeoutException, WebDriverException

from new import AutoCounselorFixed, AutomationError, EXCEL_NAME, append_progress, completed_keys


class AutomationWorker(QObject):
    message = Signal(str)
    logged_in = Signal(str)
    progress = Signal(int, int, str)
    finished = Signal(int)
    failed = Signal(str)
    closed = Signal()

    def __init__(self, data_dir, stop_event):
        super().__init__()
        self.data_dir = data_dir
        self.stop_event = stop_event
        self.engine = AutoCounselorFixed(
            progress_path=data_dir / "import_progress.jsonl", log=self.message.emit,
        )

    @Slot(str, str)
    def login(self, username, password):
        profile = self.data_dir / "browser" / hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]
        try:
            self.engine.login(username, password, profile, self.stop_event)
        except InterruptedError as exc:
            self.failed.emit(str(exc))
        except TimeoutException:
            self.failed.emit("登录等待超时。请查看浏览器是否需要完成安全验证，再重新登录。")
        except (WebDriverException, OSError, ValueError, AutomationError) as exc:
            self.failed.emit(f"登录未完成：{exc}")
        else:
            self.logged_in.emit(username)

    @Slot(object, int)
    def import_batch(self, records, limit):
        try:
            count = self.engine.import_records(
                records, limit, self.stop_event, self.progress.emit,
            )
        except TimeoutException:
            self.failed.emit(f"录入已停止：在“{self.engine.stage}”等待超时。请查看 Chrome 中的提示；结果未确认的记录会保留待核对标记。")
        except (WebDriverException, OSError, ValueError, AutomationError) as exc:
            self.failed.emit(f"录入已停止：{exc}")
        else:
            self.finished.emit(count)

    @Slot()
    def close(self):
        try:
            self.engine.close_browser()
        except WebDriverException as exc:
            self.message.emit(f"关闭浏览器时收到提示：{exc}")
        self.closed.emit()


class MainWindow(QMainWindow):
    login_requested = Signal(str, str)
    import_requested = Signal(object, int)
    close_requested = Signal()

    def __init__(self, data_dir=None, login_only=False):
        super().__init__()
        self.login_only = login_only
        self.setWindowTitle("谈话记录助手 · 仅登录测试" if login_only else "谈话记录助手")
        self.resize(1180, 820)
        self.setMinimumSize(980, 720)
        self.base_dir = Path(__file__).resolve().parent
        self.data_dir = Path(data_dir) if data_dir else Path(
            QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.progress_path = self.data_dir / "import_progress.jsonl"
        self.pending_path = self.progress_path.with_suffix(".pending.json")
        self.records = []
        self.batch_records = []
        self.stats = {"total": 0, "future": 0, "eligible": 0}
        self.busy = False
        self.ready = False
        self.closing = False
        self.close_when_idle = False
        self.file_path = None
        self.stop_event = Event()
        self.build_ui()
        self.worker_thread = QThread(self)
        self.worker = AutomationWorker(self.data_dir, self.stop_event)
        self.worker.moveToThread(self.worker_thread)
        self.login_requested.connect(self.worker.login)
        self.import_requested.connect(self.worker.import_batch)
        self.close_requested.connect(self.worker.close)
        self.worker.message.connect(self.log_message)
        self.worker.logged_in.connect(self.on_logged_in)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.closed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.close)
        self.worker_thread.start()
        self.refresh_preview()
        default_file = self.base_dir / EXCEL_NAME
        if default_file.exists():
            self.load_file(default_file)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)
        title = QLabel("谈话记录助手")
        title.setObjectName("title")
        subtitle = QLabel("仅登录测试：验证自动登录和进入谈心谈话，录入功能已禁用。" if self.login_only
                          else "选择表格，登录学校系统，按批次完成谈心谈话录入。")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        top = QHBoxLayout()
        top.setSpacing(16)
        login_group = QGroupBox("1  登录学校系统")
        login_form = QFormLayout(login_group)
        login_form.setContentsMargins(18, 22, 18, 16)
        login_form.setSpacing(12)
        self.username = QLineEdit()
        self.username.setPlaceholderText("职工号 / 学号 / 手机号")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("首次登录或会话失效时填写")
        self.login_button = QPushButton("登录并准备")
        self.login_button.setObjectName("secondary")
        self.login_button.clicked.connect(self.start_login)
        self.password.returnPressed.connect(self.start_login)
        self.login_status = QLabel("尚未登录")
        self.login_status.setWordWrap(True)
        login_form.addRow("账号", self.username)
        login_form.addRow("密码", self.password)
        login_form.addRow(self.login_button)
        login_form.addRow(self.login_status)
        top.addWidget(login_group, 2)

        file_group = QGroupBox("2  选择谈话记录表")
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(18, 22, 18, 16)
        file_layout.setSpacing(12)
        file_row = QHBoxLayout()
        self.file_name = QLineEdit()
        self.file_name.setReadOnly(True)
        self.file_name.setPlaceholderText("请选择 Excel 文件")
        self.file_button = QPushButton("选择 Excel")
        self.file_button.clicked.connect(self.choose_file)
        file_row.addWidget(self.file_name, 1)
        file_row.addWidget(self.file_button)
        file_layout.addLayout(file_row)
        self.summary = QLabel("选择文件后，将自动检查日期、时长和必填内容。")
        self.summary.setWordWrap(True)
        file_layout.addWidget(self.summary)
        hint = QLabel("读取“谈话记录”工作表。未来日期自动跳过，已保存记录自动跳过。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        file_layout.addWidget(hint)
        file_layout.addStretch()
        top.addWidget(file_group, 3)
        layout.addLayout(top)

        preview_group = QGroupBox("3  本批待录入预览")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(14, 20, 14, 14)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["姓名", "学号", "谈话日期", "时段", "分钟", "状态"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_content)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setPlaceholderText("选择一位学生，查看将要录入的完整谈话内容。")
        splitter.addWidget(self.table)
        splitter.addWidget(self.content)
        splitter.setSizes([700, 360])
        preview_layout.addWidget(splitter)
        layout.addWidget(preview_group, 1)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("本次新增"))
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 500)
        self.quantity.setValue(10)
        self.quantity.setSuffix(" 条")
        self.quantity.setFixedWidth(110)
        self.quantity.valueChanged.connect(self.refresh_preview)
        action_row.addWidget(self.quantity)
        action_row.addStretch()
        self.action_status = QLabel("请先选择表格并登录")
        action_row.addWidget(self.action_status)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.request_stop)
        self.start_button = QPushButton("开始录入")
        if self.login_only:
            self.start_button.setText("录入已禁用（登录测试）")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_import)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.start_button)
        layout.addLayout(action_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 10)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m 条")
        layout.addWidget(self.progress_bar)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(100)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setPlaceholderText("操作进度会显示在这里。")
        layout.addWidget(self.log_box)
        footer = QLabel("首次使用请保持联网，并确保电脑已安装 Chrome。密码仅用于本次登录，进度保存在本机。")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self.setStyleSheet("""
            QMainWindow { background: #f4f6fb; }
            QWidget { color: #243248; font-size: 13px; }
            QLabel#title { font-size: 27px; font-weight: 700; color: #18273d; }
            QLabel#muted { color: #6e7b90; font-size: 12px; }
            QGroupBox { background: white; border: 1px solid #dfe5ef; border-radius: 10px;
                        margin-top: 10px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 6px; }
            QLineEdit, QSpinBox { background: white; border: 1px solid #d5ddea;
                                  border-radius: 6px; padding: 8px; min-height: 18px; }
            QLineEdit:focus, QSpinBox:focus { border-color: #356ade; }
            QLineEdit:read-only { background: #f8f9fc; }
            QPushButton { background: #eef2f8; border: 1px solid #d7dfeb; border-radius: 6px;
                          padding: 9px 17px; font-weight: 600; }
            QPushButton:hover { background: #e2eafb; }
            QPushButton#primary { background: #3268d8; color: white; border-color: #3268d8; }
            QPushButton#primary:hover { background: #2557bd; }
            QPushButton#primary:disabled { color: #9aa5b5; background: #edf0f5; border-color: #e1e6ee; }
            QPushButton:disabled { color: #9aa5b5; background: #edf0f5; border-color: #e1e6ee; }
            QTableWidget { border: none; background: white; alternate-background-color: #f7f9fd;
                           gridline-color: #edf0f5; selection-background-color: #e8efff;
                           selection-color: #243248; }
            QHeaderView::section { background: #f0f4fa; color: #53627a; border: none;
                                  padding: 10px 6px; font-weight: 600; }
            QPlainTextEdit { border: 1px solid #e0e6ef; border-radius: 6px; background: white;
                             padding: 9px; selection-background-color: #dce8ff; }
            QProgressBar { border: none; border-radius: 5px; background: #e3e9f3;
                           text-align: center; min-height: 20px; }
            QProgressBar::chunk { background: #a9c3fb; border-radius: 5px; }
        """)

    def log_message(self, text):
        self.log_box.appendPlainText(text)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择谈话记录表", "", "Excel 工作簿 (*.xlsx)")
        if path:
            self.load_file(Path(path))

    def load_file(self, path):
        try:
            reader = AutoCounselorFixed(path, self.progress_path, self.log_message)
            records = reader.load_specific_excel(limit=None)
            # 兼容之前试录的确认记录；按指纹合并，原进度文件保持不动。
            done = completed_keys(self.progress_path)
            keys = {item["key"] for item in records}
            for legacy in dict.fromkeys([self.base_dir / "试录进度.jsonl", Path(path).parent / "试录进度.jsonl"]):
                if legacy.exists():
                    for line in legacy.read_text(encoding="utf-8").splitlines():
                        item = json.loads(line)
                        if item["key"] in keys and item["key"] not in done:
                            append_progress(self.progress_path, item)
                            done.add(item["key"])
        except (OSError, ValueError, BadZipFile) as exc:
            self.records = []
            self.file_path = None
            self.file_name.clear()
            self.refresh_preview()
            self.on_failed(f"表格检查未通过：{exc}")
            return
        self.file_path = Path(path)
        self.records = records
        self.stats = reader.stats
        self.file_name.setText(self.file_path.name)
        self.file_name.setToolTip(str(self.file_path))
        self.refresh_preview()

    def refresh_preview(self):
        done = completed_keys(self.progress_path)
        pending = [item for item in self.records if item["key"] not in done]
        self.batch_records = pending[:self.quantity.value()]
        self.refresh_summary(done)
        self.table.setRowCount(len(self.batch_records))
        for row, item in enumerate(self.batch_records):
            values = [item["name"], item["id"], item["date"], item["slot"], str(item["duration"]), "待录入"]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if self.batch_records:
            self.table.selectRow(0)
        else:
            self.content.clear()
        self.update_controls()

    def refresh_summary(self, done):
        imported = sum(item["key"] in done for item in self.records)
        pending_count = sum(item["key"] not in done for item in self.records)
        if self.file_path:
            self.summary.setText(
                f"共 {self.stats['total']} 条    已录入 {imported} 条    "
                f"未来日期 {self.stats['future']} 条    异常 {len(self.stats['invalid'])} 条\n"
                f"当前待录入 {pending_count} 条，本次计划新增 {len(self.batch_records)} 条。"
            )
        else:
            self.summary.setText("选择文件后，将自动检查日期、时长和必填内容。")

    def show_content(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.batch_records):
            self.content.setPlainText(self.batch_records[row]["content"])

    def update_controls(self):
        for widget in [self.username, self.password, self.file_button, self.quantity, self.login_button]:
            widget.setEnabled(not self.busy)
        self.quantity.setEnabled(not self.busy and not self.login_only)
        self.start_button.setEnabled(not self.login_only and not self.busy and self.ready and bool(self.batch_records))
        self.stop_button.setEnabled(self.busy and not self.stop_event.is_set())

    def start_login(self):
        username = self.username.text().strip()
        if not username:
            self.login_status.setText("请先填写学校账号")
            self.username.setFocus()
            return
        self.busy = True
        self.ready = False
        self.stop_event.clear()
        self.login_status.setText("正在登录并准备…")
        self.action_status.setText("登录中")
        self.update_controls()
        if self.login_only:
            print("LOGIN_TEST_STARTED", flush=True)
        self.login_requested.emit(username, self.password.text())

    def on_logged_in(self, username):
        self.password.clear()
        self.busy = False
        self.ready = True
        self.login_status.setText(f"已就绪 · 账号 {username}")
        self.login_status.setStyleSheet("color: #19815b; font-weight: 600;")
        self.action_status.setText("谈心谈话列表已就绪")
        self.update_controls()
        if self.login_only:
            print("LOGIN_TEST_READY", flush=True)

    def start_import(self):
        if self.login_only or not self.ready or self.busy:
            return
        if self.pending_path.exists():
            item = json.loads(self.pending_path.read_text(encoding="utf-8"))
            answer = QMessageBox.question(
                self, "核对上次保存结果",
                f"上次这条记录的保存结果未确认：\n{item['name']} · {item['id']} · {item['date']}\n\n"
                "请先在学校系统核对。已经保存请选择“是”，确认未保存请选择“否”，暂不确定请选择“取消”。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                append_progress(self.progress_path, item)
            self.pending_path.unlink()
        self.refresh_preview()
        if not self.batch_records:
            self.action_status.setText("当前没有可新增的记录")
            return
        self.busy = True
        self.stop_event.clear()
        self.progress_bar.setRange(0, len(self.batch_records))
        self.progress_bar.setValue(0)
        self.action_status.setText(f"本次计划新增 {len(self.batch_records)} 条")
        self.update_controls()
        self.import_requested.emit(list(self.batch_records), self.quantity.value())

    def on_progress(self, count, total, name):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(count)
        self.action_status.setText(f"已保存 {count}/{total} 条 · {name}")
        self.table.item(count - 1, 5).setText("已保存")
        self.table.item(count - 1, 5).setForeground(QColor("#19815b"))
        self.refresh_summary(completed_keys(self.progress_path))

    def request_stop(self):
        self.stop_event.set()
        self.action_status.setText("正在停止：当前记录核对完成后结束")
        self.update_controls()

    def on_finished(self, count):
        self.busy = False
        self.action_status.setText(f"本次已保存 {count} 条" + ("，已停止" if self.stop_event.is_set() else "，已完成"))
        self.refresh_preview()
        if self.close_when_idle:
            self.close()

    def on_failed(self, message):
        self.password.clear()
        self.busy = False
        self.ready = False
        self.login_status.setText("请重新登录并准备")
        self.login_status.setStyleSheet("color: #a35c26;")
        self.action_status.setText("操作已停止，请查看下方说明")
        self.log_message(message)
        self.refresh_preview()
        if self.login_only:
            print("LOGIN_TEST_FAILED", flush=True)
        if self.pending_path.exists():
            self.log_message("有一条保存结果未确认。重新登录后点击开始，工具会先请你核对这条记录。")
        if self.close_when_idle:
            self.close()

    def closeEvent(self, event):
        if self.busy:
            self.close_when_idle = True
            self.request_stop()
            event.ignore()
            return
        if self.worker_thread.isRunning():
            event.ignore()
            if not self.closing:
                self.closing = True
                self.action_status.setText("正在关闭浏览器…")
                self.close_requested.emit()
            return
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="谈话记录助手")
    parser.add_argument("--login-only", action="store_true", help="仅测试登录和进入列表，禁用录入")
    args = parser.parse_args()
    application = QApplication(sys.argv)
    application.setOrganizationName("ssAutoFold")
    application.setApplicationName("CounselorAssistant")
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "PingFang SC", "sans-serif"])
    font.setPointSize(10)
    application.setFont(font)
    window = MainWindow(login_only=args.login_only)
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
