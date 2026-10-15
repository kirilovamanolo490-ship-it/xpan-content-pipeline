---
name: telegram-auto-publish
description: 用于本项目资料的媒体准备、真实口吻文案编辑、Telegram Bot API 发送、Typefully MCP 建稿，以及已获授权的每日八条 Typefully 浏览器排期和失败续跑；不用于飞书收录或夸克归档。
---

# Telegram 自动发布 + Typefully 草稿与定时发布

在部署者明确授权每日任务后，「每日8条资料自动发布」可完成整条链路：先改好文案，再上传 Typefully，最后通过浏览器确认定时发布。准备任务每天上海时间 17:00 启动，发布槽固定为 **19:30、19:45、20:15、20:30、20:45、21:00、21:15、21:30**；**20:00 留空**。普通仅建稿请求仍止于草稿。完整排期、已有草稿续跑及当日防重复规则见 [Typefully 浏览器每日排期](references/typefully-browser-schedule.md)。

> 公开部署说明：本文件中的账号和链接均为占位示例。先配置根目录 `.env`，并通过 MCP 核对自己的账号。其他实例的既有授权、自动化和登录态不适用于新部署。正文中的固定双入口应替换为 `XPAN_X_PROFILE_URL` 和 `XPAN_TELEGRAM_CHANNEL_URL` 的实际值。

## 核心契约

始终遵守以下规则：

1. 唯一工作表固定为 `output/quark_links.typefully.xlsx`。本 Skill 直接读取这张表及其中的新夸克链接，不接受其他 Excel 路径、不另存工作副本、不重复转存、不修改夸克目录。文件名中的 `typefully` 是历史名称，但 X 发布现已固定使用 Typefully MCP。
2. 先只读递归完整夸克目录并建立目录结构，再判断首视频；不能只看分享页首屏，也不能把单次 API 返回顺序、更新时间、文件大小或字典序直接当成课程顺序。首视频选择优先使用文件名开头的明确课程/章节标记（如 `01`、`1.`、`1、`第一节`、`第1讲`、`零一`），在完整视频清单中选最小的可靠序号；同序号时保留目录深度优先顺序。没有可靠序号时，才使用保留原始深度优先顺序的 fallback，并记录判断依据和歧义。
3. 确定首视频 FID 后，只调用一次已部署的 `work/quark-auto-save/download_first_video.py` 完整下载；完整下载是源文件大小核对和源质检的前提，禁止回退旧 Cookie 下载器、浏览器下载、HLS 或公开预览地址。
4. 源质检通过后按固定顺序准备唯一发布视频：先只保留从 `00:00` 开始最多 `10:00`（600 秒）的前缀，再检查该候选的精确字节数；若 `>= 50,000,000` bytes，继续从尾部缩短，直到严格 `< 50,000,000` bytes。默认用 `ffmpeg -c copy` 截断，不转码、不降低画质、不改变开头；若源容器不是 Typefully 支持的 `.mp4/.mov`，再用流复制无损封装为 `.mp4` 并重新 QA。成功后只保留兼容命名 `project-video-original.<最终扩展名>` 这一份最终媒体，文件名中的 `original` 只是历史兼容名。
5. 只有完整递归确认没有视频时，才进入真实图片、PDF、Word、PPT、Excel 或文本预览封面流程。PDF/文档项目取得真实预览页后按源页面方向自适应：宽高比 `>= 1.10` 的偏横页面生成 `1920×1080`（16:9），其余偏竖或接近方形的页面生成 `1080×1920`（9:16）。完整保留预览页，不叠加标题、营销文案、目录统计或信息卡；即使媒体缓存标记为 `existing-local`，只要项目清单只有文档而没有图片/视频，也按此规则处理。
6. Telegram 只有一个传输：云端 Bot API。最终视频用 multipart `sendVideo`，最终图片用 `sendPhoto`；两者都必须严格 `< 50,000,000` bytes。任何媒体仍超限时阻塞并回到本地媒体准备，不使用 Chrome、Telegram Web、`file_id` 中转或其他客户端。
7. 不使用 Telethon、MTProto、Telegram Desktop、Local Bot API Server、Docker、`api_id` 或 `api_hash`。
8. X 的媒体上传、建稿和状态核验使用当前已连接的 Typefully MCP，复用 Telegram 已通过 QA 的同一发布视频/封面与 `x.txt`；建稿请求不传 `publish_at` 或 `plan_at`。每日八条任务建稿后继续通过 `cua_repl` 控制 Typefully 浏览器日程界面，确认固定时段的自动发布；不点击立即发布，不用直接 Typefully REST、旧 CLI 或 X API。分别执行 [MCP 建稿](references/typefully-mcp-publish.md) 与 [浏览器排期](references/typefully-browser-schedule.md)。
9. Telegram 与 X 独立发布、独立验收和独立记账；一端失败不得抹掉或重复另一端已经确认的成功结果。
10. 视频下载、解码、QA 或上传失败时，不得改选第二个视频或图片；记录具体原因。
11. 每日批次必须先准备媒体，再逐条阅读工作表简介、完整文件树和必要的源预览，改写 Telegram 与 X 文案并记录 `copy-review.json`；整批审阅通过后才能真实发送或创建 Typefully 草稿。`【待审初稿】` 不能外发。执行 [每日八条文案审阅](references/editorial-review.md)。

执行完整任务必须读取 [workflow.md](references/workflow.md)、[editorial-review.md](references/editorial-review.md)、[x-copy-style-pool.md](references/x-copy-style-pool.md)、[typefully-mcp-publish.md](references/typefully-mcp-publish.md) 和 [typefully-browser-schedule.md](references/typefully-browser-schedule.md)。旧的 Telegram Web/X Studio 引用不是当前路线。

## 工具路由

- **每次自动批次的 Typefully 入口预检**：在 doctor 与 Telegram Bot 只读检查通过后、任何媒体准备或 Telegram 外发前，先枚举当前会话可用的 MCP 工具，按提供方 Typefully 与动作名定位工具。当前 Codex 可能暴露为 `mcp__codex_apps__typefully_*`，其他宿主可能暴露为 `mcp__typefully__typefully_*`；下文的 `typefully_...` 是动作名，不是固定完整工具名。不能因一个前缀查不到就宣称断连。必要时重新查看完整工具清单及插件连接状态，再实际调用 `typefully_list_social_sets`（limit 不超过 50）和 `typefully_get_social_set_details` 唯一核对 X `@your_x_username`。如果真实连接或权限预检失败，新批次在媒体准备前暂停、游标不动，不给候选行写臆测的失败状态；已有单端结果仍按幂等规则保留并报告准确错误。详见 [Typefully MCP 创建 X 草稿](references/typefully-mcp-publish.md)。

- 跨平台入口：`python scripts/run_workflow.py publish --limit 1` 只准备媒体和带标记的文案初稿。先用 `python scripts/run_workflow.py doctor` 检查运行环境；缺依赖时使用 `python scripts/setup_runtime.py`。实际发送前必须按 [每日八条文案审阅](references/editorial-review.md) 重写、记录并核验，之后才加 `--telegram-send`；两次命令使用同一组明确的真实 `--row-number`。
- Windows/Mac 迁移：媒体路径使用 `xpan_auto.runtime.resolve_project_path` 按完整项目内路径重新定位。不得按同名文件猜测、篡改已完成状态或因旧路径失效重发；确实缺文件时保留失败事实。图片回写由 Python 按表头和真实行号处理，不调用旧 WPS COM 脚本。媒体工具支持 PATH、项目本地安装和 `XPAN_FFMPEG/XPAN_FFPROBE`。

- Excel：只使用 `output/quark_links.typefully.xlsx`。查数据优先运行 `.venv/bin/python scripts/query_ledger.py`，按表头直接读取单元格并返回真实 Excel 行号；不要截图、渲染、打开 GUI 或另存副本来读取表格数据。回写使用现有 Python 流水线，只更新选中行和必要输出列，并验证范围外数据与样式未变。只有用户要求排版/图表检查时才进行表格视觉检查。任何 `--xlsx` 覆盖值若不是该固定绝对路径都必须拒绝。
- 夸克：使用 `work/quark-auto-save` 和 `config/quark-storage.json`。目录只读定位后，把首视频 FID、文件名、已知大小和临时目录传给 `download_first_video.py`。
- 媒体检查与截断：先用 `ffprobe` 检查完整下载，再用 `ffmpeg -c copy` 依次执行 600 秒上限、50,000,000 bytes 上限和必要的 MP4 无损封装，最后再次用 `ffprobe` 检查唯一发布视频。所有输出先写临时文件，QA 通过后才原子替换兼容路径；失败时保留完整下载供同一 FID 重试。
- Telegram：只使用 `scripts/send_telegram.py` 和云端 Bot API；最终图片或视频只要 `>= 50,000,000` bytes 就阻塞。命令行不再产生退出码 `3` 或 Web 中转交接。发送器优先使用进程已有的 HTTP/HTTPS/ALL proxy；macOS 进程没有取得这些代理时，只为 Telegram Bot API 读取 `scutil --proxy` 中已启用的 HTTP/HTTPS 系统代理。此兜底不改变夸克或 Typefully MCP 的网络路由，也不得记录代理凭据。
- X：通过 Typefully MCP 的账号、媒体、草稿、`get_queue` 和 `list_drafts` 工具读取/建稿；二进制媒体只 PUT 到 MCP 返回的预签名 URL，建稿不传 `publish_at/plan_at`。排期使用 `cua_repl` 浏览器 UI，之后用 MCP `get_draft/get_queue` 核验；不能用 MCP 或 REST 排期写入代替用户要求的浏览器流程。
- 每日批次增加浏览器只读预检：确认 Typefully 页面已登录正确账号、日程可操作且显示 Asia/Shanghai；浏览器不可用时保留已有结果，报告具体阻塞，不用其他传输绕过。网络命令按本次有效执行权限运行，不无条件要求 `require_escalated`，也不擅自修改代理或权限配置。
- 浏览器捕获/会话短暂错误按排期参考执行最多三次只读重试，macOS 优先原生 Chrome；选稿后在 Confirm 前核对上传状态文件与媒体摘要。旧草稿缺少状态文件时，只能用真实 MCP 草稿/媒体回读及远端原始字节 SHA-256 一致证据恢复，不能重传或猜测媒体 ID。
- 凭据不得出现在 Excel、日志或回复中；即使错误信息意外包含，也不得复述。

## 范围、发布授权与幂等

- 默认先做一条 canary；只有用户明确给出连续范围或批量时才扩展。
- 区分“序号”与真实 Excel 行号。用户说“第 18 条/序号 18”时，先按 `序号=18` 定位，再报告工作表行号。
- 预览、检查、测试但未明确要求“发布/发送/同步/自动化”时，只做 dry-run，不调用 Telegram 或 X 外部写入动作。
- Telegram 发送前读取 Telegram 消息 ID 和状态；已有消息 ID、`已发送` 或 `发送中` 且用户未要求重发时跳过。
- 网络或页面超时后先查询外部状态，确认没有结果后才允许重试。
- X 建稿前读取 `Typefully草稿ID`、`Typefully状态` 和 `X发布状态`；已有 ID 时回读同一草稿，跳过重复上传/建稿。每日任务中 `draft` 仍需进入排期阶段；`scheduled/published` 不重排、不重发；`planned` 仅是占位，不能当成会自动发布。
- 未指定排期的一次性“发布/发送/同步”请求，Telegram 真实发送，X 端只上传媒体并创建不带 `publish_at/plan_at` 的草稿。每日八条任务按下项的持续排期授权执行。普通检查、预览或 dry-run 不创建媒体上传或草稿。
- 部署者对「每日8条资料自动发布」的明确持续授权可包括 Telegram 发送、Typefully MCP 建稿及固定时段的浏览器排期，不再逐条询问。该任务达到 `Typefully状态=SCHEDULED`、`X发布状态=已排期` 且时间回读正确才算排期完成；`DRAFT_CREATED/待发布` 只是中间状态。其他任务未获排期授权时止于草稿；未获 Telegram 发送授权时仍保持 Telegram dry-run。
- 每日先续排主表中已有且审阅有效的未排期草稿（包括 `next_serial` 之前的积压），不足当日空余槽位再从 `next_serial` 准备新条目。排期成功后立即记账；当天重跑只填未占用的未来固定槽，成功记录保留，不能重新凑八条。
- Typefully 上传或建稿结果不确定时写 `结果待确认`，先用 `typefully_get_media_status`、`typefully_get_draft` 或 `typefully_list_drafts` 核验，禁止盲目重复上传或建稿。

## Excel 输入与回写

固定主表：

```text
output/quark_links.typefully.xlsx
```

不得切换到 `output/quark_links.xlsx`、临时副本或其他导出表。

读取：

- `序号`
- 项目标题和项目描述
- `新夸克链接`
- `保存目录`
- Telegram 消息 ID 和 Telegram 发布状态，仅用于防重复
- `X资料状态`、`X发布状态`、`X排期时间`、`X帖子链接`，用于防重复和恢复
- `Typefully草稿ID`、`Typefully草稿链接`、`Typefully状态`、`Typefully错误信息`、`Typefully更新时间`，用于 MCP 草稿恢复和核验

写回：

- `媒体类型`：只写 `video` 或 `image`。
- 视频项目的 `原视频`、兼容列 `视频`、`Telegram视频` 和 `媒体路径`：全部写同一份最终发布视频 `project-video-original.<原扩展名>`；`原视频` 列名和文件名仅为历史兼容，不表示文件一定与夸克源大小和时长相同。
- 无视频项目的 `图片` 和 `媒体路径`：写最终 QA 通过的封面路径。
- Telegram：分别写状态、频道消息 ID、帖子链接、发布时间和错误。
- X 资料：媒体与脚本初稿准备后写 `X资料状态=文案待审阅`；最终两份文案通过审阅和本地 QA 后才写 `资料已准备完成`。
- X 草稿：草稿创建成功后写 `X发布状态=待发布`，保留 `X排期时间`、`X发布时间` 和 `X帖子链接` 为空；失败或不确定时只写 `失败` 或 `结果待确认`。
- X 排期：浏览器确认后回读同一 ID 为 `scheduled` 且时间完全匹配，才写 `Typefully状态=SCHEDULED`、`X发布状态=已排期`、上海时区 `X排期时间` 与 `Typefully更新时间`。`X发布时间/帖子链接` 只有实际发布证据才填写，不能提前写已发布。使用排期参考中的 `typefully_schedule.py record` 定点回写。
- Typefully MCP：写 `Typefully媒体路径`、`Typefully草稿ID`、`Typefully草稿链接`、`Typefully状态`、`Typefully错误信息` 和 `Typefully更新时间`；只更新选中行。已有草稿 ID 时必须先回读，不能覆盖为另一个草稿。
- 只有当 `x.txt` 与对应最终发布视频/封面都存在且通过本地检查时，才能写 `资料已准备完成`。
- 只更新选中行，不删除其他行、历史值或上游源数据。

## 夸克检查与媒体选择

### 递归检查

直接使用 Excel 中的新夸克链接或既有保存目录，不再次转存。记录本次执行需要的最小事实：

- 文件夹和文件总数
- 根目录、一级目录、课程/章节分支和相对层级
- 视频、图片、PDF、Word、PPT、Excel、音频等分类数量
- 文件名、扩展名、相对路径、层级和已知大小
- 顶层结构与内容主题线索

最小运行缓存写入：

```text
output/assets/{序号四位数}/telegram-project-details.json
```

它不是新的业务数据源，不把完整目录回写 Excel，也不修改夸克目录。

### 目录结构与首视频选择

- 必须先完成整棵文件树的递归读取，再从全部视频候选中选择首视频；不得在看到第一个 API 项目或第一个文件夹时立即下载。
- 判断时先识别主课程分支和章节结构，再解析视频文件名开头的显式序号。`62-72直播篇` 这类目录范围不能压过主课程中的 `1 第一节...`；目录名中的数字只有在视频文件名没有明确序号时才作为辅助线索。
- 展示标题可以清理 `(1)` 等复制噪音，但用于 FID、下载、QA 和 Telegram 匹配的源文件名必须保持原样。
- 运行缓存应记录 `first_video_selection_basis`、首视频文件名、FID、大小、相对路径和候选数量；无法判断时阻塞或报告歧义，不静默改选后续视频。

### 有视频：完整下载后只保存唯一发布视频

完整文件树建立后，按“目录结构与首视频选择”规则对全部视频候选做一次语义排序；最小可靠课程/章节序号对应的视频是唯一媒体。API 返回顺序只在没有可靠序号时作为深度优先 fallback；不得按更新时间、大小、时长、编码或纯字典序选择。

下载与截断步骤：

1. 调用 `work/quark-auto-save/download_first_video.py`，传入首视频 `FID`、原文件名、已知大小、`config/quark-storage.json` 和项目临时目录。
2. 下载成功后先核对本地大小与夸克已知大小，并用 `ffprobe` 完成源视频 QA；此时不得提前删除完整下载。
3. 先处理时长：源视频 `<= 600` 秒时保持不变；源视频 `> 600` 秒时用流复制保留 `[00:00, 10:00]` 前缀，丢弃其后内容。
4. 再处理大小：检查上一步候选的精确字节数；若 `< 50,000,000` bytes 即通过，若 `>= 50,000,000` bytes 则根据候选的实际时长与字节数估算截止时间，从 `00:00` 开始继续流复制，并以 `49,000,000` bytes 为目标预留容器余量。每次输出后以真实大小为准；仍超限时按实际结果继续缩短截止时间，最多有限重试，仍不合格则阻塞。
5. 对最终候选再次执行 `ffprobe` 和硬门检查：时长必须 `<= 600` 秒、大小必须严格 `< 50,000,000` bytes。通过后才原子替换为兼容路径 `project-video-original.<原扩展名>`；转换失败时保留完整下载供同一 FID 重试。
6. 清理截断临时文件和旧的 `project-video-x.mp4`、`project-video-telegram.mp4`、`project-video.mp4`。目录中只保留一份最终发布视频，不生成 Telegram/X 各自的派生文件。
7. 任一下载、源 QA、截断或最终 QA 失败时阻塞该行，不尝试后续视频或图片。

视频项目固定产物：

```text
output/assets/{序号四位数}/project-video-original.<原扩展名>
output/assets/{序号四位数}/video-quality.json
output/assets/{序号四位数}/telegram-project-details.json
output/assets/{序号四位数}/telegram-caption.html
output/assets/{序号四位数}/x.txt
```

源视频 QA 至少检查：

- 文件存在且非空
- 本地大小与夸克已知大小一致（夸克提供大小时）
- `ffprobe` 可读取并存在真实视频流
- 时长不少于 3 秒
- 分辨率至少 320×180
- 视频编码为 H.264 或 HEVC；音频存在时优先 AAC
- 文件名和 FID 对应目录首视频

最终发布视频 QA 在以上解码、流、时长下限、分辨率和编码检查之外，还必须验证：

- 从 `00:00` 开始，内容顺序未改变
- 时长 `<= 600` 秒
- 精确大小 `< 50,000,000` bytes；恰好等于 50,000,000 也不通过
- Telegram 路由固定为 `bot-api`

`video-quality.json` 记录源视频报告、是否执行十分钟截断、是否执行大小截断、是否执行 Typefully MP4 无损封装、最终报告、600 秒/50,000,000 bytes 上限和 Telegram 路由；不再含平台各自的派生报告。

### 完全无视频：资料预览封面

按以下顺序寻找可预览内容：

1. 项目真实图片
2. PDF 可读页面
3. Word、PPT、Excel、文本或其他可打开资料
4. 全部不可预览时，必须调用 ImageGen 生成基于真实项目事实的视觉封面；禁止继续使用本地纯文字信息卡

PDF、Word、PPT、Excel、电子书或文本资料取得真实预览后，使用该预览页本身作为封面并完整适配。源页面宽高比 `>= 1.10` 时选 `1920×1080`（16:9）横版；否则选 `1080×1920`（9:16）竖版，接近方形时优先竖版。允许仅用同一预览页生成柔化背景和阴影，不添加任何标题、营销文案、标签、数量或其他信息层。若缓存媒体类型为 `existing-local`，但完整清单含文档且不含图片/视频，也必须走此自适应文档封面分支。

文档封面 QA 必须确认：来源预览真实存在且可解码、最终图方向与源页面匹配且尺寸只能为 `1920×1080` 或 `1080×1920`、预览页未被截断、无新增文字叠加、PNG 可解码且文件严格 `< 50,000,000` bytes。真实图片封面按原质量门执行；ImageGen 兜底必须完整执行 [ImageGen 事实型视觉封面](references/image-generation.md)，从当前项目事实单独推导主题、构图、视觉语言和配色，并完成 2～4 个真实内容锚点、全尺寸看图、五项视觉验收和本地 QA。不得把某个题材的配色固化为后续项目模板。不合格时只做一次针对性重生成；仍不合格则阻塞，不发布。

## 文案与 X 草稿资料

生成：

```text
output/assets/{序号四位数}/telegram-caption.html
output/assets/{序号四位数}/x.txt
```

先从当前行介绍、完整文件树和必要的真实预览提取事实，再写表达；不得虚构课程数、文件数、讲师、价格、评价或收益案例，不得保证赚钱或承诺结果。生成脚本的两份文件都带 `【待审初稿】`，不能直接外发。

### 文案处理方法（默认）

不要直接把项目标题和目录统计拼成模板文案。先完成以下处理，再写 Telegram 和 X 文案：

1. 同时读取工作表当前行的完整标题、文字介绍、新夸克链接，以及 `telegram-project-details.json` 的全部 `items`、目录层级和文件顺序。简介是占位文字时不当事实；文件名不足以支持功能、方法或收入判断时，查看已有的真实预览页或本地媒体。不要只用少量代表文件或标题猜内容。
2. 先判断这条资料真正想帮人完成什么：直接分享工具、教一种技能、拆一个赚钱方法、提供可交付的模板，或仅供阅读参考。商业线索可能藏在目录里，尤其是上架、获客、成交、接单、带货、投稿、稿费、付费社群、平台结算等环节。把“做什么、给谁、钱从哪里来”核对清楚；只看见制作端时，不要把收入端写成已证实。
3. 为每条选一个最值得说的具体角度，并在审阅记录里引用真实文件名或路径。标题中的“日入”“月入”等数字不能当作已实现收益；价格、佣金、案例数字仅在源资料明确出现时使用，并标明案例性质。
4. 两个渠道共享关键事实，表达分别写：开头直接讲最吸引人的具体用处和优势，用路边聊天的口吻把关联卖点讲透。工具突出省掉的步骤，赚钱讲交付和成交，成人两性直白非露骨。可以用“我靠”“牛逼”“真挺爽”和 0～2 个 emoji，但不能八条同一个口头禅，不刻意错字，不把固定钩子、转折或目录介绍套在每条上。
5. Telegram 的完整标题必须保留以供核对；正文可去掉无意义的复制编号、扩展名等噪音。产品名可以做大小写和空格清理（如 `claudecode` → `Claude Code`），但不得改变事实。排版按内容选择短段、问句、步骤或清单，避免八条看起来只是替换了标题。

### 共同文案风格契约（Telegram 与 X 默认）

这两个渠道都用真实创作者分享发现和判断的口吻。可以直接、有力度，也要让读者看得出判断来自哪一项资料。每份文案必须满足：

- 开头直接说这条资料的关键点，可用痛点、问题、反差、具体场景或一句明确判断。口语、第一人称和感叹号只在自然时使用；不得假称自己试过、赚过或验证过。
- 情绪来自具体发现，例如某个文件把上架到成交串起来，或一套工具能减少重复操作。不要每条强行设置“惊讶转折”，也不要用同一口头禅制造热闹。
- Telegram 按内容使用自然短段落、留白或小清单；emoji 有语义作用才用。X 按 [X 文案风格池与批次去重](references/x-copy-style-pool.md) 选择结构，不采用固定段落或 emoji 模板。
- 不把“递归核验到多少个文件/视频/文件夹”、目录统计、字节数、QA 状态或内部流程写成正文卖点；这些只留在运行缓存、质量报告和汇报中。标题或源文件本身有必要的语义数字时，才可保留该数字并说明其真实含义。
- 不套用同一段落模板，也不要只写标题、目录清单或“从 A 到 B”。若初稿读起来像公告或通用介绍，必须根据具体证据重写。
- 商业、职业、流量或副业项目要用大白话说清楚“能做成什么产品/服务/内容、给谁用、收入从哪里来”；证据只覆盖其中一段时明确边界。具体金额、销量、佣金或收益只能引用源资料明确出现的数字，并标明是案例而非保证。
- 文案可以夸张表达资料的价值，但不能保证赚钱、保证通过、保证涨粉或虚构讲师、用户评价、案例效果。

Telegram 文案必须：

- 开头给出这一条的明确判断或场景，不靠“宝藏资料”“真的绝了”等空话；需要情绪时让情绪落在某个真实细节上
- 用真实文件或预览支撑“为什么值得看、怎么用、适合谁”；避免把目录逐项抄成广告
- 对有商业、流量、接单、职业或副业属性的项目，讲清证据支持的商业链路；没有收入证据时只写可做的任务或交付，不暗示必然赚钱
- 正文按信息量分自然短段，必要时用问题、步骤或清单；不要为了统一版式强凑字数或 emoji
- 包含真实新夸克链接、相关标签，以及固定双入口尾部：`𝕏 <a href="https://example.invalid/x/profile">X</a>` 和 `📣<a href="https://example.invalid/telegram/channel">频道</a>`；两者缺一不可
- 使用有效 HTML，媒体说明可见字符不超过 1024

X 文案必须：

- 读取并执行 [X 文案风格池与批次去重](references/x-copy-style-pool.md)，先按题材选择主风格，再写正文；连续 8 条至少使用 6 种主风格，相邻结构和开头不得重复
- [X 文案风格池与批次去重](references/x-copy-style-pool.md) 是自动化 X 文案的唯一格式来源。自动任务提示不得另行固定“3～6 段”“4～8 个 hashtag”“固定 Telegram 尾行”或完整介绍模板；发现这类历史规则时，必须以风格池为准并把任务配置迁移掉，防止回退
- 不设本地字数或加权字符硬上限，不用 `x_weighted_length` 截断或压缩正文。按内容安排长短和自然段，完整讲清主卖点及相关优势；不用固定字数或段落数削弱已认可的聊天口吻
- 最后一行仅为完整原始新夸克 URL，前面留空行，链接只出现一次；不加“资料在这/放这了/去看这套/值得收藏”等引导尾句。默认零 hashtag、零 Telegram 尾句；必要标签放在链接之前
- 第一人称、疑问、观点、步骤、故事、清单、媒体优先等结构按事实轮换；不得通过简单替换“我刚找到／我刚翻到”制造伪多样性
- 每条围绕一个清晰用途组织表达；与它相关的重要优势、使用步骤和商业路径可以展开，讲明白为什么有用。删掉泛泛介绍和不相关清单，正文说完就停，不加行动号召
- 商业类项目只突出一个真实机制、场景或路径；具体收益金额只能引用源资料中明确存在的价格、佣金或案例数字，禁止虚构或保证赚钱
- Typefully 如返回实际平台校验错误，记录准确错误并停止该行；不得在提交前凭本地字符数自行删减

X 发布前条件：

- 视频项目：最终 `project-video-original.<最终扩展名>` 和 `x.txt` 均存在且非空，源 QA、十分钟/大小处理、必要的 MP4 无损封装和最终 QA 全部通过。
- 无视频项目：最终封面和 `x.txt` 均存在且非空，封面 QA 通过。
- 媒体与待审初稿准备好时只写 `X资料状态=文案待审阅`；两份文案通过 [每日八条文案审阅](references/editorial-review.md) 并与 `copy-review.json` 一致后才写 `资料已准备完成`。取得并回读草稿 ID 只证明建稿完成；每日任务还须完成浏览器排期和状态回读。

### 每日批次的发送顺序

1. 对选定的真实 Excel 行号先运行不带 `--telegram-send` 的 `publish`，准备媒体和带 `【待审初稿】` 的两份文件；这一阶段不创建 Typefully 草稿。
2. 按 [每日八条文案审阅](references/editorial-review.md) 逐条改写、记录并检查。`review_copy.py` 的 `--row-index` 是序号，`--row-number` 才是 Excel 真实行号。商业类需记录交付物、受众、收入来源及证据程度；八条批次检查至少六种 X 主风格、三种版式。
3. 媒体准备失败的行单独记录、留待恢复；准备成功的行全部审阅通过后，仅对这些原选中行号加 `--telegram-send` 真实发送。发送入口再次核对发送子集的审阅记录和文件哈希，并保留手写成稿，不重新生成初稿。Typefully 上传前再核对 `x.txt` 与审阅记录一致。任一准备成功的行审阅失败时，本次不得外发、建稿或推进本批游标。
4. MCP 建稿并回读后，按 [每日浏览器排期](references/typefully-browser-schedule.md) 将同一草稿放入当天剩余固定槽，确认 `scheduled` 并回写。历史已发送 Telegram 的草稿直接复用，不重复第一阶段或 Telegram 发送。

## 发布前质量门

每条至少报告并通过：

- 序号与真实 Excel 行号
- 新夸克链接与保存目录
- 递归视频数量
- 媒体类型、首视频源文件名和唯一固定路径
- 源视频和最终发布视频 QA，或封面 QA
- 源/最终时长、源/最终精确字节数、是否执行两类截断、是否执行 MP4 无损封装与 Telegram 路由
- Telegram 文案字符数
- 当前 Excel 简介、完整目录和两个最终文案与 `copy-review.json` 一致，来源判断、真实文件证据、商业路径判断已记录；不得含 `【待审初稿】`
- X 文案非空且未被本地截断，包含真实夸克链接与 `x.txt` 路径；批次通过风格标签、开头去重和结构分布检查
- Telegram Bot、目标频道、历史消息 ID，以及最终媒体严格小于 Bot API 上限
- Typefully MCP 连接、唯一匹配 `@your_x_username` 的 social set、资料状态、历史草稿 ID 和草稿状态

未通过质量门时，不进行 Telegram 或 X 外部动作，也不写 X 准备完成或发布成功状态。

## Telegram 发布路由

1. 调用 `getMe`、`getChat` 和 `getChatMember` 核对机器人、目标频道与发帖权限，不暴露 Token。
2. 视频在发送前必须已按“先最多 10 分钟、再严格小于 50,000,000 bytes”准备完成，并使用 multipart/form-data `sendVideo` 直接上传唯一 `project-video-original.<原扩展名>`。任何最终视频 `>= 50,000,000` bytes 都视为准备失败，禁止发送或转 Web K。
3. 图片严格小于 `50,000,000` bytes 时调用 `sendPhoto`；图片大于或等于该值时阻塞并重新生成或优化最终封面，禁止 Telegram Web、浏览器中转或 `file_id` 接力。
4. 视频缩减只允许从尾部截断并保留开头，默认 `ffmpeg -c copy`；不得通过降低分辨率、码率或重新编码来满足大小限制。
5. 只有用户明确要求发布时才点击网页发送或传 `--send`；测试保持 dry-run。
6. API 返回 `ok=true` 且频道结果含 `message_id` 才算 Telegram 成功。
7. 超时后先查询 Bot 更新和频道，不得直接重复发送。

## Telegram Bot-only 硬门

以下要求适用于所有 Telegram 媒体：

1. 只调用 `scripts/send_telegram.py`；`--transport` 即使保留兼容参数也只能是 `bot-api`。
2. 最终媒体必须存在、非空且严格 `< 50,000,000` bytes；不满足时不得调用发送接口。
3. 视频只用 `sendVideo`，图片只用 `sendPhoto`。不调用任何 Telegram Web 中转、Chrome、Telethon、MTProto 或 Local Bot API Server。
4. Bot API 返回 `ok=true` 且频道结果包含 `message_id` 才算成功。上传超时后先核对频道和已知状态，确认未创建后才允许重试。

## Typefully MCP 创建 X 草稿

读取并执行 [Typefully MCP 创建 X 草稿](references/typefully-mcp-publish.md)。固定要求：

- 通过 `typefully_list_social_sets` 和 `typefully_get_social_set_details` 唯一锁定 X 账号 `@your_x_username`；账号缺失或歧义时停止。
- 通过 `typefully_create_media_upload` 取得预签名 URL，只做一次无额外请求头的原始文件 PUT，再用 `typefully_get_media_status` 等待 ready。
- 通过 `typefully_create_draft` 只启用 X，并复用最终媒体和 `x.txt`；永远不传 `publish_at` 或 `plan_at`。
- 创建后必须用 `typefully_get_draft` 回读同一 ID，确认状态为 `draft`；媒体 ready 本身不算草稿成功。
- 媒体上传/建稿不使用浏览器；每日排期只控制 Typefully 页面。始终不打开 X Studio，不调用 X API、直接 Typefully REST/API Key 客户端或旧 Typefully CLI。

## 完成标准

任务只有在以下条件满足时才算完成：

- 视频项目只存在一份最终发布视频，没有生成 X 或 Telegram 各自的派生视频；必要的 MP4 只是同一最终媒体的无损容器规范化，完整下载仅在失败恢复期间暂存
- 视频已按先 600 秒、后 50,000,000 bytes 的顺序处理并通过源/最终 QA，或封面、本地详情和两份文案均通过质量门
- Telegram 已通过 Bot API 取得频道消息 ID，或明确记录为失败/dry-run；不得存在新的“等待 Web 中转”结果
- 仅建稿请求以 MCP 回读 `draft` 为终点；每日八条任务必须继续取得正确固定时段的 `scheduled` 回读和页面队列证据。排期成功不等于帖子已经发布
- 历史 `统一发布状态=COMPLETED` 可能只代表 Telegram + Typefully 建稿，不能据此跳过待排期草稿；每日完成与游标判断以同一 ID 的 `scheduled/published` 实际状态为准
- Excel 目标行已回写必要的 Telegram、媒体、Typefully 和 X 状态，其他行和上游源数据未改变
