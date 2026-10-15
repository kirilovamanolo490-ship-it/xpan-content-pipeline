# Typefully 浏览器每日排期

这是「每日8条资料自动发布」的最后一段：文案审阅 → Telegram 发送 → Typefully MCP 建稿 → **浏览器确认定时发布** → MCP 回读 → 主表记账。首次部署必须取得使用者对每天持续执行的明确授权；仓库本身不授予发布权限。不要把 `DRAFT_CREATED`、媒体 ready、`planned` 或旧 `统一发布状态=COMPLETED` 当成排期完成。

## 时间与数量

准备任务每天 **17:00，Asia/Shanghai** 运行；八个发布槽固定如下：

| 第几条 | 上海时间 |
|---|---|
| 1 | 19:30 |
| 2 | 19:45 |
| 3 | 20:15 |
| 4 | 20:30 |
| 5 | 20:45 |
| 6 | 21:00 |
| 7 | 21:15 |
| 8 | 21:30 |

**20:00 留空**，不能因补数量、选“Next slot”或冲突而使用。自动化每天只填这八个位置；已有占位计入当天位置，不另起一批八条，不动用户在其他时段安排的内容。所有时间用带时区 ISO 值比较，UTC 回读换算为上海时间后必须精确相等；例如 19:30 对应 `11:30:00Z`。

如果运行晚了，只补当天仍在未来的固定空槽。错过的时段保持空缺，记录未完成条目；不立即发送、不自动跨天、不压缩间隔、不新增 21:45/22:00，也不把 20:00 填回来。素材不足八条时报告实际数量，不能降低媒体或文案门槛凑数。

## 开始前与选稿

1. 按主技能完成 doctor、Telegram Bot 只读检查和 Typefully MCP 账号检查。唯一目标是 X `@your_x_username`。网络命令使用当前有效权限，不固定要求 `require_escalated`，不改全局代理或凭据。
2. 浏览器只读预检：通过 `cua_repl` 查看已登录的 Typefully 页面，确认账号和 Asia/Shanghai 时区。在 macOS 已知 Chrome 打开 Typefully 时可直接 `cua.getApp('com.google.Chrome')`；浏览器扩展标签页清单失败不等于原生 Chrome 不可控制。若真实浏览器不可用或需人工处理登录，保留现有结果，停止新批次并报告具体原因。
3. 用 Typefully MCP `get_queue` 查询目标日期；另读取 `list_drafts` 的 scheduled、planned 与当天 published 条目，分页完整。队列不含已经发布的帖子，不能仅凭队列空就认定当天没有处理过。分页列表按日期有序时，读到目标日期之前才可停止；不要把截断页、错误响应或连接失败当空列表。
4. 按草稿 ID 合并当天的已排期、已计划和已发布记录。一个 ID 多份快照不一致时重新 GET；冲突时不猜。已有 scheduled/published 不重排。planned 占位置但不会自动发布：如果是本任务已选中、内容/日期/审阅均匹配的条目，可续接 Confirm；无关的 planned 不擅自转成发布或挪开。
5. 先全量查主表已有草稿 ID 的待排期行，包括 `next_serial` 之前的积压，按序号选择审阅和媒体就绪的条目。GET 确认仍是 draft 后复用同一 ID。不要重复发 Telegram、上传媒体或新建草稿。历史 COMPLETED 不足以排除它。
6. 已有合格草稿不足未来空槽数时，再从新资料游标准备新条目，走完整媒体、文案、Telegram、MCP 建稿流程。单行媒体失败保留该失败与游标，可继续核对后续资料补空槽；每次外发子集都须先全部审阅通过，不能超过当天空槽容量。
7. 已有草稿文案未符合新口吻时，先按 [editorial-review.md](editorial-review.md) 读源改写。MCP GET → 保留评论标记的 edit_draft（仅正文）→ GET，保留媒体/平台/日期等设置；同步 x.txt、主表 X文案与审阅记录。Telegram 已发内容不改不重发。没有有效审阅不得排期。

本地辅助命令 `scripts/typefully_schedule.py plan`（位于本技能目录）只计算固定时间槽，不读网页、不排期；完整参数见 `--help`。`--existing-json` 必须来自本次完整成功的 MCP 查询结果，不能手造空队列。记录每个选中草稿的序号、真实 Excel 行号、ID、正文与媒体 ID，以及分配时间。

### 浏览器预检的短暂故障恢复

- macOS 已有 Chrome 登录页时，优先直接 `cua.getApp('com.google.Chrome')`，从新读到的 UI 选择 Typefully 标签。能读取页面后核对 `@your_x_username`、上海时区及可打开的 Schedule 控件，不依赖扩展标签页清单成功。
- 只读预检遇到 ScreenCaptureKit `-3811` 或会话超时，可做总计最多三次尝试：首次失败后等待 15 秒，仍失败再等待 45 秒。工具报告 kernel reset 后按首次调用规则重新绑定；未重置而绑定失效时先 `js_reset`，随后只调用一次 `getApp` 取得新状态。不要沿用失效元素编号，也不要反复调用已经超时的全量标签页枚举。
- 三次均失败才记录浏览器预检阻塞。捕获失败不证明 Typefully 退出登录，不能据此清理 Cookie、重装扩展、重启或结束用户浏览器、改权限/代理/锁屏设置。登录、锁屏或授权页面确实需要用户操作时，报告可见证据与具体需要处理的环节。
- 本地定时任务需要电脑开机且 Codex 桌面应用运行；实际浏览器点击还需要可交互的桌面会话。排期完成后由 Typefully 到点发送，不要求本任务等待至发帖时刻。
- 页面提示被用户切换时，先刷新 UI 并重新定位 Typefully；连续被其他浏览器操作打断时，保留已确认结果，说明浏览器正被占用，等其他操作暂停后再恢复。不要在其他网站输入排期信息，不与其他任务争抢控件。原生 Chrome 可用时无需反复尝试已经超时的扩展连接。

### 旧草稿缺少上传状态文件

排期前检查 `typefully-upload-state.json` 的序号、真实行号、账号、媒体 ID、文件路径和 SHA-256，避免 Confirm 后才发现无法记账。历史草稿已有媒体但缺少该文件时，不能重传或凭文件名猜媒体 ID：

1. 实际 MCP GET 同一草稿，核对主表 ID、X-only、已审正文与唯一媒体 ID；再 MCP `get_media_status` 读取同一媒体，必须为 ready。
2. 复核本地源/最终 QA。仅使用该次媒体状态返回的 original 媒体 URL 做只读字节校验，流式计算 SHA-256 和大小，与本地最终媒体逐字节摘要一致；不创建新上传，不替换媒体。URL 只在内存或系统临时文件中使用，日志与持久状态不存 URL。
3. 校验一致才补建状态文件，记录 `serial`、`excel_row_number`、`social_set_id`、`media_id`、`media_file`、`media_sha256`、`last_verified_status=ready`、`provenance=existing-draft-and-original-byte-verification`、`verified_draft_id`、`remote_original_sha256` 和核验时间。明确这是本次恢复证据，不伪称历史上传时记录。
4. 原始字节不可读、摘要不符或媒体非 ready 时保留原草稿并阻塞该条。已有状态文件时核对而不覆盖；排期记账脚本会再次核对本地媒体摘要。

## 浏览器实际点击

每条依次完成，不并行操作同一个浏览器：

1. 用本次 GET 返回的 `private_url` 或草稿列表打开准确的同一草稿。确认当前正文、原夸克链接、媒体与主表所选项目一致，X 为唯一启用平台，页面账号为 `@your_x_username`。
   - 显示网页原文后，连续排期优先在同一页面使用 `Search & Commands → Search Drafts`，按序号检索并选择完整标题匹配项；搜索结果异步出现后再读新 UI。这样可避免每次整页导航重新触发自动翻译。每条仍核对唯一原链接和 GET 所对应的正文，不能只凭序号点击相似结果。
2. 点击右上角 **Schedule / 日程**。点击时间输入框展开日历；必要时在已聚焦的组合框按 Down，再读新 UI 状态。明确选当天日期，再点击对应的 15 分钟时间项；不要用默认 Tomorrow、Next slot 或最佳时间代替固定槽。
3. 收起时间选择器，核对输入框和 **Confirm Today, HH:MM (Asia › Shanghai)** 按钮显示完全相同的目标时间。浏览器自动翻译可能留下旧的按钮时间或改写可见中文，出现不一致时显示网页原文，再重新选择时间，直到两处一致。不要在时间不一致时确认。
4. **Natural posting time 关闭（±0m）**，保持精确时点。**Auto-RT、Auto-Plug、Auto-DM 都关闭**；Auto-RT 若打开，点击进入该条设置，再点击 Disable，等返回日程页后读取新状态确认关闭，不去修改账号的 Edit default settings。
5. 点击 **Confirm**。不要点击 Publish now，也不要点击 **Save as planned**。确认后页面可能短暂显示 Scheduling，等看到队列中同一草稿的目标时间再继续。
6. 所有点击使用刚读取的 UI 信息定位，每次动作后重新取 `getAXState()`。界面重绘导致元素编号失效时读取新状态再定位，不能沿用另一条草稿的编号，也不盲点坐标。若确认动作的结果不明，先执行下面的 MCP 核验，再决定是否恢复操作。

浏览器排期阶段只操作 Typefully；不打开 X Studio，不通过 X API、旧 CLI、直接 Typefully REST 或 MCP publish_at/plan_at 写入代替真实点击。浏览器 UI 是写入路径，MCP 是账号、队列和最终状态的核验路径。

## 回读与记账

确认后立即用 MCP `get_draft` 回读同一 ID，检查：

- `status` 必须为 **scheduled**，`scheduled_date` 必须与本条预期日期时间精确相同；planned、draft、Scheduling 提示都不算完成。
- 正文与已审 x.txt 完全相同，末行原 URL 不变；媒体 ID、标题、X 启用和其他平台关闭状态不变。
- `published_at` 此时为空；不能把“已排期”写成“已发布”。真实发布时间和帖子链接仅在实际发布回读时记账。

保存该次真实 GET JSON 到系统临时目录，再运行本技能的 `scripts/typefully_schedule.py record`，参数包含 `--row-index`、`--row-number`、`--draft-json`、`--expected-time`、`--social-set-id`。该工具只验证并定点记账，不访问外部平台；它不能代替本次实际 GET。

只写所选行的 `Typefully状态=SCHEDULED`、`X发布状态=已排期`、`X排期时间`（上海时区 ISO）、Typefully 更新时间及必要的本行错误字段；保留 Telegram 消息、正文、媒体、草稿 ID 和上游资料。回写核对其他单元格、公式、样式和 XLSX 完整性。每条成功立即记录回执，避免最后一条失败抹掉前面结果。

结束时再次核对当天队列，汇总每个固定槽的草稿 ID 和状态。报告“已排期，届时自动发送”，不提前称已发布。无需让 Codex 挂起等待到每个发送时点，实际发送由 Typefully 执行。

## 失败与重跑

- 同日重跑先重新读取队列和当天已发布记录，复用已有结果，只补剩余未来空槽。一个槽已有别的草稿时保留它，不能为凑本次八条覆盖或挤到 20:00。
- 某条确认超时：GET 同一 ID；已经是正确 scheduled 就只补记账。仍是 draft 才重新检查槽位和 UI；scheduled 时间不同、publishing、published 或结果无法确认时停止该条并报告，不自动新建或再次确认。
- 已建稿但未排期：保留 ID/媒体/Telegram 成功，下一次从排期续跑。不要调用 record_typefully_draft.py 把 scheduled 回退成 DRAFT_CREATED。
- 新资料 `next_serial` 不因只建稿而前进；以最小仍需恢复的新条目为准，已完成或明确永久跳过才可推进。旧草稿积压通过主表全量待排期扫描处理，不靠改写历史游标重发。
- 此流程的规则更新不触发当天补发，也不改动用户已安排的其他时段。下一次自动运行应用新时间表。
