# NextKDE Installer

# 独立安装器架构设计文档

**Document:** NextKDE Installer Architecture Design
**Version:** 1.0
**Status:** Proposed
**Target:** Linux / KDE Plasma 6 / Wayland
**Primary Language:** Python
**UI Framework:** Python curses
**Backend:** NextKDE kosctl
**Architecture:** Independent Installer + Product Repository

# 1. 项目概述

## 1.1 项目背景

NextKDE 目前已经具有一套 Python TUI 安装器，包含：

- Curses 交互界面。
- Plain Text 非交互模式。
- Linux 发行版识别。
- KDE Plasma、Wayland 和 KWin 环境检测。
- 安装计划生成。
- Stable / Development 源码选择。
- Debian、Arch、Ubuntu、Fedora、NixOS 等安装路径。
- 可选应用与锁屏选择。
- Spatial 构建选项。
- 安装进度和日志。
- 安装失败重试。
- 组件管理、快照管理和卸载入口。

现有代码位于：

```
NextKde/
└── tools/
    └── installer/
```

随着功能增加，安装器已经不再只是一个用于启动安装脚本的简单工具，而是一个包含用户交互、系统检测、源码获取、安装编排和状态管理的完整应用。

继续将它与 NextKDE 产品代码放在同一个仓库中，会产生以下问题：

1. 安装器更新与桌面产品更新相互耦合。
2. 安装器需要跟随产品仓库分支变化。
3. Stable、Development 和本地开发分支容易混淆。
4. 安装器升级可能影响正在使用的产品源码。
5. TUI 无法独立发布和管理版本。
6. 安装器与产品后端的接口缺乏明确约定。

因此，本项目计划将 Python TUI 迁移为独立 Git 仓库。

## 1.2 核心目标

建立一个独立维护、独立发布、可复用的 NextKDE 安装器。

安装器负责：

- 提供交互式安装向导。
- 检查系统环境。
- 管理 NextKDE 源码版本。
- 生成安装计划。
- 调用产品安装后端。
- 显示安装进度和结果。
- 管理安装器自身的更新。

NextKDE 产品仓库继续负责：

- 核心桌面组件。
- Quickshell。
- KWin 插件。
- 系统服务。
- 构建与部署。
- 系统依赖安装。
- 产品组件管理。
- 安装、启动、卸载等实际后端操作。

核心设计原则：

**NextKDE Installer 是独立的产品安装器，NextKDE 是被安装的产品。**

## 1.3 非目标

本项目不打算：

- 将 NextKDE 的构建系统整体复制到 Installer 仓库。
- 在 Python 中重新实现系统级安装逻辑。
- 替代 `kosctl`。
- 取代发行版原生包管理器。
- 强制用户使用 Stable 或 Development。
- 自动修改用户的 Git remote、分支和本地修改。
- 自动重启 KDE Plasma、KWin 或显示管理器。
- 为了 UI 美观引入不必要的 Python 依赖。

# 2. 仓库设计

## 2.1 独立仓库

建议创建：

```
SKJrpg/NextKDE-Installer
```

这是建议的新仓库名称，实际创建时以最终仓库命名为准。

产品仓库：

```
SKJrpg/NextKde
```

两个仓库有不同的开发流程和版本体系。

## 2.2 仓库职责

### NextKDE-Installer

负责安装器本身。

包括：

- Python TUI。
- 安装向导。
- 系统检测。
- Git Source Manager。
- 安装计划。
- 后端调用适配器。
- 日志和进度管理。
- 配置管理。
- 安装器自动更新。
- 安装器 Release。

### NextKDE

负责桌面产品和安装后端。

包括：

- `tools/kosctl`
- `tools/install-debian13.sh`
- `tools/install-apps.sh`
- `tools/kos-state.py`
- CMake 构建系统。
- Quickshell。
- KWin 插件。
- 系统服务。
- 可选应用。
- NixOS 安装配置。
- 产品安装接口规范。

安装器可以调用产品仓库的程序，但不得直接复制或维护另一套产品安装逻辑。

## 2.3 两仓库关系

```
                  User
                   |
                   v
          NextKDE Installer
                   |
       +-----------+-----------+
       |           |           |
       v           v           v
    System      Git Source   TUI / Plan
    Detection   Manager      Orchestrator
                   |
                   v
             NextKDE Source
                   |
                   v
             Backend Contract
                   |
          +--------+--------+
          |                 |
          v                 v
        kosctl        Platform Scripts
          |                 |
          +--------+--------+
                   |
                   v
             NextKDE Desktop
```

依赖方向：

- Installer 依赖 NextKDE 的公开安装接口。
- NextKDE 不依赖 Installer。
- NextKDE 不需要知道 Installer 的 UI 实现。
- Installer 不应依赖 NextKDE 未公开的内部 Python 实现。

# 3. 版本管理策略

两个项目必须有独立版本。

## 3.1 Installer 版本

建议使用 SemVer：

```
MAJOR.MINOR.PATCH
```

例如：

```
v1.0.0
v1.1.0
v1.2.0
v2.0.0
```

版本含义：

- MAJOR：安装器接口或核心架构产生不兼容变化。
- MINOR：增加新的安装器功能。
- PATCH：修复问题和改善兼容性。

Installer 可以提供两个发布渠道：

- Stable：普通用户使用。
- Preview：开发测试使用。

## 3.2 NextKDE 产品版本

Installer 不负责决定自身版本对应哪个 NextKDE 版本。

产品源码提供独立选择：

- Stable Release。
- Development Branch。
- Local Source。
- Custom Ref（后续扩展）。

## 3.3 渠道独立

以下组合必须能够成立：

| Installer   | NextKDE     | 预期行为                   |
| ----------- | ----------- | -------------------------- |
| Stable      | Stable      | 普通用户默认安装           |
| Stable      | Development | 稳定安装器安装开发版产品   |
| Preview     | Stable      | 测试版安装器安装稳定产品   |
| Preview     | Development | 测试安装器安装开发版产品   |
| Development | Local       | 开发安装器使用本地产品源码 |

Installer Preview 不得自动将产品来源切换到 Development。

Installer 更新也不得自动更新产品源码。

# 4. 目录与数据存储设计

## 4.1 目录分离原则

Installer Runtime、Product Source、Git Cache、Build Cache 和 State 必须独立。

采用 XDG Base Directory 规范。

```
${XDG_DATA_HOME:-~/.local/share}
${XDG_CACHE_HOME:-~/.cache}
${XDG_STATE_HOME:-~/.local/state}
```

## 4.2 Installer Runtime

```
~/.local/share/nextkde-installer/
│
├── releases/
│   ├── 1.0.0/
│   ├── 1.1.0/
│   └── 1.2.0/
│
└── current
```

说明：

- 每个 Installer Release 有独立目录。
- `current` 指向当前使用的版本。
- 更新时先下载新版本，再进行原子切换。
- 不覆盖正在运行的安装器目录。
- 保留必要的旧版本用于失败回退。

Installer 不应安装到 NextKDE 产品源码目录，也不应安装到 NextKDE 的系统安装前缀。

## 4.3 Product Source

```
~/.local/share/nextkde/
│
└── sources/
    └── <repository-id>/
        ├── <commit-sha-1>/
        ├── <commit-sha-2>/
        └── <commit-sha-3>/
```

每个受管理的源码工作区对应一个明确的 commit。

Stable 和 Development 如果解析到相同 commit，可以共享工作区。

Local Source 不应默认复制到受管理目录中，直接使用用户指定的本地 checkout。

## 4.4 Git Cache

```
~/.cache/nextkde-installer/
│
└── git/
    └── <repository-id>.git/
```

后续可以使用 Bare Repository 缓存 Git 对象，并通过 Git Worktree 创建版本化工作区。

第一阶段可以使用普通 clone 实现源码隔离，不要求一次性实现全部 Git 优化。

## 4.5 Build Cache

```
~/.cache/nextkde/
│
└── build/
    └── <repository-id>/
        └── <commit-sha>/
            ├── core/
            └── apps/
```

编译产物尽量放在源码目录之外。

Installer 应通过产品后端支持的环境变量传入构建路径。

例如当前已存在的：

- `KOS_BUILD_DIR`
- `KOS_APPS_BUILD_DIR`

必须先验证产品后端的实际路径行为，再将其作为正式接口。

## 4.6 State 与 Logs

```
~/.local/state/nextkde-installer/
│
├── logs/
│   ├── installer.log
│   └── install-<timestamp>.log
│
├── state/
│   ├── last-installer.json
│   ├── last-source.json
│   └── last-install.json
│
└── sessions/
```

日志和状态文件不应该放入 Git 工作区。

安装状态记录应使用原子写入，避免异常退出后产生损坏的 JSON 文件。

# 5. Bootstrap 设计

## 5.1 职责

Bootstrap 是用户启动安装器的入口。

它负责：

1. 检查 Linux 环境。
2. 检查 Git。
3. 检查 Python 运行环境。
4. 确定 Installer 版本。
5. 下载 Installer Release。
6. 验证下载内容。
7. 安装到 Installer Runtime 目录。
8. 启动 Python TUI。

Bootstrap 不负责：

- 获取 NextKDE 产品源码。
- 安装 NextKDE 系统依赖。
- 编译 NextKDE。
- 启动 NextKDE。
- 修改产品源码版本。

## 5.2 下载与验证

优先采用版本化 Release Archive。

示例：

```
NextKDE-Installer-1.0.0.tar.gz
NextKDE-Installer-1.0.0.sha256
```

有条件时提供签名文件或更强的发布来源证明。

Bootstrap 必须验证下载文件。

不能只因为文件来自 HTTPS 就认为其内容一定正确。

## 5.3 更新策略

安装器更新应采用：

1. 下载新的 Release。
2. 检查 SHA256 或签名。
3. 解压到新的版本目录。
4. 执行基本文件完整性检查。
5. 原子更新 `current` 指向。
6. 在下次启动时使用新版本。

不得覆盖正在执行的 Installer Python 文件。

## 5.4 执行权限

一般用户使用正常用户权限运行 Bootstrap 和 TUI。

只有确实需要系统级操作的后端步骤才请求权限。

不允许将整个 Python TUI 以 root 身份运行。

# 6. Git Source Manager

## 6.1 核心职责

Git Source Manager 是 Installer 的独立模块。

建议目录：

```
installer/
└── source/
    ├── __init__.py
    ├── manager.py
    ├── git.py
    ├── resolver.py
    ├── models.py
    └── manifest.py
```

它负责：

- 解析源码渠道。
- 选择 Git Repository。
- 解析 Tag 或 Branch。
- Fetch 对应源码。
- 解析 commit SHA。
- 创建独立工作区。
- 验证源码完整性。
- 保存源码身份信息。
- 返回 PreparedSource。

它不负责编译、安装依赖或启动桌面环境。

## 6.2 Source Modes

### Stable

- 从配置的产品仓库获取 Stable Release。
- 只选择符合稳定版规则的 Tag。
- 排除未经允许的预发布版本。
- 解析 Tag 对应 commit。
- 获取指定源码。
- 记录 Tag 与 SHA。
- 验证版本信息。

Stable 应有明确的版本解析策略。

不能简单地将任意最新 Git Tag 当作正式稳定版。

### Development

- 默认使用配置的开发分支，例如 `main`。
- 支持将来扩展自定义分支和 commit。
- 获取指定 ref。
- 解析真实 commit SHA。
- 创建对应工作区。
- 保留实际源码版本信息。

### Local

- 使用用户提供的本地目录。
- 检查它是否为有效 Git 工作区。
- 检查 NextKDE 关键文件。
- 读取 remote、branch、commit 和 dirty status。
- 不执行 fetch。
- 不执行 checkout。
- 不执行 reset。
- 不修改 origin。
- 不删除文件。
- 不覆盖未提交修改。

Local 模式必须明确提示：本地未提交的修改也会参与构建。

## 6.3 Source Result

Git 准备完成后返回统一数据对象：

```
@dataclass(frozen=True)
class PreparedSource:
    mode: str
    repository: str
    ref: str
    commit: str
    path: Path
    dirty: bool
    managed: bool
```

其中：

- `mode`：stable / development / local。
- `repository`：实际 Git Repository。
- `ref`：Tag、Branch 或本地 ref。
- `commit`：完整 commit SHA。
- `path`：实际源码工作区。
- `dirty`：工作区是否存在未提交修改。
- `managed`：该目录是否由 Installer 管理。

安装器所有后续操作应以这个结果为准。

不能再通过当前 Installer 的 `__file__` 推测产品源码目录。

## 6.4 Git Safety

必须遵守：

- 不在用户现有 checkout 上执行自动切换分支。
- 不修改用户的 Git remote。
- 不对 Local Source 执行 fetch 或 checkout。
- 不在失败的 fetch 后继续使用旧的 FETCH_HEAD。
- 验证已有缓存对应的 repository。
- 校验实际 commit。
- 防止多个安装器进程同时写入相同缓存。
- 不执行未经验证的清理。
- 不允许用户输入直接拼接成 shell 命令。

第一版可采用独立 clone。

后续再引入 Bare Repository + Worktree 优化下载和存储。

# 7. Backend Contract

## 7.1 设计目标

Installer 和 NextKDE 必须有明确的接口约定。

Installer 不应依赖 NextKDE 未公开的内部实现。

NextKDE 也不应该依赖 Installer 的 UI 实现。

## 7.2 合约文件

建议在 NextKDE 产品仓库新增：

```
packaging/
└── installer-contract.json
```

示例：

```
{
  "schema_version": 1,
  "product": {
    "id": "nextkde",
    "name": "NextKDE"
  },
  "installer_api": {
    "minimum": 1,
    "maximum": 1
  },
  "capabilities": [
    "system.doctor",
    "install.core",
    "install.apps",
    "install.lockscreen",
    "activation.start",
    "management.uninstall",
    "management.snapshots"
  ],
  "components": [
    "calendar",
    "calculator",
    "todo",
    "weather"
  ]
}
```

该文件为建议新增的接口规范，不是当前产品仓库已经提供的能力声明。

正式实现后，必须通过自动化测试确保能力列表和真实命令一致。

## 7.3 运行时接口

建议在 `kosctl` 增加：

```
kosctl installer-info --json
```

该命令只返回后端接口信息，不执行安装操作。

建议输出：

```
{
  "product": "nextkde",
  "installer_api": 1,
  "product_version": "x.y.z",
  "capabilities": [
    "system.doctor",
    "install.core",
    "install.apps",
    "activation.start"
  ],
  "components": [
    "calendar",
    "todo",
    "weather"
  ]
}
```

这是新设计的接口，当前不能假定它已经实现。

产品仓库的静态合约文件与运行时信息必须保持一致。

## 7.4 Capability Negotiation

Installer 在生成菜单和安装计划之前，必须检查后端能力。

例如：

| Capability             | TUI 行为     |
| ---------------------- | ------------ |
| `system.doctor`        | 显示诊断入口 |
| `install.core`         | 显示核心安装 |
| `install.apps`         | 显示可选应用 |
| `install.lockscreen`   | 显示锁屏安装 |
| `activation.start`     | 显示启动选项 |
| `management.uninstall` | 显示卸载入口 |
| `management.snapshots` | 显示快照管理 |

如果后端不支持某项能力：

- 不允许用户执行该操作。
- 显示不支持的原因。
- 不得默默忽略用户选择。

如果接口版本不兼容，应停止安装并显示兼容性错误。

## 7.5 旧版本兼容

第一阶段可以保留针对当前 `kosctl` 命令的 Legacy Adapter。

但 Legacy Adapter 必须明确限定支持版本。

不能在缺少接口信息时无限制地猜测产品能力。

# 8. Installer Backend Adapter

## 8.1 架构

建议增加：

```
installer/
└── backend/
    ├── __init__.py
    ├── interface.py
    ├── kosctl.py
    ├── debian.py
    ├── nixos.py
    └── capabilities.py
```

不同发行版或产品安装方式通过 Adapter 统一。

## 8.2 接口职责

Backend Adapter 负责：

- 读取后端能力。
- 生成经过验证的命令参数。
- 执行后端操作。
- 解析退出码。
- 返回统一操作结果。
- 映射发行版专用安装方式。

它不负责显示 TUI 页面。

## 8.3 命令执行

保持当前 `runner.py` 的安全执行模型：

- 使用参数数组。
- 禁止 `shell=True`。
- 保留 stdout、stderr 和 exit code。
- 使用正确的 `cwd=source_root`。
- 记录操作日志。
- 处理进程取消。
- 回收所有子进程。

不得通过 shell 字符串拼接用户输入。

# 9. TUI 架构

## 9.1 技术选择

第一阶段继续使用：

- Python。
- 标准库 curses。
- Plain Text Renderer。

暂不引入 Textual、Rich 等额外框架。

原因：

- 安装器需要尽可能少的 Python 依赖。
- 必须在 NextKDE 产品依赖安装之前运行。
- 需要支持非交互环境。
- 必须保证基本离线能力。

## 9.2 新仓库目录

```
NextKDE-Installer/
│
├── install.sh
├── pyproject.toml
├── README.md
│
├── installer/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── paths.py
│   │
│   ├── detect.py
│   ├── plan.py
│   ├── runner.py
│   ├── manage.py
│   ├── strings.py
│   │
│   ├── source/
│   │   ├── manager.py
│   │   ├── git.py
│   │   ├── resolver.py
│   │   ├── manifest.py
│   │   └── models.py
│   │
│   ├── backend/
│   │   ├── interface.py
│   │   ├── kosctl.py
│   │   ├── debian.py
│   │   ├── nixos.py
│   │   └── capabilities.py
│   │
│   └── render/
│       ├── curses_ui.py
│       ├── plain.py
│       ├── theme.py
│       ├── layout.py
│       ├── widgets.py
│       └── screens/
│           ├── welcome.py
│           ├── system.py
│           ├── source.py
│           ├── options.py
│           ├── review.py
│           ├── installation.py
│           ├── result.py
│           └── manage.py
│
├── tests/
│   ├── test_cli.py
│   ├── test_detect.py
│   ├── test_plan.py
│   ├── test_source.py
│   ├── test_backend.py
│   ├── test_runner.py
│   └── test_ui.py
│
└── docs/
    ├── Architecture.md
    ├── InstallationFlow.md
    ├── BackendContract.md
    ├── Security.md
    └── Development.md
```

这是目标结构。

现有代码应先迁移并保持功能，再按需要逐步拆分页面。

禁止为了符合目录结构而一次性重写现有 TUI。

# 10. 安装流程设计

## 10.1 总体流程

```
Bootstrap
    |
    v
Launch Installer
    |
    v
Welcome
    |
    v
System Detection
    |
    v
Source Selection
    |
    v
Git Source Preparation
    |
    v
Backend Contract Validation
    |
    v
Installation Configuration
    |
    v
Dependency / Installation Plan
    |
    v
Review & Confirmation
    |
    v
Dependency Preparation
    |
    v
Core Installation
    |
    v
Optional Components
    |
    v
Verification
    |
    v
Completion
    |
    v
Optional Start
```

## 10.2 Bootstrap

获取并启动 Installer，不获取 NextKDE 产品源码。

## 10.3 Welcome

显示：

- NextKDE Installer 版本。
- 语言设置。
- 系统信息。
- 基本产品介绍。
- 开始安装。

## 10.4 System Detection

执行只读环境检查：

- Linux Distribution。
- CPU Architecture。
- KDE Plasma。
- Wayland。
- KWin。
- Python。
- Git。
- 磁盘空间。
- 网络状态。

将检查结果分成：

- PASS
- WARN
- BLOCKED

BLOCKED 必须阻止继续执行不适用的安装计划。

## 10.5 Source Selection

选择：

- Stable。
- Development。
- Local。

用户可以查看 Repository 和版本选择说明。

## 10.6 Source Preparation

显示：

- Repository。
- Tag / Branch。
- Fetch 状态。
- Commit SHA。
- 源码目录。
- 工作区是否干净。

失败时不能继续生成基于旧源码的安装计划。

## 10.7 Backend Validation

检查：

- 是否存在 `tools/kosctl`。
- 产品身份是否正确。
- Backend Contract 是否有效。
- Installer API 是否兼容。
- 是否支持用户选择的功能。

## 10.8 Installation Configuration

将设置划分为：

### Core Components

NextKDE 核心桌面，必选。

### Optional Applications

根据后端真实支持能力展示：

- Calendar。
- Calculator。
- Todo。
- Weather。

### Lockscreen

仅当后端声明支持时显示。

### Advanced Options

包括：

- Spatial。
- 其他构建选项。
- 显式启动选项。

ListenFree 必须保持单独、明确的 opt-in，不得自动加入普通的全量应用选择。

## 10.9 Review

显示真正会执行的安装计划：

- 产品源码版本。
- Commit SHA。
- 发行版。
- 核心组件。
- 可选组件。
- 依赖安装动作。
- 预期系统修改。
- 启动行为。
- 需要重新登录或重启的项目。

用户确认后才进入可能修改系统的阶段。

## 10.10 Dependency Preparation

通过产品后端执行发行版对应的依赖安装。

不能在 Installer Python 中重复实现各发行版包管理逻辑。

## 10.11 Installation

默认流程：

1. 运行环境诊断。
2. 安装核心组件。
3. 安装选择的应用。
4. 安装选择的锁屏。
5. 执行其他受支持的安装选项。

各步骤必须依据 Backend Contract 和真实安装计划。

## 10.12 Verification

检查：

- 核心安装结果。
- 文件和组件状态。
- 服务状态。
- 安装版本。
- 组件安装状态。
- 安装后端报告。

不能仅凭最后一个命令返回成功就判断整个安装成功。

## 10.13 Completion

显示：

- 安装成功或失败。
- 已安装版本。
- 已安装组件。
- 日志位置。
- 后续登录要求。
- 管理入口。
- 是否启动。

启动必须独立确认。

不得自动重启显示管理器或热替换 KWin 插件。

# 11. 数据模型

建议使用明确的数据对象，不让 UI、Git 和安装计划通过隐式共享的 root 变量交换状态。

## 11.1 Installation Context

```
@dataclass
class InstallationContext:
    installer_root: Path
    source: PreparedSource | None
    build_root: Path
    system_info: SystemInfo
    backend_info: BackendInfo | None
    options: InstallationOptions
```

## 11.2 Installation Options

```
@dataclass
class InstallationOptions:
    source_mode: str
    apps: list[str]
    lockscreen: bool
    spatial: bool
    start_after_install: bool
```

## 11.3 Operation Result

```
@dataclass
class OperationResult:
    operation: str
    status: str
    exit_code: int | None
    stdout_log: str | None
    stderr_log: str | None
    message: str
```

允许的状态：

- SUCCESS
- FAILED
- CANCELLED
- SKIPPED

安装器必须区分这些状态。

# 12. UI / UX 设计原则

完整的视觉和交互设计另由 TUI UX Design Specification 管理。

本架构规定以下基本原则：

- 保留 Python curses。
- 支持中文和英文。
- 支持纯文本模式。
- 支持小终端。
- 支持长列表滚动。
- 当前焦点必须清晰。
- 不依赖颜色单独表达状态。
- 进度必须使用真实数据。
- 日志和操作阶段分离显示。
- 错误页面必须提供可执行的恢复指引。

推荐流程页面：

1. Welcome。
2. System。
3. Source。
4. Options。
5. Review。
6. Installation。
7. Result。
8. Management。

不得在 UI 中直接执行系统安装逻辑。

# 13. CLI 设计

交互模式为默认模式。

建议支持：

```
nextkde-installer
nextkde-installer --check
nextkde-installer --version
nextkde-installer --mode stable
nextkde-installer --mode development
nextkde-installer --mode local
nextkde-installer --non-interactive
nextkde-installer --start
```

注意：

- 参数必须有明确语义。
- 非交互模式必须能够在没有 TTY 的情况下运行。
- 必须校验所有选项。
- 不允许静默忽略参数。
- 所有命令必须映射到有效的 Backend Capability。
- 非交互模式不能默认执行有破坏性的管理操作。

具体参数应以最终 CLI Specification 为准。

# 14. 安全设计

## 14.1 权限

- 安装器以登录用户身份运行。
- 不使用 sudo 启动整个 Python TUI。
- 由后端处理必要的系统权限。
- 不自动修改用户 Home 目录之外的无关文件。

## 14.2 Git

- 不自动切换本地开发分支。
- 不修改 origin。
- 不对 Local Source 执行 Git 写操作。
- 不自动清理用户工作区。
- 不从不可信输入拼接 Shell 命令。

## 14.3 文件操作

- 验证所有 managed directory。
- 路径清理时检查真实路径。
- 不允许路径穿越。
- 不删除 Local Source。
- 保留文件权限、所有权和 SELinux 相关行为。
- 文件更新尽可能采用临时文件加原子替换。

## 14.4 进程管理

- 使用 subprocess 参数数组。
- 禁用 `shell=True`。
- 支持取消。
- 取消时终止整个子进程组。
- 有界等待后再执行强制终止。
- 始终回收子进程。
- 恢复终端状态。

## 14.5 产品激活

- 安装与启动分开。
- 启动需要明确 opt-in。
- 不自动重启显示管理器。
- 不热替换正在运行的 KWin 插件。

# 15. 测试策略

## 15.1 Installer Unit Tests

覆盖：

- CLI。
- 配置解析。
- XDG 路径。
- System Detection。
- Installation Plan。
- Source Manager。
- Git 操作。
- Backend Contract。
- Capability Mapping。
- Process Runner。
- Cancellation。
- TUI 页面状态。

## 15.2 Git Tests

使用临时本地 Bare Repository 测试：

- Stable Tag 解析。
- Development Branch 获取。
- 重复获取。
- Commit SHA 校验。
- Fetch 失败。
- Remote 不匹配。
- Dirty Local Source。
- Worktree 创建。
- Local Source 不发生 Git 写操作。

## 15.3 Backend Tests

使用 Mock Backend 测试：

- 核心安装。
- 可选应用。
- 锁屏。
- 启动。
- 卸载。
- 快照。
- 不支持的 Capability。
- API 不兼容。

不得在单元测试中执行真实系统卸载或安装。

## 15.4 UI Tests

覆盖：

- 终端尺寸变化。
- 小终端。
- 中文字符宽度。
- 页面导航。
- 焦点。
- 滚动。
- 错误显示。
- 取消流程。
- 非 TTY 模式。

## 15.5 Integration Tests

使用 Disposable VM 或 Hosted CI。

至少验证：

- Arch。
- Debian。
- Ubuntu。
- Fedora。
- NixOS（单独适配与验证）。

不同发行版测试必须记录实际完成的步骤。

不能用 Mock 测试替代全部真实安装测试。

# 16. CI / Release

## 16.1 Installer CI

每次 Pull Request 执行：

- Python 编译检查。
- Unit Tests。
- Source Manager Tests。
- Backend Contract Tests。
- CLI Tests。
- 代码静态检查。
- 安全相关测试。

## 16.2 Installer Release

Release 应包含：

```
NextKDE-Installer-x.y.z.tar.gz
NextKDE-Installer-x.y.z.sha256
```

有条件时提供签名和发布来源证明。

## 16.3 Release Channel

- Stable：正式发行版本。
- Preview：预发布版本。

两条渠道独立于 NextKDE 产品 Stable / Development 渠道。

## 16.4 Compatibility Matrix

记录：

- Installer Version。
- Supported Installer API。
- NextKDE Product Version。
- Backend Capability Set。
- Supported Distribution。

不兼容组合必须明确显示。

# 17. 现有代码迁移计划

## 17.1 代码迁移

从当前 NextKDE 仓库迁移：

| 当前文件                    | 目标                      |
| --------------------------- | ------------------------- |
| `tools/installer/`          | 迁入 Installer 仓库       |
| `tools/installer/tests/`    | 迁入 Installer 仓库       |
| Installer 相关文档          | 迁入 Installer 仓库并更新 |
| `tools/install.sh`          | 改造成兼容 Bootstrap      |
| `tools/kosctl`              | 保留在 NextKDE            |
| `tools/install-debian13.sh` | 保留在 NextKDE            |
| `tools/install-apps.sh`     | 保留在 NextKDE            |
| `tools/kos-state.py`        | 保留在 NextKDE            |
| 产品构建与部署代码          | 保留在 NextKDE            |

## 17.2 Git 历史

优先保留现有 `tools/installer/` 的提交历史。

迁移时可以使用 `git filter-repo` 提取相关目录和提交。

不要只复制当前文件而无必要地丢弃已有开发历史。

## 17.3 过渡入口

在原 NextKDE 仓库保留：

```
tools/install.sh
```

作为兼容入口。

它负责启动或获取独立 Installer。

原有用户的安装习惯可以在迁移期继续使用。

确认新仓库稳定后，再考虑是否移除旧的完整安装器代码。

# 18. 开发实施阶段

## Phase 1 — Repository Extraction

目标：

- 创建独立 Installer 仓库。
- 迁移现有 TUI。
- 保留 Git 历史。
- 保证基础功能正常。
- 保留现有测试。

不进行大规模架构重构。

## Phase 2 — Path Separation

目标：

- 引入 installer_root。
- 引入 source_root。
- 引入 build_root。
- 引入 XDG 数据目录。
- 改造 `__main__.py` 和 `plan.py`。

消除原来单一 `root` 代表所有目录的设计。

## Phase 3 — Source Manager

目标：

- Stable。
- Development。
- Local。
- Git Repository 选择。
- Commit SHA 记录。
- 源码完整性检查。
- Git 安全保护。

先完成可靠的独立 clone 流程。

Bare Repository + Worktree 可以后续实现。

## Phase 4 — Backend Contract

目标：

- 在 NextKDE 产品仓库增加合约。
- 增加运行时 capability 查询接口。
- 定义 API 兼容范围。
- 实现 Installer Adapter。
- 增加兼容性测试。

## Phase 5 — Installation Flow

目标：

- 完成 Source Preparation 页面。
- 完成 Review 页面。
- 支持不同后端。
- 统一 Debian 和其他发行版的执行顺序。
- 修复已有计划中的错误。

## Phase 6 — UI Redesign

目标：

- 改善视觉设计。
- 引入可复用 UI Widget。
- 适配不同终端尺寸。
- 改进日志与进度显示。
- 完善成功与失败页面。

## Phase 7 — Bootstrap and Release

目标：

- 发布版本化 Installer。
- 实现校验和更新。
- 建立 Stable / Preview 渠道。
- 保留旧安装入口。
- 完成迁移。

## Phase 8 — Integration Verification

目标：

- 在隔离环境测试。
- 验证不同发行版。
- 验证 Stable / Development / Local。
- 验证失败恢复。
- 验证产品与 Installer 版本兼容。

# 19. 最终验收标准

只有满足以下条件，才认为独立安装器架构基本完成。

### Repository

- Installer 已在独立仓库发布。
- NextKDE 仍独立维护产品后端。
- 两个仓库不互相依赖对方的内部实现。

### Bootstrap

- 能独立获取 Installer。
- 能验证 Release。
- 能独立更新 Installer。
- 更新不会覆盖正在运行的版本。

### Git Source Manager

- Stable 正确解析。
- Development 正确解析。
- Local 保留用户工作区。
- Installer 和产品源码路径完全分离。
- Commit SHA 可追踪。

### Backend Contract

- 合约已定义。
- 能查询后端版本。
- 能查询 Capability。
- 不支持的操作不会出现在可执行菜单中。
- 不兼容版本会明确阻止安装。

### TUI

- 原有功能得到保留。
- 新安装流程完整。
- 进度、日志和错误可见。
- 中英文正常。
- Plain Mode 正常。

### Safety

- 不自动修改 Local Source。
- 不自动启动桌面。
- 不自动重启显示管理器。
- 不执行未经确认的破坏性操作。
- 不会因为 Installer 更新而改变产品源码。

### Testing

- 单元测试通过。
- CI 已注册测试。
- 至少完成主要发行版的真实集成验证。
- 测试结果可追踪。

# 20. 架构决策总结

本项目最终采用以下架构决策：

| 决策项         | 方案                                                |
| -------------- | --------------------------------------------------- |
| Installer 仓库 | 独立 Git 仓库                                       |
| 产品仓库       | 保留 NextKDE                                        |
| TUI 技术       | Python curses                                       |
| 安装器依赖     | 尽量只使用标准库                                    |
| Installer 更新 | 独立 Release                                        |
| Product 更新   | 独立 Git Source Manager                             |
| Source Modes   | Stable / Development / Local                        |
| Git 工作区     | 与 Installer Runtime 分离                           |
| Git 缓存       | 第一阶段普通 clone，后续优化为 Bare Repo + Worktree |
| 构建目录       | 独立 XDG Cache                                      |
| 后端           | NextKDE 原生 kosctl                                 |
| 接口           | Backend Contract + Capability Negotiation           |
| 系统安装       | 通过后端 Adapter                                    |
| 产品启动       | 明确 opt-in                                         |
| 测试           | 单元测试 + CI + Disposable VM                       |

**最终原则：**

1. Installer 是独立产品。
2. NextKDE 是独立产品。
3. 两者通过稳定的 Backend Contract 协作。
4. Installer 负责用户体验与安装编排。
5. NextKDE 负责系统构建、部署和生命周期管理。
6. Git Source Manager 负责确定真正被安装的产品版本。
7. Installer 更新不得影响产品源码。
8. Product 更新不得影响 Installer Runtime。
9. 用户的 Local Source 永远不能被安装器擅自修改。
10. 所有安装操作必须能够追踪、验证和恢复。

**Architecture Goal:**

A version-independent, repository-independent and capability-aware installer for NextKDE, with a stable user experience and a clearly defined boundary between installer orchestration and product installation.NextKDE Installer
