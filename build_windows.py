"""在 Mac 或 Windows 上组装 Windows x64 免安装包。"""
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.request import urlretrieve

BASE = Path(__file__).resolve().parent
VERSION = "3.13.17"
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
cache = BASE / ".windows-build" / stamp
package = BASE / "dist" / f"谈话记录助手-Windows-x64-{stamp}"
wheels = cache / "wheels"
wheels.mkdir(parents=True)
package.mkdir(parents=True)

print("下载 Windows Python 和依赖…", flush=True)
python_zip = cache / "python-embed.zip"
urlretrieve(f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip", python_zip)
subprocess.run([
    sys.executable, "-m", "pip", "download", "--only-binary=:all:",
    "--platform", "win_amd64", "--implementation", "cp", "--python-version", "313",
    "--abi", "cp313", "--dest", str(wheels), "-r", str(BASE / "requirements-windows.txt"),
], check=True)

runtime = package / "runtime"
with zipfile.ZipFile(python_zip) as archive:
    archive.extractall(runtime)
site_packages = runtime / "Lib" / "site-packages"
site_packages.mkdir(parents=True)
for wheel in sorted(wheels.glob("*.whl")):
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site_packages)
(runtime / "python313._pth").write_text(
    "python313.zip\n.\nLib/site-packages\n..\nimport site\n", encoding="utf-8",
)
# 通用构建仅包含代码和说明，不依赖或打包本地学生进度。
for name in ["new.py", "desktop_app.py", "launch.pyw", "requirements.txt", "requirements-windows.txt", "Windows使用说明.txt", "README.md"]:
    shutil.copy2(BASE / name, package / name)
(package / "双击启动.cmd").write_text(
    '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
    'start "" "%~dp0runtime\\pythonw.exe" "%~dp0launch.pyw"\r\n', encoding="ascii",
)
(package / "仅测试登录.cmd").write_text(
    '@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
    'start "" "%~dp0runtime\\pythonw.exe" "%~dp0launch.pyw" --login-only\r\n', encoding="ascii",
)
for required in [
    runtime / "pythonw.exe", runtime / "python313.dll",
    site_packages / "PySide6" / "QtWidgets.pyd",
    site_packages / "PySide6" / "plugins" / "platforms" / "qwindows.dll",
    site_packages / "selenium" / "webdriver" / "common" / "windows" / "selenium-manager.exe",
]:
    if not required.is_file():
        raise FileNotFoundError(f"Windows 包缺少文件：{required}")
print("压缩免安装包…", flush=True)
archive_path = shutil.make_archive(str(package), "zip", package.parent, package.name)
print(f"已生成：{archive_path}", flush=True)
