"""All user-visible text, in one place, for both languages.

The installer inherits the pattern already used by the repo: Chinese-first
output (tools/install-debian13.sh) with an English companion (tools/kosctl).
``--lang`` overrides the locale-derived default.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_TEXT = {
    "title": ("KOS 安装器", "KOS Installer"),
    "subtitle": (
        "检测发行版，选择已经存在的安装方式并执行。",
        "Detect the distribution, choose the install path that already exists, run it.",
    ),
    "start": ("开始", "Start"),
    "quit": ("退出", "Quit"),
    "cancel": ("取消", "Cancel"),
    "retry": ("重试", "Retry"),
    "skip": ("跳过", "Skip"),
    "abort": ("中止", "Abort"),
    "components": ("组件", "Components"),
    "checks_passed": ("项检测通过", "checks passed"),
    "details_hint": ("按 d 查看全部检测项 · F5 重新检测", "d for all checks · F5 re-check"),
    "step_review": ("确认", "Review"),
    "step_install": ("安装", "Install"),
    "step_result": ("完成", "Finish"),
    "probe_os": ("操作系统", "Operating system"),
    "probe_arch": ("架构", "Architecture"),
    "probe_session": ("会话类型", "Session type"),
    "probe_plasma": ("Plasma 桌面", "Plasma desktop"),
    "probe_kwin": ("KWin 版本", "KWin version"),
    "probe_quickshell": ("Quickshell 版本", "Quickshell version"),
    "probe_disk": ("磁盘空间", "Disk space"),
    "probe_git": ("Git", "Git"),
    "probe_python": ("Python", "Python"),
    "probe_sudo": ("sudo 授权", "sudo access"),
    "probe_manager": ("包管理器", "Package manager"),
    "probe_packages": ("构建依赖", "Build packages"),
    "method": ("安装方式", "Install path"),
    "method_debian": ("使用 tools/install-debian13.sh（apt、backports、代理、构建、校验）",
                      "tools/install-debian13.sh (apt, backports, proxy, build, verify)"),
    "method_kosctl": ("使用 tools/kosctl（装依赖、构建、部署、接管桌面）",
                      "tools/kosctl (deps, build, deploy, takeover)"),
    "method_nixos": ("使用 tools/kosctl nix install（flake）",
                     "tools/kosctl nix install (flake)"),
    "method_report": ("只给出该发行版的手册命令，不执行安装",
                      "Prints the manual commands for this distribution; runs nothing"),
    "method_unknown": ("无法识别的发行版，只给出最接近的手册链接",
                       "Unknown distribution; prints the closest manual recipe"),
    "opt_source": ("来源版本", "Source release"),
    "opt_apps": ("可选应用", "Optional apps"),
    "opt_lockscreen": ("锁屏主题", "Lock screen theme"),
    "opt_spatial": ("景深/空间壁纸", "Depth / 3D wallpaper"),
    "opt_spatial_hint": ("额外拉 OpenCV + ONNX（约 150 MB）", "pulls OpenCV + ONNX (~150 MB)"),
    "opt_proxy": ("代理", "Proxy"),
    "on": ("开", "on"),
    "off": ("关", "off"),
    "unset": ("未设置", "unset"),
    "review_title": ("安装确认", "Review"),
    "review_warn": ("以下命令将以你的用户身份执行：", "These commands will run as you:"),
    "review_target": ("安装到 ~/.local（用户目录，无需 root）", "Installs to ~/.local (user directory, no root)"),
    "review_takeover_short": ("完成后接管 plasmashell（重新登录生效）",
                              "takes over plasmashell · effective after the next login"),
    "review_apps_missing": ("应用依赖缺失", "app dependencies missing"),
    "review_apps_ok": ("应用依赖齐全", "app dependencies present"),
    "review_none": ("该发行版没有自动安装路径。", "No automatic path for this distribution."),
    "install_title": ("安装执行", "Installation"),
    "phase_idle": ("等待开始", "waiting"),
    "failed": ("失败", "failed"),
    "cancelled": ("已取消", "cancelled"),
    "log_hint": ("日志：", "Log: "),
    "cancel_confirm": ("确定取消安装？当前步骤会被终止。", "Cancel the install? The current step will be terminated."),
    "skipped_source": ("当前 checkout 有未提交改动或不在 main，跳过来源选择。",
                       "Checkout is dirty or not on main; source selection skipped."),
    "success_title": ("安装完成", "Install finished"),
    "failure_title": ("安装失败", "Install failed"),
    "next_steps": ("注销并重新登录，使 KWin 插件和桌面接管生效。",
                   "Log out and back in so KWin plugins and the desktop takeover apply."),
    "row_system": ('系统检查', 'System checks'),
    "row_manage": ('管理已安装单元', 'Manage installed units'),
    "row_install": ('安装', 'Install'),
    "system_title": ('系统检查', 'System checks'),
    "system_ok": ('全部通过', 'all passed'),
    "system_issues": ('项需注意', 'need attention'),
    "step_menu": ('菜单', 'Menu'),
    "step_system": ('检查', 'Checks'),
    "step_manage": ('管理', 'Manage'),
    "opt_start": ('安装后立即启动', 'Start after install'),
    "manage_units": ('单元', 'Units'),
    "manage_snapshots": ('快照', 'Snapshots'),
    "manage_doctor": ('Doctor', 'Doctor'),
    "manage_logs": ('日志', 'Logs'),
    "manage_uninstall": ('卸载', 'Uninstall'),
    "manage_empty": ('还没有安装任何单元。', 'Nothing installed yet.'),
    "units_title": ('已安装单元', 'Installed units'),
    "units_hint": ('Space 启用/停用 · Esc 返回', 'Space enable/disable · Esc back'),
    "units_none": ('未记录任何单元；先完成一次安装。', 'No units recorded; install first.'),
    "snapshots_title": ('配置快照', 'Config snapshots'),
    "snapshots_create": ('新建快照', 'Create snapshot'),
    "snapshots_none": ('还没有快照。', 'No snapshots yet.'),
    "snapshots_hint": ('Space 新建 · Enter 回滚所选 · Esc 返回', 'Space create · Enter roll back the selection · Esc back'),
    "action_title": ('执行', 'Running'),
    "action_done": ('完成', 'done'),
    "action_failed": ('失败', 'failed'),
    "action_hint": ('Enter 返回', 'Enter back'),
    "log_title": ('日志', 'Log'),
    "log_hint": ('↑↓ 滚动 · Esc 返回', '↑↓ scroll · Esc back'),
    "logs_none": ('还没有日志。', 'No logs yet.'),
    "confirm_uninstall": ('卸载核心并撤销桌面接管？', 'Uninstall core and revert the desktop takeover?'),
    "confirm_rollback": ('回滚到这个快照？当前配置会先自动备份。', 'Roll back to this snapshot? The current config is backed up first.'),
    "hint_menu": ('↑↓ 移动 · Space 切换 · Enter 进入 · q 退出', '↑↓ move · Space toggle · Enter open · q quit'),
    "hint_system": ('Enter/Esc 返回 · F5 重新检测', 'Enter/Esc back · F5 re-check'),
    "hint_units": ('Space 启用/停用 · Esc 返回', 'Space enable/disable · Esc back'),
    "hint_snapshots": ('Space 新建 · Enter 回滚 · Esc 返回', 'Space create · Enter roll back · Esc back'),
    "hint_manage": ('↑↓ 移动 · Enter 进入 · Esc 返回', '↑↓ move · Enter open · Esc back'),
    "detail_system": ('12 项环境检查：发行版、会话、KWin、Quickshell、磁盘、sudo、包管理器、构建依赖。', 'Twelve checks: distro, session, KWin, Quickshell, disk, sudo, package manager, build packages.'),
    "detail_source": ('stable = 最新发布 tag；main = 开发分支。只在 checkout 位于 main 且干净时才会执行 update。', 'stable = latest release tag; main = development. Only runs when the checkout is clean and on main.'),
    "detail_apps": ('日历、待办、天气、计算器，装进 ~/.local；需要 KF6 的 calendarcore 和 pkgconf。', 'Calendar, Todo, Weather, Calculator into ~/.local; needs KF6 calendarcore and pkgconf.'),
    "detail_lockscreen": ('把锁屏主题装进桌面接管包；卸载核心时会一起移除。', 'Installs the lock screen theme into the takeover package; removed with the core install.'),
    "detail_spatial": ('景深引擎 + 3D 壁纸插件。会拉 OpenCV（约 113 MB）和 pin 死的 ONNX Runtime（约 40 MB），构建时间明显变长。', 'Depth engine + 3D wallpaper. Pulls OpenCV (~113 MB) and the pinned ONNX Runtime (~40 MB); the build takes noticeably longer.'),
    "detail_start": ('安装完成后立刻执行 kosctl start（会重启用户服务）；关掉则等下次登录。', 'Runs kosctl start right after the install (restarts user services); otherwise it waits for the next login.'),
    "detail_manage": ('单元开关、配置快照与回滚、doctor、日志、卸载。', 'Unit toggles, config snapshots and rollback, doctor, logs, uninstall.'),
    "detail_install": ('进入确认页：先列出将要执行的命令，再开始安装。', 'Opens the review: it lists the commands before anything runs.'),
    "detail_hint": ('当前值', 'current'),
    "row_settings": ('安装设置', 'Install settings'),
    "menu_back": ('返回', 'Back'),
    "crumb_root": ('主菜单', 'Main menu'),
    "detail_settings": ('来源版本与三个可选组件。Enter 进入，Esc 返回。', 'Source release and the three optional components. Enter opens, Esc goes back.'),
    "detail_back": ('返回上一级菜单。', 'Back to the previous menu.'),
    "app_calendar": ('日历', 'Calendar'),
    "app_todo": ('待办', 'Todo'),
    "app_weather": ('天气', 'Weather'),
    "app_calculator": ('计算器', 'Calculator'),
    "welcome_version": ('选择版本', 'Select version'),
    "branch_main": ('main（开发分支）', 'main (development)'),
    "branch_release": ('release（最新发布）', 'release (latest)'),
    "hint_version": ('↑↓ 选择 · Enter 继续 · Esc 返回', '↑↓ select · Enter continue · Esc back'),
    "why_probe_os": ('决定走哪条安装路径：Debian 用包装脚本，Arch/Fedora 用 kosctl，其它发行版只给手册命令。', 'Decides the install path: the Debian wrapper, kosctl on Arch/Fedora, a manual recipe elsewhere.'),
    "why_probe_arch": ('只有 x86_64 和 aarch64 有准备好的依赖；其它架构缺 ONNX 运行时。', 'Only x86_64 and aarch64 have prepared dependencies; other architectures lack the ONNX runtime.'),
    "why_probe_session": ('KOS 是 Wayland shell，X11 或纯控制台下起不来，只能显示成墙纸。', 'KOS is a Wayland shell; under X11 or a bare console it cannot come up.'),
    "why_probe_plasma": ('安装做的是接管 plasmashell，没有 Plasma 就没有可接管的桌面。', 'The install takes over plasmashell; without Plasma there is no desktop to take over.'),
    "why_probe_kwin": ('原生特效/装饰和 KWin 的 ABI 绑定，6.6 以下加载不了。', "Native effects and the decoration bind to KWin's ABI; below 6.6 they cannot load."),
    "why_probe_quickshell": ('Shell 需要 0.3.x；缺失时由安装步骤负责补上。', 'The shell needs 0.3.x; the install step provides it when missing.'),
    "why_probe_disk": ('构建树加依赖约 3–5 GB，低于 6 GB 会在编译中途失败。', 'Build tree plus dependencies need ~3–5 GB; under 6 GB the build dies halfway.'),
    "why_probe_git": ('用来取源码和切换发布标签，缺了安装器无法开始。', 'Fetches the source and checks out release tags; without it the installer cannot start.'),
    "why_probe_python": ('安装器和 kosctl 的辅助脚本都依赖 python3。', "The installer and kosctl's helper scripts both need python3."),
    "why_probe_sudo": ('装系统包和写 /usr 需要 root；提前授权，避免十几分钟的构建被打断。', 'Package installs and /usr writes need root; priming it avoids interrupting a long build.'),
    "why_probe_manager": ('决定构建依赖和运行期集成由哪个包管理器装。', 'Decides which package manager installs the build and runtime packages.'),
    "why_probe_packages": ('这些包由 kosctl install 通过包管理器补上，通常是几十秒。', 'These are added by kosctl install through the package manager, usually seconds.'),
    "row_deps": ('依赖包', 'Packages'),
    "deps_title": ('构建依赖（%s）', 'Build packages (%s)'),
    "deps_summary": ('已安装 %d/%d', '%d/%d installed'),
    "deps_empty": ("读不到依赖列表（kosctl deps 失败）", "Could not read the package list (kosctl deps failed)"),
    "deps_scroll_hint": ("PgUp/PgDn 滚动", "PgUp/PgDn to scroll"),
    "deps_hint": ('↑↓ 滚动 · Enter/Esc 返回', '↑↓ scroll · Enter/Esc back'),
    "review_deps_missing": ('依赖缺失：%s', 'missing packages: %s'),
    "review_deps_hint": ('[i] 先安装这些依赖（kosctl deps --install）', '[i] install them first (kosctl deps --install)'),
    "review_deps_ok": ('依赖齐全', 'dependencies present'),
    "label_system": ("系统", "System"),
    "hint_setup": ("↑↓ 移动 · Space 切换 · Enter 下一步 · d 详情 · q 退出",
                   "↑↓ move · Space toggle · Enter next · d details · q quit"),
    "hint_review": ("Enter 开始安装 · Esc 返回", "Enter install · Esc back"),
    "hint_install": ("Ctrl+C 取消", "Ctrl+C cancel"),
    "hint_result": ("Enter 退出 · r 重试", "Enter quit · r retry"),
    "note_no_cjk": ("未找到中文字体，改用英文界面（--lang zh 可强制中文）",
                    "no CJK font found; showing English (--lang zh forces Chinese)"),
}


def effective_locale(env: dict) -> str:
    """glibc's precedence: LC_ALL, then LC_MESSAGES, then LANG, then LANGUAGE."""
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = (env.get(key) or "").split(":")[0].strip()
        if value:
            return value
    return ""


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


class Strings:
    def __init__(self, lang: str) -> None:
        self.lang = lang

    def __call__(self, key: str) -> str:
        pair = _TEXT.get(key)
        if pair is None:
            return key
        return pair[0] if self.lang == "zh" else pair[1]
