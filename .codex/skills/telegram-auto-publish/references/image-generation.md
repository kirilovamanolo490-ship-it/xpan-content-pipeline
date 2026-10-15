# ImageGen 事实型视觉封面

仅在递归确认项目没有可用真实图片、视频帧或文档预览时使用本流程。真实素材优先级不变；ImageGen 不是替换真实预览的捷径。

## 硬性流程

1. 从 `telegram-project-details.json` 的真实标题、描述、`items`、`representative_files` 中提取一个核心主题和 2～4 个内容锚点，并为当前项目单独推导视觉方向、画面隐喻、构图与配色理由。不得使用文件数、文件夹数、格式数、QA 状态或流程信息作为封面内容。
2. 必须调用内置 ImageGen 生成 16:9 横版图片，目标尺寸 `1672×941`。不要用 Pillow/HTML/CSS 本地绘制纯文字卡替代生图调用。
3. 生成图只保留一个主标题、2～4 个内容锚点和一个连贯主视觉。禁止六宫格或多卡片堆砌、重复标题、徽章、目录清单、无意义英文、库存指标和模板化科技装饰。
4. 全尺寸查看成图。若存在错字、额外文字、主题错误、配色错误、拥挤、廉价霓虹或内容虚构，只允许围绕一个明确问题做一次定向重生成；仍不合格则阻塞。
5. 把选中的原始生成图保存到项目资产目录，另存最终 QA 图，不覆盖旧封面。生成 `imagegen-review.json` 后调用：

```text
prepare_telegram_asset.py ... \
  --generated-image <原始生成图> \
  --generated-review <imagegen-review.json> \
  --output-name <新的版本化最终封面名> \
  --metadata-name <新的版本化元数据名>
```

6. 运行 Telegram 封面 QA 并再次查看最终图。只有 PNG、`1672×941`、严格 `< 50,000,000` bytes、五项视觉验收全部通过时才能进入 Telegram 或 Typefully；测试请求不得触发外部发送、上传或建稿。

## 视觉语言

- 每一条都从当前项目的主题、受众、内容形态、情绪和使用场景推导配色与材质。不得因为同属“临床”“科技”“教育”等大类就复用固定色值或上一张图的视觉模板，也不能从“数据”“科技”一个泛词直接套用霓虹蓝紫。
- 提示词必须写出本项目的配色理由，例如需要可信克制、轻松亲和、历史质感或行动张力；颜色名称和色值只是本次项目的执行选择，不成为后续项目默认值。
- 视觉方向同样按项目推导：课程、书籍、工具、行业报告和商业案例应使用不同的主视觉隐喻与构图。不得为了“饱满度”塞满组件。
- 优先使用能说明当前内容的连贯视觉隐喻；医学项目可以在适合时组合病历界面、统计曲线或研究数据网络，但不能把这些元素固定用于所有医学项目。不要使用患者隐私、血腥场景、假机构标识或无关摆拍。
- 允许有负空间。标题应清楚但不能压过画面；支持文字应是一行短语，而不是目录摘要。

## ImageGen 提示词最小结构

```text
Use case: scientific-educational 或与主题匹配的类型
Asset type: 16:9 Telegram/X course cover
Primary request: 当前项目的核心主题与希望表达的价值
Scene/backdrop: 与主题对应的一个连贯场景
Style/medium: 高质量编辑视觉，不使用通用信息卡
Composition/framing: 一个主视觉 + 清晰标题 + 2～4 个内容锚点
Color palette: 为当前项目单独选择的颜色及选择理由；不得引用固定题材色板
Text (verbatim): 精简后的真实主标题
Supporting text (verbatim): 2～4 个真实内容锚点
Constraints: 中文逐字正确、无额外文字、无统计数量、无水印
Avoid: 六宫格、卡片墙、霓虹、赛博朋克、模板感、随机英文、内容虚构
```

## `imagegen-review.json`

```json
{
  "tool": "imagegen",
  "prompt_contract": "factual-social-cover-v1",
  "displayed_title": "真实精简标题",
  "content_anchors": ["真实锚点一", "真实锚点二"],
  "visual_direction": "为什么这种视觉方向适合当前项目",
  "palette_reason": "为什么这组配色适合当前项目，而不是类别默认色",
  "prompt": "实际使用的完整提示词",
  "checks": {
    "subject_relevant": true,
    "palette_compliant": true,
    "text_readable": true,
    "uncluttered_composition": true,
    "no_fabricated_content": true
  }
}
```

五项检查必须来自对最终生成图的实际观察。不得为了通过 QA 把未确认项写成 `true`。
