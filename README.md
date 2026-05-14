# 微信本地右上角弹窗提醒工具

这是一个本地运行、隐私友好的 Windows 微信通知增强工具。它不会读取、破解、解密或访问微信数据库，不注入微信进程，不模拟登录，不自动回复、转发、点击聊天，也不会保存、上传或打印聊天内容、联系人列表、账号信息或登录信息。

默认效果：检测到微信新消息相关信号后，在屏幕右上角显示一个接近 macOS 通知横幅的深色半透明弹窗：

```text
微信
给你发送了一条新消息
```

如果你显式开启 `show_sender`，且系统公开窗口标题或 macOS 系统通知横幅能稳定提供联系人/群聊名称，才会显示：

```text
XXX
给你发送了一条微信消息
```

无法稳定获取时不会伪造名称，直接回退为“微信”。

## 技术方案比较

Python 方案：

- 优点：安装简单，代码短，便于你自己修改；Tkinter 随 Python 自带，适合做本地小工具和自定义弹窗。
- 缺点：Windows 官方 Notification Listener 属于 UWP/WinRT 能力，普通 Python 桌面脚本无法稳定、通用地读取第三方应用通知内容。
- 本项目采用：Python + Tkinter 自定义横幅 + 安全降级监听。Windows 上主要通过系统公开窗口枚举和状态变化做提醒，拿不到可靠来源时只显示通用文案。

C#/.NET 方案：

- 优点：更适合接入 Windows App SDK / WinRT 通知相关 API，做托盘、开机启动、打包安装体验也更自然。
- 缺点：项目复杂度更高；想读取其他 App 通知仍可能需要受限能力、打包身份或用户授权，不保证能拿到微信通知内容。
- 适用场景：你后续想做成长期使用的 Windows 桌面产品，建议迁移到 C#/.NET。

## 最安全、最稳定的路线

1. 不读微信数据库、不解密、不 Hook、不注入、不模拟操作。
2. 优先使用系统公开 UI/窗口/通知状态作为“有新消息”的信号。
3. 联系人名称默认关闭；开启后也只使用系统已经公开显示的标题或通知横幅文本。
4. 任何不稳定或拿不到来源的情况，都显示“微信 给你发送了一条新消息”。
5. 弹窗只做通知增强：右上角显示、4-6 秒自动消失、队列顺序展示、不抢当前输入焦点。

## 项目结构

```text
.
├── README.md
├── .github/workflows/build-windows-installer.yml
├── build_windows_installer.ps1
├── config.example.json
├── installer.iss
├── requirements.txt
├── setup_macos.sh
└── wechat_local_notifier.py
```

## 安装依赖

Windows 推荐 Python 3.10+，安装 Python 时勾选 `Add python.exe to PATH`，并保留 Tcl/Tk 组件。

```powershell
cd "你的项目目录"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Windows 运行时不需要额外第三方包；`requirements.txt` 里的 macOS 依赖只会在 macOS 安装。

## 配置文件

复制一份本地配置：

```powershell
copy config.example.json config.json
```

常用配置：

- `popup_seconds`：弹窗停留秒数，默认 5。
- `popup_width` / `popup_height`：弹窗宽高，默认 390 x 104。
- `popup_margin_top` / `popup_margin_right`：距离屏幕顶部和右侧的边距，默认 20。
- `show_sender`：是否尝试显示联系人/群聊名称，默认 `false`。
- `play_sound`：是否播放系统提示音，默认 `false`。
- `enable_startup`：运行时自动写入当前 Windows 用户开机启动，默认 `false`。
- `enable_windows_notification_listener`：优先使用 Windows 官方通知监听 API，默认 `true`。
- `notification_cooldown_seconds`：冷却时间，避免短时间重复弹窗。

## 运行

测试弹窗：

```powershell
python wechat_local_notifier.py --config config.json --test-popup
```

开始监听：

```powershell
python wechat_local_notifier.py --config config.json
```

开启联系人名称的最佳努力识别：

```powershell
python wechat_local_notifier.py --config config.json --show-sender
```

调试检测状态，输出会隐藏可能含隐私的微信标题或 OCR 文本：

```powershell
python wechat_local_notifier.py --config config.json --verbose
```

## 最终交付物：Windows 安装包

最终可交付文件建议是：

```text
installer\WeChatLocalNotifierSetup-1.0.0.exe
```

这是给最终用户使用的自包含安装包。用户下载这个安装包后双击安装即可，不需要提前安装 Python、pip、PyInstaller、Inno Setup 或任何项目依赖。

安装包会包含：

- 主程序 `WeChatLocalNotifier.exe`
- 默认配置 `config.json`
- 开始菜单快捷方式
- 可选桌面快捷方式
- 可选开机自启动
- 卸载入口

说明：Python 运行时和 Tkinter 会被 PyInstaller 打进 `WeChatLocalNotifier.exe`，所以最终用户只接触安装包。下面的 Python / Inno Setup 只是在你制作安装包时需要。

### 一键构建安装包

打包人员在 Windows 电脑上安装：

- Python 3.10+
- Inno Setup 6

然后运行：

```powershell
cd "你的项目目录"
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows_installer.ps1 -Version 1.0.0
```

生成结果：

```text
installer\WeChatLocalNotifierSetup-1.0.0.exe
```

这个文件就是可以上传到网盘、GitHub Releases、内网文件服务器后让自己下载使用的安装包。

如果 Inno Setup 没装在默认目录，可以手动指定：

```powershell
.\build_windows_installer.ps1 -Version 1.0.0 -InnoSetupCompiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

### 不用本地 Windows 电脑：GitHub 自动构建

如果你不想自己准备 Windows 打包环境，可以把项目推到 GitHub，然后用 Actions 自动生成安装包：

1. 打开 GitHub 仓库的 `Actions` 页面。
2. 选择 `Build Windows Installer`。
3. 点击 `Run workflow`，输入版本号，例如 `1.0.0`。
4. 等构建完成后，在页面底部 `Artifacts` 下载 `WeChatLocalNotifierSetup-1.0.0`。
5. 解压 artifact，里面的 `WeChatLocalNotifierSetup-1.0.0.exe` 就是最终用户可直接安装的文件。

也可以推送 tag 自动构建：

```powershell
git tag v1.0.0
git push origin v1.0.0
```

### 只打包为 exe

安装 PyInstaller：

```powershell
python -m pip install pyinstaller
```

打包：

```powershell
pyinstaller --onefile --noconsole --name WeChatLocalNotifier wechat_local_notifier.py
```

生成文件在：

```text
dist\WeChatLocalNotifier.exe
```

运行 exe 时建议把 `config.json` 放在 exe 同目录，或显式指定：

```powershell
.\dist\WeChatLocalNotifier.exe --config config.json
```

## 开机自启动

方式一：配置文件启用：

```json
{
  "enable_startup": true
}
```

然后运行一次程序，它会写入当前用户的注册表启动项：

```powershell
python wechat_local_notifier.py --config config.json
```

方式二：命令启用或关闭：

```powershell
python wechat_local_notifier.py --config config.json --enable-startup
python wechat_local_notifier.py --config config.json --disable-startup
```

注册表位置：

```text
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
```

这不需要管理员权限，因为只写当前用户。

## 常见问题

不弹窗：

- 确认微信本身有系统通知或窗口状态变化。
- 如果 Windows 弹出通知访问授权，请允许本工具读取通知；它只读取系统通知元信息，不读取微信数据库。
- 确认 Windows 设置里微信通知已开启，且专注助手/勿扰模式没有拦截通知。
- 先运行 `--test-popup`，确认 Tkinter 弹窗能显示。
- Windows 专注助手、勿扰模式或微信通知设置可能会影响新消息信号。
- 在安全边界内，如果 Windows 没有向脚本暴露可用信号，程序会保守地不读取微信数据库。

不显示联系人名：

- 这是默认隐私策略。
- 设置 `show_sender: true` 或运行 `--show-sender` 后，仍只有在系统公开标题/通知横幅稳定提供来源时才显示。
- 识别失败会显示“微信”，不会猜测或伪造联系人。

弹窗抢焦点：

- 程序已在 Windows 上设置 `WS_EX_NOACTIVATE`，正常不会影响当前打字。
- 少数 Python/Tk/系统组合可能仍会短暂改变焦点，建议打包为 `--noconsole` exe 后再测试。

需要管理员权限吗：

- 普通运行、弹窗、当前用户开机自启动都不需要管理员权限。
- 本项目不使用需要绕过系统安全边界的能力。
- 如果未来接入 Windows 官方 Notification Listener，可能需要打包身份、用户授权或特殊受限能力；不建议为了联系人名称使用高风险方案。

## 隐私承诺

- 不保存聊天内容、联系人列表、账号信息或登录信息。
- 不上传任何数据。
- 默认不打印微信窗口标题或 OCR 文本。
- 只在内存里处理“是否有新消息”和可选的公开来源名称。
- 点击弹窗只尝试激活微信窗口，不自动进入具体聊天，不读取消息。
