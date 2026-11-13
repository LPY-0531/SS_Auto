import hashlib
import json
import os
import threading
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

import new
from desktop_app import AutomationWorker, MainWindow


def sample_records():
    records = []
    for i in range(12):
        item = {
            "id": str(7000000000 + i), "name": f"测试同学{i + 1}",
            "date": "2026-10-10", "slot": "下午", "duration": 25,
            "content": f"这是本地自动化测试的第 {i + 1} 条完整内容，包含中文与换行。\n不会提交到学校系统。",
        }
        item["key"] = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        records.append(item)
    return records


RECORDS = sample_records()
LOGIN_HTML = """<!doctype html><meta charset='utf-8'>
<ul><li onclick="document.getElementById('credentials').style.display='block'">账号密码登录</li></ul>
<div id='credentials' style='display:none'>
<input placeholder='请输入职工号/学号/手机号' value='remembered-user'><input type='password' placeholder='请输入登录密码' value='old-password'>
<button class='login-btn' onclick='login()'>登录</button></div><div id='error'></div>
<script>async function login(){
const response=await fetch('/login',{method:'POST',body:JSON.stringify({
username:document.querySelector('input').value,password:document.querySelector('input[type=password]').value})});
if(response.ok) location.href='CALLBACK_URL';
else document.getElementById('error').innerHTML='<div role="alert">账号或密码错误</div>';
}</script>"""

APP_HTML = """<!doctype html><meta charset='utf-8'><script src='/jquery.js'></script><h2>谈心谈话</h2>
<div id='rzxxTable'>总记录数 <span id='count'>COUNT_VALUE</span></div>
<button id='rzxx_AddButton' onclick='openForm()'>新增</button>
<div role='option' style='display:none'>测试同学1 7000000000</div>
<script>
const students=STUDENTS_JSON;let selectedId='';
function openForm(){
document.getElementById('rzxx_AddButton').style.display='none';
const form=document.createElement('section');form.id='form';
form.innerHTML=`<input class="jqx-combobox-input" oninput="lookup(this.value)">
<div id="options"></div><input name="SJH">
<input bh-form-role="dateTimeInput" style="display:none">
<div data-name="THRQ"><input bh-form-role="dateTimeInput"></div>
<label><input type="radio" name="THLB" data-caption="日常谈话">日常谈话</label>
<label><input type="radio" name="THSD" data-caption="下午">下午</label>
<input name="THSCXS"><input name="THSCFZ"><textarea name="THNR"></textarea>
<button id="saveTxthBtn" onclick="save()">保存</button>
<button id="cancelBtn" onclick="document.getElementById('form').remove();document.getElementById('rzxx_AddButton').style.display=''">关闭</button>`;
document.body.appendChild(form);
}
function lookup(id){const student=students.find(s=>s.id===id);
document.getElementById('options').innerHTML='';if(!student)return;
const option=document.createElement('div');option.setAttribute('role','option');
option.textContent=student.name+' '+student.id;
option.onclick=()=>{selectedId=id;document.querySelector('[name=SJH]').value='13800000000';option.remove();};
document.getElementById('options').appendChild(option);}
async function save(){const data={id:selectedId,
date:document.querySelector('[data-name=THRQ] input').value,
hours:document.querySelector('[name=THSCXS]').value,
minutes:document.querySelector('[name=THSCFZ]').value,
content:document.querySelector('textarea').value,
slot:document.querySelector('[name=THSD]:checked').getAttribute('data-caption')};
jQuery.ajax({url:'/gztb/saveTxthData.do',type:'POST',data:JSON.stringify(data),contentType:'application/json',success:function(result){
if(result.code!=='0'){const error=document.createElement('div');error.setAttribute('role','alert');error.textContent=result.msg;document.getElementById('form').appendChild(error);return;}
document.getElementById('count').textContent=result.count;document.getElementById('form').remove();
document.getElementById('rzxx_AddButton').style.display='';}});}
</script>"""


class SchoolFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/jquery.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write((Path(__file__).parent / "vendor/jquery-3.6.0.min.js").read_bytes())
            return
        if self.path == "/callback":
            self.send_response(302)
            self.send_header("Set-Cookie", "authenticated=1; Path=/; Max-Age=3600")
            self.send_header("Location", "/app")
            self.end_headers()
            return
        if self.path == "/app" and "authenticated=1" not in self.headers.get("Cookie", ""):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/login")
            self.end_headers()
            return
        if self.path == "/login":
            content = LOGIN_HTML.replace("CALLBACK_URL", f"http://localhost:{self.server.server_port}/callback")
        elif self.path == "/app":
            content = APP_HTML.replace("COUNT_VALUE", str(len(self.server.saved))).replace(
                "STUDENTS_JSON", json.dumps(RECORDS, ensure_ascii=False))
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/login":
            self.send_response(200 if data == {"username": "demo", "password": "test-only"} else 401)
            self.end_headers()
        elif self.path == "/gztb/saveTxthData.do":
            if self.server.reject_next:
                self.server.reject_next = False
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"code": "blocked", "msg": "测试：学校拒绝保存"}).encode())
                return
            self.server.saved.append(data)
            if self.server.timeout_after_save:
                self.send_error(504, "Save response interrupted")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            count = len(self.server.saved) - int(self.server.stale_count)
            self.wfile.write(json.dumps({"code": "0", "msg": "成功", "count": count}).encode())
        else:
            self.send_error(404)


class BrowserIntegrationTests(unittest.TestCase):
    def test_login_navigation_batch_resume_stop_and_uncertain_save(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), SchoolFixture)
        server.saved = []
        server.reject_next = False
        server.stale_count = False
        server.timeout_after_save = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        folder = Path(mkdtemp(prefix="ssautofold-browser-test-"))
        engine = new.AutoCounselorFixed(progress_path=folder / "progress.jsonl", log=lambda _: None)
        stop = threading.Event()

        def open_headless(profile_dir=None, debugger_address=None):
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument(f"--user-data-dir={profile_dir}")
            options.page_load_strategy = "eager"
            engine.driver = webdriver.Chrome(options=options)
            engine.wait = WebDriverWait(engine.driver, 5)

        try:
            with patch("new.TARGET_URL", f"http://localhost:{server.server_port}/app"), patch.object(
                engine, "open_browser", side_effect=open_headless,
            ):
                with self.assertRaisesRegex(ValueError, "账号或密码错误"):
                    engine.login("demo", "wrong", folder / "browser", stop)
                engine.login("demo", "test-only", folder / "browser", stop)
                self.assertTrue(engine.is_ready())
                # 固定资料复用登录状态，第二次不提供密码也能进入列表。
                engine.login("demo", "", folder / "browser", stop)
                self.assertTrue(engine.is_ready())

                self.assertEqual(engine.import_records(RECORDS), 10)
                self.assertEqual(len(server.saved), 10)
                self.assertEqual(len(new.completed_keys(engine.progress_path)), 10)
                for saved, source in zip(server.saved, RECORDS):
                    self.assertEqual(saved["id"], source["id"])
                    self.assertEqual(saved["date"], source["date"])
                    self.assertEqual(saved["content"], source["content"])
                    self.assertEqual(saved["slot"], source["slot"])
                    self.assertEqual(int(saved["hours"]) * 60 + int(saved["minutes"]), source["duration"])

                server.reject_next = True
                with self.assertRaisesRegex(new.AutomationError, "学校拒绝保存"):
                    engine.import_records(RECORDS)
                self.assertEqual(len(server.saved), 10)
                self.assertFalse(engine.pending_path.exists())
                engine.driver.find_element(new.By.ID, "cancelBtn").click()

                def stop_after_one(*_args):
                    stop.set()

                server.stale_count = True
                self.assertEqual(engine.import_records(RECORDS, stop_event=stop, on_progress=stop_after_one), 1)
                self.assertEqual(len(server.saved), 11)
                self.assertEqual(engine.get_record_count(), 10)
                self.assertEqual(len(new.completed_keys(engine.progress_path)), 11)
                self.assertFalse(engine.pending_path.exists())
                stop.clear()
                server.timeout_after_save = True
                engine.wait = WebDriverWait(engine.driver, 1)
                with self.assertRaisesRegex(new.AutomationError, "504"):
                    engine.import_records(RECORDS)
                self.assertEqual(len(server.saved), 12)
                self.assertEqual(len(new.completed_keys(engine.progress_path)), 11)
                self.assertTrue(engine.pending_path.exists())
                with self.assertRaisesRegex(new.AutomationError, "尚未确认"):
                    engine.import_records(RECORDS)
                self.assertEqual(len(server.saved), 12)
        finally:
            engine.close_browser()
            server.shutdown()
            server.server_close()
            thread.join()


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.folder = Path(mkdtemp(prefix="ssautofold-ui-test-"))
        frame = pd.DataFrame([
            {"姓名": r["name"], "学号": r["id"], "谈话时间": r["date"] + "（周六）14:00-14:25",
             "谈话时长": "25分钟", "谈话内容（约300字，可直接录入）": r["content"]}
            for r in RECORDS
        ])
        future = frame.iloc[0].copy()
        future["学号"] = "7999999999"
        future["谈话时间"] = str(pd.Timestamp.now(tz="Asia/Shanghai").date() + timedelta(days=30)) + "（周一）14:00-14:25"
        invalid = frame.iloc[0].copy()
        invalid["学号"] = "姓名误填"
        frame = pd.concat([frame, pd.DataFrame([future, invalid])], ignore_index=True)
        with patch("new.pd.read_excel", return_value=frame), patch("desktop_app.EXCEL_NAME", "test-source-not-on-disk.xlsx"):
            self.window = MainWindow(self.folder)
            self.window.load_file(self.folder / "sample.xlsx")
        self.window.login_requested.disconnect()
        self.window.import_requested.disconnect()
        self.login_calls = []
        self.import_calls = []
        self.window.login_requested.connect(lambda *args: self.login_calls.append(args))
        self.window.import_requested.connect(lambda *args: self.import_calls.append(args))

    def tearDown(self):
        self.window.busy = False
        self.window.close()
        while self.window.worker_thread.isRunning():
            self.application.processEvents()
            QTest.qWait(10)

    def test_default_preview_and_login_gate(self):
        self.assertEqual(self.window.quantity.value(), 10)
        self.assertEqual(self.window.table.rowCount(), 10)
        self.assertIn("未来日期 1 条", self.window.summary.text())
        self.assertIn("异常 1 条", self.window.summary.text())
        self.assertFalse(self.window.start_button.isEnabled())
        self.window.start_login()
        self.assertFalse(self.login_calls)
        self.window.username.setText("demo")
        self.window.password.setText("test-only")
        self.window.start_login()
        self.assertEqual(len(self.login_calls), 1)
        self.assertTrue(self.window.busy)
        self.window.on_logged_in("demo")
        self.assertEqual(self.window.password.text(), "")
        self.assertTrue(self.window.start_button.isEnabled())
        self.window.start_import()
        self.assertEqual(len(self.import_calls[0][0]), 10)
        self.assertEqual(self.import_calls[0][1], 10)
        self.window.request_stop()
        self.assertTrue(self.window.stop_event.is_set())

    def test_login_only_never_enables_or_emits_import(self):
        self.window.login_only = True
        self.window.on_logged_in("demo")
        self.assertFalse(self.window.start_button.isEnabled())
        self.window.start_import()
        self.assertFalse(self.import_calls)

    def test_confirmed_history_is_skipped_and_quantity_means_new_rows(self):
        for item in self.window.records[:3]:
            new.append_progress(self.window.progress_path, item)
        self.window.refresh_preview()
        self.assertEqual(len(self.window.batch_records), 9)
        self.assertEqual(self.window.batch_records[0]["id"], RECORDS[3]["id"])
        self.window.quantity.setValue(4)
        self.assertEqual(self.window.table.rowCount(), 4)

    def test_failure_refreshes_confirmed_count(self):
        for item in self.window.records[:2]:
            new.append_progress(self.window.progress_path, item)
        self.window.on_failed("测试保存中断")
        self.assertIn("已录入 2 条", self.window.summary.text())
        self.assertEqual(self.window.batch_records[0]["id"], RECORDS[2]["id"])

    def test_timeout_reports_the_actual_save_stage(self):
        worker = AutomationWorker(self.folder, threading.Event())
        worker.engine.stage = "等待学校返回保存结果"
        errors = []
        worker.failed.connect(errors.append)
        with patch.object(worker.engine, "import_records", side_effect=TimeoutException()):
            worker.import_batch(RECORDS, 3)
        self.assertEqual(len(errors), 1)
        self.assertIn("等待学校返回保存结果", errors[0])

    def test_uncertain_save_requires_a_decision(self):
        item = self.window.records[0]
        self.window.pending_path.write_text(json.dumps(item), encoding="utf-8")
        self.window.ready = True
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.window.start_import()
        self.assertFalse(self.import_calls)
        self.assertTrue(self.window.pending_path.exists())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.start_import()
        self.assertFalse(self.window.pending_path.exists())
        self.assertIn(item["key"], new.completed_keys(self.window.progress_path))
        self.assertNotIn(item["key"], {r["key"] for r in self.import_calls[0][0]})

    def test_closing_during_a_batch_waits_for_the_current_record(self):
        self.window.busy = True
        self.window.close()
        self.assertTrue(self.window.stop_event.is_set())
        self.assertTrue(self.window.close_when_idle)
        self.assertTrue(self.window.worker_thread.isRunning())
        self.window.on_finished(0)
        while self.window.worker_thread.isRunning():
            self.application.processEvents()
            QTest.qWait(10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
