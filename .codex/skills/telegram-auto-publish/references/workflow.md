# 完整工作流程

跨平台启动与检查：`python scripts/run_workflow.py doctor`、`python scripts/run_workflow.py publish --limit 1`。项目 `.venv` 必须在当前系统原生创建；不复用 Windows 的可执行文件。图片回写不依赖 WPS COM，媒体路径通过公共路径解析器兼容项目迁移。

## 目录

1. 输入与范围
2. Excel 读取
3. 夸克只读定位
4. 媒体决策
5. 标准本地产物
6. 文案
7. 质量门
8. Telegram 发布
9. Typefully MCP 创建 X 草稿
   - 每日任务继续浏览器排期
10. Excel 回写
11. 失败恢复

## 1. 输入与范围

- 唯一主表固定为 `output/quark_links.typefully.xlsx`；不得通过参数切换到其他 Excel 文件。
- 单条按 `序号` 定位，并同时报告真实 Excel 行号。
- 默认只做一条 canary；批量必须由用户明确指定。
- “检查/测试/预览”只做 dry-run；“发布/发送/同步”才允许 Telegram 与 X 外部动作；用户说“自动化”时，直接授权 X 端进入 Typefully 草稿流程。
- 未指定排期的一次性发布/发送/同步请求，Telegram 使用 Bot API 发送，X 通过 MCP 建稿。每日八条任务获得部署者的持续排期授权后：MCP 建稿后必须继续浏览器日程确认。
- 每日任务不再逐步询问确认：doctor、Telegram 只读检查通过后，按 [MCP 建稿](typefully-mcp-publish.md) 完成工具发现与 `@your_x_username` 只读预检，并确认 Typefully 浏览器已登录且可排期，再开始新媒体准备和外发。工具前缀变化不是断连证据。预检失败时新批次停止、游标不动；已有结果保留。日常命令使用当前有效权限，不固定要求额外提权或修改代理。
- 每天上海时间 17:00 准备；八个固定发布槽为 19:30、19:45、20:15、20:30、20:45、21:00、21:15、21:30，20:00 留空。先核对当日已排期、已计划和已发布记录，再按 [浏览器排期](typefully-browser-schedule.md) 只填未来空槽，既有结果不算一批新的八条。
- 优先按序号续排已有且审阅有效的 `draft`，包括新资料游标之前的积压；不足当日空槽数再从 `next_serial` 准备新条目。旧 `统一发布状态=COMPLETED` 可能仅表示 Telegram + 建稿，不能直接过滤这些待排期草稿。已发送 Telegram 的条目不重复发送或重建媒体。

## 2. Excel 读取

使用 `.venv/bin/python scripts/query_ledger.py` 直接读取数据；默认只返回表头和记录数。按需加 `--seq 253-260 --columns '资料标题,Telegram发布状态,Typefully草稿ID'`，结果包含真实 Excel 行号。常规数据查询不截图、不渲染、不打开 Excel，也不生成检查用副本。涉及源图片/文档封面的视觉 QA 是独立步骤，不应用于读取台账数据。

始终打开并原位回写：

```text
output/quark_links.typefully.xlsx
```

文件名中的 `typefully` 是历史名称；当前路线为 Typefully MCP 建稿、浏览器排期、MCP 回读。不得改用旧 CLI/REST，也不得另存新的业务主表。

按表头读取，不依赖固定列号：

```text
row_number
serial
title
description
new_quark_link
save_directory
telegram_message_id
telegram_status
x_asset_status
x_publish_status
x_scheduled_at
x_post_url
typefully_draft_id
typefully_status
typefully_draft_url
```

Typefully 草稿字段参与防重复和恢复；已有草稿 ID 时必须先通过 MCP 回读，不得直接覆盖或另建草稿。

## 3. 夸克只读定位

1. 使用 `work/quark-auto-save` 和 `config/quark-storage.json`。
2. 直接使用 Excel 中的新夸克链接或保存目录，不再次转存或修改。
3. 先递归完整文件树并建立根目录、一级目录、章节分支和相对层级，再判断首视频；不能把单次 API 返回顺序、更新时间、大小或字典序直接当成课程顺序。优先解析视频文件名开头的 `01`、`1.`、`1、`第一节`、`第1讲`、`零一` 等明确序号，选择主课程分支中最小可靠序号；同序号保留深度优先顺序。没有可靠序号时才使用原始深度优先 fallback，并记录依据或歧义。
4. 不能凭分享页首屏判断没有视频。
5. `telegram-project-details.json` 只作为本次文案、媒体和封面脚本的运行缓存。

## 4. 媒体决策

### 有视频

1. 只调用一次 `download_first_video.py`，传入首视频 FID、原文件名、已知大小、配置和临时目录。
2. 完整下载后先核对夸克已知大小，并用 `ffprobe` 完成源视频 QA。
3. 先限制时长：视频超过 600 秒时，用 `ffmpeg -c copy` 保留从 `00:00` 开始的前 600 秒；不超过时保持完整内容。
4. 再限制大小：检查上一步候选的精确字节数；若 `>= 50,000,000` bytes，根据候选的实际时长与字节数估算截止时间，从尾部继续截短，以 `49,000,000` bytes 为目标。每次输出后重测真实大小，仍超限时按实际结果继续缩短截止时间，最多有限重试；最终必须严格 `< 50,000,000` bytes。
5. 若候选容器不是 Typefully 支持的 `.mp4/.mov`，用 `ffmpeg -c copy` 只映射主视频和可选音频，无损封装成 `.mp4`；不重新编码。
6. 对最终候选再次执行 `ffprobe`，确认可解码、时长不少于 3 秒且不超过 600 秒、分辨率至少 320×180、H.264/HEVC 编码以及严格小于大小上限。通过后才原子替换为兼容路径 `project-video-original.<最终扩展名>`。
7. 删除截断/封装临时文件和旧的 `project-video-x.mp4`、`project-video-telegram.mp4`、`project-video.mp4`；只保留这一份最终发布视频。文件名中的 `original` 是历史兼容名。
8. 下载、源 QA、截断、MP4 封装或最终 QA 失败时阻塞并保留完整下载供同一 FID 重试；不尝试第二个视频或图片。

### 完全无视频

按真实图片、PDF、Office/文本资料、ImageGen 事实型视觉封面的顺序准备最终封面并进行视觉与内容 QA。没有真实预览时必须读取并执行 [ImageGen 事实型视觉封面](image-generation.md)，禁止回退到本地纯文字信息卡。

PDF、Word、PPT、Excel、电子书或文本项目一旦取得真实预览页，按源页面宽高比自适应选择画布：`>= 1.10` 使用 `1920×1080`（16:9）横版，否则使用 `1080×1920`（9:16）竖版；接近方形时优先竖版。把页面完整适配进所选画布，只允许使用同一页面生成柔化背景和阴影，不叠加标题、营销文案、标签、数量或信息卡。`media.kind=existing-local` 但完整清单含文档且没有图片/视频时同样执行此分支。QA 必须核对真实源预览、方向与尺寸匹配、完整页面、无文字叠加、PNG 可解码以及严格 `< 50,000,000` bytes。

全部资料均不可预览时，先从项目标题、描述和真实文件名归纳一个核心主题与 2～4 个内容锚点，再为这一条项目单独推导视觉方向、构图和配色后调用 ImageGen。不得复用上一条的题材模板或固定色板。生成后必须全尺寸看图并写 `imagegen-review.json`，同时说明本项目为什么选择该视觉方向和配色；只有主题相关、配色合规、文字可读、构图不拥挤、内容无虚构五项均为真，才能把图片交给 `prepare_telegram_asset.py --generated-image ... --generated-review ...`。脚本在缺少生成图或验收记录时必须阻塞。

## 5. 标准本地产物

视频项目：

```text
output/assets/{序号四位数}/project-video-original.<原扩展名>
output/assets/{序号四位数}/video-quality.json
output/assets/{序号四位数}/telegram-project-details.json
output/assets/{序号四位数}/telegram-caption.html
output/assets/{序号四位数}/x.txt
```

无视频项目：

```text
output/assets/{序号四位数}/cover-v1-information-card.png
output/assets/{序号四位数}/telegram-quality.json
output/assets/{序号四位数}/telegram-project-details.json
output/assets/{序号四位数}/telegram-caption.html
output/assets/{序号四位数}/x.txt
```

视频目录中不得出现第二份标准视频。`video-quality.json` 必须记录源报告、十分钟截断、大小截断和 MP4 无损封装是否发生、最终报告与硬上限。

## 6. 文案

本节必须结合 [每日八条文案的事实提炼与发送前审阅](editorial-review.md) 执行。`build_telegram_caption.py` 生成的 `telegram-caption.html` 和 `x.txt` 带 `【待审初稿】`，仅供准备阶段参考。每日任务分为“不带 `--telegram-send` 的准备 → 逐条读源与改写 → `review_copy.py record/check` → 对准备成功的原选中行号真实发送”四步；媒体失败行留待恢复，任一准备成功行的审阅失败时本次不发送、不建稿，也不推进游标。

- 当前行的完整标题、文字介绍和新夸克链接，加上 `telegram-project-details.json` 的全部 `items` 和层级，是写作依据。文件名不足以支持具体说法时，查看已有真实预览页或本地媒体。标题噪音可在正文清理，但 Telegram 保留完整标题供核对。
- 先辨认核心用途：工具能完成什么任务、方法教读者怎样操作、商业资料最终能交付什么及如何收到钱。赚钱线索可能只出现在目录的上架、引流、成交、接单、带货、投稿、稿费或平台结算章节里。只看到制作环节就写制作环节，不把可能的收益写成已验证结果。
- Telegram：用真实细节支撑一个明确判断和适用场景；段落、问题、步骤或清单由内容决定，情绪自然，不强行套用同一钩子或转折。包含真实夸克链接、2～8 个相关标签和固定 X／频道双入口；HTML 有效，完整 caption 不超过 1024 字符。
- X：读取 [x-copy-style-pool.md](x-copy-style-pool.md)，先讲具体用处及优势，再用自然口语讲透关联卖点；赚钱说成交/交付路径，工具说省掉的步骤，成人两性保持直白非露骨。通常 0～2 个 emoji，不刻意错字、不每句机械换行、不统一口头禅。连续 8 条至少 6 种主风格、3 种版式，内容实际变化而非只换标签。末行只能是完整原始夸克 URL，前留空行且仅出现一次，不加 CTA 或 Telegram 尾句。不设本地字符硬门。
- 目录、版本核验、未证实部分写进 `copy-review.json` 的来源与商业证据记录。证据不足就继续读源或缩窄正文主张，不把一条条“仅核到/目录能确认/收益未核实”写成公开文案；也不能为了语气强而虚构结果。
- 两个渠道都不得虚构试用经历、数量、身份、价格、评价、案例或保证收益。收入数字只有源资料明确支持时才使用，并说明案例属性。

## 7. 质量门

外部动作前检查：

```text
Excel: 序号、行号、标题、链接、历史 Telegram 状态、X 资料与发布状态
Quark: 完整递归结论、首视频 FID/文件名/大小
Media: 唯一最终发布视频或最终封面、源/最终 QA 报告
Telegram: 源/最终时长与精确字节数、两类截断结果、路由、频道、文案、重复风险
Copy: 当前 Excel 简介、完整目录、Telegram 与 X 最终文案通过 copy-review.json 的身份、来源判断及哈希核对；商业线索有路径和证据程度记录；无待审标记
X: x.txt 与最终媒体均存在且审阅通过；末行原始链接正确；批次语言有变化；MCP 建稿阶段只建 draft，每日任务另外验收浏览器 scheduled 时间
```

最终媒体路由：

```text
最终视频 <= 600 秒且 < 50,000,000 bytes -> Bot API sendVideo
最终视频未满足任一硬门                  -> 阻塞，不进入 Web K
图片 < 50,000,000 bytes                -> Bot API sendPhoto
图片 >= 50,000,000 bytes               -> 阻塞并重新生成/优化最终封面
```

## 8. Telegram 发布

### 连接检查

从安全环境读取 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`，调用 `getMe`、`getChat`、`getChatMember`。

连接器优先使用进程已有的 HTTP/HTTPS/ALL proxy。macOS 自动化进程未取得这些代理时，`send_telegram.py` 读取 `scutil --proxy`，仅为 Telegram Bot API 构造已启用的 HTTP/HTTPS 系统代理；不为夸克、Typefully MCP 或其他程序全局修改代理。检查结果中的 `network_route` 只记录 `environment-proxy`、`macos-system-proxy` 或 `direct`，不得输出代理凭据。系统代理存在但不可用时连接检查必须失败，不得切换 Telegram Web、Telethon 或 MTProto。

### Bot API 图片或视频

- 小图片调用 `sendPhoto`。
- 通过双重硬门的最终视频直接把兼容路径 `project-video-original.<原扩展名>` 交给 `sendVideo`。
- 不生成或读取 `project-video-telegram.mp4`。

图片和视频都必须严格 `< 50,000,000` bytes。仍超限时阻塞，不调用任何 Telegram Web 中转、Chrome、Telethon 或 MTProto；命令行不再返回退出码 `3`。

## 9. Typefully MCP 创建 X 草稿

读取 [typefully-mcp-publish.md](typefully-mcp-publish.md) 并执行：

1. 本地媒体和待审初稿准备后只写 `X资料状态=文案待审阅`；最终 `x.txt` 通过 `review_copy.py check --row-index 序号 --row-number Excel真实行号` 后才写 `资料已准备完成`。上传前再次检查审阅记录与最终文件一致。
2. 读取历史 Typefully 草稿 ID 和状态；已有 ID 时先用 `typefully_get_draft` 回读，排除重复。
3. 用 `typefully_list_social_sets` 和 `typefully_get_social_set_details` 唯一锁定 `@your_x_username`。
4. 用 `typefully_create_media_upload` 取得预签名 URL，对其执行一次无额外请求头的原始文件 PUT，再用 `typefully_get_media_status` 等待 ready。
5. 用 `typefully_create_draft` 只启用 X，永远不传 `publish_at` 或 `plan_at`。
6. 用 `typefully_get_draft` 回读同一 ID；状态为 `draft` 才算草稿创建成功。
7. 成功后写 `Typefully状态=DRAFT_CREATED`、`X发布状态=待发布`；媒体 ready 或只取得不可回读的 ID 不算完成。
8. 仅建稿请求在 draft 回读后结束。每日八条任务不等待逐条确认，继续 [Typefully 浏览器每日排期](typefully-browser-schedule.md)：读取当天队列与已发布条目，选未来固定空槽，浏览器 Schedule → 日历日期 → 时间 → Confirm，关闭 Auto-RT/Auto-Plug/Auto-DM 和自然随机时间；回读同一 ID 的 scheduled 时间后记账。始终不用 X Studio、X API、直接 Typefully REST/API Key 或旧 CLI。

## 10. Excel 回写

Telegram：

```text
Telegram发布状态
Telegram消息ID
Telegram帖子链接（存在该列时）
Telegram发布时间
Telegram错误信息
```

媒体：

```text
媒体类型
媒体路径
视频
原视频
Telegram视频
图片
```

视频项目的四个视频/媒体路径全部指向同一份最终发布视频；`原视频` 列名只为历史兼容。

X：

```text
X资料状态
X发布状态
X排期时间
X发布时间
X帖子链接
X错误信息
```

Typefully：

```text
Typefully媒体路径
Typefully草稿ID
Typefully草稿链接
Typefully状态
Typefully错误信息
Typefully更新时间
```

`X资料状态` 只表示本地准备事实。`DRAFT_CREATED/待发布` 代表建稿阶段；每日排期成功必须是 `SCHEDULED/已排期`，并记录上海时区 `X排期时间`。只有实际发布回读才写 `PUBLISHED/已发布`、`X发布时间` 和帖子链接。历史 `统一发布状态=COMPLETED` 仍可能只有建稿完成，不能拿它代替新的每日排期验收。

已有消息、媒体、草稿 ID 保持不变。排期只修改选中行的 Typefully/X 排期元数据，使用排期参考中的 `typefully_schedule.py record`，校验其他单元格与样式不变；不要把新确认的 scheduled 记录又交给建稿脚本回写为 DRAFT_CREATED。

回写后重新读取目标行，确认字段位置正确、其他行未改变、历史 Typefully 值未改变。

## 11. 失败恢复

- 夸克授权或下载失败：只重试同一首视频 FID，不切换下载器或视频。
- 源视频 QA 失败：阻塞 Telegram 与 X 完成状态。
- 十分钟或大小截断失败：保留完整下载和具体错误，只重试同一 FID；不得上传、改选视频或降级图片。
- 最终视频 QA 失败：阻塞 Telegram 与 X；不得转 Web K。若 Bot API 仍报文件过大，说明本地硬门或实际上传路径不一致，先修复本地媒体选择。
- 图片 `>= 50,000,000` bytes 时阻塞 Telegram 并重新生成或优化最终封面；不得转 Web K。
- Bot 频道发送超时：先检查频道结果，确认未创建后才重试。
- X 资料缺文件：不写“资料已准备完成”，修复本地媒体或 `x.txt` 后再验收；不使用本地加权字数门。
- Typefully 预签名 PUT 超时：先查同一 `media_id`，确认失败后才创建新上传。
- Typefully 建稿结果不确定：先查同一草稿 ID或最近草稿；存在匹配记录即恢复，不得重复上传或建稿。
- Typefully MCP 未连接、账号不符、权限不足或服务错误：保留 Telegram 结果，写 `失败` 或 `结果待确认`，停止 X 流程。
- 浏览器排期失败或确认结果不明：保留草稿和已发送 Telegram，只 GET 同一 ID 与当日队列核查，不重复点击或新建。`planned` 不是已排期；正确 `scheduled` 才记成功。
- 开始太晚或媒体准备错过时段：只用当日仍在未来的固定空槽，20:00 仍留空，不立即发布、不加密间隔、不延长到 21:30 以后、不擅自挪到次日。未完成条目保留待续跑。
- `next_serial` 是新资料处理游标；排期积压另按主表草稿 ID 全量核对。新条目只有实际 scheduled/published 或明确永久跳过才推进；失败保持最小待重试序号，次日由排期队列防重复、补缺口。
