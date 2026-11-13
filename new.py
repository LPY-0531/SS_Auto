import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

EXCEL_NAME = "【待谈】大二第一学期学生谈话记录与重点关注名单（新版谈话内容）.xlsx"
SHEET_NAME = "谈话记录"
IMPORT_LIMIT = 10
TARGET_URL = "https://ss.xjtu.edu.cn/xsfw/sys/fdyrzappxjtu/*default/index.do?THEME=indigo#/gztb"
ACCOUNT_TAB = (By.XPATH, "//li[normalize-space(.)='账号密码登录']")
USERNAME_INPUT = (By.CSS_SELECTOR, "input[placeholder='请输入职工号/学号/手机号']")
PASSWORD_INPUT = (By.CSS_SELECTOR, "input[placeholder='请输入登录密码']")


class AutomationError(Exception):
    """网页状态或保存结果与本次操作不一致。"""


def completed_keys(path):
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as file:
        return {json.loads(line)["key"] for line in file}


def append_progress(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps({
            "key": item["key"], "id": item["id"], "name": item["name"],
            "date": item["date"], "slot": item["slot"], "duration": item["duration"],
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n")


class AutoCounselorFixed:
    def __init__(self, file_path=None, progress_path=None, log=print):
        self.base_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
        self.file_path = Path(file_path) if file_path else self.base_dir / EXCEL_NAME
        self.progress_path = Path(progress_path) if progress_path else self.base_dir / "试录进度.jsonl"
        self.pending_path = self.progress_path.with_suffix(".pending.json")
        self.log = log
        self.driver = None
        self.stats = {}
        self.stage = "尚未开始录入"

    def load_specific_excel(self, limit=IMPORT_LIMIT):
        df = pd.read_excel(self.file_path, sheet_name=SHEET_NAME, dtype={"学号": str})
        columns = ["姓名", "学号", "谈话时间", "谈话时长", "谈话内容（约300字，可直接录入）"]
        missing = set(columns) - set(df.columns)
        if missing:
            raise ValueError(f"Excel 缺少列：{sorted(missing)}")
        if df[columns].isna().any().any():
            raise ValueError("Excel 存在空的必填字段，请补全后重新选择文件")

        today = pd.Timestamp.now(tz="Asia/Shanghai").date()
        dates = pd.to_datetime(df["谈话时间"].str[:10], format="%Y-%m-%d").dt.date
        selected = df.loc[dates <= today]
        self.stats = {"total": len(df), "future": int((dates > today).sum()), "invalid": []}
        if limit is not None:
            selected = selected.head(limit)
        valid_ids = selected["学号"].str.fullmatch(r"\d{10}")
        for index, row in selected.loc[~valid_ids].iterrows():
            self.stats["invalid"].append(f"第 {index + 2} 行：{row['姓名']} 的学号“{row['学号']}”不是 10 位数字，请核对源表。")
        selected = selected.loc[valid_ids]
        self.stats["eligible"] = len(selected)
        if selected["学号"].duplicated().any():
            raise ValueError("选中的记录有重复学号，请核对源表")

        records = []
        for index, row in selected.iterrows():
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})（周[一二三四五六日]）(\d{2}:\d{2})-(\d{2}:\d{2})", str(row["谈话时间"]).strip())
            duration_match = re.fullmatch(r"(\d+)分钟", str(row["谈话时长"]).strip())
            if not match or not duration_match:
                raise ValueError(f"Excel 第 {index + 2} 行时间或时长格式错误")
            date, start_text, end_text = match.groups()
            start = datetime.strptime(f"{date} {start_text}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{date} {end_text}", "%Y-%m-%d %H:%M")
            duration = int(duration_match.group(1))
            if duration <= 0 or (end - start).total_seconds() != duration * 60:
                raise ValueError(f"Excel 第 {index + 2} 行起止时间与时长不一致")
            student_id = str(row["学号"]).strip()
            content = str(row[columns[-1]])
            if not content.strip() or len(content) > 1000:
                raise ValueError(f"Excel 第 {index + 2} 行谈话内容为空或超过 1000 字")
            slot = "上午" if start.hour < 12 else "中午" if start.hour < 14 else "下午" if start.hour < 18 else "晚上"
            item = {
                "id": student_id, "name": str(row["姓名"]).strip(),
                "date": date, "slot": slot, "duration": duration, "content": content,
            }
            item["key"] = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            records.append(item)
        self.log(f"读取 {len(df)} 条记录；跳过 {self.stats['future']} 条未来日期。")
        for message in self.stats["invalid"]:
            self.log(f"已跳过异常记录：{message}")
        return records

    def open_browser(self, profile_dir=None, debugger_address=None):
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "eager"
        if debugger_address:
            options.debugger_address = debugger_address
        else:
            options.add_experimental_option("detach", True)
            if profile_dir:
                Path(profile_dir).mkdir(parents=True, exist_ok=True)
                options.add_argument(f"--user-data-dir={Path(profile_dir).resolve()}")
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(60)
        self.wait = WebDriverWait(self.driver, 30)

    def is_ready(self):
        return any(element.is_displayed() and element.is_enabled()
                   for element in self.driver.find_elements(By.ID, "rzxx_AddButton"))

    def login(self, username, password, profile_dir, stop_event):
        if self.driver is not None:
            self.close_browser()
        self.log("正在打开学校系统…")
        self.open_browser(profile_dir=profile_dir)
        self.driver.get(TARGET_URL)
        self.wait.until(lambda d: stop_event.is_set() or self.is_ready() or
                        any(e.is_displayed() for e in d.find_elements(*ACCOUNT_TAB)))
        if stop_event.is_set():
            raise InterruptedError("已取消登录")
        if not self.is_ready():
            if not password:
                raise ValueError("当前需要账号密码登录，请填写密码后再次点击“登录并准备”")
            self.wait.until(EC.element_to_be_clickable(ACCOUNT_TAB)).click()
            account_input = self.wait.until(EC.visibility_of_element_located(USERNAME_INPUT))
            account_input.clear()
            account_input.send_keys(username)
            password_input = self.driver.find_element(*PASSWORD_INPUT)
            password_input.clear()
            password_input.send_keys(password)
            self.driver.find_element(By.CSS_SELECTOR, "button.login-btn").click()
            self.log("正在登录；如浏览器提示安全验证，请在浏览器完成，工具会继续等待。")

            def authenticated(driver):
                if stop_event.is_set():
                    return True
                for alert in driver.find_elements(By.CSS_SELECTOR, "[role='alert']"):
                    if alert.is_displayed() and alert.text.strip():
                        raise ValueError(f"学校登录提示：{alert.text.strip()}")
                return urlsplit(driver.current_url).hostname == urlsplit(TARGET_URL).hostname

            WebDriverWait(self.driver, 300).until(authenticated)
            if stop_event.is_set():
                raise InterruptedError("已取消登录")
            self.log("登录成功，正在进入谈心谈话…")
            self.driver.get(TARGET_URL)
            self.wait.until(lambda d: stop_event.is_set() or self.is_ready())
            if stop_event.is_set():
                raise InterruptedError("已取消登录")
        self.log("谈心谈话列表已就绪，可以开始录入。")

    def get_record_count(self):
        text = self.driver.find_element(By.ID, "rzxxTable").get_attribute("textContent")
        match = re.search(r"总记录数\s*(\d+)", text)
        if not match:
            raise AutomationError("未找到系统列表的总记录数，已停止录入")
        return int(match.group(1))

    def fill_and_save(self, item):
        self.stage = "打开新增表单"
        self.driver.find_element(By.ID, "rzxx_AddButton").click()
        student_input = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.jqx-combobox-input")))
        student_input.clear()
        student_input.send_keys(item["id"])
        self.stage = "等待学生搜索结果"
        option = self.wait.until(EC.visibility_of_any_elements_located((
            By.XPATH, f"//div[@role='option' and contains(., '{item['id']}')]"
        )))[0]
        if item["name"] not in option.text:
            raise AutomationError(f"学号 {item['id']} 的搜索结果姓名不符，已停止保存")
        option.click()
        self.stage = "等待学生信息加载"
        self.wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "input[name='SJH']").get_attribute("value").strip())
        self.stage = "填写并核对谈话信息"
        for name, caption in [("THLB", "日常谈话"), ("THSD", item["slot"])]:
            radio = self.driver.find_element(By.XPATH, f"//input[@name='{name}' and @data-caption='{caption}']/..")
            self.driver.execute_script("arguments[0].click();", radio)
        for selector, value in [
            ("div[data-name='THRQ'] input[bh-form-role='dateTimeInput']", item["date"]),
            ("input[name='THSCXS']", str(item["duration"] // 60)),
            ("input[name='THSCFZ']", str(item["duration"] % 60)),
            ("textarea[name='THNR']", item["content"]),
        ]:
            element = self.driver.find_element(By.CSS_SELECTOR, selector)
            element.clear()
            element.send_keys(value)
            element.send_keys(Keys.TAB)
            if element.get_attribute("value") != value:
                raise AutomationError(f"{item['name']} 的 {selector} 填写结果不符，已停止保存")
        for name, caption in [("THLB", "日常谈话"), ("THSD", item["slot"])]:
            radio = self.driver.find_element(By.CSS_SELECTOR, f"input[name='{name}'][data-caption='{caption}']")
            if not radio.is_selected():
                raise AutomationError(f"{item['name']} 未正确选中 {caption}，已停止保存")

        # 观察学校自己的保存请求，不替换页面保存逻辑，也不自动重试提交。
        self.driver.execute_script("""
            window.__ssAutoFoldSaveResponse = null;
            jQuery(document).off('ajaxComplete.ssAutoFoldSave')
                .on('ajaxComplete.ssAutoFoldSave', function(event, xhr, settings) {
                    if (new URL(settings.url, location.href).pathname.endsWith('/gztb/saveTxthData.do')) {
                        window.__ssAutoFoldSaveResponse = {status: xhr.status, body: xhr.responseText};
                        jQuery(document).off('ajaxComplete.ssAutoFoldSave');
                    }
                });
        """)
        # 先留下待确认标记。保存后网络中断时，下次由使用者核对，避免直接重复提交。
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        self.stage = "点击保存"
        self.driver.find_element(By.ID, "saveTxthBtn").click()
        self.stage = "等待学校返回保存结果"
        response = self.wait.until(lambda d: d.execute_script("return window.__ssAutoFoldSaveResponse;"))
        if response["status"] != 200:
            raise AutomationError(f"学校保存请求返回 HTTP {response['status']}，保存结果仍需核对")
        result = json.loads(response["body"])
        if str(result["code"]) != "0":
            self.pending_path.unlink()
            raise AutomationError(f"学校未保存这条记录：{result['msg']}")
        append_progress(self.progress_path, item)
        self.pending_path.unlink()
        self.log(f"学校已确认保存：{item['name']}")
        self.stage = "等待已保存的表单关闭"
        self.wait.until(EC.invisibility_of_element_located((By.ID, "saveTxthBtn")))

    def import_records(self, records, limit=IMPORT_LIMIT, stop_event=None, on_progress=None):
        if self.pending_path.exists():
            raise AutomationError("上次有一条保存结果尚未确认，请先在工具中完成核对")
        if not self.is_ready():
            raise AutomationError("谈心谈话列表尚未就绪，请重新登录并准备")
        stop_event = stop_event if stop_event is not None else Event()
        done = completed_keys(self.progress_path)
        pending = [item for item in records if item["key"] not in done][:limit]
        count = 0
        for index, item in enumerate(pending, 1):
            if stop_event.is_set():
                break
            self.log(f"[{index}/{len(pending)}] 正在录入 {item['name']}（{item['id']}）")
            self.fill_and_save(item)
            count += 1
            if on_progress is not None:
                on_progress(count, len(pending), item["name"])
        self.log(f"本次学校已确认新增 {count} 条。")
        return count

    def close_browser(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def run(self, records, debugger_address=None):
        # 保留命令行试录的累计 10 条限制；桌面界面使用“本次新增条数”。
        remaining = IMPORT_LIMIT - len(completed_keys(self.progress_path))
        if remaining <= 0:
            self.log("已累计完成 10 条试录，未继续导入。")
            return
        self.open_browser(debugger_address=debugger_address)
        self.driver.get(TARGET_URL)
        if not debugger_address:
            input("请登录并进入谈心谈话列表，完成后按回车：")
        self.wait.until(lambda d: self.is_ready())
        self.import_records(records, limit=remaining)
        self.driver.save_screenshot(str(self.base_dir / "试录结果.png"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="谈心谈话试录 10 条，跳过未来日期")
    parser.add_argument("--check", action="store_true", help="只检查 Excel，不启动浏览器、不提交")
    parser.add_argument("--debugger-address", help="接管已开启调试端口的 Chrome")
    args = parser.parse_args()
    app = AutoCounselorFixed()
    records = app.load_specific_excel()
    for item in records:
        print(f"{item['id']} {item['name']} {item['date']} {item['slot']} {item['duration']}分钟")
    if not args.check:
        app.run(records, args.debugger_address)
