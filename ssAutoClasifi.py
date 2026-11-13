import time
import random
import calendar
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区域 =================

# 仍然从服务大厅进入
TARGET_URL = "https://ss.xjtu.edu.cn/" 
TARGET_YEAR = 2025
TARGET_MONTH = 11

STUDENT_IDS = [
    # 在这里继续添加学号...
]

# ===========================================

class AutoCounselorFinal:
    def __init__(self):
        options = webdriver.ChromeOptions()
        # 防拦截、防检测配置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        # 允许跨域iframe交互
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 5) 

    def generate_ai_content(self):
        openings = ["近期与该生进行交流，", "在宿舍走访中与该生交谈，", "课后与该生了解情况，", "主动约谈该生，"]
        topics = ["询问了近期的学习状态", "了解了宿舍人际关系", "关心了近期的情绪状态", "询问了职业规划意向", "提醒了近期防诈骗事项"]
        details = ["，学生表示压力适中。", "，学生反馈舍友关系融洽。", "，学生状态良好。", "，已提醒其注意休息。", "，学生情绪稳定。"]
        conclusions = ["后续将持续关注。", "已叮嘱有困难及时联系。", "目前情况稳定。", "鼓励其保持积极心态。"]
        return f"{random.choice(openings)}{random.choice(topics)}{random.choice(details)}{random.choice(conclusions)}"

    def get_random_date(self, year, month):
        last_day = calendar.monthrange(year, month)[1]
        while True:
            day = random.randint(1, last_day)
            try:
                if calendar.weekday(year, month, day) < 5: return f"{year}-{month:02d}-{day:02d}"
            except: continue

    def find_form_context(self):
        """自动寻找表单所在的窗口或iframe"""
        print("🔍 正在寻找表单...")
        
        # 1. 检查新窗口
        handles = self.driver.window_handles
        if len(handles) > 1:
            self.driver.switch_to.window(handles[-1])
            time.sleep(1)

        # 2. 检查主文档
        try:
            self.driver.find_element(By.CSS_SELECTOR, "input.jqx-combobox-input")
            print("  ✅ 找到表单（在主页面）")
            return True
        except:
            pass

        # 3. 遍历iframe
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        for i, frame in enumerate(iframes):
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(frame)
                self.driver.find_element(By.CSS_SELECTOR, "input.jqx-combobox-input")
                print(f"  ✅ 找到表单（在第 {i+1} 个 iframe）")
                return True
            except:
                continue
        
        print("❌ 未找到表单，请确认您已打开【新增】弹窗。")
        return False

    def run(self):
        print("🚀 启动脚本 (日期随机修复版)...")
        self.driver.get(TARGET_URL)
        print("\n" + "="*60)
        print("【操作指引】")
        print("1. 请手动登录并进入【工作日志】。")
        print("2. 点击【新增】按钮，确保看到填报弹窗。")
        print("3. 回到这里，按回车。")
        print("="*60 + "\n")
        input(">>> 准备就绪，按回车开始 >>>")

        if not self.find_form_context():
            return

        for index, stu_id in enumerate(STUDENT_IDS):
            print(f"\n[{index+1}/{len(STUDENT_IDS)}] 正在处理: {stu_id}")
            try:
                # =================================================
                # 1. 学号 (保持您确认可用的逻辑)
                # =================================================
                input_stu = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.jqx-combobox-input")))
                input_stu.click()
                time.sleep(0.3)
                input_stu.send_keys(Keys.CONTROL, 'a')
                input_stu.send_keys(Keys.BACK_SPACE)
                input_stu.send_keys(stu_id)
                print("  已输入学号，等待搜索...")
                time.sleep(2.0) 

                try:
                    # 查找下拉项 (role='option')
                    target_xpath = f"//div[@role='option']//*[contains(text(),'{stu_id}')]"
                    target_opt = WebDriverWait(self.driver, 5).until(
                        EC.visibility_of_element_located((By.XPATH, target_xpath))
                    )
                    target_opt.click()
                    print("  ✅ 已选中学生")
                except:
                    print("  ⚠️ 没点到下拉项，尝试回车...")
                    input_stu.send_keys(Keys.ENTER)

                time.sleep(1.5)

                # =================================================
                # 2. 谈话类别 (默认点日常谈话)
                # =================================================
                try:
                    # 定位 name='THLB' 且文字为 '日常谈话' 的选项
                    cate_ele = self.driver.find_element(By.XPATH, "//input[@name='THLB' and @data-caption='日常谈话']/..")
                    self.driver.execute_script("arguments[0].click();", cate_ele)
                except: pass

                # =================================================
                # 3. 日期 (修复：精准定位可见的日期框)
                # =================================================
                try:
                    rand_date = self.get_random_date(TARGET_YEAR, TARGET_MONTH)
                    print(f"  生成随机日期: {rand_date}") 
                    
                    # 关键修复：使用 XPath 定位紧跟在“谈话日期”标签后的输入框
                    # 这样可以避开页面上其他隐藏的 dateTimeInput
                    date_xpath = "//label[contains(text(),'谈话日期')]/following::input[@bh-form-role='dateTimeInput']"
                    date_input = self.driver.find_element(By.XPATH, date_xpath)
                    
                    self.driver.execute_script(f"""
                        arguments[0].value = '{rand_date}'; 
                        arguments[0].dispatchEvent(new Event('input'));
                        arguments[0].dispatchEvent(new Event('change'));
                        arguments[0].dispatchEvent(new Event('blur'));
                    """, date_input)
                    print(f"  ✅ 已填入日期: {rand_date}")
                except Exception as e:
                    print(f"  ⚠️ 日期填写失败: {e}")

                # =================================================
                # 4. 谈话时段 (根据源码 name='THSD' 精准定位)
                # =================================================
                print("  选择时段...")
                try: 
                    slot_name = random.choice(['上午', '中午', '下午', '晚上'])
                    # 滚动到可见区域，防止被挡住
                    xpath_slot = f"//input[@name='THSD'][@data-caption='{slot_name}']/.."
                    slot_ele = self.driver.find_element(By.XPATH, xpath_slot)
                    self.driver.execute_script("arguments[0].scrollIntoView(false);", slot_ele)
                    time.sleep(0.5)
                    self.driver.execute_script("arguments[0].click();", slot_ele)
                    print(f"  ✅ 已选: {slot_name}")
                except Exception as e:
                    print(f"  ⚠️ 时段选择失败: {e}")
                
                # =================================================
                # 5. 谈话时长 (根据源码 name='THSC' 强力注入)
                # =================================================
                print("  填写时长...")
                try: 
                    # 找到输入框
                    duration_input = self.driver.find_element(By.CSS_SELECTOR, "input[name='THSC']")
                    val = str(random.randint(20, 40))
                    
                    # 这里的 input 往往被一个 div 遮挡，所以用 JS 直接设置值是最稳的
                    self.driver.execute_script(f"""
                        arguments[0].value = '{val}'; 
                        arguments[0].dispatchEvent(new Event('input'));
                        arguments[0].dispatchEvent(new Event('change'));
                    """, duration_input)
                    print(f"  ✅ 已填: {val}分钟")
                except Exception as e:
                    print(f"  ⚠️ 时长填写失败: {e}")

                # =================================================
                # 6. 谈话内容 (根据源码 name='THNR')
                # =================================================
                try: 
                    content_area = self.driver.find_element(By.CSS_SELECTOR, "textarea[name='THNR']")
                    content_area.send_keys(self.generate_ai_content())
                except: pass

                # =================================================
                # 7. 保存
                # =================================================
                try:
                    save_btn = self.driver.find_element(By.ID, "saveTxthBtn")
                    self.driver.execute_script("arguments[0].click();", save_btn)
                    print(f"  ✅ 保存成功")
                    time.sleep(3.0)
                except:
                    print("  ⚠️ 找不到保存按钮")

            except Exception as e:
                print(f"  ❌ 出错: {e}")

if __name__ == "__main__":
    AutoCounselorFinal().run()
