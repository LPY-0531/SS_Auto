import time
import os
import random
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区域 =================

# 1. 目标网址
TARGET_URL = "https://ss.xjtu.edu.cn/" 

# 2. Excel 文件名 (必须在同目录下)
EXCEL_FILE = "Conversation_Ylq.xlsx"

# ===========================================

class AutoCounselorExcel:
    def __init__(self):
        # 1. 读取 Excel
        if not os.path.exists(EXCEL_FILE):
            raise FileNotFoundError(f"找不到文件: {EXCEL_FILE}")
        
        print(f"📖 正在读取 {EXCEL_FILE} ...")
        self.df = pd.read_excel(EXCEL_FILE, dtype={'学号': str})
        
        try:
            self.df['谈话日期'] = pd.to_datetime(self.df['谈话日期']).dt.strftime('%Y-%m-%d')
        except: pass
            
        self.df = self.df.fillna('')
        print(f"✅ 读取成功，共 {len(self.df)} 条待填记录。")

        # 2. 初始化浏览器 (Eager模式加速)
        options = webdriver.ChromeOptions()
        options.page_load_strategy = 'eager' # 关键优化：不等图片加载完就开始操作
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        # 【关键】加回这两个参数，确保所有内网组件（即使是不安全的）都能加载，防止控件失效
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 5) # 缩短等待时间

    def handle_blocking_dialog(self):
        """
        查杀阻断弹窗 (高效版)
        """
        try:
            # 优先检查当前上下文，速度最快
            btns = self.driver.find_elements(By.CSS_SELECTOR, "a.bh-dialog-btn.bh-bg-primary")
            for btn in btns:
                if btn.is_displayed():
                    print("  🔨 [拦截] 发现警告弹窗，正在点击【确定】...")
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.5) 
                    return True
        except: pass
        return False

    def ensure_form_context(self):
        """确保当前处在表单上下文中 (只在迷路时调用)"""
        # 1. 先快速检查当前是否还在表单里
        try:
            if len(self.driver.find_elements(By.CSS_SELECTOR, "input.jqx-combobox-input")) > 0:
                return True
        except: pass

        print("🔄 正在重新定位表单...")
        
        # 2. 检查新窗口
        try:
            handles = self.driver.window_handles
            if len(handles) > 1:
                self.driver.switch_to.window(handles[-1])
                # 切窗口后检查一下主文档
                if len(self.driver.find_elements(By.CSS_SELECTOR, "input.jqx-combobox-input")) > 0:
                    print("  ✅ 重新锁定表单 (主文档)")
                    return True
        except: pass

        # 3. 遍历 iframe (只找可见的)
        try:
            self.driver.switch_to.default_content()
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                if not frame.is_displayed(): continue # 跳过不可见的，加速！
                try:
                    self.driver.switch_to.frame(frame)
                    if len(self.driver.find_elements(By.CSS_SELECTOR, "input.jqx-combobox-input")) > 0:
                        print("  ✅ 重新锁定表单 (Iframe)")
                        return True
                    self.driver.switch_to.default_content()
                except:
                    self.driver.switch_to.default_content()
                    continue
        except: pass
        
        return False

    def run(self):
        print("🚀 启动脚本 (Excel高效版)...")
        self.driver.get(TARGET_URL)
        print("\n" + "="*60)
        print("【操作指引】")
        print("1. 请手动登录并进入【工作日志】。")
        print("2. 点击【新增】按钮。")
        print("3. 回到这里，按回车开始。")
        print("="*60 + "\n")
        input(">>> 准备就绪，按回车开始 >>>")

        # 首次定位
        while not self.ensure_form_context():
            print("  ⏳ 等待【新增】弹窗出现...", end='\r')
            time.sleep(1)

        for index, row in self.df.iterrows():
            stu_id = str(row['学号']).strip()
            date_str = str(row['谈话日期']).strip()
            time_slot = str(row['谈话时段']).strip()
            duration = str(row['谈话时长']).strip()
            assist_type = str(row['帮扶形式']).strip() 
            content = str(row['谈话内容'])

            print(f"\n[{index+1}/{len(self.df)}] 正在处理: {stu_id}")

            try:
                # 检查上下文，防止上一轮操作跑偏
                self.ensure_form_context()
                self.handle_blocking_dialog() # 清理残留弹窗

                # =================================================
                # 1. 学号
                # =================================================
                input_stu = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.jqx-combobox-input")))
                input_stu.click()
                time.sleep(0.2)
                input_stu.send_keys(Keys.CONTROL, 'a')
                input_stu.send_keys(Keys.BACK_SPACE)
                input_stu.send_keys(stu_id)
                print("  已输入学号，等待检测弹窗...")
                
                # 【关键】输入后立即检测弹窗，不等待搜索结果
                time.sleep(0.5)
                if self.handle_blocking_dialog():
                    print("  ✅ 成功拦截并关闭弹窗")
                
                # 等待搜索结果
                time.sleep(1.5)
                
                # 再次检测，防止弹窗有延迟
                self.handle_blocking_dialog()

                try:
                    # 查找下拉项 (role='option')
                    target_xpath = f"//div[@role='option']//*[contains(text(),'{stu_id}')]"
                    target_opt = self.driver.find_element(By.XPATH, target_xpath)
                    target_opt.click()
                    print("  ✅ 已选中学生")
                except:
                    # 如果点不到下拉，且没有弹窗，可能是因为只有一个结果且被回车默认选中了
                    # 这里尝试回车兜底
                    input_stu.send_keys(Keys.ENTER)

                time.sleep(1.0)
                self.handle_blocking_dialog() # 选完人后再次确认

                # =================================================
                # 2. 帮扶形式
                # =================================================
                if assist_type and assist_type.lower() != 'nan':
                    print(f"  正在填写帮扶: {assist_type}...")
                    try:
                        # 找 data-caption="帮扶形式"
                        assist_widget = self.driver.find_element(By.XPATH, "//div[@data-caption='帮扶形式']")
                        
                        # 滚动并点击展开
                        self.driver.execute_script("arguments[0].scrollIntoView(false);", assist_widget)
                        self.driver.execute_script("arguments[0].click();", assist_widget)
                        time.sleep(1.0)

                        # 点击选项
                        opt_xpath = f"//div[@role='option']//span[contains(text(), '{assist_type}')] | //div[@role='option' and contains(., '{assist_type}')]"
                        assist_opt = WebDriverWait(self.driver, 3).until(
                            EC.visibility_of_element_located((By.XPATH, opt_xpath))
                        )
                        self.driver.execute_script("arguments[0].click();", assist_opt)
                        print(f"  ✅ 已选中: {assist_type}")

                    except Exception as e:
                        print(f"  ℹ️ 帮扶填写跳过: {e}")

                # =================================================
                # 3. 谈话类别 (默认点日常谈话)
                # =================================================
                try:
                    cate_ele = self.driver.find_element(By.XPATH, "//input[@name='THLB' and @data-caption='日常谈话']/..")
                    self.driver.execute_script("arguments[0].click();", cate_ele)
                except: pass

                # =================================================
                # 4. 日期
                # =================================================
                try:
                    date_xpath = "//label[contains(text(),'谈话日期')]/following::input[@bh-form-role='dateTimeInput']"
                    date_input = self.driver.find_element(By.XPATH, date_xpath)
                    
                    self.driver.execute_script(f"""
                        arguments[0].value = '{date_str}'; 
                        arguments[0].dispatchEvent(new Event('input'));
                        arguments[0].dispatchEvent(new Event('change'));
                        arguments[0].dispatchEvent(new Event('blur'));
                    """, date_input)
                    print(f"  ✅ 日期已填: {date_str}")
                except Exception as e:
                    print(f"  ⚠️ 日期填写失败: {e}")

                # =================================================
                # 5. 时段
                # =================================================
                if time_slot and time_slot.lower() != 'nan':
                    try: 
                        xpath_slot = f"//input[@name='THSD'][@data-caption='{time_slot}']/.."
                        slot_ele = self.driver.find_element(By.XPATH, xpath_slot)
                        self.driver.execute_script("arguments[0].scrollIntoView(false);", slot_ele)
                        self.driver.execute_script("arguments[0].click();", slot_ele)
                        print(f"  ✅ 已选时段: {time_slot}")
                    except:
                        print(f"  ⚠️ 无法选择时段: {time_slot}")

                # =================================================
                # 6. 时长
                # =================================================
                if duration and duration.lower() != 'nan':
                    try: 
                        duration_input = self.driver.find_element(By.CSS_SELECTOR, "input[name='THSC']")
                        val = str(int(float(duration)))
                        self.driver.execute_script(f"arguments[0].value = '{val}'; arguments[0].dispatchEvent(new Event('input'));", duration_input)
                        print(f"  ✅ 已填时长: {val}分钟")
                    except: pass

                # =================================================
                # 7. 内容
                # =================================================
                try: 
                    content_area = self.driver.find_element(By.CSS_SELECTOR, "textarea[name='THNR']")
                    content_area.clear()
                    content_area.send_keys(content)
                except: pass

                # =================================================
                # 8. 保存
                # =================================================
                try:
                    save_btn = self.driver.find_element(By.ID, "saveTxthBtn")
                    self.driver.execute_script("arguments[0].click();", save_btn)
                    print(f"  ✅ 点击保存")
                    time.sleep(2.0) # 保存通常需要一点时间
                    
                    self.handle_blocking_dialog() # 再次检查是否有报错弹窗

                    # 尝试点击新增 (如果有的话)
                    try:
                        add_btn = self.driver.find_element(By.XPATH, "//button[contains(text(),'新增')]")
                        if add_btn.is_displayed():
                            print("  点击【新增】准备下一条...")
                            add_btn.click()
                            time.sleep(1.0)
                    except: pass

                except:
                    print("  ⚠️ 找不到保存按钮")

            except Exception as e:
                print(f"  ❌ 本条出错: {e}")

if __name__ == "__main__":
    AutoCounselorExcel().run()