"""知识渠道资料自动预分类。

按标题关键词把资料归入用户定义的六大类。规则是纯关键词打分，
结果只作为「预分类」，最终以人工确认为准（程序不覆盖用户在 Excel
里改过的分类值）。
"""

from __future__ import annotations

CATEGORIES = [
    "AI方向",
    "赚钱",
    "使用工具教程",
    "工具分享",
    "男女情感",
    "性爱相关",
]

# (category, [keywords]) —— 关键词命中即给该类 +1 分
# 注意：同一关键词可能命中多类（如"AI短视频变现"同时含 AI 与变现），
# 采用计分制，得分最高者胜出；平分时按 CATEGORIES 顺序优先。
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "AI方向",
        (
            "ai", "人工智能", "大模型", "llm", "rag", "agent", "agentic",
            "gpt", "claude", "codex", "openai", "midjourney", "stable diffusion",
            "sd绘画", "提示词", "prompt", "机器学习", "深度学习", "神经网络",
            "aigc", "ai绘画", "ai编程", "ai视频", "ai数字人", "ai漫剧", "ai动画",
            "ai短剧", "ai量化", "ai售图", "ai复刻", "ai电商", "ai办公", "ai算法",
            "模型微调", "微调", "部署微调", "huggingface", "transformers",
            "token", "多模态", "生成式", "文生图", "文生视频", "数字人",
            "智能体", "自动化办公", "vibe coding", "cursor", "copilot",
            "chatgpt", "豆包", "文心一言", "通义千问", "kimi", "deepseek",
        ),
    ),
    (
        "赚钱",
        (
            "变现", "赚钱", "搞钱", "副业", "收益", "佣金", "分佣", "商单",
            "引流", "获客", "涨粉", "带货", "直播", "流量", "私域", "社群",
            "创业", "生意", "项目", "操盘", "打法", "玩法", "营销", "运营",
            "财富", "理财", "投资", "基金", "金融", "量化交易", "付费文",
            "知识星球", "会员", "付费", "签约", "过稿", "写作变现", "网文",
            "小说", "出单", "成交", "客单价", "跨境", "tiktok", "shopee",
            "亚马逊", "淘宝", "电商", "拼多多", "抖音", "小红书", "快手",
            "视频号", "公众号", "b站", "bilibili", "知乎", "喜马拉雅",
            "播客", "广告", "品牌", "ip变现", "超级ip", "个人ip",
        ),
    ),
    (
        "使用工具教程",
        (
            "教程", "课程", "实战", "训练营", "指南", "入门", "进阶",
            "零基础", "从零", "实操", "教学", "全流程", "系统课", "课",
            "速成", "精通", "通关", "通关课", "大课", "小课", "速记",
            "精讲", "详解", "解析", "攻略", "方法", "技巧", "玩法",
            "操盘术", "学习", "课堂", "讲座", "公开课", "讲",
        ),
    ),
    (
        "工具分享",
        (
            "软件", "破解", "直装版", "绿色版", "工具箱", "工具合集",
            "插件", "素材包", "模板", "合集", "资源", "idm", "下载工具",
            "激活", "注册机", "便携", "开源", "源码", "脚本", "爬虫",
            "app", "应用", "数据集", "语料", "prompt库", "预设", "预设库",
            "书单", "书籍", "pdf", "电子书", "文档", "课件", "讲义",
            "笔记", "模板库", "字体", "音效", "配乐", "剪辑素材",
        ),
    ),
    (
        "男女情感",
        (
            "情感", "恋爱", "脱单", "挽回", "婚姻", "两性", "情商",
            "沟通", "说话", "人性", "社交", "撩", "亲密", "关系",
            "择偶", "吸引", "约会", "表白", "暧昧", "夫妻", "女友",
            "男友", "老婆", "老公", "相处", "家庭", "心理",
            "说话成事",
        ),
    ),
    (
        "性爱相关",
        (
            "写真", "福利", "私房", "内衣", "丝袜", "女主播", "岛国",
            "打碟", "大尺度", "露骨", "情趣", "涩", "色情", "成人",
            "夜店", "泳装", "性感", "bra", "睡衣", "换衣",
            "持久", "性爱", "做爱", "私密",
        ),
    ),
]

# 权重：命中性爱相关关键词基本可以断定内容方向，给予更高权重；
# 其余类别平分时按 CATEGORIES 顺序优先。
CATEGORY_WEIGHTS = {"性爱相关": 3}

# 反向排除：命中这些词不归入该类的关键词对（category, keyword）
# 用于降低明显误判（例如"内衣"同时命中情感/性爱时由计分决定，不单独排除）。
_EXCLUDE_PAIRS: tuple[tuple[str, str], ...] = ()


def classify(title: str) -> tuple[str, list[str]]:
    """返回 (预分类, 命中关键词列表)。标题为空时返回 (未分类, [])。"""
    text = (title or "").lower()
    if not text.strip():
        return "未分类", []
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for category, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword in text:
                scores[category] = scores.get(category, 0) + CATEGORY_WEIGHTS.get(category, 1)
                hits.setdefault(category, []).append(keyword)
    if not scores:
        return "未分类", []
    best = max(CATEGORIES, key=lambda c: scores.get(c, 0))
    return best, hits.get(best, [])


def summarize_rules() -> str:
    lines = []
    for category, keywords in CATEGORY_RULES:
        lines.append(f"- {category}: {', '.join(keywords[:12])}" + ("…" if len(keywords) > 12 else ""))
    return "\n".join(lines)
