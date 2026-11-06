"""All user-visible text, in one place, for both languages.

The installer inherits the pattern already used by the repo: Chinese-first
output (tools/install-debian13.sh) with an English companion (tools/kosctl).
``--lang`` overrides the locale-derived default.
"""

from __future__ import annotations

from functools import lru_cache
import os
import shutil
import subprocess
from pathlib import Path

_TEXT = {
    "title": ("KOS 安装器", "KOS Installer"),
    "start": ("开始", "Start"),
    "quit": ("退出", "Quit"),
    "cancel": ("取消", "Cancel"),
    "retry": ("重试", "Retry"),
    "skip": ("跳过", "Skip"),
    "abort": ("中止", "Abort"),
    "components": ("组件", "Components"),
    "step_review": ("确认", "Review"),
    "step_install": ("安装", "Install"),
    "probe_os": ("操作系统", "Operating system"),
    "probe_arch": ("架构", "Architecture"),
    "probe_plasma": ("Plasma 版本", "Plasma version"),
    "probe_graphics": ("图形平台", "Graphics platform"),
    "probe_kwin": ("KWin 版本", "KWin version"),
    "probe_quickshell": ("Quickshell 版本", "Quickshell version"),
    "probe_qt": ("Qt 版本", "Qt version"),
    "probe_disk": ("磁盘空间", "Disk space"),
    "probe_sudo": ("sudo 授权", "sudo access"),
    "probe_manager": ("包管理器", "Package manager"),
    "probe_packages": ("构建依赖", "Build packages"),
    "method": ("安装方式", "Method"),
    "method_wrapper": ("使用 tools/install-debian13.sh（apt、backports、代理、构建、校验）",
                       "tools/install-debian13.sh (apt, backports, proxy, build, verify)"),
    "method_kosctl": ("使用 tools/kosctl（装依赖、构建、部署、接管桌面）",
                      "tools/kosctl (deps, build, deploy, takeover)"),
    "method_nixos": ("使用 tools/kosctl nix install（flake）",
                     "tools/kosctl nix install (flake)"),
    "method_report": ("只给出该发行版的手册命令，不执行安装",
                      "Prints the manual commands for this distribution; runs nothing"),
    "method_unknown": ("无法识别的发行版，只给出最接近的手册链接",
                       "Unknown distribution; prints the closest manual recipe"),
    "opt_lockscreen": ("锁屏主题", "Lock screen theme"),
    "opt_spatial": ("景深/空间壁纸", "Depth / 3D wallpaper"),
    "opt_proxy": ("代理", "Proxy"),
    "on": ("开", "on"),
    "off": ("关", "off"),
    "review_target": ("安装到 ~/.local", "Installs to ~/.local"),
    "review_none": ("该发行版没有自动安装路径。", "No automatic path for this distribution."),
    "failed": ("失败", "failed"),
    "cancelled": ("已取消", "cancelled"),
    "cancel_confirm": ("确定取消安装？当前步骤会被终止。", "Cancel the install? The current step will be terminated."),
    "skipped_source": ("当前 checkout 有未提交改动或不在 main，跳过来源选择。",
                       "Checkout is dirty or not on main; source selection skipped."),
    "skipped_local": ("本地源码模式：沿用当前 checkout，不切换版本。",
                      "Local source mode: the current checkout is used as is."),
    "success_title": ("安装完成", "Install finished"),
    "failure_title": ("安装失败", "Install failed"),
    "next_steps": ("注销并重新登录，使 KWin 插件和桌面接管生效。",
                   "Log out and back in so KWin plugins and the desktop takeover apply."),
    "row_manage": ('管理已安装单元', 'Manage installed units'),
    "step_system": ('检查', 'Checks'),
    "opt_start": ('安装后立即启动', 'Start after install'),
    "manage_units": ('单元', 'Units'),
    "manage_snapshots": ('快照', 'Snapshots'),
    "manage_doctor": ('Doctor', 'Doctor'),
    "manage_logs": ('日志', 'Logs'),
    "manage_uninstall": ('卸载', 'Uninstall'),
    "manage_empty": ('还没有安装任何单元。', 'Nothing installed yet.'),
    "units_title": ('已安装单元', 'Installed units'),
    "units_none": ('未记录任何单元；先完成一次安装。', 'No units recorded; install first.'),
    "snapshots_title": ('配置快照', 'Config snapshots'),
    "snapshots_create": ('新建快照', 'Create snapshot'),
    "snapshots_none": ('还没有快照。', 'No snapshots yet.'),
    "action_title": ('执行', 'Running'),
    "log_title": ('日志', 'Log'),
    "log_path": ('日志：', 'Log: '),
    "logs_none": ('还没有日志。', 'No logs yet.'),
    "confirm_uninstall": ('卸载核心并撤销桌面接管？', 'Uninstall core and revert the desktop takeover?'),
    "confirm_rollback": ('回滚到这个快照？当前配置会先自动备份。', 'Roll back to this snapshot? The current config is backed up first.'),
    "confirm": ('确认', 'Confirm'),
    "confirm_uninstall_word": ('输入 uninstall 确认', 'Type uninstall to confirm'),
    "dialog_keys": ("←/→ 或 h/l 选择 · ⏎ 确认 · esc 取消",
                    "←/→ or h/l choose · ⏎ confirm · esc cancel"),
    "unit_core_locked": ('core 不能关闭；要移除请用卸载。', 'core cannot be switched off; use uninstall'),
    "action_ok": ('操作完成', 'Action finished'),
    "action_failed": ('操作失败', 'Action failed'),
    "detail_source_stable": ('使用最新的稳定发布，适合日常使用；安装时会准备对应的源码。',
                             'Uses the latest stable release, the usual choice for everyday use; the install prepares that source.'),
    "detail_source_main": ('跟随 main 的最新提交，能提前用到新功能，也可能遇到未测试的改动。',
                           'Follows the tip of main: new features early, plus changes that may not be tested yet.'),
    "detail_source_local": ('直接使用当前检出的分支和工作区，不拉取也不切换；未提交的修改会一起构建。',
                            'Uses the checkout as it is: no fetch, no switch, and uncommitted changes are built too.'),
    "detail_app_calendar": ('日历与任务：日程、提醒和待办集中在一个应用里。',
                            'Calendar with tasks: events, reminders and to-dos in one app.'),
    "detail_app_todo": ('待办事项清单，适合记录临时事项。',
                        'A to-do list for quick, temporary notes.'),
    "detail_app_weather": ('天气与逐小时预报；可与桌面上的天气组件共用数据。',
                           'Weather and hourly forecast; it can share data with the desktop weather widget.'),
    "detail_app_calculator": ('键盘优先的快速计算器，适合日常计算。',
                              'A keyboard-first calculator for everyday sums.'),
    "detail_lockscreen": ('把锁屏主题装进桌面接管包；卸载核心时会一起移除。', 'Installs the lock screen theme into the takeover package; removed with the core install.'),
    "detail_spatial": ('景深引擎 + 3D 壁纸插件。会拉 OpenCV（约 113 MB）和固定版本的 ONNX Runtime（约 40 MB），构建时间明显变长。', 'Depth engine + 3D wallpaper. Pulls OpenCV (~113 MB) and the pinned ONNX Runtime (~40 MB); the build takes noticeably longer.'),
    "detail_start": ('安装完成后立刻执行 kosctl start（会重启用户服务）；关掉则等下次登录。', 'Runs kosctl start right after the install (restarts user services); otherwise it waits for the next login.'),
    "detail_manage": ('单元开关、配置快照与回滚、doctor、日志、卸载。', 'Unit toggles, config snapshots and rollback, doctor, logs, uninstall.'),
    "app_calendar": ('日历', 'Calendar'),
    "app_todo": ('待办', 'Todo'),
    "app_weather": ('天气', 'Weather'),
    "app_calculator": ('计算器', 'Calculator'),
    "why_probe_arch": ('x86_64 和 aarch64 有现成的依赖与 ONNX 运行时。', 'x86_64 and aarch64 have prepared dependencies and the ONNX runtime.'),
    "why_probe_plasma": ('需要 6.x 及以上', '6.x or newer is required'),
    "why_probe_graphics": ('KOS 是 Wayland shell；X11 或纯 TTY 会话里无法启动。', 'KOS is a Wayland shell; it cannot start under X11 or a bare TTY session.'),
    "why_probe_kwin": ('需要 6.6 及以上', '6.6 or newer is required'),
    "why_probe_quickshell": ('需要 0.3.x', '0.3.x is required'),
    "why_probe_qt": ('需要 6.6 及以上', '6.6 or newer is required'),
    "why_probe_disk": ('源码树和依赖约占 3–5 GiB；低于 6 GiB 时编译可能中途失败。', 'Source tree and dependencies take about 3–5 GiB; under 6 GiB the build may die halfway.'),
    # Recovery text for a probe, in the UI language; detect.py's English remedy
    # is the fallback for a probe that has no pair here.
    "remedy_probe_os": ("读取 /etc/os-release；无法识别这台系统。",
                        "Read /etc/os-release; this system is not identifiable."),
    "remedy_probe_arch": ("只有 x86_64 和 aarch64 经过测试。",
                          "Only x86_64 and aarch64 are tested."),
    "remedy_probe_plasma": ("安装或升级 KDE Plasma 6。",
                            "Install or upgrade KDE Plasma 6."),
    "remedy_probe_graphics": ("请在 Plasma 6 的 Wayland 会话里运行，而不是 X11 或纯 TTY。",
                              "Run inside a Plasma 6 Wayland session, not X11 or a bare TTY."),
    "remedy_probe_kwin": ("需要 KWin 6.6+，否则原生插件加载不了。",
                          "KWin 6.6+ is required for the native plugins."),
    "remedy_probe_quickshell": ("需要 Quickshell 0.3.x，安装步骤可以补上。",
                                "Quickshell 0.3.x is required; the install step can provide it."),
    "remedy_probe_qt": ("安装或升级 qt6-base（提供 qmake6 / Qt6Core）。",
                        "Install or upgrade qt6-base (provides qmake6 / Qt6Core)."),
    "remedy_probe_disk": ("构建至少需要 6 GiB 空闲空间。",
                          "At least 6 GiB of free space is needed for the build."),
    "remedy_probe_sudo": ("sudo 需要密码时安装器会询问；也可以先执行 `sudo -v`。",
                          "The installer asks when a step needs it; `sudo -v` beforehand also works."),
    "remedy_probe_manager": ("没有找到受支持的包管理器。",
                             "No supported package manager was found."),
    "remedy_probe_packages": ("kosctl install 会用系统包管理器补上这些包。",
                              "kosctl install adds these with the system package manager."),
    "why_probe_sudo": ('安装系统包和写入 /usr 需要 root；安装器只在需要时询问密码，不会打断构建。', 'Installing system packages and writing to /usr needs root; the installer asks only when needed, so a build is not interrupted.'),
    "sudo_password_body": ("安装软件包和构建环境需要 root",
                           "Needs root for packages and build"),
    "sudo_bar_hint": ("⏎ 继续 · esc 取消", "⏎ continue · esc cancel"),
    "sudo_password_prompt": ("sudo 密码：", "sudo password: "),
    "sudo_prompt": ("[sudo] password for %s: ", "[sudo] password for %s: "),
    "sudo_password_missing": ("未提供 sudo 密码，sudo 无法执行，安装已停止。",
                              "No sudo password was provided, so sudo could not run; "
                              "the install stopped."),
    "sudo_needs_password": ("sudo 需要密码，但当前没有终端可以输入。先执行 `sudo -v`，再运行安装器。",
                            "sudo needs a password and there is no terminal to ask on. "
                            "Run `sudo -v` first, then start the installer again."),
    "sudo_password_wrong": ("sudo 拒绝了密码（3 次尝试失败）；密码未保存，请重试。",
                            "sudo rejected the password (3 incorrect password attempts); "
                            "it was not kept, retry to enter it again."),
    "why_probe_manager": ('决定构建依赖和运行期组件由哪个包管理器安装。', 'Decides which package manager installs build and runtime packages.'),
    "why_probe_packages": ('这些包由 kosctl install 通过包管理器补齐，通常只要几十秒。', 'kosctl install adds these through the package manager, usually in seconds.'),
    "deps_title": ('构建依赖（%s）', 'Build packages (%s)'),
    "deps_summary": ('已安装 %d/%d', '%d/%d installed'),
    "review_deps_missing": ('缺少 %s', 'missing %s'),
    "review_deps_ok": ('齐全', 'all present'),
    "review_blocked": ("有检查未通过（❌），安装已禁用。先修好再回来。",
                       "A check failed (❌); the install is disabled until it passes."),
    "unsupported_options": ("当前发行版路径不支持：%s；没有执行任何操作。",
                            "Not supported by this backend: %s; nothing was run."),
    "note_no_cjk": ("未找到中文字体，改用英文界面（--lang zh 可强制中文）",
                    "no CJK font found; showing English (--lang zh forces Chinese)"),
    "note_no_textual": ("未找到 Textual（运行 python3 tools/vendor.py），改用纯文本模式。",
                        "Textual not found (run python3 tools/vendor.py); using plain mode."),

    # -- wizard chrome -------------------------------------------------
    "step_welcome": ("欢迎", "Welcome"),
    "step_options": ("安装设置", "Options"),
    "step_of": ("步骤 %d/%d", "Step %d/%d"),
    "nav_manage": ("管理", "Manage"),
    "notice_big": ("终端太小：至少 %dx%d，当前 %dx%d", "Terminal too small: need %dx%d, have %dx%d"),
    "listing_range": ("%d–%d / %d", "%d–%d / %d"),

    # -- welcome -------------------------------------------------------
    "welcome_intro": ("为 KDE Plasma 打造的 Quickshell 桌面。\n"
                      "液态玻璃、浮动 Dock，以及可以随心打造的专属工作空间。",
                      "A Quickshell desktop for KDE Plasma.\n"
                      "Liquid glass, a floating dock, and a workspace you can make your own."),
    "label_distro": ("发行版", "Distribution"),
    "label_arch": ("架构", "Architecture"),
    "label_session": ("会话", "Session"),
    "label_path": ("安装位置", "Install path"),
    "label_language": ("语言", "Language"),
    "label_source": ("安装来源", "Source"),
    "label_repo": ("源码仓库", "Repository"),
    "label_ref": ("版本", "Ref"),
    "label_commit": ("提交", "Commit"),
    "label_workspace": ("源码工作区", "Workspace"),
    "label_dirty": ("工作区状态", "Workspace state"),
    "label_apps": ("可选应用", "Optional apps"),
    "label_deps": ("依赖", "Dependencies"),
    "label_core": ("核心", "Core"),
    "label_required": ("必需", "required"),
    "welcome_start": ("开始安装", "Start"),
    "source_stable": ("稳定发布", "Stable release"),
    "source_main": ("开发分支 main", "Development branch main"),
    "source_local": ("本地源码", "Local checkout"),
    "label_local_path": ("路径", "Path"),
    "local_detecting": ("正在检测本地源码…", "Looking for a local checkout…"),
    "local_not_found": ("未找到 NextKDE 检出；按 ctrl+e 输入路径",
                        "No NextKDE checkout found; ctrl+e to enter a path"),
    "local_path_title": ("本地源码路径", "Local checkout path"),
    "local_path_body": ("输入 NextKDE 检出的根目录；支持 ~。",
                        "Root of a NextKDE checkout; ~ is allowed."),
    "local_path_use": ("使用此路径", "Use this path"),
    "local_path_empty": ("请输入一个路径", "Enter a path"),
    "local_path_checking": ("正在验证这个路径…", "Checking this path…"),

    # -- system checks -------------------------------------------------
    "system_head": ("系统兼容性", "System compatibility"),
    "system_counts": ("通过 %d · 注意 %d · 失败 %d", "%d pass · %d warn · %d fail"),
    "check_what": ("检查内容", "Checked"),
    "check_why": ("说明", "Notes"),
    "check_result": ("检测结果", "Detected"),
    "check_status": ("状态", "Status"),
    "check_fixable": ("安装器能否处理", "Installer can fix"),
    "check_fix_yes": ("可以，由安装步骤完成", "Yes, the install steps do it"),
    "check_fix_no": ("不行，需要你先处理", "No, fix it first"),
    "check_remedy": ("恢复方法", "How to fix"),
    "check_none": ("没有可用的检测结果", "No check results"),
    "os_note_arch": ("Arch 系，使用 kosctl", "Arch family, uses kosctl"),
    "os_note_debian": ("Debian 系，使用 install-debian13.sh",
                       "Debian family, uses install-debian13.sh"),
    "os_note_ubuntu": ("Ubuntu 系，使用 kosctl", "Ubuntu family, uses kosctl"),
    "os_note_fedora": ("Fedora 系，使用 kosctl", "Fedora family, uses kosctl"),
    "os_note_opensuse": ("openSUSE 系，仅提供手动命令",
                         "openSUSE family, manual commands only"),
    "os_note_nixos": ("NixOS，使用 kosctl nix install",
                      "NixOS, uses kosctl nix install"),
    "os_note_unknown": ("未识别的发行版，仅提供手册命令",
                        "Unrecognized distribution, manual commands only"),
    "status_pass": ("通过", "pass"),
    "status_warn": ("注意", "warn"),
    "status_fail": ("失败", "fail"),

    # -- options -------------------------------------------------------
    "options_head": ("安装设置", "Install settings"),
    "group_source": ("1. 安装来源", "1. Installation source"),
    "group_core": ("2. 核心组件", "2. Core components"),
    "group_optional": ("3. 可选应用", "3. Optional apps"),
    "group_advanced": ("4. 高级选项", "4. Advanced options"),
    "core_shell": ("KOS Shell", "KOS Shell"),
    "detail_core": ("重写后的 Plasma 桌面：面板、启动器、锁屏与 KWin 插件；必需组件，不能取消。",
                    "The rebuilt Plasma desktop: panels, launcher, lock screen, KWin plugins; required, cannot be turned off."),

    # -- review --------------------------------------------------------
    "review_head": ("安装确认", "Review"),
    "review_summary": ("摘要", "Summary"),
    "review_steps": ("将执行的步骤", "Steps that will run"),
    "review_resolving": ("正在解析源码…", "Resolving the source…"),
    "review_side": ("提示", "Notes"),
    "review_details": ("[Ctrl+E] 展开完整命令", "[Ctrl+E] show full commands"),
    "review_details_on": ("[Ctrl+E] 收起完整命令", "[Ctrl+E] hide full commands"),
    "review_side_takeover": ("安装会接管 plasmashell，注销重新登录后生效。",
                             "The install takes over plasmashell; it applies after a log out and back in."),
    "review_side_session": ("安装后会重启用户服务，当前桌面会短暂闪断。",
                            "User services restart after the install; the current session blips."),
    "review_side_userpath": ("文件写入 ~/.local，不需要 root；系统包由包管理器安装。",
                             "Files go to ~/.local, no root needed; system packages come from the package manager."),
    "review_side_log": ("完整输出写入日志文件。", "Full output goes to a log file."),
    "review_no_steps": ("没有可执行的安装步骤。", "No install steps to run."),
    "review_unsupported": ("当前安装路径不支持：%s；这些选择不会执行。",
                           "Not supported by this install path: %s; those choices will not run."),
    "review_skip_missing": ("依赖未装齐，安装可能中途失败。", "Dependencies are missing; the install may fail halfway."),
    "review_apps_none": ("无", "none"),
    "review_cmd": ("命令", "command"),
    "review_dirty": ("有未提交修改，会一起构建", "uncommitted changes are built too"),
    "review_clean": ("干净", "clean"),
    "prepare_running": ("正在准备源码…", "preparing source…"),
    "prepare_failed": ("源码准备失败", "Source preparation failed"),
    "review_prepare_failed": ("源码准备（git clone）失败，没有安装任何内容。",
                               "Preparing the source (git clone) failed; nothing was installed."),
    "review_error_keys": ("[Ctrl+R] 重试 · [Ctrl+L] 日志 · [Esc] 返回",
                          "[Ctrl+R] retry · [Ctrl+L] log · [Esc] back"),
    "advice_network": ("看起来是网络问题：检查代理或网络后重试。",
                       "Looks like a network problem: check the proxy or the connection, then retry."),
    "advice_tag": ("这个版本标签还没有发布：换回稳定发布或 main 再试。",
                   "That release tag is not published: pick the stable release or main instead."),
    "advice_credentials": ("凭据被拒绝：检查 git 的 SSH key 或凭据助手后重试。",
                           "Credentials were refused: check the git SSH key or credential helper, then retry."),
    "advice_permissions": ("没有权限写入目标目录：检查目录所有者与权限后重试。",
                           "No permission to write into the target directory: "
                           "check its owner and permissions, then retry."),
    "confirm_heading": ("确认安装", "Ready to install"),
    "confirm_summary": ("将执行 %d 个步骤", "Steps to run: %d"),
    "confirm_install": ("开始安装", "Start the install"),
    "confirm_back": ("返回上一步", "Go back"),
    "confirm_yes": ("确认（开始安装）", "Confirm (install)"),
    "confirm_no": ("取消（返回上一步）", "Cancel (back)"),
    "backend_label": ("后端", "Backend"),
    "backend_incompatible": ("后端不兼容：%s", "Incompatible backend: %s"),
    "cap_unavailable": ("不可用，后端未提供 %s", "unavailable, backend lacks %s"),
    "step_count": ("%d 个步骤", "%d steps"),

    # -- install dashboard ---------------------------------------------
    "install_head": ("安装执行", "Installation"),
    "install_running": ("正在安装", "Installing"),
    "install_cancelling": ("正在取消…", "Cancelling…"),
    "install_done": ("安装完成", "Finished"),
    "install_failed": ("安装失败", "Failed"),
    "install_stage": ("阶段", "Phase"),
    "install_elapsed": ("已用 %s", "%s elapsed"),
    "install_step_progress": ("已完成 %d/%d 步", "%d/%d steps done"),
    "install_log_live": ("自动滚动", "auto-scroll"),
    "install_log_paused": ("已暂停自动滚动，↑↓ 查看历史", "auto-scroll paused, ↑↓ to read back"),
    "stage_done": ("完成", "done"),
    "stage_running": ("进行中", "running"),
    "stage_failed": ("失败", "failed"),
    "stage_skipped": ("跳过", "skipped"),
    "stage_waiting": ("等待", "waiting"),

    # -- result --------------------------------------------------------
    "result_ran": ("已完成的操作", "What ran"),
    "result_components": ("已安装组件", "Installed components"),
    "result_exit_code": ("退出码", "Exit code"),
    "result_error": ("错误摘要", "Error summary"),
    "result_tail": ("日志末尾", "Log tail"),
    "result_retry_safe": ("重试只重复未完成的步骤", "retry repeats only what did not finish"),
    "result_none_logged": ("没有输出", "no output"),
    "result_skipped": ("已跳过：%s", "skipped: %s"),
    "result_cancelled": ("安装已取消，没有完成。", "The install was cancelled before it finished."),
    "result_units_none": ("（未记录组件）", "(no components recorded)"),

    # -- footer key labels ---------------------------------------------
    "key_move": ("移动", "move"),
    "key_select": ("选择", "select"),
    "key_confirm": ("确认", "confirm"),
    "key_open": ("打开", "open"),
    "key_toggle": ("切换", "toggle"),
    "key_cycle": ("选择", "choose"),
    "key_continue": ("继续", "continue"),
    "key_back": ("返回", "back"),
    "key_previous": ("上一步", "back"),

    "key_start": ("开始安装", "start install"),
    "key_help": ("帮助", "help"),
    "key_refresh": ("重新检测", "re-check"),
    "key_cancel": ("取消", "cancel"),
    "key_pause": ("暂停日志", "pause log"),
    "key_resume": ("继续滚动", "resume log"),
    "key_scroll": ("滚动", "scroll"),
    "key_details": ("命令详情", "details"),
    "key_commands": ("命令", "commands"),
    "key_retry": ("重试", "retry"),
    "key_log": ("日志", "log"),

    "key_language": ("语言", "language"),
    "key_create": ("新建", "create"),
    "key_rollback": ("回滚", "roll back"),
    "key_deps": ("安装依赖", "install deps"),
    "key_next": ("下一步", "next"),
    "key_abort": ("中止", "abort"),
    "key_install": ("开始安装", "install"),
    "key_ends": ("首末", "first/last"),
    "key_below": ("下方选项", "options below"),
    "key_path": ("路径", "path"),
    "key_page": ("翻页", "page"),
    "key_focus_next": ("下一项", "next field"),
    "key_focus_prev": ("上一项", "previous field"),
    "menu_goto": ("直达", "go to"),
    "menu_back": ("返回", "Back"),
    "manage_need_units": ("不可用：未安装", "unavailable: nothing installed"),
    "manage_need_logs": ("不可用：没有日志", "unavailable: no logs"),
    "ctrl_c_hint": ("再按一次 Ctrl+C 退出", "Press Ctrl+C again to quit"),
    "cmd_title": ("命令", "Commands"),
    "cmd_here": ("当前页面", "current page"),
    "cmd_log": ("当前日志", "Current log"),
    "cmd_refresh": ("重新检测", "Re-check"),
    "cmd_help": ("帮助", "Help"),
    "cmd_details": ("查看计划 / 命令详情", "Plan / command details"),
    "cmd_keys": ("↑/↓ 选择 · ←/→ 调整 · ⏎ 运行 · esc 关闭",
                 "↑/↓ select · ←/→ adjust · ⏎ run · esc close"),
    "cmd_language": ("语言", "Language"),
    "cmd_no_log": ("还没有日志", "no log yet"),
    "cmd_need_local": ("仅在本地源码时可用", "local checkout only"),
    "cmd_plan_unavailable": ("计划不可用", "plan unavailable"),
    "about_title": ("关于", "About"),
    "about_version": ("版本", "Version"),
    "about_python": ("Python", "Python"),
    "about_installer": ("安装器", "Installer"),
    "about_source": ("源码", "Source"),
    "about_state": ("状态", "State"),
    "help_title": ("快捷键", "Keys"),
    "help_close": ("任意键关闭", "any key closes"),
    "help_heading": ("当前页面可用的按键：", "Keys on this page:"),
}


def effective_locale(env: dict) -> str:
    """glibc's precedence: LC_ALL, then LC_MESSAGES, then LANG, then LANGUAGE."""
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = (env.get(key) or "").split(":")[0].strip()
        if value:
            return value
    return ""


def terminal_is_utf8(env: dict | None = None) -> bool:
    """Whether the terminal itself is UTF-8, not whether Python thinks so.

    Python coerces a C/POSIX locale to UTF-8 (PEP 538), so
    ``sys.stdout.encoding`` says utf-8 on a terminal that cannot draw "✔".
    The environment locale is the honest signal.
    """
    env = os.environ if env is None else env
    return _is_utf8(env, effective_locale(env))


def ascii_terminal(env: dict | None = None) -> bool:
    """One signal for every glyph decision: no Unicode on this terminal.

    The Linux console has no line drawing or status glyphs at all, and a
    non-UTF-8 locale cannot encode them; both fall back to ASCII.
    """
    env = os.environ if env is None else env
    return env.get("TERM") == "linux" or not terminal_is_utf8(env)


def _is_utf8(env: dict, locale: str) -> bool:
    charset = locale.split(".", 1)[1] if "." in locale else ""
    if "utf" in charset.lower():
        return True
    return "utf" in (env.get("LC_CTYPE") or "").lower()


_CJK_PATTERNS = ("*CJK*", "*wqy*", "*WenQuanYi*", "*SourceHan*", "*DroidSansFallback*")

_FONT_DIRS = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local" / "share" / "fonts",
)


def cjk_fonts_available(env: dict | None = None) -> bool:
    """Whether this terminal can actually draw Chinese.

    A UTF-8 locale is not enough: without a CJK font every glyph is a box, and
    the Linux console has no CJK glyphs at all regardless of what is installed.
    """
    env = os.environ if env is None else env
    if env.get("TERM") == "linux":
        return False
    fontconfig = shutil.which("fc-list")
    if fontconfig:
        try:
            result = subprocess.run(
                [fontconfig, ":lang=zh", "family"],
                capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            return bool(result.stdout.strip())
    for directory in _FONT_DIRS:
        if not directory.is_dir():
            continue
        for pattern in _CJK_PATTERNS:
            if next(directory.rglob(pattern), None) is not None:
                return True
    return False


def nerd_font_available(env: dict | None = None) -> bool:
    """Whether a Nerd Font is installed; the sudo prompt uses its lock glyph.

    This is a fontconfig probe, not a promise that the terminal is using that
    font: KOS_NERD_FONT=0/1 overrides it when the terminal differs.
    """
    env = os.environ if env is None else env
    choice = env.get("KOS_NERD_FONT", "").strip().lower()
    if choice in ("1", "true", "yes", "on"):
        return True
    if choice in ("0", "false", "no", "off"):
        return False
    return _fontconfig_has_nerd_font()


@lru_cache(maxsize=1)
def _fontconfig_has_nerd_font() -> bool:
    """The fontconfig probe once per process; the bar composes on every page."""
    fontconfig = shutil.which("fc-list")
    if not fontconfig:
        return False
    try:
        result = subprocess.run([fontconfig, ":family"], capture_output=True,
                                text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "nerd font" in result.stdout.lower()


def resolve_lang(explicit: str | None, env: dict | None = None,
                 cjk_ok: bool | None = None) -> str:
    """Pick zh or en: explicit flag, then the locale, then the project default.

    C and POSIX mean "no preference", not "English"; they get Chinese when the
    terminal can render it, and stay ASCII otherwise.
    """
    if explicit in ("zh", "en"):
        return explicit
    env = os.environ if env is None else env
    locale = effective_locale(env)
    base = locale.lower().split(".", 1)[0].split("@", 1)[0]
    if base.startswith("zh"):
        return "zh" if cjk_ok is not False else "en"
    if base and base not in ("c", "posix"):
        return "en"
    if not _is_utf8(env, locale):
        return "en"
    return "zh" if cjk_ok is not False else "en"


def choose_language(explicit: str | None, env: dict | None = None,
                    probe=None) -> tuple[str, bool]:
    """Resolve the language and say whether a font check forced a fallback.

    The font probe only runs when the locale actually asks for Chinese, so an
    English or German machine never pays for a fontconfig lookup.
    """
    preferred = resolve_lang(explicit, env)
    if explicit or preferred != "zh":
        return preferred, False
    fonts = (probe or cjk_fonts_available)()
    return ("zh", False) if fonts else ("en", True)


_ASCII_PUNCTUATION = {"·": "|", "—": "-", "…": "..."}


class Strings:
    def __init__(self, lang: str) -> None:
        self.lang = lang
        # Punctuation a non-UTF-8 terminal cannot show is transliterated; the
        # words themselves are unchanged.
        self.ascii = ascii_terminal()

    def __call__(self, key: str) -> str:
        pair = _TEXT.get(key)
        if pair is None:
            return key
        text = pair[0] if self.lang == "zh" else pair[1]
        if self.ascii:
            for source, target in _ASCII_PUNCTUATION.items():
                text = text.replace(source, target)
        return text
