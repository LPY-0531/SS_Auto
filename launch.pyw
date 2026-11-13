"""Windows 双击入口：启动失败时显示日志位置。"""
import ctypes
import os
import sys
import traceback
from pathlib import Path


def report_error(error_type, error, stack):
    folder = Path(os.environ["LOCALAPPDATA"]) / "ssAutoFold" / "CounselorAssistant"
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "error.log"
    log.write_text("".join(traceback.format_exception(error_type, error, stack)), encoding="utf-8")
    ctypes.windll.user32.MessageBoxW(None, f"程序已停止。错误详情保存在：\n{log}", "谈话记录助手", 0x10)
    os._exit(1)


sys.excepthook = report_error
from desktop_app import main

main()
