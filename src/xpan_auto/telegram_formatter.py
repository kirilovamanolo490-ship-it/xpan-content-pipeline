from __future__ import annotations

from html import escape
import re
from collections.abc import Iterable, Mapping, Sequence


from .deployment import setting

TELEGRAM_X_URL = setting("XPAN_X_PROFILE_URL", "https://example.invalid/x/profile")
TELEGRAM_CHANNEL_URL = setting("XPAN_TELEGRAM_CHANNEL_URL", "https://example.invalid/telegram/channel")
X_POST_MAX_CHARS = 274
X_TELEGRAM_CHANNEL_TAIL = f"📣 Telegram频道：{TELEGRAM_CHANNEL_URL}"
X_TRANSFORMED_URL_LENGTH = 23
X_FALLBACK_TAGS = ("#学习资料", "#资源分享", "#实战教程", "#技能提升")

_X_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.IGNORECASE)
_X_SINGLE_WEIGHT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)


def _x_plain_text_weight(value: str) -> int:
    return sum(
        1 if any(start <= ord(character) <= end for start, end in _X_SINGLE_WEIGHT_RANGES) else 2
        for character in value
    )


def x_weighted_length(value: str) -> int:
    """Return a conservative X character count with URLs shortened to 23 units."""

    total = 0
    cursor = 0
    for match in _X_URL_RE.finditer(value):
        total += _x_plain_text_weight(value[cursor : match.start()])
        total += X_TRANSFORMED_URL_LENGTH
        cursor = match.end()
    return total + _x_plain_text_weight(value[cursor:])


def _truncate_x_text(value: str, max_weight: int) -> str:
    if x_weighted_length(value) <= max_weight:
        return value
    ellipsis = "…"
    remaining = max_weight - x_weighted_length(ellipsis)
    if remaining <= 0:
        return ""
    kept: list[str] = []
    used = 0
    for character in value:
        weight = _x_plain_text_weight(character)
        if used + weight > remaining:
            break
        kept.append(character)
        used += weight
    prefix = "".join(kept).rstrip()
    return f"{prefix}{ellipsis}" if prefix else ""


# Rules are deliberately ordered from specific topics to broad content types.
# The input can contain a title, an introduction, and source file names.
_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("小红书运营", ("小红书",)),
    ("虚拟电商", ("虚拟电商", "虚拟产品")),
    ("监督服务", ("监督服务", "监督陪跑")),
    ("高客单服务", ("高客单",)),
    ("服务变现", ("服务变现", "变现案例", "按单成交")),
    ("内容获客", ("内容获客", "笔记获客", "篇笔记")),
    ("AI漫剧", ("ai漫剧", "漫剧")),
    ("古风人物", ("古风人物", "古代言情")),
    ("三视图", ("三视图",)),
    ("Cursor", ("cursor",)),
    ("AI编程", ("ai编程", "cursor", "codex")),
    ("Java", ("java",)),
    ("设计模式", ("设计模式", "单例模式", "适配器模式", "观察者模式")),
    ("软考", ("软考",)),
    ("系统架构", ("系统架构",)),
    ("大模型", ("大模型", "llama", "rag", "agent")),
    ("AI绘画", ("ai绘画", "人工智能绘画", "midjourney", "stable diffusion", "comfyui", "文生图")),
    ("AI办公", ("ai办公", "workbuddy", "办公自动化")),
    ("远程控制", ("远程控制", "claw")),
    ("提示词技巧", ("提示词", "prompt")),
    ("肩颈舒缓", ("肩颈", "肩颈舒缓")),
    ("自我理疗", ("自我理疗", "居家理疗")),
    ("体态调整", ("体态", "站姿", "卧姿")),
    ("网络营销", ("网络营销", "营销课程")),
    ("SEO", ("seo",)),
    ("SEM", ("sem",)),
    ("新媒体运营", ("新媒体运营", "社会化媒体")),
    ("电商营销", ("电商网络营销", "电商营销")),
    ("股票交易", ("股票", "主升浪", "量能")),
    ("买点系统", ("买点", "红心买点")),
    ("技术分析", ("结构图形", "双底", "头肩底", "技术分析")),
    ("IP运营", ("ip切片", "切片运营", "切片电商")),
    ("切片剪辑", ("切片", "混剪", "粗剪")),
    ("内容运营", ("内容运营", "自媒体", "流量推流", "爆单")),
    ("电商运营", ("切片电商", "商品类目", "橱窗")),
    ("电商设计", ("电商设计", "商品视觉", "产品图", "商品图", "美妆场景")),
    ("图生图", ("图生图",)),
    ("ControlNet", ("controlnet",)),
    ("PS教程", ("ps beta", "photoshop", "ps教程")),
    ("强肾健体", ("强肾", "肾功能", "肾脏", "壮阳")),
    ("男性健康", ("男性健康", "男科", "房中")),
    ("前列腺调理", ("前列腺",)),
    ("养生保健", ("养生", "保健", "调理", "经络")),
    ("古诗词", ("古诗词", "古诗", "唐诗", "宋词", "诗词")),
    ("诗词鉴赏", ("品读", "诗词鉴赏", "诗词赏析", "诗歌鉴赏")),
    ("传统文化", ("腹有诗书", "国学", "传统文化", "文化积累")),
    ("职业成长", ("超级个体", "职业成长", "个人成长", "职业重启", "求职转型", "核心竞争力", "人生设计")),
    ("职业重启", ("职业重启", "求职转型")),
    ("自我效能", ("自我效能",)),
    ("领导力", ("领导力",)),
    ("副业发展", ("副业发展", "副业")),
    ("哲学思考", ("哲学", "爱好智慧", "思考人生", "哲学家", "苏格拉底", "存在")),
    ("逻辑思辨", ("逻辑思辨", "三段论", "论证", "诡辩", "真理")),
    ("人生哲学", ("人生哲学", "人生的价值", "幸福", "孤独", "意义")),
    ("自我成长", ("自我成长", "自我效能", "自尊", "自卑", "自由", "独立")),
    ("社会与信仰", ("社会制度", "制度", "信仰", "宗教")),
    ("幽默表达", ("幽默", "发笑", "段子", "喜剧")),
    ("社交沟通", ("社交沟通", "人际交往", "拓展人脉", "社交救场")),
    ("沟通技巧", ("说话", "表达观点", "自我介绍", "演讲")),
    ("人际魅力", ("魅力", "好人缘", "好印象", "赞美")),
    ("破冰技巧", ("破冰", "自嘲", "吐槽")),
    ("即兴创意", ("即兴创意", "喜剧创意", "幽默风格")),
    ("肌筋膜", ("肌筋膜", "myofascial", "fascia")),
    ("筋膜链", ("筋膜链", "fascia chain", "myofascial chain")),
    ("康复理疗", ("康复理疗", "理疗", "康复")),
    ("疼痛康复", ("疼痛康复", "疼痛", "pain rehabilitation")),
    ("运动康复", ("运动康复", "运动康复")),
    ("康复师", ("康复师", "康复医师", "医师培训")),
    ("解剖学", ("解剖", "anatomy", "anatomical")),
    ("体态评估", ("体态评估", "姿态评估", "评估")),
    ("筋膜培训", ("筋膜培训", "培训班")),
    ("人像摄影", ("人像摄影",)),
    ("摄影实战", ("摄影实战", "影棚闪光灯", "影棚")),
    ("摄影后期", ("修图", "中性灰", "双曲线")),
    ("视频剪辑", ("视频剪辑", "剪映", "premiere", "pr课程", "短视频")),
    ("视觉表达", ("视觉表达", "视觉观点", "从视觉到观点")),
    ("PPT设计", ("ppt设计", "ppt模板", "pptx", "演示文稿")),
    ("模板设计", ("模板制作", "ppt模板", "模板设计")),
    ("案例拆解", ("案例拆解", "案例修改", "参考案例")),
    ("摄影", ("摄影", "人像", "相机", "镜头")),
    ("PPT", ("ppt", "powerpoint")),
    ("职场效率", ("职场", "办公", "效率", "office", "workbuddy")),
    ("编程开发", ("编程", "python", "开发", "代码", "linux", "qemu")),
    ("投资理财", ("投资", "理财", "股票", "买点")),
    ("考试备考", ("考试", "题库", "备考", "考前")),
    ("亲子教育", ("亲子", "育儿", "儿童", "幼儿")),
    ("英语学习", ("英语", "英语语法", "英语写作", "雅思", "托福")),
    ("瑜伽健身", ("瑜伽", "健身", "减脂", "增肌", "运动")),
    ("视频课程", ("视频课程", "课程视频", ".mp4", ".avi", "视频")),
    ("课件资料", ("课件", ".pdf", ".doc", ".docx", ".ppt")),
    ("课程资料", ("课程资料", "课程", "训练营", "教程", "合集", "资料", "培训")),
    ("课程分享", ("课程", "训练营", "教程", "合集", "资料", "课")),
)

_FALLBACK_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("视频课程", (".mp4", ".avi", "视频")),
    ("课件资料", (".pdf", ".doc", ".docx", ".ppt", "课件", "文档")),
    ("课程资料", ("课程", "培训", "教程", "资料")),
    ("学习资料", ("资料", "学习", "课程")),
)

PROJECT_DESCRIPTION_PLACEHOLDERS = (
    "来源飞书页面已识别",
    "待转存后补充",
    "项目内容待补充",
)

_DESCRIPTION_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI绘画与电商设计", ("ai绘画", "电商设计", "controlnet", "商品视觉")),
    ("AI办公与职场效率", ("ai办公", "workbuddy", "办公自动化", "任务管理")),
    ("肩颈舒缓与自我理疗", ("肩颈", "肩颈舒缓", "自我理疗", "居家理疗")),
    ("网络营销与新媒体运营", ("网络营销", "seo", "sem", "新媒体运营", "社会化媒体")),
    ("股票交易与技术分析", ("股票", "买点", "主升浪", "量能", "结构图形", "双底", "头肩底")),
    ("IP切片与内容运营", ("ip切片", "切片运营", "切片电商", "自媒体", "流量推流")),
    ("肌筋膜与康复评估", ("肌筋膜", "筋膜链", "康复", "疼痛康复")),
    ("人像摄影与后期", ("人像摄影", "摄影", "影棚", "修图", "胶片")),
    ("PPT与视觉表达", ("ppt", "视觉表达", "视觉观点", "演示文稿")),
    ("古诗词与人文阅读", ("古诗词", "古诗", "唐诗", "宋词", "诗词", "腹有诗书")),
    ("职业成长与个人进阶", ("超级个体", "职业重启", "求职转型", "核心竞争力", "自我效能", "领导力", "副业发展", "人生设计")),
    ("哲学入门与思考", ("哲学", "爱好智慧", "思考人生", "哲学家", "苏格拉底", "存在")),
    ("逻辑与论证", ("逻辑思辨", "什么是逻辑", "有逻辑", "三段论", "论证", "诡辩", "真理")),
    ("人生价值与幸福", ("人生的价值", "幸福", "孤独", "痛苦", "人生", "意义")),
    ("自我与自由", ("自我成长", "自我效能", "自尊", "自卑", "自由", "独立")),
    ("社会、制度与信仰", ("社会制度", "制度", "信仰", "宗教")),
    ("幽默表达", ("幽默", "发笑", "段子", "喜剧")),
    ("社交破冰", ("社交沟通", "人际交往", "社交技巧", "拓展人脉")),
    ("观点与演讲表达", ("表达观点", "说话", "自我介绍", "演讲")),
    ("情绪与尴尬处理", ("化解尴尬", "情绪低谷", "冒犯")),
    ("赞美与沟通", ("赞美", "提建议", "建议")),
    ("创意与思维", ("创意与思维", "喜剧创意", "有意思", "有思想", "思维训练")),
    ("自我认知与表达风格", ("接纳你自己", "幽默风格", "自我认知", "自我成长")),
)

_LESSON_PREFIX_RE = re.compile(
    r"^\s*(?:第\s*\d+\s*(?:讲|课|节)|\d{1,3}\s*(?:[_\-—–:：.｜|]|\[[^\]]*\]|【[^】]*】)|\d{1,3}(?=[\u4e00-\u9fff]))"
)
_LESSON_NUMBER_RE = re.compile(
    r"^\s*(?:第\s*(\d+)\s*(?:讲|课|节)|(\d{1,3})\s*(?:[_\-—–:：.｜|]|(?=[\u4e00-\u9fff])))"
)
_AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".wav", ".wma"}
_DOCUMENT_EXTENSIONS = {".doc", ".docx", ".epub", ".pdf", ".ppt", ".pptx", ".txt"}


def _clean_content_label(value: str) -> str:
    """Turn a source filename into a short content label for descriptions."""

    label = str(value or "").strip()
    label = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", label)
    label = re.sub(r"^\s*\d{1,3}\s*(?:\[[^\]]*\]|【[^】]*】)\s*", "", label)
    label = re.sub(r"【[^】]*】", "", label)
    label = re.sub(r"\[[^\]]*\]", "", label)
    label = re.sub(r"^\s*(?:第\s*\d+\s*(?:讲|课|节)|\d{1,3})\s*[_\-—–:：.｜|]+\s*", "", label)
    label = re.sub(r"^\s*\d{1,3}(?=[\u4e00-\u9fff])", "", label)
    label = re.sub(r"^[（(](?:上|下|中|一|二)[）)]\s*", "", label)
    label = re.sub(r"^\s*[_\-—–:：.]+\s*", "", label)
    label = re.sub(r"\s+", " ", label)
    return label.strip(" _-—–:：")


def _unique_content_labels(names: Iterable[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for name in names:
        label = _clean_content_label(name)
        if not label:
            continue
        key = re.sub(r"[\s_·•]+", "", label).casefold()
        if key and key not in seen:
            seen.add(key)
            labels.append(label)
    return labels


def _detail_item_names(details: Mapping[str, object]) -> list[str]:
    names: list[str] = []
    for item in details.get("items", ()) or ():
        if isinstance(item, Mapping):
            if item.get("type") and item.get("type") != "file":
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    if names:
        return list(dict.fromkeys(names))
    return detail_file_names(details)


def _description_topics(text: str) -> list[str]:
    topics: list[str] = []
    for topic, keywords in _DESCRIPTION_TOPIC_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            topics.append(topic)
    return topics


def _extension_counts(summary: Mapping[str, object]) -> dict[str, int]:
    raw_counts = summary.get("extension_counts")
    if not isinstance(raw_counts, Mapping):
        return {}
    counts: dict[str, int] = {}
    for extension, count in raw_counts.items():
        try:
            counts[str(extension).casefold()] = max(0, int(count))
        except (TypeError, ValueError):
            continue
    return counts


def _count_extensions(counts: Mapping[str, int], extensions: set[str]) -> int:
    return sum(count for extension, count in counts.items() if extension in extensions)


def _combined_text(title: str, description: str, file_names: Iterable[str]) -> str:
    parts = [title, description, *file_names]
    return re.sub(r"\s+", " ", "\n".join(str(part) for part in parts if part)).casefold()


def is_placeholder_description(description: str) -> bool:
    normalized = " ".join(str(description or "").split())
    return not normalized or any(marker in normalized for marker in PROJECT_DESCRIPTION_PLACEHOLDERS)


def detail_file_names(details: Mapping[str, object] | None) -> list[str]:
    """Return stable file and path names from an extracted project-details JSON."""

    if not details:
        return []
    values: list[str] = []
    for item in details.get("items", ()) or ():
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        path = str(item.get("path") or "").strip()
        if name:
            values.append(name)
        if path and path != name:
            values.append(path)
    return list(dict.fromkeys(values))


def build_project_description(title: str, details: Mapping[str, object]) -> str:
    """Build a content overview from the verified recursive project listing."""

    summary = details.get("summary") if isinstance(details, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    folder_count = int(summary.get("folder_count") or 0)
    file_count = int(summary.get("file_count") or 0)
    extension_counts = _extension_counts(summary)
    source_names = _detail_item_names(details)
    content_labels = _unique_content_labels(source_names)
    top_level = []
    for item in details.get("top_level", ()) or ():
        if isinstance(item, Mapping):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name:
            top_level.append(name)
    source_text = _combined_text(title, "", [*top_level, *content_labels])

    focus = title.strip() or "项目资料"
    if any(word in source_text for word in ("古诗词", "古诗", "唐诗", "宋词", "诗词")):
        focus = "古诗词品读与人文积累"
    elif any(word in source_text for word in ("ai办公", "workbuddy", "办公自动化")):
        focus = "AI办公与职场效率"
    elif any(word in source_text for word in ("肩颈", "肩颈舒缓", "自我理疗")):
        focus = "肩颈舒缓与自我理疗"
    elif any(word in source_text for word in ("网络营销", "seo", "sem", "新媒体运营", "社会化媒体")):
        focus = "网络营销与新媒体运营"
    elif any(word in source_text for word in ("股票", "买点", "主升浪", "量能", "结构图形")):
        focus = "股票交易与技术分析"
    elif any(word in source_text for word in ("ip切片", "切片运营", "切片电商")):
        focus = "IP切片与内容运营"
    elif "肌筋膜" in source_text or "筋膜链" in source_text:
        focus = "肌筋膜链与康复评估"
    elif any(word in source_text for word in ("超级个体", "职业重启", "求职转型", "核心竞争力", "自我效能", "副业发展")):
        focus = "职业成长与个人进阶"
    elif "幽默" in source_text and ("社交" in source_text or "人际" in source_text):
        focus = "幽默表达与社交沟通"
    elif "哲学" in source_text:
        focus = "哲学思考与人生智慧"
    elif "ppt" in source_text and ("视觉" in source_text or "演示" in source_text):
        focus = "PPT视觉表达"

    category_rules = (
        ("肌筋膜理论文档", ("肌筋膜文档", "理论知识")),
        ("肌筋膜医师培训视频", ("医师培训", "医师班")),
        ("筋膜链康复与疼痛评估视频", ("筋膜链", "疼痛康复", "评估视频")),
        ("中文与英文课件", ("课件", "翻译", "anatomy")),
        ("CC点图谱资料", ("cc点图谱", "manual level 1")),
    )
    categories = [
        label for label, keywords in category_rules if any(keyword in source_text for keyword in keywords)
    ]
    topics = categories[:4] or _description_topics(source_text)
    if "哲学" in source_text:
        topics = [topic for topic in topics if topic != "观点与演讲表达"][:5]

    lesson_source_names = [name for name in source_names if _LESSON_PREFIX_RE.search(name)]
    lesson_labels = _unique_content_labels(lesson_source_names)
    lesson_count = len(lesson_labels)
    lesson_numbers = {
        int(match.group(1) or match.group(2))
        for name in source_names
        for match in [_LESSON_NUMBER_RE.search(name)]
        if match
    }
    special_units: list[str] = []
    label_text = " ".join(content_labels)
    if any("发刊词" in name for name in source_names):
        special_units.append("发刊词")
    if "结束语" in label_text:
        special_units.append("结束语")
    if "课程回顾" in label_text:
        special_units.append("课程回顾")
    audio_count = _count_extensions(extension_counts, _AUDIO_EXTENSIONS)
    document_count = _count_extensions(extension_counts, _DOCUMENT_EXTENSIONS)
    parts = [f"本资料围绕{focus}整理"]

    course_units: list[str] = []
    if lesson_numbers:
        course_units.append(f"{len(lesson_numbers)}讲课程")
    course_units.extend(special_units)
    if course_units:
        parts.append(f"，包含{'、'.join(course_units)}")
    if audio_count and document_count:
        document_label = "PDF讲义" if extension_counts.get(".pdf") == document_count else "配套文档"
        parts.append(f"，配套{audio_count}份音频和{document_count}份{document_label}")
    elif lesson_count:
        parts.append(f"，共{lesson_count}个课程单元")
    elif folder_count or file_count:
        structure: list[str] = []
        if folder_count:
            structure.append(f"{folder_count}个文件夹")
        if file_count:
            structure.append(f"{file_count}个文件")
        parts.append(f"，包含{'和'.join(structure)}")

    if topics:
        parts.append(f"，内容涵盖{'、'.join(topics[:6])}等主题")
    else:
        fallback_topics = [label for label in content_labels if len(label) <= 28][:4]
        if fallback_topics:
            parts.append(f"，主要内容包括{'、'.join(fallback_topics)}")
        else:
            parts.append("，内容包括项目目录中的课程、文档或配套资料")

    if any(word in source_text for word in ("古诗词", "古诗", "唐诗", "宋词", "诗词")):
        parts.append("，适合诗词爱好者进行鉴赏学习、文化积累与日常诵读")
    elif any(word in source_text for word in ("ai办公", "workbuddy", "办公自动化")):
        parts.append("，适合希望用 AI 提升日常办公、任务协同与自动化能力的学习者")
    elif any(word in source_text for word in ("肩颈", "肩颈舒缓", "自我理疗")):
        parts.append("，适合久坐人群进行日常肩颈放松、体态调整与自我护理")
    elif any(word in source_text for word in ("网络营销", "seo", "sem", "新媒体运营", "社会化媒体")):
        parts.append("，适合网络营销、新媒体和电商运营学习者系统查阅与实操")
    elif any(word in source_text for word in ("股票", "买点", "主升浪", "量能", "结构图形")):
        parts.append("，适合希望建立买点判断、图形分析与交易复盘框架的学习者")
    elif any(word in source_text for word in ("ip切片", "切片运营", "切片电商")):
        parts.append("，适合从事短视频切片、内容运营与电商转化的实操学习者")
    elif "康复师" in source_text or "医师" in source_text:
        parts.append("，适合康复师及相关从业者系统学习、评估查阅与备课参考")
    elif "幽默" in source_text and ("社交" in source_text or "人际" in source_text):
        parts.append("，适合提升表达魅力、人际沟通和社交应对能力")
    elif "摄影" in source_text:
        parts.append("，适合摄影学习者按主题练习、复盘与查阅")
    elif "ppt" in source_text or "视觉表达" in source_text:
        parts.append("，适合设计学习者进行演示表达、案例分析与模板参考")
    elif any(word in source_text for word in ("超级个体", "职业重启", "求职转型", "核心竞争力", "自我效能", "副业发展")):
        parts.append("，适合希望提升职业竞争力、自我效能与个人发展能力的学习者")
    elif "哲学" in source_text:
        parts.append("，适合系统学习哲学基础、逻辑思辨和人生议题")
    else:
        parts.append("，适合相关学习者按主题学习和查阅")
    return "".join(parts) + "。"


def _promotional_angle(source_text: str) -> tuple[str, str]:
    text = source_text.casefold()
    if any(word in text for word in ("网络营销", "seo", "sem", "新媒体", "电商", "带货", "ip切片", "运营")):
        return (
            "如果你正在做流量、内容或转化，这套资料很值得认真翻一遍：难得的是，它把获客、内容、成交和复盘放进了同一条业务链。",
            "很多人卡在零散技巧上，这套内容更适合收藏下来边看边做；遇到具体问题时再回来查，也能更快找到可落地的环节。",
        )
    if any(word in text for word in ("ai办公", "workbuddy", "办公自动化", "提示词")):
        return (
            "真正拉开效率差距的，不是装了多少 AI 工具，而是有没有一套能反复复用的工作方法；这一套把关键步骤、案例和落地动作放在了一起，完整度很高。",
            "它不是看完就算的资料，更适合边做边拆，把里面的流程整理成自己的模板，日常工作和项目推进都会顺手很多。",
        )
    if any(word in text for word in ("摄影", "ppt", "设计", "剪辑", "短视频", "ai绘画")):
        return (
            "想把作品做得更专业，这套资料会很有吸引力：它不只讲概念，还把审美、方法、案例和实操细节一起摆了出来。",
            "从照着做，到真正独立完成作品，最缺的往往就是这种可拆解、可对照、能反复看的完整资料，很适合留作长期参考。",
        )
    if any(word in text for word in ("股票", "买点", "主升浪", "交易")):
        return (
            "这套资料最吸引人的不是喊口号，而是把看盘、判断和复盘框架完整摆出来，适合想摆脱凭感觉操作的人认真研究。",
            "能否盈利仍取决于执行和风控，但把分析过程练得更清楚、把常见误区提前看明白，本身就很有参考价值。",
        )
    if any(word in text for word in ("康复", "筋膜", "理疗", "肩颈", "医师")):
        return (
            "这类系统资料平时很难一次找全，这一套难得在于把学习路径、动作细节和实操线索集中到了一起，查阅起来很省心。",
            "无论用于专业学习、备课还是日常复盘，都能反复回来对照，是一套实用性很强、值得长期留存的资料。",
        )
    if any(word in text for word in ("职业", "超级个体", "副业", "表达", "沟通", "幽默", "领导力")):
        return (
            "真正能让人拉开差距的，往往不是更忙，而是更早看懂一套靠谱的方法；这套内容把很多平时说不清的关键点讲得更集中。",
            "它适合慢慢看、反复想，再把其中的方法放回自己的工作和生活里验证；越认真拆，越容易发现真正有用的部分。",
        )
    return (
        "这套资料最让人心动的地方，是把平时零散、难找、需要反复筛选的重点集中到了一起，既能快速建立全局，也方便随用随查。",
        "它不是看一遍就放着的资料，而是可以反复翻、按需拆、直接拿来补盲区的一套内容；越往后看，越容易发现里面真正有用的部分。",
    )


def build_promotional_description(
    title: str,
    details: Mapping[str, object],
    description: str = "",
) -> str:
    """Build bold, natural marketing copy without inventing project facts or guaranteed income."""

    overview = build_project_description(title, details)
    factual_description = description.strip()
    if is_placeholder_description(factual_description):
        factual_description = overview
    source_text = _combined_text(title, factual_description, detail_file_names(details))
    hook, payoff = _promotional_angle(source_text)
    return f"{hook}\n\n{factual_description}\n\n{payoff}"


def finalize_x_post(
    *,
    body_parts: Sequence[str],
    link: str,
    tags: Sequence[str] = (),
    max_chars: int | None = None,
) -> str:
    """Assemble an X post; only truncate when a caller explicitly supplies a limit."""

    quark_line = f"🔗 {link.strip()}"
    if not link.strip():
        raise ValueError("X post requires a Quark link")
    body = [part.strip() for part in body_parts if part and part.strip()]
    normalized_tags: list[str] = []
    for tag in tags:
        candidate = str(tag or "").strip()
        if not candidate:
            continue
        if not candidate.startswith("#"):
            candidate = f"#{candidate}"
        if candidate not in normalized_tags:
            normalized_tags.append(candidate)

    def required_parts() -> list[str]:
        parts = [quark_line]
        if normalized_tags:
            parts.append(" ".join(normalized_tags))
        parts.append(X_TELEGRAM_CHANNEL_TAIL)
        return parts

    if max_chars is None:
        return "\n\n".join([*body, *required_parts()])

    while len(normalized_tags) > 1 and x_weighted_length("\n\n".join(required_parts())) > max_chars:
        normalized_tags.pop()
    required = "\n\n".join(required_parts())
    if x_weighted_length(required) > max_chars:
        raise ValueError("Required X links and hashtags exceed the configured character limit")

    full_parts = [*body, *required_parts()]
    full = "\n\n".join(full_parts)
    if x_weighted_length(full) <= max_chars:
        return full

    for keep in range(len(body), 0, -1):
        compact = "\n\n".join([*body[:keep], *required_parts()])
        if x_weighted_length(compact) <= max_chars:
            return compact

    required_weight = x_weighted_length(required)
    if not body:
        return required
    available = max_chars - required_weight - x_weighted_length("\n\n")
    headline = _truncate_x_text(body[0], available)
    return "\n\n".join((headline, required)) if headline else required


def build_x_promotional_post(
    *,
    title: str,
    description: str,
    link: str,
    file_names: Sequence[str] = (),
    max_tags: int = 8,
) -> str:
    """Build a lively, detailed X draft with factual value and monetization context."""

    effective_max_tags = max(4, max_tags)
    tags = build_dynamic_tags(title, description, file_names, max_tags=effective_max_tags)
    for fallback in X_FALLBACK_TAGS:
        if len(tags) >= 4:
            break
        if fallback not in tags:
            tags.append(fallback)
    factual_description = " ".join(description.split())
    hook, payoff = _promotional_angle(_combined_text(title, factual_description, file_names))
    return finalize_x_post(
        body_parts=[f"🔥 {title.strip()}｜这份真的值得认真看", hook, factual_description, payoff],
        link=link,
        tags=tags[:effective_max_tags],
    )


def build_dynamic_tags(
    title: str,
    description: str = "",
    file_names: Sequence[str] = (),
    *,
    max_tags: int = 8,
) -> list[str]:
    """Build stable, deduplicated hashtags from the row's verified text fields."""

    if max_tags < 1:
        return []

    text = _combined_text(title, description, file_names)
    tags: list[str] = []
    for tag, keywords in _TAG_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            tags.append(f"#{tag}")
        if len(tags) >= max_tags:
            break
    if file_names and len(tags) < min(6, max_tags):
        for tag, keywords in _FALLBACK_TAG_RULES:
            candidate = f"#{tag}"
            if candidate not in tags and any(keyword.casefold() in text for keyword in keywords):
                tags.append(candidate)
            if len(tags) >= min(6, max_tags):
                break
    return tags


def _inline_link(url: str, label: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def _fixed_inline_links(
    *,
    x_url: str = TELEGRAM_X_URL,
    channel_url: str = TELEGRAM_CHANNEL_URL,
) -> str:
    """Return fixed links embedded in the message caption itself."""

    return f"𝕏 {_inline_link(x_url, 'X')}  📣{_inline_link(channel_url, '频道')}"


def build_telegram_post(
    *,
    title: str,
    description: str,
    link: str,
    file_names: Sequence[str] = (),
    max_tags: int = 8,
) -> dict[str, object]:
    """Build an HTML caption with dynamic tags and fixed inline links."""

    tags = build_dynamic_tags(title, description, file_names, max_tags=max_tags)
    caption_parts = [
        escape(title.strip(), quote=False),
        "",
        escape(description.strip(), quote=False),
        "",
        f"🔗 {escape(link.strip(), quote=False)}",
    ]
    if tags:
        caption_parts.extend(["", " ".join(tags)])
    caption_parts.extend(["", _fixed_inline_links()])
    return {
        "caption": "\n".join(caption_parts),
        "parse_mode": "HTML",
        "fixed_links": [
            {"label": "X", "url": TELEGRAM_X_URL},
            {"label": "频道", "url": TELEGRAM_CHANNEL_URL},
        ],
        "tags": tags,
    }
