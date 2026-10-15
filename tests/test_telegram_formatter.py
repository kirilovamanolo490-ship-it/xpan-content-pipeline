import unittest

from xpan_auto.telegram_formatter import (
    TELEGRAM_CHANNEL_URL,
    TELEGRAM_X_URL,
    X_POST_MAX_CHARS,
    build_dynamic_tags,
    build_promotional_description,
    build_project_description,
    build_telegram_post,
    build_x_promotional_post,
    detail_file_names,
    is_placeholder_description,
    x_weighted_length,
)


class TelegramFormatterTests(unittest.TestCase):
    def test_promotional_copy_is_lively_factual_and_x_keeps_detailed_tags(self):
        details = {
            "summary": {"folder_count": 1, "file_count": 3, "extension_counts": {".mp4": 3}},
            "items": [
                {"type": "file", "name": "SEO流量实战.mp4"},
                {"type": "file", "name": "新媒体转化复盘.mp4"},
            ],
        }

        factual_description = "覆盖 SEO 获客、新媒体内容、转化复盘和服务交付，可用于搭建内容到成交的业务链路。"
        description = build_promotional_description(
            "网络营销与新媒体运营",
            details,
            factual_description,
        )
        x_text = build_x_promotional_post(
            title="网络营销与新媒体运营",
            description=description,
            link="https://pan.quark.cn/s/demo",
            file_names=detail_file_names(details),
        )

        self.assertIn(factual_description, description)
        self.assertIn("值得认真翻一遍", description)
        self.assertNotIn("1个文件夹", description)
        self.assertNotIn("保证赚钱", description)
        self.assertIn("这份真的值得认真看", x_text)
        self.assertIn("https://pan.quark.cn/s/demo", x_text)
        self.assertIn("📣 Telegram频道：https://example.invalid/telegram/channel", x_text)
        self.assertGreaterEqual(len([token for token in x_text.split() if token.startswith("#")]), 4)
        self.assertTrue(x_text.endswith(f"📣 Telegram频道：{TELEGRAM_CHANNEL_URL}"))

    def test_long_x_copy_is_not_locally_truncated_and_keeps_links_and_tags(self):
        x_text = build_x_promotional_post(
            title="很长的课程标题" * 40,
            description="很长的课程说明" * 80,
            link="https://pan.quark.cn/s/demo",
            file_names=["001第一课.mp4"],
        )

        self.assertGreater(x_weighted_length(x_text), X_POST_MAX_CHARS)
        self.assertIn("很长的课程说明" * 20, x_text)
        self.assertIn("https://pan.quark.cn/s/demo", x_text)
        self.assertGreaterEqual(len([token for token in x_text.split() if token.startswith("#")]), 4)
        self.assertTrue(x_text.endswith(f"📣 Telegram频道：{TELEGRAM_CHANNEL_URL}"))

    def test_x_weighted_length_counts_chinese_double_and_shortens_urls(self):
        self.assertEqual(
            x_weighted_length("中文 A https://pan.quark.cn/s/demo"),
            4 + 3 + 23,
        )

    def test_first_row_topics_become_dynamic_tags(self):
        tags = build_dynamic_tags(
            "极光社AI绘画电商设计速成训练营",
            "内容包括大模型和插件安装、图生图、ControlNet，以及电器、食品饮料、美妆场景设计。",
            ["第04课 电器产品、食品饮料、美妆场景类设计（PS Beta高阶功能讲解）.mp4"],
        )

        self.assertEqual(len(tags), 8)
        self.assertEqual(len(tags), len(set(tags)))
        for expected in ("#AI绘画", "#大模型", "#电商设计", "#图生图", "#ControlNet", "#PS教程"):
            self.assertIn(expected, tags)

    def test_health_example_uses_specific_topics(self):
        tags = build_dynamic_tags(
            "男人终极王牌训练",
            "本训练系统强肾健体，涵盖男性健康、前列腺调理。",
        )

        self.assertEqual(tags, ["#强肾健体", "#男性健康", "#前列腺调理", "#养生保健"])

    def test_humor_project_does_not_use_unrelated_health_topic(self):
        tags = build_dynamic_tags(
            "104 有趣实用的幽默课，让你说话有魅力，社交更轻松（完结）",
            "本课程讲解幽默表达、观点表达、社交破冰和人际交往。",
            [
                "第03讲 _ 用自嘲吐槽破冰，拉近距离、拓展人脉.mp3",
                "第13讲 _ 给男性、女性的幽默建议.pdf",
                "第24讲 _ 更有创意：喜剧创意这样来.pdf",
            ],
        )

        self.assertEqual(
            tags,
            [
                "#幽默表达",
                "#社交沟通",
                "#沟通技巧",
                "#人际魅力",
                "#破冰技巧",
                "#即兴创意",
                "#课件资料",
                "#课程资料",
            ],
        )

    def test_portrait_photography_project_uses_specific_topics(self):
        tags = build_dynamic_tags(
            "人像摄影实战训练营10大主题",
            "本资料包含31节视频课程，涵盖复古情绪、日式浴袍、日系胶片、古风人像、影棚闪光灯和修图更新。",
            ["第31节11.（修图课更新）中性灰和双曲线.mp4"],
        )

        self.assertEqual(
            tags,
            [
                "#人像摄影",
                "#摄影实战",
                "#摄影后期",
                "#摄影",
                "#视频课程",
                "#课程资料",
                "#课程分享",
            ],
        )

    def test_ppt_project_uses_specific_topics(self):
        tags = build_dynamic_tags(
            "299. PPT·从视觉到观点（完结）",
            "本资料包含PPT模板制作、视觉观点、案例拆解和参考素材。",
            ["PPT研习屋-PPT模板-成品.pptx", "精选PPT案例拆解.pdf"],
        )

        self.assertEqual(
            tags,
            [
                "#视觉表达",
                "#PPT设计",
                "#模板设计",
                "#案例拆解",
                "#PPT",
                "#课件资料",
                "#课程资料",
                "#课程分享",
            ],
        )

    def test_super_individual_project_prioritizes_growth_topics(self):
        details = {
            "summary": {
                "folder_count": 10,
                "file_count": 490,
                "extension_counts": {".mp3": 203, ".pdf": 274, ".mp4": 7, ".zip": 6},
            },
            "top_level": [
                {"name": "第一模块求职转型"},
                {"name": "核心竞争力"},
                {"name": "领导力"},
                {"name": "自我效能"},
                {"name": "副业发展"},
                {"name": "人生设计"},
            ],
            "items": [
                {"type": "file", "name": "发刊词丨52次加速，助你成为超级个体.pdf"},
                {"type": "file", "name": "让我们一起职业重启.mp3"},
                {"type": "file", "name": "自我效能与领导力.pdf"},
                {"type": "file", "name": "副业发展方法.pdf"},
            ],
        }
        description = build_project_description("古典·《超级个体》", details)
        tags = build_dynamic_tags(
            "古典·《超级个体》",
            description,
            detail_file_names(details),
        )

        self.assertIn("职业成长与个人进阶", description)
        self.assertEqual(
            tags[:5],
            ["#职业成长", "#职业重启", "#自我效能", "#领导力", "#副业发展"],
        )

    def test_specific_operational_topics_beat_generic_keywords(self):
        ai_tags = build_dynamic_tags(
            "WorkBuddy多场景AI办公实战，系统提升职场效率",
            "课程覆盖任务管理、Claw远程控制与高质量提示词模板。",
        )
        marketing_tags = build_dynamic_tags(
            "传智播客网络营销课程SEO SEM 社会化媒体 新媒体运营 电商网络营销",
            "课程覆盖 SEO、SEM 与电商网络营销。",
        )
        finance_tags = build_dynamic_tags(
            "股道九杨红心买点系统课买点的底层根基",
            "内容包括量能、主升浪与结构图形分析。",
        )
        ip_tags = build_dynamic_tags(
            "IP切片剪辑运营陪跑实操课程",
            "课程讲解切片电商、自媒体运营、混剪和商品类目趋势。",
        )

        self.assertEqual(ai_tags[:4], ["#AI办公", "#远程控制", "#提示词技巧", "#职场效率"])
        self.assertEqual(marketing_tags[:5], ["#网络营销", "#SEO", "#SEM", "#新媒体运营", "#电商营销"])
        self.assertEqual(finance_tags[:4], ["#股票交易", "#买点系统", "#技术分析", "#投资理财"])
        self.assertEqual(ip_tags[:4], ["#IP运营", "#切片剪辑", "#内容运营", "#电商运营"])

    def test_specialized_descriptions_use_project_specific_audience(self):
        details = {
            "summary": {"folder_count": 0, "file_count": 3, "extension_counts": {".mp4": 3}},
            "items": [
                {"type": "file", "name": "1-1认识workbuddy-AI办公新范式.mp4"},
                {"type": "file", "name": "2-2任务管理.mp4"},
                {"type": "file", "name": "3-1Claw远程控制.mp4"},
            ],
        }

        description = build_project_description("WorkBuddy多场景AI办公实战", details)

        self.assertIn("AI办公与职场效率", description)
        self.assertIn("AI 提升日常办公", description)

    def test_marketing_description_does_not_inherit_social_or_creative_topics(self):
        details = {
            "summary": {"folder_count": 0, "file_count": 3, "extension_counts": {".mp4": 3}},
            "items": [
                {"type": "file", "name": "传智播客-1SEO.mp4"},
                {"type": "file", "name": "传智播客-2SEM.mp4"},
                {"type": "file", "name": "传智播客-3社会化媒体营销.mp4"},
            ],
        }

        description = build_project_description("传智播客网络营销课程SEO SEM 社会化媒体 新媒体运营", details)

        self.assertIn("网络营销与新媒体运营", description)
        self.assertNotIn("社交破冰", description)
        self.assertNotIn("创意与思维", description)

    def test_post_contains_tags_and_fixed_buttons(self):
        post = build_telegram_post(
            title="极光社AI绘画电商设计速成训练营",
            description="围绕 AI 绘画电商设计场景展开。",
            link="https://pan.quark.cn/s/example",
        )

        caption = str(post["caption"])
        self.assertLess(caption.index("🔗"), caption.index("#AI绘画"))
        self.assertEqual(post["parse_mode"], "HTML")
        self.assertIn(f'𝕏 <a href="{TELEGRAM_X_URL}">X</a>', caption)
        self.assertIn(f'<a href="{TELEGRAM_CHANNEL_URL}">频道</a>', caption)
        self.assertNotIn("reply_markup", post)

    def test_caption_escapes_html_text(self):
        post = build_telegram_post(
            title="A&B <课程>",
            description="说明 <重点>",
            link="https://pan.quark.cn/s/example?a=1&b=2",
        )

        caption = str(post["caption"])
        self.assertIn("A&amp;B &lt;课程&gt;", caption)
        self.assertIn("说明 &lt;重点&gt;", caption)
        self.assertIn("a=1&amp;b=2", caption)

    def test_project_details_generate_description_and_richer_tags(self):
        details = {
            "summary": {"folder_count": 7, "file_count": 42},
            "top_level": [
                {"name": "肌筋膜文档总汇", "type": "folder"},
                {"name": "肌筋膜医师培训班", "type": "folder"},
                {"name": "筋膜链分析与疼痛康复评估视频", "type": "folder"},
                {"name": "课件", "type": "folder"},
            ],
            "items": [
                {"name": "肌筋膜理论知识1.doc", "path": "肌筋膜文档总汇/肌筋膜理论知识1.doc"},
                {"name": "Fascia Anatomy.pdf", "path": "课件/Fascia Anatomy.pdf"},
                {"name": "筋膜链康复评估.avi", "path": "筋膜链分析与疼痛康复评估视频/筋膜链康复评估.avi"},
            ],
        }

        description = build_project_description("肌筋膜链康复技术大汇总（康复师必备掌握）", details)
        tags = build_dynamic_tags(
            "肌筋膜链康复技术大汇总（康复师必备掌握）",
            description,
            detail_file_names(details),
        )

        self.assertFalse(is_placeholder_description(description))
        self.assertIn("肌筋膜理论文档", description)
        self.assertIn("7个文件夹和42个文件", description)
        self.assertGreaterEqual(len(tags), 6)
        self.assertLessEqual(len(tags), 8)
        self.assertEqual(len(tags), len(set(tags)))
        self.assertIn("#肌筋膜", tags)
        self.assertIn("#筋膜链", tags)
        self.assertIn("#视频课程", tags)

    def test_project_description_summarizes_lesson_content(self):
        details = {
            "summary": {
                "folder_count": 0,
                "file_count": 8,
                "extension_counts": {".mp3": 4, ".pdf": 4},
            },
            "items": [
                {"name": "第01讲 _ 与人交往，让人发笑的三个秘密.mp3"},
                {"name": "第01讲 _ 与人交往，让人发笑的三个秘密.pdf"},
                {"name": "第02讲 _ 怎样用幽默表达观点【免费获取：example.cn】.mp3"},
                {"name": "第02讲 _ 怎样用幽默表达观点.pdf"},
                {"name": "第03讲 _ 用自嘲吐槽破冰，拓展人脉.mp3"},
                {"name": "第03讲 _ 用自嘲吐槽破冰，拓展人脉.pdf"},
                {"name": "【发刊词】学点幽默，有趣的人有好人缘.mp3"},
                {"name": "【发刊词】学点幽默，有趣的人有好人缘.pdf"},
            ],
        }

        description = build_project_description("幽默表达与社交沟通课", details)

        self.assertIn("包含3讲课程、发刊词", description)
        self.assertIn("配套4份音频和4份PDF讲义", description)
        self.assertIn("幽默表达", description)
        self.assertIn("社交破冰", description)
        self.assertNotIn("第01讲", description)
        self.assertNotIn(".mp3", description)
        self.assertNotIn("【免费获取", description)

    def test_philosophy_project_summarizes_topics_and_formats(self):
        details = {
            "summary": {
                "folder_count": 1,
                "file_count": 8,
                "extension_counts": {".m4a": 4, ".pdf": 4},
            },
            "items": [
                {"type": "file", "name": "01 _ 欢迎来到哲学的世界.m4a"},
                {"type": "file", "name": "01 _ 欢迎来到哲学的世界.pdf"},
                {"type": "file", "name": "02 _ 什么是逻辑，怎样才算有逻辑.m4a"},
                {"type": "file", "name": "02 _ 什么是逻辑，怎样才算有逻辑.pdf"},
                {"type": "file", "name": "03 _ 幸福是可以自己把握的吗？.m4a"},
                {"type": "file", "name": "03 _ 幸福是可以自己把握的吗？.pdf"},
                {"type": "file", "name": "00[发刊词]究竟要懂多少道理？.m4a"},
                {"type": "file", "name": "00[发刊词]究竟要懂多少道理？.pdf"},
            ],
        }

        description = build_project_description("傅佩荣的人生哲学课", details)

        self.assertIn("哲学思考与人生智慧", description)
        self.assertIn("包含3讲课程、发刊词", description)
        self.assertIn("配套4份音频和4份PDF讲义", description)
        self.assertIn("哲学入门与思考", description)
        self.assertIn("逻辑与论证", description)
        self.assertIn("人生价值与幸福", description)
        self.assertIn("适合系统学习哲学基础、逻辑思辨和人生议题", description)
        self.assertNotIn(".m4a", description)

    def test_philosophy_project_uses_specific_tags(self):
        tags = build_dynamic_tags(
            "傅佩荣的人生哲学课",
            "包含课程，涵盖哲学入门、逻辑思辨、人生价值、自我成长、社会制度与信仰。",
            ["01 _ 欢迎来到哲学的世界.m4a", "02 _ 什么是逻辑，怎样才算有逻辑.pdf"],
        )

        self.assertEqual(
            tags,
            [
                "#哲学思考",
                "#逻辑思辨",
                "#人生哲学",
                "#自我成长",
                "#社会与信仰",
                "#课件资料",
                "#课程资料",
                "#课程分享",
            ],
        )


if __name__ == "__main__":
    unittest.main()
