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
    "back": ("返回", "Back"),
    "next": ("下一步", "Next"),
    "confirm": ("确认安装", "Install"),
    "cancel": ("取消", "Cancel"),
    "retry": ("重试", "Retry"),
    "skip": ("跳过", "Skip"),
    "abort": ("中止", "Abort"),
    "env_title": ("环境检测", "Environment"),
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
    "options_title": ("参数配置", "Configuration"),
    "opt_source": ("来源版本", "Source release"),
    "opt_apps": ("可选应用", "Optional apps"),
    "opt_lockscreen": ("锁屏主题", "Lock screen theme"),
    "opt_start": ("安装后立即启动", "Start after install"),
    "opt_all": ("连同应用与锁屏一并安装", "Include apps and lock screen"),
    "opt_proxy": ("使用环境中的代理", "Use proxy from environment"),
    "on": ("开", "on"),
    "unset": ("未设置", "unset"),
    "off": ("关", "off"),
    "review_title": ("安装确认", "Review"),
    "review_warn": ("以下命令将以你的用户身份执行：", "These commands will run as you:"),
    "review_none": ("该发行版没有自动安装路径。", "No automatic path for this distribution."),
    "install_title": ("安装执行", "Installation"),
    "phase_idle": ("等待开始", "waiting"),
    "done": ("已完成", "done"),
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
    "log_path": ("日志目录", "Logs"),
    "press_any": ("按任意键返回", "Press any key"),
    "note_no_cjk": ("未找到中文字体，改用英文界面（--lang zh 可强制中文）",
                    "no CJK font found; showing English (--lang zh forces Chinese)"),
    "label_system": ("系统", "System"),
    "label_target": ("安装到", "Installs to"),
    "target_value": ("~/.local（用户目录，不需要 root）", "~/.local (user directory, no root)"),
    "hint_welcome": ("Enter 开始 · q 退出", "Enter start · q quit"),
    "hint_environment": ("Enter 继续 · Esc 返回 · F5 重新检测", "Enter continue · Esc back · F5 re-check"),
    "hint_options": ("↑↓ 移动 · Space 切换 · Enter 下一步 · Esc 返回",
                     "↑↓ move · Space toggle · Enter next · Esc back"),
    "hint_review": ("Enter 开始安装 · Esc 返回", "Enter install · Esc back"),
    "hint_install": ("Ctrl+C 取消", "Ctrl+C cancel"),
    "hint_result": ("Enter 退出 · r 重试", "Enter quit · r retry"),
    "no_plan": ("没有可执行的步骤。", "Nothing to run."),
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
