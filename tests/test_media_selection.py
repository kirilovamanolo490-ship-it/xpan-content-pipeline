import unittest

from xpan_auto.media_selection import order_video_records, selection_basis


class MediaSelectionTests(unittest.TestCase):
    def test_chinese_stage_and_lesson_parts_precede_environment_appendix(self):
        records = [
            {"kind": "video", "name": "第1课-07-ClaudeCode介绍.mp4", "path": "课程/环境准备/第1课-07-ClaudeCode介绍.mp4"},
            {"kind": "video", "name": "第一阶段-005-API深入.mp4", "path": "课程/第一阶段/第一阶段-005-API深入.mp4"},
            {"kind": "video", "name": "第一阶段 直播答疑（二）.mp4", "path": "课程/第一阶段/第一阶段 直播答疑（二）.mp4"},
            {"kind": "video", "name": "第一阶段-001-搭建开发环境.mp4", "path": "课程/第一阶段/第一阶段-001-搭建开发环境.mp4"},
        ]
        selected = order_video_records(records)[0]
        self.assertEqual(selected["name"], records[3]["name"])
        self.assertEqual(selection_basis(selected), "explicit-lesson-sequence:1.1")

    def test_presenter_recording_dates_use_tree_order(self):
        records = [
            {"kind": "video", "name": "24.2.4丁老师《原生家庭与自我探索》.mp4"},
            {"kind": "video", "name": "2.22耶耶老师《小猫爬床》.mp4"},
            {"kind": "video", "name": "24.1.5周老师《魅力修炼》.mp4"},
        ]
        selected = order_video_records(records)[0]
        self.assertEqual(selected["name"], records[0]["name"])
        self.assertEqual(selection_basis(selected), "depth-first-fallback-no-explicit-sequence")

    def test_task_prefix_outranks_inner_lesson_number(self):
        records = [
            {"kind": "video", "name": "任务132：11-Vuejs第一节课-小结.mp4"},
            {"kind": "video", "name": "任务002：艾编程架构师VIP开班典礼+学习心里分享.mp4"},
        ]
        ordered = order_video_records(records)
        self.assertEqual(ordered[0]["name"], records[1]["name"])
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:2")

    def test_numbered_course_stage_precedes_later_stage_task_one(self):
        records = [
            {"kind": "video", "name": "任务1：1、Docker.mp4", "path": "课程/03-第三阶段/任务1：1、Docker.mp4"},
            {"kind": "video", "name": "任务002：开班典礼.mp4", "path": "课程/01-第一阶段/任务002：开班典礼.mp4"},
        ]
        self.assertEqual(order_video_records(records)[0]["name"], records[1]["name"])

    def test_explicit_lesson_number_beats_api_return_order(self):
        records = [
            {"type": "file", "extension": ".mov", "name": "62、私域流量 (1).mov", "depth": 1},
            {"type": "file", "extension": ".mp4", "name": "1 第一节认知篇三个理由让你非做IP不可 (1).mp4", "depth": 1},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "1 第一节认知篇三个理由让你非做IP不可 (1).mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1")

    def test_chinese_lesson_marker_is_supported(self):
        records = [
            {"kind": "video", "name": "第二节认知篇.mp4", "depth": 0},
            {"kind": "video", "name": "第一节认知篇.mp4", "depth": 0},
        ]

        self.assertEqual(order_video_records(records)[0]["name"], "第一节认知篇.mp4")

    def test_arabic_number_followed_by_lesson_unit_is_supported(self):
        records = [
            {"kind": "video", "name": "17节2.6 用AI来做产品策划.mp4", "depth": 1},
            {"kind": "video", "name": "1节1.AI课程知识体系.mp4", "depth": 1},
            {"kind": "video", "name": "2节1.1 分享国内可用的免费AI平台.mp4", "depth": 1},
        ]

        ordered = order_video_records(records)
        self.assertEqual(ordered[0]["name"], "1节1.AI课程知识体系.mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1")

    def test_explicit_episode_after_common_series_prefix_is_supported(self):
        records = [
            {"kind": "video", "name": "阿U学科学 第23集 隐身人.mkv", "depth": 1},
            {"kind": "video", "name": "阿U学科学 第01集 一滴水.webm", "depth": 1},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "阿U学科学 第01集 一滴水.webm")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1")

    def test_day_marker_sorts_by_full_explicit_number(self):
        records = [
            {"kind": "video", "name": "第161天.mp4", "depth": 0},
            {"kind": "video", "name": "第1天.mp4", "depth": 0},
        ]

        self.assertEqual(order_video_records(records)[0]["name"], "第1天.mp4")

    def test_zero_padded_prefix_directly_before_chinese_title_is_supported(self):
        records = [
            {"kind": "video", "name": "009第9课：社群运营.mp4", "depth": 0},
            {"kind": "video", "name": "001第1课：画像与定位.mp4", "depth": 0},
            {"kind": "video", "name": "000先导课.mp4", "depth": 0},
        ]

        self.assertEqual(order_video_records(records)[0]["name"], "000先导课.mp4")
        self.assertEqual(selection_basis(order_video_records(records)[0]), "explicit-lesson-sequence:0")

    def test_unmarked_videos_keep_original_tree_order(self):
        records = [
            {"kind": "video", "name": "导学试看.mp4", "depth": 0},
            {"kind": "video", "name": "课程片段.mp4", "depth": 1},
        ]

        self.assertEqual(
            [item["name"] for item in order_video_records(records)],
            ["导学试看.mp4", "课程片段.mp4"],
        )

    def test_same_file_sequence_uses_week_and_chapter_path_order(self):
        records = [
            {
                "kind": "video",
                "name": "1.本章内容概述.mp4",
                "path": "课程/第2周-第5章/1.本章内容概述.mp4",
                "depth": 2,
            },
            {
                "kind": "video",
                "name": "1.课程整体内容安排.mp4",
                "path": "课程/第1周-第1章/1.课程整体内容安排.mp4",
                "depth": 2,
            },
        ]

        self.assertEqual(order_video_records(records)[0]["name"], "1.课程整体内容安排.mp4")

    def test_same_sequence_and_chapter_preserves_depth_first_tree_order(self):
        records = [
            {
                "kind": "video",
                "name": "第一章.mp4",
                "path": "/课程/第1章 课程介绍/1/第一章.mp4",
                "depth": 3,
            },
            {
                "kind": "video",
                "name": "1-1 课程简介.avi",
                "path": "/课程/第1章 课程介绍/1-1 课程简介.avi",
                "depth": 2,
            },
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "第一章.mp4")

    def test_directory_numbers_do_not_override_explicit_file_sequence(self):
        records = [
            {
                "kind": "video",
                "name": "2.第二个视频.mp4",
                "path": "课程/第1周-第1章/2.第二个视频.mp4",
                "depth": 2,
            },
            {
                "kind": "video",
                "name": "1.第九周视频.mp4",
                "path": "课程/第9周-第22章/1.第九周视频.mp4",
                "depth": 2,
            },
        ]

        self.assertEqual(order_video_records(records)[0]["name"], "1.第九周视频.mp4")

    def test_bracketed_decimal_sequence_is_ordered_numerically(self):
        records = [
            {"kind": "video", "name": "[1.5]--快速生成专业主图.mp4", "depth": 0},
            {"kind": "video", "name": "[1.11]--电影级分镜.mp4", "depth": 0},
            {"kind": "video", "name": "[1.1]--一键海报生成.mp4", "depth": 0},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "[1.1]--一键海报生成.mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1.1")

    def test_unbracketed_decimal_sequence_is_ordered_numerically(self):
        records = [
            {"kind": "video", "name": "1.7 操作系统结构.mp4", "path": "/课程/1.7 操作系统结构.mp4"},
            {"kind": "video", "name": "1.1 课程概述.mp4", "path": "/课程/1.1 课程概述.mp4"},
            {"kind": "video", "name": "1.11 实验说明.mp4", "path": "/课程/1.11 实验说明.mp4"},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "1.1 课程概述.mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1.1")

    def test_hyphenated_chapter_sequence_is_ordered_numerically(self):
        records = [
            {"kind": "video", "name": "1-2 终端日志记录与监控.mp4", "depth": 1},
            {"kind": "video", "name": "1-1 端点安全基础.mp4", "depth": 1},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "1-1 端点安全基础.mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1.1")

    def test_decimal_sequence_directly_before_chinese_title_is_supported(self):
        records = [
            {"kind": "video", "name": "5.5起号带货形式.mp4", "depth": 1},
            {"kind": "video", "name": "5.2新号启动+老号转型.mp4", "depth": 1},
            {"kind": "video", "name": "0粉开橱窗教程.mp4", "depth": 1},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "5.2新号启动+老号转型.mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:5.2")

    def test_sequence_after_bracketed_date_label_is_supported(self):
        records = [
            {"kind": "video", "name": "【26年5月】03.第1章-信息化发展.mp4", "depth": 1},
            {"kind": "video", "name": "【26年5月】01.软考介绍及学习方式说明.mp4", "depth": 1},
            {"kind": "video", "name": "【26年5月】02.机考常见问题说明.mp4", "depth": 1},
        ]

        ordered = order_video_records(records)

        self.assertEqual(ordered[0]["name"], "【26年5月】01.软考介绍及学习方式说明.mp4")
        self.assertEqual(selection_basis(ordered[0]), "explicit-lesson-sequence:1")


if __name__ == "__main__":
    unittest.main()
