# 键位与菜单设计（KOS 安装器 TUI）

**已实现**（`installer/ui/keymap.py`、`installer/ui/widgets/footer.py`、`installer/ui/screens/confirm.py`）。本轮把功能键统一成 `Ctrl+…`、把单字母让给 Vim 导航（§12 记录这次的改动与理由）；第 8 节是冲突清单，第 11 节是实现与本稿的历史差异。

适用范围：`installer/ui/`（Textual 8.2.8，vendored）、`installer/__main__.py` 的 `--plain`/非 TTY 分支。所有可见文案进 `installer/strings.py`，zh/en 成对。

---

## 1. 七条定案

| 议题 | 结论 | 一句话理由 |
|---|---|---|
| 换页 | 向导页 `Tab` 下一页、`Shift+Tab` 上一页；其余屏幕 `Tab` 仍是焦点 | 线性向导用 Tab 最自然；表单/列表自己还要用 Tab 走焦点 |
| Enter | 只做“确认/激活”：Options 上作用于当前行，Review 进确认页，别的页不做页面切换；**Confirm 上 Enter 不做任何事** | 换页归 Tab；最后一页只认 Y 和 N |
| 确认页 | `Y` 开始安装、`N` 返回上一步（`Shift+Tab`/`Esc` 是 N 的别名）；Enter/Tab/方向键/数字都不响应 | 一屏两键，比“移动选中再确认”少一步，也不会被误触 |
| 功能键 | 一律 `Ctrl+…`：重试/重检 `ctrl+r`、日志 `ctrl+l`、详情 `ctrl+e`、新建 `ctrl+n`、管理 `ctrl+p`、帮助 `ctrl+k`、中止 `ctrl+z` | 单字母键让给导航；功能键同一前缀 |
| 退出 | **连按两次 `ctrl+c`**：第一次只提示，5 秒内第二次退出；模态问题里不生效 | Ctrl+C 已经在手边；两次按下既好记又不会误触，`ctrl+x` 不再绑定 |
| 导航 | Vim：`j`/`k` 下/上、`h`/`l` 左/右、`g`/`G` 首/末；方向键、`Space`、菜单数字不变 | 导航是**别名**，挂在已有动作上 |
| 安装来源 | 独立成块：`↑/↓` 只换来源，`Enter` 下到下方选项；下方块有自己的光标，首行 `↑` 回到来源 | 来源是单选且会重写工作区，和复选项不是一类东西 |
| Esc | Esc 只“返回”（向导页是 `Shift+Tab` 的别名），永不退出 | Esc 最易误触，退出必须是另一个手势 |
| 帮助 | `ctrl+k`（keys）；`?` 保留为**隐藏别名** | `Ctrl+?` 打不出来；`?` 可用但不上海报 |

全局不变式（后面所有表都由它推出）：

1. **Tab 换页**（仅向导页）；Enter 确认/激活，模态框与输入框除外。
2. **Space = 切换**，只作用于复选框；不选来源。
3. **Esc = 后退一层**，向导页上与 `Shift+Tab` 同义；没有后退时就不绑定。
4. **功能键一律 Ctrl**；单字母只做导航（`j k h l g G`），`?` 是唯一例外且不上海报。
5. Ctrl 选键避开终端、shell、tmux 的冲突（§9.3）；中止是 `ctrl+z`（raw 模式下就是普通按键），`ctrl+c` 两次是退出。
6. 数字只用于**有序选项**：菜单行（`[n]`）；确认页不再有数字。

---

## 2. 上下文（context）

屏幕声明一个上下文；聚焦的控件再追加一个，取并集后解析出这一屏的键位表。

| context | 由谁提供 | 说明 |
|---|---|---|
| `app` | `ChromeScreen` | 全局可用（`help.open`）；退出由 `KosApp` 的 Ctrl+C×2 负责，不在表里 |
| `wizard.welcome` | `WelcomeScreen` | 语言与入口 |
| `wizard.checks` | `SystemScreen` | 探针列表 |
| `wizard.options` | `OptionsScreen` | 表单页 |
| `option.source` | `SourceRow` 聚焦 | 安装来源块（独立光标） |
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

默认键位。底栏原样打印键名（`ctrl+r` 比 `^R` 长两格，但不用猜）；ASCII 终端把 `↑/↓`、`←/→`、`⏎` 降级成单词（`Strings.ascii`）。

| 动作 ID | 主键 | 别名 | 上下文 | 标签（strings key） | 备注 |
|---|---|---|---|---|---|
| `wizard.next` | `Tab` | | welcome / checks / options / review | `key_next` 下一步 / next | 换页；Confirm 上没有下一页 |
| `wizard.previous` | `Shift+Tab` | `Esc` | checks / options / review | `key_previous` 上一步 / back | Esc 是别名，不上底栏 |
| `app.manage` | `ctrl+p` | | welcome / result | `key_manage` 管理 / manage | 命令面板已关 |
| `help.open` | `ctrl+k` | `?` | 全部 | `key_help` 帮助 / help | 别名不进底栏；底栏永远最后一项 |
| `focus.next` | `Tab` | | result / menu / list.* / log.view | `key_focus_next` 下一项 / next field | 隐藏：向导页的 Tab 是换页 |
| `focus.prev` | `Shift+Tab` | | result / menu / list.* / log.view | `key_focus_prev` 上一项 / previous field | 隐藏 |
| `review.continue` | `Enter` | | review | `key_continue` 继续 / continue | 进确认页，不执行 |
| `wizard.back` | `Esc` | | menu / list.* / log.view | `key_back` 返回 / back | 无后退就不绑定 |
| `welcome.language` | `←` `→` | `h` `l` | welcome | `key_language` 语言 / language | 仍然不用 Tab |
| `check.move` | `↑` `↓` | `k` `j` | checks | `key_select` 选择 / select | |
| `check.refresh` | `ctrl+r` | | checks | `key_refresh` 重新检测 / re-check | 删除 F5 |
| `option.pick` | `↑` `↓` | `k` `j` | option.source | `key_select` 选择 / select | 只在来源内移动，且移动即选中 |
| `option.below` | `Enter` | | option.source | `key_below` 下方选项 / options below | 跳到下方第一个可用行 |
| `option.move` | `↑` `↓` | `k` `j` | option.check | `key_move` 移动 / move | 下方块内移动；首行 `↑` 回来源 |
| `option.activate` | `Enter` | | option.check | `key_confirm` 确认 / confirm | 切换当前复选框 |
| `option.toggle` | `Space` | | option.check | `key_toggle` 切换 / toggle | 不选来源 |
| `review.details` | `ctrl+e` | | review | `key_details` 命令详情 / commands | e = expand |
| `review.retry` | `ctrl+r` | | review（仅失败） | `key_retry` 重试 / retry | 失败前不绑定 |
| `log.open` | `ctrl+l` | | review（失败）、result | `key_log` 日志 / log | 复用 `LogViewerScreen` |
| `confirm.install` | `y` | | confirm | `key_confirm` 确认 / confirm | **danger**；这一页唯一的安装键 |
| `confirm.back` | `n` | `Esc` `Shift+Tab` | confirm | `key_cancel` 取消 / cancel | 别名不上底栏 |
| `result.retry` | `ctrl+r` | | result（非成功） | `key_retry` 重试 / retry | |
| `run.abort` | `ctrl+z` | | run / menu / list.*（运行中） | `key_abort` 中止 / abort | **danger**，立即生效，不再问 |
| `run.guard` | `ctrl+c` | | 同上（菜单里只在中止可用时） | — | 隐藏：吃掉 App 的退出键，运行中 Ctrl+C 不退出 |
| `menu.move` | `↑` `↓` | `k` `j` | menu / list.* | `key_select` 选择 / select | `OptionList` 自带方向键 |
| `menu.ends` | `g` `G` | | menu / list.* | `key_ends` 首末 / first/last | 列表首行/末行 |
| `menu.act` | `Enter` | | menu | `key_open` 打开 / open | 列表里 = 行的主动作 |
| `menu.goto` | `1`…`6` | | menu | `menu_goto` 直达 / go to | 只是说明行 |
| `menu.item.units` … `menu.item.back` | `1`…`6` | | menu | — | 隐藏绑定；禁用项保留槽位 |
| `unit.toggle` | `Enter` | `Space` | list.units | `key_toggle` 切换 / toggle | 关 `core` 已拒绝 |
| `snapshot.rollback` | `Enter` | | list.snapshots | `key_rollback` 回滚 / roll back | **danger**，确认框 |
| `snapshot.create` | `ctrl+n` | | list.snapshots | `key_create` 新建 / create | n = new |
| `logs.open` | `Enter` | | list.logs | `key_open` 打开 / open | |
| `log.scroll` | `↑` `↓` | `k` `j` `PgUp` `PgDn` | log.view | `key_scroll` 滚动 / scroll | |
| `log.halfpage` | `ctrl+u` `ctrl+d` | | log.view | `key_page` 翻页 / page | 只读视图，`ctrl+d` 不会关程序 |
| `log.ends` | `g` `G` | | log.view | `key_ends` 首末 / first/last | 顶部/底部 |
| `dialog.confirm` | `←` `→` `h` `l` `j` `k` 移动焦点，`Enter` 确认，`Esc` 取消 | | 对话框 | `confirm` / `cancel` | 默认焦点 = 取消；有输入框时字母让位 |
| `dialog.secret` | `Enter` / `Esc` | | 密码框 | `key_continue` / `cancel` | 输入框拥有全部字母 |

绑定细则：

- 一个动作可以有多把键；同一上下文里不允许两动作抢同一键（`resolve()` 直接 `raise`）。
- 别名（`j`、`k`、`h`、`l`、`?`）只在帮助覆盖层展开成 `↑/↓ j/k`，不占底栏。
- `hidden=True` 的动作（Result/菜单/列表上的 Tab、菜单数字）只进帮助。
- 禁用/不适用 = `check_action` 返回 `False`：底栏、帮助、按键三者同时消失。

---

## 4. 逐屏键位与默认焦点

`Tab` 只换页，不换焦点：向导页的“下一步/上一步”是 `Tab`/`Shift+Tab`，`Esc` 是 `Shift+Tab` 的别名但不上底栏。`h/l` 仍然只是左/右，不做翻页。

| 屏幕 | 默认焦点 | 键位 | 禁用/例外 |
|---|---|---|---|
| Welcome | 无（`#language` 只是文本） | `←/→` 或 `h/l` 语言 · `Tab` 下一步 · `ctrl+p` 管理 · `ctrl+k` 帮助 · `ctrl+c`×2 退出 | **Enter 不做任何事**（没有可确认的东西）；没有 Esc |
| Checks | 第一行探针 | `↑/↓` 或 `j/k` 选择 · `Tab` 下一步 · `ctrl+r` 重新检测 · `Shift+Tab` 上一步 · `ctrl+k` · `ctrl+c`×2 退出 | Enter 不做任何事 |
| Options（来源块） | 当前来源行 | `↑/↓` 或 `j/k` 选来源 · `Enter` 下到下方选项 · `Tab` 下一步 · `Shift+Tab` 上一步 · `ctrl+k` | 来源块不越界；`core` 不可选、Tab 不经过；`ctrl+c`×2 退出 |
| Options（下方块） | 第一个可用行 | `↑/↓` 或 `j/k` 移动 · `Enter` 切换复选框 · `Space` 同上（别名） · `Tab` 下一步 · `Shift+Tab` 上一步 · `ctrl+k` | 首行 `↑` 回到当前来源行；末行 `↓` 停住；`ctrl+c`×2 退出 |
| Review（正常） | 页面本身 | `Enter` 进确认页 · `Tab` 同上（下一页） · `ctrl+e` 命令详情 · `Shift+Tab` 上一步 · `ctrl+k` · `ctrl+c`×2 退出 | Enter 进的是确认页，不安装 |
| Review（准备失败） | 页面本身 | `ctrl+r` 重试 · `ctrl+l` 日志 · `Shift+Tab` 上一步 · `ctrl+k` · `ctrl+c`×2 退出 | `Enter`/`Tab`/`ctrl+e` 在失败页禁用 |
| Confirm | 页面本身 | `y` 开始安装 · `n` 返回上一步（`Shift+Tab`/`Esc` 同义） · `ctrl+k` | **Enter、Tab、方向键、数字都不响应**，整页保持原样 |
| Installation | 无（`#cancel` 仅鼠标） | `ctrl+z` 中止（立即） · `ctrl+k` | 导航键全部不绑定：无 Esc、无 Tab、无数字；Ctrl+C 在这里被吞掉，既不中止也不退出 |
| Result | 失败/取消 →「重试」；成功 →「退出」 | `Enter` 激活聚焦按钮（「退出」也用它） · `Tab`/`Shift+Tab` 换按钮 · `ctrl+r` 重试（非成功） · `ctrl+l` 日志 · `ctrl+p` 管理 · `ctrl+k` | 成功页无 `ctrl+r`；`ctrl+c`×2 也能退出 |
| Management | 第一行菜单项 | `1–6` 直达 · `↑/↓` 或 `j/k` 选择 · `g/G` 首末 · `Enter` 打开 · `Tab` 换焦点 · `Esc` 返回 · `ctrl+k`；运行中 `ctrl+z` 中止 | 禁用项保留编号与文字标注；运行中 Ctrl+C 不退出 |
| Units | 第一行单元 | `↑/↓` `j/k` 选择 · `g/G` 首末 · `Enter`/`Space` 切换 · `Tab` 换焦点 · `Esc` 返回 · `ctrl+k` | `core` 关闭被拒绝并给一行原因 |
| Snapshots | 第一行快照 | `↑/↓` `j/k` 选择 · `g/G` 首末 · `Enter` 回滚（确认） · `ctrl+n` 新建 · `Esc` 返回 · `ctrl+k` | 空列表时 `ctrl+n` 仍可用 |
| Logs（列表） | 第一个文件 | `↑/↓` `j/k` 选择 · `g/G` 首末 · `Enter` 打开 · `Esc` 返回 · `ctrl+k` | 无日志时列出空态文本 |
| LogViewer | 日志区 | `↑/↓` `j/k` 滚动 · `PgUp/PgDn` · `ctrl+u/d` 翻页 · `g/G` 首末 · `Esc` 返回 · `ctrl+k` | 只读，无单字符功能键 |

Options 的两块模型：

- **安装来源**是一个独立光标：`↑/↓`/`j/k` 在 stable / main / local 之间移动，移动即选中（标记 `(•)` 跟着走，`opts.source` 立即更新），到两端就停住，不会掉进下面的选项。
- `Enter` 在来源行上是“下去”：跳到下方第一个可用行（跳过 disabled 的 `core`），即第一个可选应用；没有应用时就是第一个高级项。底栏这时写 `⏎ 下方选项`。
- **下方块**（应用 + 高级）是自己的光标：`↑/↓`/`j/k` 在启用的行间移动，`Enter` 切换当前复选框，`Space` 同义。首行再 `↑` 回到当前选中的来源行——这是回去的唯一键盘路径，来源不会变得不可达；末行 `↓` 停住。
- `core` 行禁用且不在任何光标里；不可用的能力项同样跳过并有文字说明。
- 行控件在构造时摘掉 `enter`（`EnterPasses`）和 `space`（`ChoicePasses`），所以页面的 `Enter`/`Space` 不会被控件吃掉。

---

## 5. 执行确认页

`installer/ui/screens/confirm.py`，`STEP = 3`（侧栏仍停在「确认」）、`JUMP = False`，从 Review `Enter` 推入。66×20 版式：

```
 确认安装
 ────────────────────────────────────────
 将执行    2 个步骤
 源码      v0.3.0 · 2ca59a1f
 写入      ~/.local（无需 root）

 安装会接管 plasmashell，注销重新登录后生效。

 Y 确认（开始安装）    N 取消（返回上一步）
```

规则：

- `Y` 是唯一安装路径，只在这一页有效；`N` 返回 Review，`Shift+Tab` 与 `Esc` 是它的别名。
- 其余按键一律不响应：`Enter`、`Tab`、`↑/↓`、`j/k`、`h/l`、`1`/`2` 都不会安装、也不会改页面。
- 这一页本身就是计划的二次确认，所以 `Y` 不再叠加第二个对话框（那是用户明确要的单键确认）。
- `ctrl+c` 在模态页上不生效（卸载、回滚、密码），连按两下也不会绕过问题框；中止已经不需要问题框了，`ctrl+z` 直接停。
- 计划正文留在 Review 页；确认页只放“会改什么”与两个键，因此 66×20 不需要滚动。

---

## 6. 菜单层级

Management（`ManagementScreen`）是唯一菜单；子页是列表。

```
管理  (从 Welcome/Result 按 ctrl+p 进入)
├─ [1] 单元 (3)            → UnitsScreen        列表：↑↓ j/k 选择 · g/G 首末 · Enter/Space 切换 · Esc 返回
├─ [2] 快照 (2)            → SnapshotsScreen    列表：↑↓ j/k · g/G · Enter 回滚(确认) · ctrl+n 新建 · Esc 返回
├─ [3] Doctor              → 就地执行，日志在下方动作区
├─ [4] 日志                → LogsScreen          列表：↑↓ j/k · g/G · Enter 打开 · Esc 返回
│                             └─ LogViewerScreen  ↑↓ j/k · PgUp/PgDn · ctrl+u/d · g/G · Esc 返回
├─ [5] 卸载                不可用：未安装        （禁用，槽位保留）
└─ [6] 返回                （= Esc）
```

- 行文本固定带编号：`[1] 单元      3`、`[5] 卸载      不可用：未安装`。禁用行不只靠颜色：前缀 `·` + 明确文字；编号不变，按数字无动作。
- 有两处可验证的禁用谓词：`[5]` 要求至少一个单元已安装；`[4]` 要求 `paths.log_dir` 里有文件。其余始终可用。
- 子页不使用数字：列表长度随数据变，数字槽位会被数据推翻。行内动作一律 Enter，Esc 弹一层（`push_screen`/`pop_screen` 已是栈语义）。
- 首末用 `g`/`G`：列表用 `OptionList.action_first/last`，日志用 `scroll_home/scroll_end`，两者都只在本页绑定。
- 侧栏的 1–5 数字跳转删除；点击侧栏跳到已完成步骤**保留**（指针操作，不占键盘语义）。

---

## 7. 底栏文案（一行）

格式 `键 词`，项间两空格，帮助（`ctrl+k`）永远最后一项。宽度按**实际绘制**算（键 + 空格 + 词，行间 2 格）；放不下就按优先级整行裁掉，不裁字符。

优先级：帮助 1 → 中止 5 → 换页（Tab / Shift+Tab）5 → 主操作 10 → 次要功能 30–40 → 移动提示 35 → 首末 45 / 翻页 50 / 管理 50。换页和帮助排在最前，任何尺寸下都先保住；退出不在底栏（Ctrl+C 两下）。

### 100×30（全量）

| 场景 | zh | en |
|---|---|---|
| Welcome | `Tab 下一步  ←/→ 语言  ctrl+p 管理  ctrl+k 帮助` | `Tab next  ←/→ language  ctrl+p manage  ctrl+k help` |
| Checks | `↑/↓ 选择  Tab 下一步  ctrl+r 重新检测  Shift+Tab 上一步  ctrl+k 帮助` | `↑/↓ select  Tab next  ctrl+r re-check  Shift+Tab back  ctrl+k help` |
| Options（来源行） | `↑/↓ 选择  ⏎ 下方选项  Tab 下一步  Shift+Tab 上一步  ctrl+k 帮助` | `↑/↓ select  ⏎ options below  Tab next  Shift+Tab back  ctrl+k help` |
| Options（下方行） | `↑/↓ 移动  ⏎ 确认  space 切换  Tab 下一步  Shift+Tab 上一步  ctrl+k 帮助` | `↑/↓ move  ⏎ confirm  space toggle  Tab next  Shift+Tab back  ctrl+k help` |
| Review（正常） | `⏎ 继续  Tab 下一步  ctrl+e 命令详情  Shift+Tab 上一步  ctrl+k 帮助` | `⏎ continue  Tab next  ctrl+e commands  Shift+Tab back  ctrl+k help` |
| Review（失败） | `ctrl+r 重试  ctrl+l 日志  Shift+Tab 上一步  ctrl+k 帮助` | `ctrl+r retry  ctrl+l log  Shift+Tab back  ctrl+k help` |
| Confirm | `y 确认  n 取消  ctrl+k 帮助` | `y confirm  n cancel  ctrl+k help` |
| Installation | `ctrl+z 中止  ctrl+k 帮助` | `ctrl+z abort  ctrl+k help` |
| Result（成功） | `ctrl+l 日志  ctrl+p 管理  ctrl+k 帮助` | `ctrl+l log  ctrl+p manage  ctrl+k help` |
| Result（失败/取消） | `ctrl+r 重试  ctrl+l 日志  ctrl+p 管理  ctrl+k 帮助` | `ctrl+r retry  ctrl+l log  ctrl+p manage  ctrl+k help` |
| Management | `1–6 直达  ↑/↓ 选择  g/G 首末  ⏎ 打开  esc 返回  ctrl+k 帮助` | `1–6 go to  ↑/↓ select  g/G first/last  ⏎ open  esc back  ctrl+k help` |
| Units | `↑/↓ 选择  g/G 首末  ⏎ 切换  esc 返回  ctrl+k 帮助` | `↑/↓ select  g/G first/last  ⏎ toggle  esc back  ctrl+k help` |
| Units（运行中） | `↑/↓ 选择  g/G 首末  ⏎ 切换  esc 返回  ctrl+z 中止  ctrl+k 帮助` | `↑/↓ select  g/G first/last  ⏎ toggle  esc back  ctrl+z abort  ctrl+k help` |
| Snapshots | `↑/↓ 选择  g/G 首末  ⏎ 回滚  ctrl+n 新建  esc 返回  ctrl+k 帮助` | `↑/↓ select  g/G first/last  ⏎ roll back  ctrl+n create  esc back  ctrl+k help` |
| Logs | `↑/↓ 选择  g/G 首末  ⏎ 打开  esc 返回  ctrl+k 帮助` | `↑/↓ select  g/G first/last  ⏎ open  esc back  ctrl+k help` |
| LogViewer | `↑/↓ 滚动  ctrl+u/d 翻页  g/G 首末  esc 返回  ctrl+k 帮助` | `↑/↓ scroll  ctrl+u/d page  g/G first/last  esc back  ctrl+k help` |

### 66×20（英文实测；中文通常多留一行，因为汉字标签更窄）

| 场景 | 底栏 |
|---|---|
| Welcome | `Tab next  ←/→ language  ctrl+p manage  ctrl+k help` |
| Checks | `↑/↓ select  Tab next  Shift+Tab back  ctrl+k help` |
| Options（来源行） | `⏎ options below  Tab next  Shift+Tab back  ctrl+k help` |
| Options（下方行） | `⏎ confirm  space toggle  Tab next  Shift+Tab back  ctrl+k help` |
| Review | `⏎ continue  Tab next  Shift+Tab back  ctrl+k help` |
| Review（失败） | `ctrl+r retry  Shift+Tab back  ctrl+k help` |
| Confirm | `y confirm  n cancel  ctrl+k help` |
| Installation | `ctrl+z abort  ctrl+k help` |
| Result（成功） | `ctrl+l log  ctrl+p manage  ctrl+k help` |
| Result（失败） | `ctrl+r retry  ctrl+l log  ctrl+p manage  ctrl+k help` |
| Management | `1–6 go to  ↑/↓ select  ⏎ open  esc back  ctrl+k help` |
| Units | `↑/↓ select  g/G first/last  ⏎ toggle  esc back  ctrl+k help` |
| Units（运行中） | `↑/↓ select  g/G first/last  ⏎ toggle  esc back  ctrl+z abort  ctrl+k help` |
| Snapshots | `↑/↓ select  ⏎ roll back  ctrl+n create  esc back  ctrl+k help` |
| Logs | `↑/↓ select  g/G first/last  ⏎ open  esc back  ctrl+k help` |
| LogViewer | `↑/↓ scroll  ctrl+u/d page  g/G first/last  esc back  ctrl+k help` |

66 列最先被裁的是移动提示（`↑/↓`）与 `ctrl+r`；`Tab`、`Shift+Tab` 与 `ctrl+k` 始终保留。退出不在底栏：它是 Ctrl+C 两下，第一次会自己弹提示。中文底栏因为汉字更窄，那几行通常能多留一项。

新增文案：`key_below`（下方选项 / options below）；`key_ends`（首末）、`key_page`（翻页）沿用上一轮。

---

## 8. 冲突与迁移

### 8.1 本轮重绑（旧 → 新）

| 动作 | 旧键 | 新键 | 说明 |
|---|---|---|---|
| 退出 | `q` → `ctrl+x` → **`ctrl+c` 两次** | 最终回到 Ctrl+C：一次提示、5 秒内第二次退出；`ctrl+x` 不再绑定 |
| 帮助 | `?` | `ctrl+k`（`?` 隐藏别名） | 终端里 `Ctrl+?` 无法可靠输入；`?` 继续可用但不上海报 |
| 重试 / 重新检测 | `r` | `ctrl+r` | 单字母 r 不再占 |
| 日志 | `l` | `ctrl+l` | l 让给“右” |
| 命令详情 | `t` | `ctrl+e` | e = expand |
| 新建快照 | `c` | `ctrl+n` | n = new |
| 管理 | `^P` | `ctrl+p`（底栏写全） | 已经是 Ctrl；命令面板关闭 |
| 导航 | 仅方向键 | 增加 `j/k`、`h/l`、`g/G` | 别名，挂在原动作上 |

### 8.1b 本轮换页键（旧 → 新）

| 动作 | 旧键 | 新键 | 说明 |
|---|---|---|---|
| 下一页 | `Enter`（Welcome/Checks/Options） | `Tab` | Enter 回到“确认/激活”的本义 |
| 上一页 | `Esc` | `Shift+Tab`（`Esc` 保留为别名） | Shift+Tab 是 Tab 的自然反键，且不退出 |
| Options 来源 | `↑/↓` 走到下方 | `↑/↓` 只在来源内；`Enter` 下去 | 来源是单选且会重写工作区，与复选项分开 |
| 下方块返回 | — | 首行 `↑` 回到来源行 | 来源必须仍然可达 |
| 表单焦点 | `Tab`/`Shift+Tab` | 只有菜单/列表/Result 保留 Tab 焦点 | 同一键不在两种语义间打架 |
| 安装后启动 | 默认关 | 默认开（`--no-start` 关闭） | 装完就用的默认体验；关闭方式仍显式存在 |

### 8.2 Ctrl 选键与理由

| 候选 | 结论 | 原因 |
|---|---|---|
| `ctrl+q` | 不用 | XON/流控，按键到不了应用 |
| `ctrl+s` | 不用 | XOFF，冻结终端输出 |
| `ctrl+m` / `ctrl+i` / `ctrl+j` / `ctrl+h` | 不用 | 分别是 Enter / Tab / LF / Backspace |
| `ctrl+z` | 中止 | raw 模式下就是普通按键；cooked 终端会把它当挂起（§9.3） |
| `ctrl+\` | 不用 | SIGQUIT |
| `ctrl+a` / `ctrl+b` | 不用 | tmux / screen 前缀 |
| `ctrl+p` | 管理 | 命令面板已关（`ENABLE_COMMAND_PALETTE=False`）；shell 里是上一条历史，但 TUI 独占输入 |
| `ctrl+x` | 不绑 | 退出改用 Ctrl+C×2；`ctrl+x` 留空，避免两个退出键 |
| `ctrl+r` | 重试 / 重检 | R = retry；shell 的反向搜索在 TUI 里不生效 |
| `ctrl+l` | 日志 | L = log；shell 的清屏同理 |
| `ctrl+e` | 详情 | E = expand |
| `ctrl+n` | 新建 | N = new |
| `ctrl+k` | 帮助 | K = keys；`Ctrl+?` 打不出来，所以不选它 |
| `ctrl+c` | 退出（两次） | 其它页面由 App 接住：一次提示、5 秒内第二次退出；运行页与运行中的菜单动作被隐藏的 `run.guard` 吞掉（不中止也不退出）；模态问题里被屏蔽 |
| `ctrl+u` / `ctrl+d` | 日志翻页 | 只读视图；这里的 `ctrl+d` 不会结束程序。其它页面不绑 |

### 8.2b 换页与 Enter 的冲突处理

| 冲突 | 处理 |
|---|---|
| `Tab` 既是 Textual 的焦点键又是页面键 | 向导页在绑定时把继承的 `tab`/`shift+tab` 摘掉，再由注册表绑定；Result/菜单/列表的 `focus.next/prev` 只在这些上下文里出现（`OTHERS`），`resolve()` 的重复键检查保证不会双绑 |
| Confirm 没有下一页，但继承的 Tab 会移动焦点 | Confirm 属于 `PAGES`，继承的 Tab 同样被摘掉且注册表不绑 Tab：按 Tab 什么也不做 |
| 来源块与下方块共用一个方向键动作 | 拆成 `option.pick`（来源）与 `option.move`（下方），上下文互斥，注册表里不会重复 |
| Enter 在来源行与下方行含义不同 | 拆成 `option.below`（来源：下去）与 `option.activate`（下方：切换），底栏各写各的词 |
| 来源行用方向键移动时同时选中 | 移动后调用 `_select_source`：值、标记、明细、`opts.source` 一次性同步 |

### 8.2c 本轮确认页（旧 → 新）

| 动作 | 旧 | 新 | 说明 |
|---|---|---|---|
| 安装 | 移动选中项 + `Enter` | `y` | 用户明确改为单键确认；一页两键，误触风险由“必须在这一页”兜住 |
| 返回 | `1`/`2` 选中「返回」+ `Enter`，或 `Shift+Tab` | `n`（`Esc`/`Shift+Tab` 别名） | 返回键在任何状态下都只回上一页 |
| 选择 | `1`/`2`、`↑/↓`、`h/l/j/k` | 无 | 没有可选项，就没有“移动选中” |
| `Enter` | 确认当前选中项 | 不响应 | 单键安装只留给 Y |
| `review.install` / `confirm.pick` / `confirm.move` | — | 删除 | 换成一个安装键、一个返回键 |

### 8.3 Textual / 布局层面的冲突

| 现象 | 修法 |
|---|---|
| `RadioSet` 的箭头只移动一个不可见的“光标”，等 Space 才改值 | `CursorKeys` 丢掉 `up/down/left/right` 绑定，页面按值移动（标记跟着动） |
| `Checkbox`/`RadioButton` 自带 `enter,space`，会吃掉页面的 Enter | `EnterPasses` 在构造时把 `enter` 从行控件的绑定里摘掉 |
| Textual `Footer` 按焦点控件合并绑定，会隐藏本页提示 | 自绘 `KeyFooter`，只读注册表 |
| 窄屏按字符裁剪，提示被切一半 | `fit()` 按实际宽度整行裁，帮助优先级 1 |
| 对话框里的字母键抢走输入 | 无 `word` 时 `h/l/j/k` 移焦点；有输入框时 `check_action` 禁用这组绑定 |

### 8.4 历史迁移表（首版动作 → 新 ID）

| 现有 action | 屏幕 | 新 ID | 新键 |
|---|---|---|---|
| `cycle_language` | Welcome | `welcome.language` | `←/→`（`h/l` 别名） |
| `open_system` | Welcome | `wizard.next` | `Enter` |
| `open_manage` | Welcome / Result | `app.manage` | `ctrl+p` |
| `quit`（Welcome 屏） | Welcome | —（App 级） | `ctrl+c` 两次 |
| `move(±1)` | Checks | `check.move` | `↑/↓`（`j/k` 别名） |
| `refresh` | Checks | `check.refresh` | `ctrl+r` |
| `next` | Options / 各向导页 | `wizard.next` | `Tab` |
| `start` | Review → Confirm | `review.continue`（Enter 进确认页）+ `confirm.install`（`y` 安装） | `Enter` → `y` |
| `details` | Review | `review.details` | `ctrl+e` |
| `retry` | Review | `review.retry` | `ctrl+r`（仅失败） |
| `open_log` | Review | `log.open` | `ctrl+l` |
| `cancel` | Installation | `run.abort` | `ctrl+z`（立即） |
| `retry` | Result | `result.retry` | `ctrl+r` |
| `quit` | Result | —（「退出」按钮 + `Enter`） | 无 |
| `cancel_action` | Management / Units / Snapshots | `run.abort` | `ctrl+z`（运行中，立即） |
| `back` | 向导各屏 | `wizard.previous` | `Esc` |
| `back` | 菜单 / 列表 / 日志 | `wizard.back` | `Esc` |
| `toggle` | Units | `unit.toggle` | `Enter`（`Space` 别名） |
| `create` | Snapshots | `snapshot.create` | `ctrl+n` |
| `help` | 全部 | `help.open` | `ctrl+k`（`?` 隐藏别名） |
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
    danger: bool = False          # 危险色；单键入口也可以（Y、Ctrl+Z）

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
{ "keys": { "wizard.previous": "esc", "menu.item.logs": "l", "unit.toggle": "space" } }
```

- 未知动作 ID 与配置里其它未知键一样 `SystemExit`，并列出合法 ID。
- 覆盖在 App 构造前应用（模块级 `apply_overrides`），底栏/帮助/绑定自动跟随。
- 不支持改“上下文”，只改键位；空数组表示禁用该动作。

### 9.3 终端冲突（默认键位里一个都不出现）

| 组合 | 冲突 | 处理 |
|---|---|---|
| `Ctrl+M` / `Ctrl+I` / `Ctrl+J` / `Ctrl+H` | 分别是 Enter / Tab / LF / Backspace，无法区分 | 不绑；只用 `Enter`/`Tab` 本体 |
| `Ctrl+S` | XOFF，冻结终端输出 | 不绑 |
| `Ctrl+Q` | XON，按键到不了应用 | 不绑；退出用 `Ctrl+C` 两次 |
| `Ctrl+Z` | cooked 终端里是挂起（SIGTSTP） | 绑中止：TUI 在 raw 模式下收到的是普通 `^Z` 字节；若某终端/复用器仍截获它，用 `keys` 覆盖 `run.abort`（§9.2） |
| `Ctrl+\` | SIGQUIT | 不绑 |
| `Ctrl+D` | shell 的 EOF | 只在日志视图做半页（只读，且没有 shell 在读） |
| `Ctrl+A` / `Ctrl+B` | tmux/screen 前缀 | 不绑 |
| `Ctrl+C` | SIGINT；同时是 Textual 的复制 | 运行页/运行中的菜单动作由隐藏的 `run.guard` 吞掉；其余页面是 App 的“Ctrl+C×2 退出”；模态里不生效 |
| `Ctrl+R` / `Ctrl+L` / `Ctrl+E` / `Ctrl+N` / `Ctrl+P` / `Ctrl+K` | shell/readline 的常用键，但 TUI 独占输入 | 全部只做功能键（§8.2）；`Ctrl+X` 不绑 |
| `Alt-<键>` | 终端/SSH 下常被拆成裸 Esc，产生误后退 | 不绑任何 Alt 组合 |
| `Esc` 时序 | 真终端里裸 Esc 不等待；箭头是 `ESC [` 序列 | 只用裸 `Esc`；不依赖“Esc 连按” |
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
5. 危险动作：`confirm.install`、`run.abort`、`menu.item.uninstall`、`snapshot.rollback`；`confirm.install` 只存在于确认页（`Y` 之前必须经过 Review），卸载与回滚经过 `ConfirmDialog`，`run.abort` 直接生效。
6. 键位覆盖：`{"wizard.previous": "b"}` 后底栏出现 `b 上一步`，`esc` 不再后退。
7. 导航链：Welcome（Esc 不动）→ Checks → Options → Review → Confirm（`N` 回 Review）→ Esc/Shift+Tab 逐层回到 Welcome。
8. 数字：向导页没有数字绑定；管理区 `1..6` 命中对应行；禁用行按数字无状态变化。
9. 焦点穿透：Options 里 Enter = 下一步（不切换任何复选框），Space 才切换；`Tab` 走组。

---

## 10. 未决 / 后续

- 日志暂停（`key_pause`/`key_resume` 文案已在）仍未实现。若要做，只能占一个 Ctrl 键（建议 `ctrl+o`，`ctrl+p` 已被管理占用），且只出现在 Installation——与“进度页只留中止”相冲突，倾向**先不做**。
- Result 的按钮文本保持单词（「重试」/「退出」），键位写在底栏与帮助里，不再在按钮上贴 `[r]`。
- 侧栏数字删除后，`sidebar` 是否加行号仍待定；点击目标本来就可见，倾向不加。

---

## 11. 实现记录（首版与 §1–§10 的差异）

> 这是**上一轮**的记录；本轮（§12）覆盖其中与 Ctrl/Vim 有关的行。

| 项 | 差异 | 原因 |
|---|---|---|
| `resolve()` | 多一个可选 `measure`：`resolve(contexts, overrides, budget, measure)` | 行宽取决于当前语言的 `strings`，注册表不引 `Strings`；屏幕传入测量函数 |
| 窄屏裁剪 | 只裁**底栏**（`keymap.fit`），绑定永不裁剪 | 提示可以少一行，按键不能因为终端窄而失效 |
| 方向键 | 一个 id、两个方法：`check.move` → `checks_move(±1)`，`option.move` → `option_move(±1)` | Textual 的参数化 action 需要逐键目标，id 保持给配置用 |
| 单选组箭头 | 新增 `option.pick`（**本轮起**由页面按值移动，见 §12） | 单选的词是“选择”，复选的是“移动”，一行动作一个词 |
| Result 退出 | 新增 `result.exit`（`q`），与 `app.quit` 分开 | 结果页的词是“退出 / exit”，不是“quit”；成功页把它排到第一位 |
| 菜单数字 | `menu.item.*` 是隐藏绑定；可见的说明行是 `menu.goto`（`1–6 直达`） | 六个动作各绑一个数字，底栏只需要一行说明 |
| 列表回车 | 表的行只提供提示，实际由 `OptionList` 的 `Enter → OptionSelected` 落到同一个方法 | 列表控件已经拥有 Enter，重复绑定没有意义 |
| 对话框 | 不进注册表；`ConfirmDialog` 增加 `confirm_label`/`cancel_label` | 模态屏幕只活在自己的栈帧里，文案按动作命名（中止/继续运行） |
| 焦点 | `focus.next` 绑 `app.focus_next`，Options 覆写为“跳到下一组” | 表单要按组走，其它屏仍是逐控件 |
| 进度页 | `#stages_box`、`#log`、`#cancel` 全部不可聚焦 | 误触 Enter 不能中止；中止只走 Ctrl+Z（§16 前是 Ctrl+C + 确认） |
| Ctrl+C | `KosApp` 用 `inherit_bindings=False` 真正去掉 Textual 自带的 `ctrl+q`；该轮曾让 Ctrl+C 只做中止（**§15 起又回到双击退出，§16 起中止改 Ctrl+Z**） | 继承的 `ctrl+q` 原来仍能退出；双击退出的提示又把“退出”说成了 Ctrl+C |

测试：`tests/ui/test_keymap.py`（表本身：重复键、双语标签、冲突键、覆写）与
`tests/ui/test_navigation.py`（每屏整行底栏 100×30 / 66×20、帮助 ⊇ 底栏、禁用槽位、
危险动作非单键、Esc 链、向导无数字、Options 的 Enter 穿透、直接中止）。

---

## 12. 本轮变更记录（Ctrl 功能键 + Vim 导航）

用户的指示：**功能键全部 Ctrl，单字母让给 Vim 导航**。做法是把现有动作重绑，而不是再造一套按键。

### 12.1 最终键位

| 功能 | 键 | 理由 |
|---|---|---|
| 退出（向导 / 结果页） | `ctrl+x`（**§15 起改为 Ctrl+C×2**） | X = exit；`ctrl+q` 是 XON 到不了应用 |
| 管理 | `ctrl+p` | 已是 Ctrl；命令面板关闭后无冲突（`ctrl+m` 是 Enter） |
| 帮助 | `ctrl+k`，`?` 隐藏别名 | K = keys；`Ctrl+?` 在终端里打不出来，`?` 保留但不上底栏 |
| 重试 / 重新检测 | `ctrl+r` | R = retry；`ctrl+r` 在 shell 里是反向搜索，TUI 独占输入 |
| 日志 | `ctrl+l` | L = log；同一理由 |
| 命令详情 | `ctrl+e` | E = expand |
| 新建快照 | `ctrl+n` | N = new |
| 中止 | `ctrl+c`（**§16 起改为 `ctrl+z`**） | 当时不变；只在中止与运行中菜单动作上绑定 |
| 日志翻页 | `ctrl+u` / `ctrl+d` | 只读视图；`ctrl+d` 的 EOF 语义在这里没有 shell |

### 12.2 Vim 是别名，不是第二套动作

`j/k` 挂在 `check.move`、`option.move`、`option.pick`、`menu.move`、`log.scroll` 上；`h/l` 挂在 `welcome.language`；`g/G` 是新动作 `menu.ends` / `log.ends`（列表首末、日志顶部/底部），因为它们没有现成动作可挂。（确认页的两个选项已在 §14 改成 Y/N，`confirm.move` 不复存在。）

`h/l` **不做翻页**：向导的“上一步/下一步”仍然只有 Esc / Enter。原因：`l` 翻页会让一次误触跳过整页，而且与“`h/l` = 左/右”的 Vim 语义打架。向导页不需要横向移动，所以 `h/l` 在 Checks / Options / Review 上没有绑定。

### 12.3 为了 Vim 顺手而修的两处控件行为

- **单选组**：Textual `RadioSet` 的箭头只移动一个不可见的 `_selected`，值要等 Space。`CursorKeys` 把 `up/down/left/right` 从集合的绑定里摘掉，页面按键直接改 `value`，标记（`(•)`）跟着动。Options 的来源组因此“一按就变”。（确认页此后不再用单选组，见 §14。）
- **确认页不环绕**：在「返回」上按 `l`/`j` 不动，`h`/`k` 才移到「开始安装」——默认态永远是最安全的。

### 12.4 底栏宽度

`fit()` 现在按**实际绘制宽度**算（键 + 空格 + 词，行间 2 格），预算 = 终端宽度 − 2（底栏左右各 1 格内边距）。之前按 `键+2` 估算，66 列时会多裁一行。优先级：帮助 1 → 中止 5 → 主操作 10 → 上一步 15 → 退出 20 → 移动 35 → 次要功能 40 → 首末 45 → 翻页/管理 50。帮助永远是最后一项、也最后被裁。

66×20 下英文会裁 1–3 行（`ctrl+r` 重检、`↑/↓` 移动、`g/G`、`ctrl+p` 管理、失败页的 `ctrl+n`），中文因为汉字标签更窄通常多留一行。两种语言的整行文本都在 `tests/ui/test_navigation.py` 里钉住。

### 12.5 对话框

`ConfirmDialog`：无输入框时 `←/→` 与 `h/l/j/k` 在「取消 / 确认」之间移焦点，`Enter` 按当前按钮，`Esc` 取消；**有输入框（卸载要输入的 `uninstall`）时这组字母被 `check_action` 关掉**，输入框拥有全部字母。密码框同理，不绑任何字母。

### 12.6 去掉的

- `ctrl+c` 双击退出与它的提示文案：退出只保留 `ctrl+x` 一条路。（§15 起又改回双击 Ctrl+C。）
- `?` 不再是底栏上的帮助键（改成 `ctrl+k`），但按 `?` 仍然打开覆盖层。
- 单字符功能键 `q`、`r`、`l`、`t`、`c`、`m` 全部移除。

### 12.7 测试

`tests/ui/test_keymap.py` 增加：功能键必须 `ctrl+`、导航不得用 `ctrl+`、Vim 别名齐全、`ctrl+q/s/z/…` 不被使用、帮助是 `ctrl+k` + `?` 别名。`tests/ui/test_navigation.py` 更新两种尺寸的整行底栏，并新增 Vim 用例（Checks 的 j/k、Options 的来源 j/k、Confirm 的 h/l、菜单/日志的 j/k/g/G/`ctrl+u/d`），以及“Ctrl+C 只中止、从不退出”。`tests/ui/test_app.py`、`test_wizard.py`、`test_sudo.py`、`test_manage.py` 里的旧键同步改成 `ctrl+r`/`ctrl+e`/`ctrl+p`。

---

## 13. 本轮变更记录（Tab 换页、来源独立成块、默认启动）

### 13.1 换页与 Enter

- 向导页（Welcome/Checks/Options/Review/Confirm）用 `Tab` 下一页、`Shift+Tab` 上一页；`Esc` 在向导页上是 `Shift+Tab` 的别名，但不上底栏。
- `Enter` 只做确认/激活：Welcome/Checks 上没有动作（按了不动），Options 看当前行（来源 → 下去；复选 → 切换），Review 进确认页。（Confirm 上的 Enter 在 §14 改为不响应。）
- Confirm 没有 `Tab`：最后一页没有下一页，误触不会安装，也不会改选中项。
- Result、菜单、列表、日志仍然用 `Tab`/`Shift+Tab` 换焦点（`focus.next/prev` 只在这些上下文里）。

### 13.2 Options 的两块

- 安装来源是独立光标：`↑/↓`/`j/k` 只在 stable/main/local 之间移动并即时选中；到两端停住，不越界。
- 来源行上 `Enter` = 下到下方第一个可用行（跳过 disabled 的 `core`），底栏写 `⏎ 下方选项`；没有可选应用时落在第一个高级项。
- 下方块（应用 + 高级）是自己的光标：`↑/↓`/`j/k` 在启用行间移动，`Enter` 切换，`Space` 同义；首行 `↑` 回到当前选中的来源行。
- `Tab` 不再承担组间跳转；表单的“往上回去”由首行 `↑` 提供，来源不会不可达。

### 13.3 安装后立即启动默认开

- `plan.Options.start` 默认改为 `True`；`build_plan` 因此在最后追加 `kosctl start`。
- CLI 新增 `--no-start`（`--start` 保留，默认已是开）；配置文件 `start: false` 仍然生效，命令行 `--no-start` 优先。
- 向导里 `安装后立即启动` 首次打开即勾选；Review 的 `安装后会重启用户服务` 警告默认出现。
- 测试：`test_installer_plan` 的默认计划现在以 `start` 结尾，并新增默认开 / `--no-start` / `config start:false` 三条用例；`test_wizard` 断言复选框默认勾选、Review 有警告、计划含 `kosctl start`。

### 13.4 测试与尺寸

`tests/ui/test_navigation.py` 用 Tab 走页面，新增：Tab 换页而 Enter 不换页、Confirm 上 Tab 无效（§14 起整页只认 Y/N）、来源块不越界、Enter 下去 / 首行 `↑` 回来、空格只切换复选框；底栏两种尺寸整行钉住（英文 66 列表另列）。`tests/ui/test_keymap.py` 增加页面键与焦点键的上下文互斥、以及 `option.pick`/`option.below` 的断言。整套 `232` 项全绿。

### 13.5 66×20

`Tab`、`Shift+Tab`、`ctrl+k` 的优先级最高，任何宽度都会保留；被裁的是移动提示、`space 切换`、`ctrl+r`。（§15 起底栏不再有退出项，退出是 Ctrl+C 两下。）来源行在 66 列英文下只剩 `⏎ options below  Tab next  Shift+Tab back  ctrl+k help`。

---

## 14. 本轮变更记录（确认页改成 Y / N）

- 确认页删掉 `RadioSet` 与 `1`/`2` 选择，只剩摘要 + 一行提示：`Y 确认（开始安装）    N 取消（返回上一步）`。
- 按键：`confirm.install` = `y`（`danger`，调 `app.start_install()`），`confirm.back` = `n`（`Esc`/`Shift+Tab` 为别名）。`review.install`、`confirm.pick`、`confirm.move` 删除；`wizard.previous` 不再覆盖 Confirm。
- 页面保持惰性：`Enter`、`Tab`、方向键、`j/k/h/l`、`1/2` 都不响应；Tab 仍然因为向导页摘掉继承绑定而为空。
- 底栏：`y 确认  n 取消  ctrl+k 帮助`（en: `y confirm  n cancel  ctrl+k help`），两种尺寸都只有三项。
- “不可用单键安装”的旧规则被用户本轮显式推翻：Y 是单键，但只在这一页、只在这一屏可选；其余危险动作仍需确认框。
- 测试：`test_confirm_is_inert_until_y_or_n`（Enter/Tab/1/2/方向/vim 全部无动作、N 返回）、`test_y_installs_and_n_goes_back`、`test_shift_tab_and_escape_both_leave_the_confirm_page`；`start_install` 辅助函数改为 `y`；危险动作集合改为 `confirm.install`。

---

## 15. 本轮变更记录（退出改回 Ctrl+C 两下）

- 退出不再是键位表里的一行：`app.quit` 与 `result.exit` 删除，`ctrl+x` 不绑任何东西。`KosApp.BINDINGS` 里绑一条 `ctrl+c`（继承绑定仍然关闭）。
- 手势：第一次 `ctrl+c` 在右下角弹出 `再按一次 Ctrl+C 退出` / `Press Ctrl+C again to quit`，5 秒内第二次调用 `app.exit()`；窗口过去后重新计数。宽度自适应（`Toast { width: auto }`）。
- 模态屏蔽：`ConfirmDialog`、`PasswordDialog`、`HelpScreen` 都是 `ModalScreen`，App 的处理函数先看屏幕类型直接返回，所以问题框里的 Ctrl+C 不会绕过它、也不会“预热”退出计时。
- 运行中让位：Installation 与管理区动作的 `run.abort` 是屏幕绑定，链条里先于 App，所以 Ctrl+C 依旧是中止；第一次中止会弹出确认框（**§16 起改为 Ctrl+Z 立即中止**）。
- Result 只保留「退出」按钮，`Enter` 激活它（`Tab`/`Shift+Tab` 换按钮）；底栏不再有退出项。
- 底栏因此空出一格：66 列英文下 `ctrl+r` 重检、`space 切换` 等更容易留下（见 §7）。`ctrl+k` 仍是最后一项、最后被裁。
- 删掉的字符串：`key_quit`、`key_exit`、`quit_title`、`quit_confirm`、`quit_stay`、`quit_leave`（退出对话框整条路径随 `request_quit` 一起删除）；恢复 `ctrl_c_hint`。
- 测试：`test_ctrl_c_twice_quits_from_the_wizard`（第一次只提示、第二次 `_exit`）、`test_a_modal_question_suppresses_the_quit_gesture`（中止框里连按不退出）、`test_help_overlay_does_not_arm_the_quit_gesture`（帮助关闭且不计时）、`test_abort_question_takes_arrows_and_vim_keys`（把原来的退出框测试改成中止框）、`test_ctrl_x_is_not_a_quit_key`；底栏两种尺寸整行更新。

---

## 16. 本轮变更记录（中止改 Ctrl+Z，不再确认）

用户的指示：**不需要确认终止框了，`ctrl+z` 为中止**。

- 键位表：`run.abort` 从 `ctrl+c` 换到 `ctrl+z`，`danger` 保留（底栏仍用红色）。新增隐藏行 `run.guard`（`ctrl+c`，同一组上下文，无标签、不上底栏），它唯一的职责是让 App 的退出绑定在运行中收不到按键。表里的顺序就是绑定的顺序：屏幕绑定先于 App 绑定。
- 立即中止：`KosApp.request_abort()` 与 `_abort_answer()` 删除，换成 `abort()`——有 `action_screen` 就 `cancel_action()`，否则 `cancel_install()`。`cancel_install()` 设事件并调用 `InstallationScreen.note_cancel()`，页面进入已有的 `install_cancelling` 状态（标题变 `正在取消…`），随后照常进 Result（`cancelled` / 130）。没有第二个问题框，也不再有“继续运行”的默认焦点。
- 鼠标：Installation 的 `取消` 按钮走同一个 `app.abort()`。
- Ctrl+C 的三层含义：向导/Result 上是 App 的“两次退出”；Installation 与运行中的管理动作上被 `run.guard` 吞掉（既不中止也不退出）；`ConfirmDialog`/`PasswordDialog`/`HelpScreen` 等模态里被 App 的 `ModalScreen` 判断挡住。管理区的 `check_action` 只在 `busy` 时允许 `run.abort` 与 `run.guard`，所以空闲时 Ctrl+C 照常可以退出。
- 运行中底栏：Installation `ctrl+z 中止  ctrl+k 帮助`；管理区动作运行中多一项 `ctrl+z 中止`（§7 的 `Units（运行中）` 行）。空闲的管理区底栏不变。
- 管理区运行中底栏原先不刷新：`action_started`/`handle_action_done` 从 `refresh_bindings()` 改成 `_bind_keys()`，自绘的 `KeyFooter` 才会跟着重画。
- 删掉的字符串：`abort_title`、`abort_body`、`abort_confirm`、`abort_keep`。`key_abort`（中止 / abort）保留。
- 终端注意：`Ctrl+Z` 在 cooked 终端里是 SIGTSTP（挂起）。TUI 处在 raw 模式，收到的是普通 `^Z` 字节，所以默认能用；如果某个终端、tmux 配置或 SSH 层把它提前截获（表现为进程被挂起而不是中止），用配置覆盖即可：
  ```json
  {"keys": {"run.abort": ["ctrl+shift+z"]}}
  ```
  其余键位、底栏与帮助会一起跟着换。
- 测试：`test_abort_is_immediate_on_the_run_page`（`ctrl+z` 后事件立即置位、Result 为 `cancelled`/130）、`test_ctrl_c_does_nothing_while_a_run_owns_it`（运行中连按不退出也不中止）、`test_abort_on_a_busy_menu_stops_the_action`（运行中底栏有 `ctrl+z abort`，Ctrl+C 被吞，`ctrl+z` 停掉动作）、`test_ctrl_z_cancels_a_running_action`（test_manage）、`test_ctrl_c_is_guarded_where_abort_runs`（test_keymap：guard 与 abort 同上下文、guard 隐藏且可解析）、`test_a_modal_question_suppresses_the_quit_gesture` 改用卸载问题框；`abort_the_run` 改为直接按 `ctrl+z`。
