# 键位与菜单设计（KOS 安装器 TUI）

本文件是**设计稿**，不对应任何已实现的代码。现状以 `8ef49d4` 为准；第 8 节逐条列出与现有实现的冲突和最小改动。

适用范围：`installer/ui/`（Textual 8.2.8，vendored）、`installer/__main__.py` 的 `--plain`/非 TTY 分支。所有可见文案进 `installer/strings.py`，zh/en 成对。

---

## 1. 六条定案

| 议题 | 结论 | 一句话理由 |
|---|---|---|
| Esc / q | Esc 只做“返回”，任何页面都不退出；退出只走 q（向导有状态时先弹确认） | Esc 是 TUI 里最容易被误触的键，退出必须是显式意图 |
| Review 的执行 | Enter 只进入**确认页**；确认页默认选中「返回」，选中「开始安装」后才由 Enter 执行 | 计划页与执行页分离：在计划页上按任何键都不会启动安装 |
| Result | Enter = 执行当前聚焦的按钮（失败页默认聚焦「重试」）；q = 退出；新增 l = 日志 | 失败后最可能的动作是重试，不是退出 |
| 向导数字跳转 1–5 | **删除**；数字只给有序选项（菜单、确认页）；侧栏保留鼠标点击跳转 | 线性向导的数字会与菜单数字撞义，且跳回前页会重问条件 |
| Checks 刷新 | `r`（隐藏别名：无 F5） | 助记、单键；F5 在 macOS/tmux 里常被截走或拦截 |
| 管理区 | Management 变成 `[1]…[6]` 栈式菜单；子页是列表（↑↓/Enter），Esc 弹一层 | 同一套“数字=菜单、列表=回车”模型，不再逐屏发明键位 |

全局不变式（后面所有表都由它推出）：

1. **Enter = 推进/确认**，永远不做“切换”。切换只用 Space（复选/单选）或 ↑↓（单选）。
2. **Space = 切换/选中**，只作用于有布尔或选项的控件。
3. **Esc = 后退一层**，没有后退时就不绑定（不出现、不响应）。
4. **q = 退出**，向导有状态时 `ConfirmDialog` 确认，默认焦点「继续」。
5. 单字符键（`m` 管理、`r` 重试/重检、`l` 日志、`t` 详情、`c` 新建）只在**没有文本输入聚焦**时生效；`Input` 聚焦时全部让位。只在菜单里出现的行（Doctor、卸载）不额外给字母——`[n]` 已足够，字母留给跨屏反复出现的动作。
6. 数字只用于**有序选项**：菜单行（`[n]`）与确认页的两个选项（`1`/`2`）；不用于线性向导跳步。禁用项保留自己的槽位。

---

## 2. 上下文（context）

屏幕声明一个上下文；聚焦的控件再追加一个，取并集后解析出这一屏的键位表。

| context | 由谁提供 | 说明 |
|---|---|---|
| `app` | `ChromeScreen` | 全局可用（`app.quit`、`help.open`、焦点键） |
| `wizard.welcome` | `WelcomeScreen` | 语言与入口 |
| `wizard.checks` | `SystemScreen` | 探针列表 |
| `wizard.options` | `OptionsScreen` | 表单页 |
| `option.radio` | `SourceRow` 聚焦 | 单选框组上下文 |
| `option.check` | `CheckRow` 聚焦 | 复选组上下文 |
| `wizard.review` | `ReviewScreen` | 计划页（不执行） |
| `wizard.confirm` | `ConfirmScreen`（新） | 执行确认页 |
| `wizard.run` | `InstallationScreen` | 运行中，屏蔽导航 |
| `wizard.result` | `ResultScreen` | 结果页 |
| `menu` | `ManagementScreen` | 数字菜单 |
| `list.units` / `list.snapshots` / `list.logs` | 对应列表页 | 数据列表 |
| `log.view` | `LogViewerScreen` | 只读日志 |
| `dialog.confirm` / `dialog.secret` | `ConfirmDialog` / `PasswordDialog` | 模态，屏蔽底层单字符键 |

`Input` 聚焦时把 `menu.*`、单字符动作全部排除（输入 `main` 不能触发 m/a/i/n）。

---

## 3. 动作注册表（action id → 键位）

默认键位。`显示` 是底栏/帮助里的键名（ASCII 终端自动降级为 `Enter/Esc/Up/Down/Space/Tab`，见 `Strings.ascii`）。

| 动作 ID | 默认键 | 上下文 | 标签（strings key） | 备注 |
|---|---|---|---|---|
| `app.quit` | `q` | app（`wizard.run` 除外） | `key_quit` 退出 / quit | 有状态时先确认 |
| `app.manage` | `m` | `wizard.welcome`、`wizard.result` | `key_manage` 管理 / manage | 栈式进入管理区 |
| `help.open` | `?` | app | `key_help` 帮助 / help | 覆盖层用当前上下文 |
| `focus.next` | `Tab` | app | `key_focus_next` 下一项 / next field | 隐藏：不进底栏，只进帮助 |
| `focus.prev` | `Shift+Tab` | app | `key_focus_prev` 上一项 / previous field | 隐藏，同上 |
| `wizard.next` | `Enter` | `wizard.welcome` / `wizard.checks` / `wizard.options` | `key_next` 下一步 / next | 各屏自己实现“下一步是谁” |
| `review.continue` | `Enter` | `wizard.review` | `key_continue` 继续 / continue | 进确认页，不执行 |
| `wizard.back` | `Esc` | checks / options / review / confirm / menu / list.* / log.view | `key_back` 返回 / back | 无后退就不绑定 |
| `welcome.language` | `←` `→` | `wizard.welcome` | `key_language` 语言 / language | **不再用 Tab**（Tab 归焦点） |
| `check.move` | `↑` `↓` | `wizard.checks` | `key_select` 选择 / select | |
| `check.refresh` | `r` | `wizard.checks` | `key_refresh` 重新检测 / re-check | F5 删除 |
| `option.move` | `↑` `↓` | `option.check` | `key_move` 移动 / move | 复选组内移动焦点，不改值 |
| `option.toggle` | `Space` | `option.check`、`option.radio` | `key_toggle` 切换 / toggle | 单选组也用它确认选中 |
| `review.details` | `t` | `wizard.review` | `key_details` 命令详情 / commands | |
| `review.retry` | `r` | `wizard.review`（仅准备失败） | `key_retry` 重试 / retry | 失败前不绑定 |
| `log.open` | `l` | `wizard.review`（失败）、`wizard.result` | `key_log` 日志 / log | 复用 `LogViewerScreen` |
| `review.install` | `Enter` | `wizard.confirm`（仅当选中「开始安装」） | `key_install` 开始安装 / install | **danger**，见 §5 |
| `confirm.pick.install` | `1` | `wizard.confirm` | 行文本自带 | 只移动选中项，不执行 |
| `confirm.pick.back` | `2` | `wizard.confirm` | 行文本自带 | 只移动选中项，不执行 |
| `result.retry` | `r` | `wizard.result`（非成功） | `key_retry` 重试 / retry | |
| `run.abort` | `Ctrl+C` | `wizard.run`、`menu`/`list.*`（动作运行中） | `key_abort` 中止 / abort | **danger**，先确认 |
| `menu.move` | `↑` `↓` | `menu`、`list.*` | `key_select` 选择 / select | `OptionList` 原生 |
| `menu.act` | `Enter` | `menu`、`list.*` | `key_open` 打开 / open | 列表里 = 该行的主动作 |
| `menu.item.units` | `1` | `menu` | 行文本自带 | → `UnitsScreen` |
| `menu.item.snapshots` | `2` | `menu` | | → `SnapshotsScreen` |
| `menu.item.doctor` | `3` | `menu` | | 就地执行 |
| `menu.item.logs` | `4` | `menu` | | → `LogsScreen` |
| `menu.item.uninstall` | `5` | `menu` | | **danger**，需输入 `uninstall` |
| `menu.item.back` | `6` | `menu` | `key_back` 返回 / back | 与 Esc 等价 |
| `unit.toggle` | `Enter`（`Space` 为隐藏别名） | `list.units` | `key_toggle` 切换 / toggle | 关 `core` 已拒绝 |
| `snapshot.create` | `c` | `list.snapshots` | `key_create` 新建 / create | |
| `snapshot.rollback` | `Enter` | `list.snapshots` | `key_rollback` 回滚 / roll back | **danger**，确认框 |
| `log.scroll` | `↑` `↓` `PgUp` `PgDn` | `log.view` | `key_scroll` 滚动 / scroll | |
| `dialog.confirm.yes` / `.no` | `Enter`（按钮）/ `Esc` | `dialog.confirm` | `confirm` / `cancel` | 默认焦点 = 取消 |
| `dialog.secret.submit` / `.cancel` | `Enter` / `Esc` | `dialog.secret` | `key_continue` / `cancel` | 密码对话框 |

绑定细则：

- 一个动作可以有多键（`welcome.language` = ←,→）；同一上下文里不允许两动作抢同一个键（启动时断言）。
- `hidden=True` 的动作（`unit.toggle` 的 Space、`log.scroll` 的 PgUp/PgDn）只在帮助覆盖层出现，不占底栏。
- 禁用/不适用 = `check_action` 返回 `False`：底栏、帮助、按键三者同时消失，不会出现“写着但按了没反应”。

---

## 4. 逐屏键位与默认焦点

| 屏幕 | 默认焦点 | 键位 | 禁用/例外 |
|---|---|---|---|
| Welcome | 无（`#language` 只是文本） | `←/→` 语言 · `Enter` 下一步 · `m` 管理 · `q` 退出 · `?` | **没有 Esc**（无路可退）；q 直接退出 |
| Checks | 第一行探针 | `↑/↓` 选择 · `Enter` 下一步 · `r` 重新检测 · `Esc` 返回 · `q` 退出 · `?` | 无探针时 `check.move` 不绑定 |
| Options | `source_stable` | `Tab/Shift+Tab` 换控件 · `↑/↓` 组内移动 · `Space` 切换 · `Enter` 下一步 · `Esc` 返回 · `q` 退出 · `?` | `core` 行 disabled，Tab 跳过；后端不支持的项 disabled + 文字标记 |
| Review（正常） | 页面本身 | `Enter` 进入确认页 · `t` 命令详情 · `Esc` 返回 · `q` 退出 · `?` | 计划为空时 Enter 不绑定 |
| Review（准备失败） | 页面本身 | 上一行去掉 `Enter`/`t`，加 `r` 重试 · `l` 日志 | 失败块本身写明这三个键 |
| Confirm（新） | 「返回上一步」单选行 | `↑/↓` 或 `1`/`2` 选择 · `Enter` 确认 · `Esc` 返回 · `?` | 未选「开始安装」时 Enter = 返回；`q` 不绑定（先返回再退，避免运行中被 q 打断） |
| Installation | 无（`#cancel` 仅鼠标，`can_focus=False`） | `Ctrl+C` 中止（确认框） · `?` | 导航键全部不绑定：无 Esc、无 q、无 Tab、无数字。`?` 允许——只读覆盖层，不改运行状态 |
| Result | 失败/取消 →「重试」；成功 →「退出」 | `Enter` 激活聚焦按钮 · `r` 重试（非成功） · `l` 日志 · `m` 管理 · `q` 退出 · `?` | 成功页无 `r` |
| Management | 第一行菜单项 | `1–6` 直达 · `↑/↓` 选择 · `Enter` 打开 · `Esc` 返回 · `?`；动作运行中另加 `Ctrl+C` 中止 | 禁用项保留编号、文字标注、按数字无动作 |
| Units | 第一行单元 | `↑/↓` 选择 · `Enter`/`Space` 切换 · `Esc` 返回 · `?`；运行中加 `Ctrl+C` | `core` 关闭被拒绝并给一行原因 |
| Snapshots | 第一行快照 | `↑/↓` 选择 · `Enter` 回滚（确认） · `c` 新建 · `Esc` 返回 · `?`；运行中加 `Ctrl+C` | 空列表时 `c` 仍可用 |
| Logs（列表） | 第一个文件 | `↑/↓` 选择 · `Enter` 打开 · `Esc` 返回 · `?` | 无日志时列出空态文本 |
| LogViewer | 日志区 | `↑/↓`/`PgUp`/`PgDn` 滚动 · `Esc` 返回 · `?` | 只读，无单字符动作 |

Options 的焦点模型（现状只有控件默认行为，这是要新写的部分）：

- `Tab`/`Shift+Tab` 按组合顺序走：来源组 →（跳过 `core`）→ 应用组 → 高级组；组内用 `↑/↓`。
- 来源组是 `RadioSet`：`↑/↓` 移动选中项（原生），`Space` 再次确认。
- 应用组是若干 `CheckRow`：`↑/↓` 把**焦点**移到上/下一个复选行（屏幕级 `on_key` 实现），`Space` 改值，移动不改值。
- `Enter` 必须在这些行上“穿透”到屏幕（`wizard.next`）：现状 `Checkbox`/`RadioButton` 自带 `enter,space` → `toggle_button`，会把 Enter 吃掉。最小改动是给 `CheckRow`/`SourceRow` 加 `BINDINGS = [("space", "toggle_button", "")]`。

---

## 5. 执行确认页（新）

`installer/ui/screens/confirm.py`，`STEP = 3`（侧栏仍停在「确认」）、`JUMP = False`，从 Review `Enter` 推入；`Esc` 弹回 Review。66×20 版式：

```
 确认安装？
 ────────────────────────────────────────
 将执行    6 个步骤
 源码      v0.3.0 · 2ca59a1f
 写入      ~/.local（无需 root）
 接管      plasmashell，注销后生效

   ( ) [1] 开始安装
   (•) [2] 返回上一步          ← 默认

 1/2 选择   ⏎ 确认   esc 返回   ? 帮助
```

规则：

- 默认选中「返回上一步」；`Enter` 在默认态 = 返回，不是安装。
- 安装需要两步：先 `↓`（或 `1`）把选中移到「开始安装」，再 `Enter`。
- 只有「开始安装」被选中时 `Enter` 才走 `review.install`（`danger`）；该动作不再叠加第二个确认框——这一页本身就是计划的二次确认。
- `q` 在这一页不绑定：要退出先 `Esc` 回 Review，从那里 `q`（确认后退出）。
- 计划正文留在 Review 页；确认页只放“会改什么”，因此 66×20 不需要滚动。

---

## 6. 菜单层级

Management（`ManagementScreen`）是唯一菜单；子页是列表。

```
管理  (从 Welcome/Result 按 m 进入)
├─ [1] 单元 (3)            → UnitsScreen        列表：↑↓ 选择 · Enter/Space 切换 · Esc 返回
├─ [2] 快照 (2)            → SnapshotsScreen    列表：↑↓ 选择 · Enter 回滚(确认) · c 新建 · Esc 返回
├─ [3] Doctor              → 就地执行，日志在下方动作区
├─ [4] 日志                → LogsScreen          列表：↑↓ 选择 · Enter 打开 · Esc 返回
│                             └─ LogViewerScreen  ↑↓/PgUp/PgDn 滚动 · Esc 返回
├─ [5] 卸载                不可用：未安装        （禁用，槽位保留）
└─ [6] 返回                （= Esc）
```

- 行文本固定带编号：`[1] 单元      3`、`[5] 卸载      不可用：未安装`。禁用行不只靠颜色：前缀 `·` + 明确文字；编号不变，按数字无动作。
- 有两处可验证的禁用谓词：`[5]` 要求至少一个单元已安装；`[4]` 要求 `paths.log_dir` 里有文件。其余始终可用。
- 子页不使用数字：列表长度随数据变，数字槽位会被数据推翻。行内动作一律 Enter，Esc 弹一层（`push_screen`/`pop_screen` 已是栈语义）。
- 侧栏的 1–5 数字跳转删除；点击侧栏跳到已完成步骤**保留**（指针操作，不占键盘语义）。

---

## 7. 底栏文案（一行，66 列内）

格式：`键 词`，项间两空格；`? 帮助` 永远在最后。低于优先级的项在窄屏被裁掉，帮助覆盖层仍是全集。

实测（Textual `Footer`，66 列，`ENABLE_COMMAND_PALETTE=False`）：最宽的是 Checks 与 Options（复选聚焦），各 58 格；表中其余行不超过它。

`Tab`/`Shift+Tab` 不占底栏（表单通用约定，占 9–14 格不值），只在 `?` 里列出，所以 Options 底栏仍是 5 项 + `?`。

| 场景 | zh | en |
|---|---|---|
| Welcome | `⏎ 下一步  ←/→ 语言  m 管理  q 退出  ? 帮助` | `⏎ next  ←/→ language  m manage  q quit  ? help` |
| Checks | `↑↓ 选择  ⏎ 下一步  r 重新检测  esc 返回  q 退出  ? 帮助` | `↑↓ select  ⏎ next  r re-check  esc back  q quit  ? help` |
| Options（复选聚焦） | `空格 切换  ↑↓ 移动  ⏎ 下一步  esc 返回  q 退出  ? 帮助` | `space toggle  ↑↓ move  ⏎ next  esc back  q quit  ? help` |
| Options（单选聚焦） | `↑↓ 选择  ⏎ 下一步  esc 返回  q 退出  ? 帮助` | `↑↓ select  ⏎ next  esc back  q quit  ? help` |
| Review（正常） | `⏎ 继续  t 命令详情  esc 返回  q 退出  ? 帮助` | `⏎ continue  t commands  esc back  q quit  ? help` |
| Review（失败） | `r 重试  l 日志  esc 返回  q 退出  ? 帮助` | `r retry  l log  esc back  q quit  ? help` |
| Confirm | `1/2 选择  ⏎ 确认  esc 返回  ? 帮助` | `1/2 choose  ⏎ confirm  esc back  ? help` |
| Installation | `ctrl+c 中止  ? 帮助` | `ctrl+c abort  ? help` |
| Result（成功） | `q 退出  l 日志  m 管理  ? 帮助` | `q exit  l log  m manage  ? help` |
| Result（失败/取消） | `r 重试  l 日志  m 管理  q 退出  ? 帮助` | `r retry  l log  m manage  q exit  ? help` |
| Management | `1–6 直达  ↑↓ 选择  ⏎ 打开  esc 返回  ? 帮助` | `1–6 go to  ↑↓ select  ⏎ open  esc back  ? help` |
| Units | `↑↓ 选择  ⏎ 切换  esc 返回  ? 帮助` | `↑↓ select  ⏎ toggle  esc back  ? help` |
| Snapshots | `↑↓ 选择  ⏎ 回滚  c 新建  esc 返回  ? 帮助` | `↑↓ select  ⏎ roll back  c create  esc back  ? help` |
| Logs / LogViewer | `↑↓ 选择  ⏎ 打开  esc 返回  ? 帮助` / `↑↓ 滚动  esc 返回  ? 帮助` | `↑↓ select  ⏎ open  esc back  ? help` / `↑↓ scroll  esc back  ? help` |
| ConfirmDialog / PasswordDialog | 底栏沿用下层页面；对话框正文末行写明 `⏎ 确认  esc 取消` | 同 |

现有 `key_*` 复用为主，新增：`key_next`（下一步/next）、`key_abort`（中止/abort）、`key_install`（开始安装/install）、`key_focus_next`（下一项/next field）、`key_focus_prev`（上一项/previous field）、`menu_goto`（直达/go to）。`key_jump` 删除；`hint_review`/`hint_install`/`hint_result` 三条死文案删除（底栏由注册表生成后它们不再有来源）。

---

## 8. 与现状的冲突与迁移

| # | 现状（文件） | 问题 | 最小改动 |
|---|---|---|---|
| 1 | Welcome `("escape,q","ask_quit")`，底栏只显示 `Esc`（`welcome.py`） | Esc 在退出，q 不可见；与“Esc=返回”冲突 | 键位改 `("q","app.quit")`；Welcome 不绑定 Esc |
| 2 | `KEYS` 元组把键硬编码在每屏（`screens/*.py`） | 无法配置、底栏与帮助靠人工同步 | 见 §9 注册表；`KEYS` 退化为屏幕声明 context + 启用谓词 |
| 3 | Review `Enter → start_install`（`review.py`） | 单键触发不可逆操作 | Enter 改为 `review.continue` → 推入 `ConfirmScreen`；新增 `review.install` 只在确认页执行 |
| 4 | `ConfirmDialog.on_mount` 无 `word` 时聚焦 Confirm（`widgets/confirm.py`） | 默认焦点在危险按钮上 | 默认焦点改 `#confirm_cancel`；`word` 存在时仍聚焦输入框 |
| 5 | Welcome `left,right,tab` 切语言（`welcome.py`） | Tab 是全局焦点键，被抢占 | 只留 `←/→`；Tab 归 `focus.next` |
| 6 | `Checkbox`/`RadioButton` 自带 `enter,space → toggle_button` | Enter 被控件吃掉，Options 无法“Enter 下一步” | `CheckRow`/`SourceRow` 的 `BINDINGS` 只留 `space` |
| 7 | 向导 `1–5` 跳步（`screens/__init__.py` `JUMP_KEYS`/`on_key`） | 数字与菜单撞义 | 删除数字绑定；保留侧栏点击 |
| 8 | Checks `F5`（`system.py`） | 键盘可达性差，与“单字符助记”不一致 | 改 `r`；删除 F5 |
| 9 | Result `Enter → quit`（`result.py`） | 失败后 Enter 直接退出 | `Enter` 激活聚焦按钮（失败默认「重试」）；退出改 `q`；加 `l` |
| 10 | Management 无数字（`management.py`） | 不是菜单，无法直达 | 行文本加 `[n]`，绑 `menu.item.*`，禁用项保留槽位 |
| 11 | App 级 `ctrl+q → quit`（Textual `App.BINDINGS`，隐藏） | 与 XON 冲突；一处看不见的退出 | `app.BINDINGS` 里移除；退出只走 `q` |
| 12 | Installation `Ctrl+C → cancel_install` 立即中止（`installation.py`） | 运行中单键即中止 | Ctrl+C 先开确认框（默认「继续安装」），确认后才 `cancel_event.set()` |
| 13 | Installation 的 `#cancel` 按钮可被自动聚焦（`AUTO_FOCUS`），Enter 即可中止 | 与“进度页屏蔽导航/确认键”冲突 | `can_focus=False`，改成鼠标专用；中止只走 Ctrl+C + 确认 |
| 14 | `hint_*` 三条文案无引用 | 死文案，且与底栏可能不一致 | 删除；底栏全部由注册表生成 |
| 15 | `?_help` 覆盖层列出按键，但不管禁用态（`widgets/help.py`） | 帮助可能列出不可用键 | 复用同一解析函数，只取 `check_action is not False` 的行 |

动作迁移对照（现有方法 → 新 ID）：

| 现有 action | 屏幕 | 新 ID | 新键 |
|---|---|---|---|
| `cycle_language` | Welcome | `welcome.language` | `←/→`（去掉 Tab） |
| `open_system` | Welcome | `wizard.next` | `Enter` |
| `open_manage` | Welcome / Result | `app.manage` | `m` |
| `quit`（Welcome 屏） | Welcome | `app.quit` | `q` |
| `move(±1)` | Checks | `check.move` | `↑/↓` |
| `refresh` | Checks | `check.refresh` | `r` |
| `next` | Options | `wizard.next` | `Enter` |
| `start` | Review | `review.continue`（Enter→确认页）+ `review.install`（确认页） | `Enter` |
| `details` | Review | `review.details` | `t` |
| `retry` | Review | `review.retry` | `r`（仅失败） |
| `open_log` | Review | `log.open` | `l`（仅失败；Result 也绑） |
| `cancel` | Installation | `run.abort` | `Ctrl+C`（先确认） |
| `retry` | Result | `result.retry` | `r` |
| `quit` | Result | `app.quit` | `q`（Enter 只激活聚焦按钮） |
| `cancel_action` | Management / Units / Snapshots | `run.abort` | `Ctrl+C`（`busy` 时） |
| `back` | 各屏 | `wizard.back` | `Esc` |
| `toggle` | Units | `unit.toggle` | `Enter`（`Space` 隐藏别名） |
| `create` | Snapshots | `snapshot.create` | `c` |
| `help` | 全部 | `help.open` | `?` |
| `goto_step` + `JUMP_KEYS` | 向导 | — | 删除 |
| App `ctrl+q` | 全局 | — | 删除 |

---

## 9. 工程落地

### 9.1 模块

新增 `installer/ui/keymap.py`（约 80 行，无新依赖），是唯一事实来源：

```python
@dataclass(frozen=True)
class Action:
    id: str                       # "wizard.next"
    keys: tuple[str, ...]         # ("enter",)
    label: str                    # strings key，如 "key_next"
    contexts: frozenset[str]      # {"wizard.checks", "wizard.options"}
    priority: int = 50            # 底栏裁剪顺序，小者优先保留
    hidden: bool = False          # 生效、进帮助、不占底栏
    danger: bool = False          # 必须先确认；测试断言其入口不是单键

ACTIONS: tuple[Action, ...] = (...)


def resolve(contexts, overrides=None, budget=None) -> list[tuple[str, str, str]]:
    """(键显示, 标签, action id)：去重、套用覆盖、按 priority 排序；
    budget（列数）不为 None 时丢掉放不下的末位项。"""
```

- 屏幕声明 `CONTEXT: str`；控件声明 `context`（复选行/单选组/列表）。
- `ChromeScreen._bind_keys()` 改为 `resolve()` 的消费者；`DescendantFocus`/`DescendantBlur` 与 `Resize` 时重解析（宽度作为 budget）并 `refresh_bindings()`。
- 底栏仍是 Textual `Footer`（读 screen 的 bindings），帮助覆盖层读同一 `resolve()` 结果；两者不可能不一致。
- 菜单行由 `ManagementScreen` 声明 `(id, 标签, 计数, 启用谓词)`，`[n]` 由顺序生成 → 禁用项自然保留槽位。
- 冲突检测：`resolve()` 对同一上下文内的重复键 `raise`，测试里对每个上下文跑一遍。

### 9.2 配置覆盖

`installer/__main__.py` 的 `CONFIG_KEYS` 增加 `"keys"`：

```json
{ "keys": { "wizard.back": "esc", "menu.item.logs": "l", "unit.toggle": "space" } }
```

- 未知动作 ID 与配置里其它未知键一样 `SystemExit`，并列出合法 ID。
- 覆盖在 App 构造前应用（模块级 `apply_overrides`），底栏/帮助/绑定自动跟随。
- 不支持改“上下文”，只改键位；空数组表示禁用该动作。

### 9.3 终端冲突（默认键位里一个都不出现）

| 组合 | 冲突 | 处理 |
|---|---|---|
| `Ctrl+M` / `Ctrl+I` / `Ctrl+J` / `Ctrl+H` | 分别是 Enter / Tab / LF / Backspace，无法区分 | 不绑；只用 `Enter`/`Tab` 本体 |
| `Ctrl+S` | XOFF，冻结终端输出 | 不绑（原本也没有） |
| `Ctrl+Q` | XON；现有 App 还藏了 quit | 删掉 App 的 `ctrl+q`；退出只走 `q` |
| `Ctrl+Z` / `Ctrl+\` / `Ctrl+D` | 挂起 / SIGQUIT / EOF | 不绑 |
| `Ctrl+C` | SIGINT；同时是 Textual 的复制 | 只在 Installation（`run.abort`）和管理区动作运行中绑；其余屏交给复制 |
| `Ctrl+A` / `Ctrl+B` | tmux/screen 前缀 | 不绑 |
| `Ctrl+P` | 命令面板（已 `ENABLE_COMMAND_PALETTE=False`） | 不绑 |
| `Alt-<键>` | 终端/SSH 下常被拆成裸 Esc，产生误后退 | 不绑任何 Alt 组合 |
| `Esc` 时序 | 真终端里裸 Esc 不等待；箭头是 `ESC [` 序列 | 只用裸 `Esc`；不要依赖“Esc 连按”语义 |
| `F1–F12` | macOS/tmux/终端常拦截 | 默认不用（F5 已删） |

### 9.4 无 TTY / 弱终端降级

| 情况 | 行为 |
|---|---|
| `stdout` 或 `stdin` 不是 TTY、`--plain`、`--yes` | 现状即降级到 `render/plain.py`，无按键；取消 = 进程 SIGINT |
| `TERM` 为空或 `dumb` | 追加判断，降级到 plain 并打印一行说明（新增 `note_dumb_terminal` zh/en） |
| 非 UTF-8 / Linux 控制台 | `Strings.ascii` 已有：字形降级，键名显示 `Enter/Esc/Up/Down/Space/Tab`（`_display()` 扩展） |
| 终端吞掉某键（如 F 键） | 默认键位不含 F 键；`keys` 配置可换 |
| 终端宽度 < 66 列 | 现状**没有**尺寸守卫（`notice_big` 文案存在但未接线）。底栏按 `budget` 裁剪；建议在 `KosApp.on_mount`/`on_resize` 小于 66×20 时用 `notice_big` 覆盖一屏，而不是让布局挤坏 |

### 9.5 测试（只断言文本，不碰颜色）

`tests/ui/test_keymap.py`：

1. 每个 context：`resolve()` 无重复键；每个动作都有 zh、en 标签（`Strings("zh")/Strings("en")` 不返回 key 本身）。
2. 底栏：对 §7 的每个 (屏幕, 焦点, 状态) 断言**整行文本**在 100×30 与 66×20 下与表一致，且 `cell_len ≤ 66`。
3. 一致性：底栏出现的每一段文本都能在 `resolve()` 里找到同名 label 的动作，且该动作有 `action_*` 方法；帮助行 ⊇ 底栏行。
4. 禁用：构造“无单元/无日志”的管理区，断言 `[5]`/`[4]` 仍在行文本里、带文字标记、`check_action` 为 False、底栏不出现其主动作。
5. 危险动作：`review.install`、`run.abort`、`menu.item.uninstall`、`snapshot.rollback` 的入口都经过 `ConfirmDialog`（用 `push_screen` spy 或断言首个按键不改变状态）。
6. 键位覆盖：`{"wizard.back": "b"}` 后底栏出现 `b 返回`，`esc` 不再后退。
7. 导航链：Welcome（Esc 不动）→ Checks → Options → Review → Confirm（默认返回）→ Esc 逐层回到 Welcome。
8. 数字：向导页没有数字绑定；管理区 `1..6` 命中对应行；禁用行按数字无状态变化。
9. 焦点穿透：Options 里 Enter = 下一步（不切换任何复选框），Space 才切换；`Tab` 走组。

---

## 10. 未决 / 后续

- `install_log_paused` / `key_pause` / `key_resume` 三条文案已存在但未实现（日志暂停）。若要做，动作是 `log.pause`（`p`），只在 Installation 页出现——与“进度页只留中止”冲突，建议**先不做**。
- Result 的按钮与键位双入口（`r` 与「重试」按钮）保留；按钮文本用 `[r] 重试` 形式，让屏幕阅读与键位一致。
- 侧栏数字删除后，`sidebar` 是否加行号仍待定；倾向不加（点击目标本来就可见），在 `?` 帮助里说明“可点击”。
