# Typefully MCP 创建 X 草稿

## 目标与不变量

X 的媒体上传、草稿创建和草稿核验通过当前会话已连接的 Typefully MCP 完成。本文只定义建稿阶段；每日八条任务还必须衔接 [Typefully 浏览器每日排期](typefully-browser-schedule.md)，直到同一草稿回读为正确时段的 `scheduled`。仅建稿请求仍止于 `draft`。

- 目标 X 账号由部署者指定；`@your_x_username` 仅为占位，必须与配置的 XPAN_X_PROFILE_URL 及已核对的 social set 匹配。
- 不打开 X Studio，不调用 X API，也不运行 `src/xpan_auto/typefully_cli.py`、`src/xpan_auto/typefully_publisher.py` 或任何直接 Typefully REST/API Key 客户端。浏览器只用于授权后的 Typefully 日程确认，不替代 MCP 媒体上传或建稿。
- 本阶段的 Typefully 操作使用已核实的 MCP 工具。本文的 `typefully_...` 是逻辑动作名；完整工具名可能是 `mcp__codex_apps__typefully_*` 或 `mcp__typefully__typefully_*`。唯一允许的非 MCP 程序化网络写请求是将媒体原始字节 PUT 到 MCP 返回的预签名 URL；另一个独立步骤是 `cua_repl` 的真实浏览器日程点击，不是直接 REST 写入。
- Telegram 与 X 复用同一份最终媒体和同目录 `x.txt`，但两端结果独立记账。
- “媒体 ready”不等于草稿已创建；必须回读 Typefully 草稿 ID 并确认状态为 `draft`。

## 连接发现与只读预检

每日自动批次在 doctor 与 Telegram Bot 只读检查通过后、媒体准备及任何外发前执行：

1. 枚举当前会话可用工具的名称与提供方说明，按 Typefully 提供方和 `list_social_sets`、`get_social_set_details` 等动作后缀匹配；先检查 `mcp__codex_apps__typefully_*`，也接受 `mcp__typefully__typefully_*` 等实际暴露的同一提供方入口。不要只搜索旧前缀。
2. 若首次工具清单没有匹配，重新检查完整工具清单，并通过插件管理查询 Typefully 的安装及连接状态；不能仅凭工具名搜索结果写“连接断开”，更不能给选中行写 `FAILED`。
3. 实际调用 `typefully_list_social_sets`（`limit <= 50`）及候选的 `typefully_get_social_set_details`，唯一确认 X 用户名 `@your_x_username`。只读调用的真实错误、权限缺失或确认无可用工具，才构成 Typefully 预检失败。
4. 新批次若在此门失败，停止媒体准备、Telegram 外发和 Typefully 写入，保持 `next_serial`；记录具体连接错误并通知用户。已有 Telegram 消息或媒体 ID 的续跑不得抹掉历史成功，也不得重复上传或重发。连接成功后按原行号继续，直至逐行完成或遇到真实资料质量门。


每行固定得到：

```text
serial
excel_row_number
media_path
x_copy_path
new_quark_link
publish_mode = draft
```

- “检查/预览/准备”只完成本地质量门，不调用任何 Typefully 写工具或预签名上传。
- 未指定排期的一次性“发布/发送/同步”请求，X 端只创建草稿；每日八条自动化只有获得部署者明确的连续建稿、浏览器排期授权后，才可免于逐条询问。
- 本地质量门通过后上传、建稿和回读；每日任务随后进入浏览器排期，不能在本阶段写 `DRAFT_CREATED` 后直接结束整条链路。失败或结果不确定时保留已确认结果并按同一 ID 恢复。
- `typefully_create_draft` 不传 `publish_at` 或 `plan_at`；MCP 不承担排期写入，定时发布由浏览器日程页的 Confirm 完成。

## 账户锁定

1. 调用 `typefully_list_social_sets`。
   - 当前连接器可能在外层返回 `isError=true`，但文本体为 `API Response (Status: 200)` 且包含合法 `results`。只在状态为 2xx 且 JSON 结构有效时把它当作成功；非 2xx、无结果字段或无法解析时仍按失败处理。
2. 对候选调用 `typefully_get_social_set_details`，只接受 X 平台用户名去掉前导 `@` 后精确等于 `your_x_username` 的 social set。
3. 零个匹配或多个匹配时停止，报告歧义；不得按返回顺序、名称相似或历史 ID 猜测。
4. 本次运行只在内存中保留选定的 `social_set_id`，不得把凭据或 MCP 认证信息写入 Excel、日志或回复。

## 发布前检查与防重复

1. 最终媒体存在、非空并通过本 Skill 的本地 QA；视频还必须满足时长 `<= 600` 秒且大小 `< 50,000,000` bytes。
2. Typefully MCP 媒体扩展名必须受支持：图片 `.jpg/.jpeg/.png/.webp/.gif`，视频 `.mp4/.mov`。源视频为其他容器时，本地媒体准备必须先用 `ffmpeg -c copy` 无损封装为 `.mp4` 并重新 QA；封装失败时阻塞该行的双端发布，不临时重新编码或改选图片。
3. `x.txt` 必须是 UTF-8、非空且未被本地字符数规则截断；不设 `x_weighted_length` 硬上限。先读取 [每日八条文案审阅](editorial-review.md)，用 `.venv/bin/python .codex/skills/telegram-auto-publish/scripts/review_copy.py check --row-index 序号 --row-number Excel真实行号` 核对当前 Excel 简介、完整目录与最终文案的审阅记录；带 `【待审初稿】`、缺记录或哈希过期都阻断上传和建稿。随后读取 [x-copy-style-pool.md](x-copy-style-pool.md) 按题材选择结构，并对连续批次执行风格标签、开头和版式去重。该参考是自动化 X 文案的唯一格式来源；历史任务中的固定长文段落、4～8 个 hashtag 或 Telegram 尾行不得覆盖它。正文必须包含本行真实夸克链接；每条只完成一个主要表达任务，默认不加 hashtag、不追加固定 Telegram 尾行。不得把目录统计、QA 状态或内部流程写进正文，不得虚构试用经历、数字、效果或收益。
4. 读取 Excel 的 `Typefully草稿ID`、`Typefully状态`、`Typefully草稿链接`、`X发布状态`、`X排期时间` 和 `X帖子链接`。
5. 已有 `Typefully草稿ID` 时，先调用 `typefully_get_draft` 回读；只要同一草稿仍存在就不得新建重复草稿。状态不确定时再用 `typefully_list_drafts` 核对。

## 媒体上传

1. 调用 `typefully_create_media_upload`，传入锁定的 `social_set_id` 和最终媒体的纯文件名。
2. 响应必须同时包含 `media_id` 和预签名 `upload_url`。
3. 对预签名 URL 发送一次原始文件 PUT：推荐 `curl -T <绝对媒体路径> <upload_url>`。不得添加 `Content-Type`、`Authorization` 或其他请求头；HTTP `200` 或 `204` 才算上传完成。
4. 使用 `typefully_get_media_status` 有限轮询同一 `media_id`：只有 `ready/completed/succeeded` 才继续；`failed/error` 立即阻塞。超时时先回读状态，不重新创建上传。

## 创建 X 草稿

调用 `typefully_create_draft`，只启用 X：

```json
{
  "social_set_id": 123,
  "requestBody": {
    "draft_title": "序号-项目标题",
    "platforms": {
      "x": {
        "enabled": true,
        "posts": [
          {
            "text": "x.txt 原文",
            "media_ids": ["media_id"]
          }
        ]
      }
    }
  }
}
```

- 请求体不得包含 `publish_at` 或 `plan_at`。
- 返回必须包含草稿 ID；没有 ID 视为结果不确定，先查最近草稿，不得立即重建。

## 结果核验

用 `typefully_get_draft` 回读同一草稿 ID：

- `draft`：草稿创建成功；仅建稿请求在此结束，每日八条任务转入浏览器排期。
- `scheduled`、`publishing` 或 `published`：回读核对并保留既有结果；不得重新上传、另建草稿或无故改时。每日任务中只有 `scheduled` 时间正确或实际 `published` 才可计入对应完成记录。
- `planned`：只有日期占位，尚不会自动发布；不能记为 `SCHEDULED`，按排期参考处理。
- `error`：记录 Typefully 返回的简短错误并写失败，不自动复制草稿。

只看到上传 ready 或 `create_draft` 返回成功但没有可回读草稿 ID，不足以声明草稿完成。

## Excel 回写

Typefully 传输事实：

```text
Typefully媒体路径
Typefully草稿ID
Typefully草稿链接
Typefully状态
Typefully错误信息
Typefully更新时间
```

X 结果事实：

```text
X资料状态
X发布状态
X排期时间
X发布时间
X帖子链接
X错误信息
```

- 草稿创建并回读成功：`Typefully状态=DRAFT_CREATED`，`X发布状态=待发布`。
- 返回不确定：`Typefully状态=RESULT_UNKNOWN`，`X发布状态=结果待确认`。
- 失败：两组错误字段写同一条已脱敏的简短原因；不得覆盖 Telegram 成功证据。
- 现有建稿脚本可能在 Telegram 成功且 `Typefully状态=DRAFT_CREATED` 时写历史阶段值 `统一发布状态=COMPLETED`。每日任务不能用这个值判断排期完成，必须继续到 `SCHEDULED/已排期` 并核对准确日期时间；本地资料就绪、媒体 ready 均不能代替该证据。

## 故障恢复

- 预签名 PUT 超时：先查询 `media_id` 状态；只有确认没有收到文件或状态为 `failed` 时才创建新上传。
- `create_draft` 超时或返回缺少 ID：按标题、`x.txt` 文案、媒体和创建时间查询最近草稿；确认不存在后才允许重试。
- 草稿结果不确定：只回读同一草稿或最近草稿，不新建草稿、不再次上传媒体。
- Typefully MCP 未连接、无目标 social set、缺少 WRITE 权限或服务错误：保留本地资料和 Telegram 结果，写 X/Typefully 失败或结果待确认，停止该行的 X 流程。
