# 谈话记录助手

Windows 10/11 x64 桌面工具，复用项目中已验证的 Selenium 填报逻辑。

## 使用

将打包生成的 Windows 压缩包完整解压，双击文件夹里的 `双击启动.cmd`。
包内附带 Windows Python 和依赖。电脑需要安装 Chrome，首次准备驱动需要联网。
源码仓库不包含 Excel、个人进度、浏览器资料、截图或打包产物；构建方法见下方。

选择 Excel，填写学校账号密码，点击“登录并准备”。工具会切换到“账号密码登录”，
并在谈心谈话列表的“新增”按钮可用后启用“开始录入”。默认本次新增 10 条。
首次安全验证在 Chrome 中完成，后续按账号复用固定浏览器资料。
仅验证登录时，可双击 `仅测试登录.cmd`；此模式即使登录成功也保持录入禁用。

已确认保存、未来日期和异常学号会跳过，并显示原因。表格、日期和时长格式见
[Windows使用说明.txt](Windows使用说明.txt)。源表不会被改写。

已确认保存的历史进度保存在本机。已有的 `试录进度.jsonl` 可放在程序或 Excel 同目录，
工具会按记录指纹合并到本机进度，避免再次导入；此文件仅在本地保留，不提交到 Git。
窗口的“本次新增条数”按每批计算；原命令行入口仍保留累计 10 条试录限制。
保存前写入待确认标记，以学校保存接口明确返回成功作为完成依据。列表数量刷新滞后不再误判。
学校拒绝保存时显示具体原因；网络或响应未确认时保留标记，下次开始前先核对这一条。

## 开发与验证

界面入口：`desktop_app.py`；读表、登录和填写：`new.py`。
密码只在本次登录时使用，成功或失败后清空界面密码框。
浏览器资料和导入进度放在系统应用数据目录，Windows 为
`%LOCALAPPDATA%\ssAutoFold\CounselorAssistant`。

```bash
python -m pip install -r requirements.txt
python desktop_app.py
python -m unittest discover -s tests -v
```

macOS 26 开发机使用 Python 3.10 以上和 `requirements-macos.txt` 中的 Qt 6.12，
避免旧 Qt 6.8.3 在 Mac 辅助功能访问时的窗口崩溃。当前电脑的环境为 `.venv-mac`：

```bash
.venv-mac/bin/python desktop_app.py
```

测试在本地模拟站点中运行真实 Chrome，覆盖登录模式切换、错误密码、已登录会话复用、
自动进入列表、中文及换行内容、每批 10 条、后续批次跳过历史、停止边界、列表计数滞后、
学校拒绝保存和保存结果未确认。
界面测试覆盖默认预览、登录门槛、密码清空、异常学号、历史跳过和关闭等待。
测试不会向学校系统提交记录。

已在当前 Mac 上由使用者输入真实账号密码，验证自动切换账号密码登录、登录成功并自动进入
谈心谈话列表；仅登录测试模式未新增记录。Windows 真机运行仍待验证。

## Windows 打包

```bash
python build_windows.py
```

使用 Python 官方 Windows embeddable runtime 和 Windows x64 wheels 组装免安装目录及 ZIP，
可在 Mac 上准备。`requirements-windows.txt` 补充跨平台下载时会遗漏的 Windows 条件依赖。
不会删除已有输出；每次创建带时间的独立目录。
