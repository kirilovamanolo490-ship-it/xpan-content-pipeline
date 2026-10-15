import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from xpan_auto.telegram_quality import inspect_telegram_outputs, measure_cover_activity


class TelegramQualityTests(unittest.TestCase):
    def _fixture(self, *, metadata: dict[str, object] | None = None, caption: str | None = None):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)
        image_path = root / "cover.png"
        caption_path = root / "caption.html"
        metadata_path = root / "telegram-asset.json"
        details_path = root / "telegram-project-details.json"

        image = Image.new("RGB", (1672, 941), (12, 24, 48))
        draw = ImageDraw.Draw(image)
        for x in range(30, 1672, 110):
            draw.line((x, 20, x, 920), fill=(45 + x % 160, 150, 195), width=3)
        for y in range(30, 941, 95):
            draw.line((20, y, 1650, y), fill=(90, 80 + y % 150, 180), width=3)
        draw.rectangle((80, 80, 740, 420), outline=(80, 220, 180), width=12)
        draw.ellipse((1040, 180, 1510, 650), fill=(160, 90, 120), outline=(240, 210, 120), width=10)
        image.save(image_path, format="PNG")
        measured = measure_cover_activity(image_path)

        metadata_path.write_text(
            json.dumps(
                metadata
                or {
                    "quality_version": 12,
                    "font_fallback": False,
                    "font_files": [str(Path(__file__).resolve())],
                    "layout": "text-only-summary",
                    "placeholder_texts": [],
                    "design": {
                        "visual_profile": "modern",
                        "composition": "semantic-summary",
                        "layout_strategy": "semantic-summary",
                        "layout_basis": {
                            "title_units": 4,
                            "title_length_class": "short",
                            "source_kind": "none",
                            "source_aspect_ratio": None,
                            "metric_count": 1,
                            "reason": "项目没有可预览素材，使用信息摘要构图",
                        },
                        "fullness": {
                            "source_coverage": 0.0,
                            "occupied_ratio": measured["activity_ratio"],
                            "rendered_activity_ratio": measured["activity_ratio"],
                            "rendered_left_activity_ratio": measured["left_activity_ratio"],
                            "rendered_right_activity_ratio": measured["right_activity_ratio"],
                            "title_line_count": 1,
                            "support_line_count": 0,
                            "keyword_line_count": 1,
                            "metric_count": 1,
                        },
                        "overlay_mode": "none",
                        "layout_geometry": {},
                        "metric_presentation": "single-badge",
                        "content_regions": [],
                        "information_tiers": ["topic", "title", "keywords", "metrics"],
                        "topic_text": "专题学习",
                        "title_display": "示例课程",
                        "title_display_source": "示例课程",
                        "title_display_basis": "完整显示清洗后的项目标题",
                        "keyword_text": "系统课程 · 方法整理",
                        "support_text": "",
                        "support_source": "",
                        "title_lines": ["示例课程"],
                        "metrics": [{"label": "视频", "count": 1}],
                        "semantic_basis": {
                            "selected_profile": "modern",
                            "scores": {"modern": 0},
                            "matched_signals": [],
                        },
                        "typography_basis": {
                            "title_family": "sans",
                            "eyebrow_family": "sans",
                            "body_family": "sans",
                            "reason": "根据现代课程语义选择字体角色",
                        },
                        "palette": {
                            "background": "#0a192a",
                            "accent": "#4ac4d6",
                            "secondary": "#987ae0",
                            "basis": "project-media-dominant",
                            "source_weight": 0.68,
                            "semantic_reason": "现代课程语义基础色",
                            "semantic_palette": {
                                "background": "#0a192a",
                                "accent": "#4ac4d6",
                                "secondary": "#987ae0",
                            },
                            "source_palette": {
                                "background": "#143052",
                                "accent": "#4a8cd2",
                                "secondary": "#d7b060",
                            },
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        details_path.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "no-project-media", "source_path": None},
                    "summary": {"file_count": 1, "extension_counts": {".bin": 1}},
                    "items": [{"type": "file", "name": "01.bin", "extension": ".bin"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        caption_path.write_text(
            caption
            or (
                "<b>示例课程</b>\n\n"
                "这是一段真实资料介绍。\n\n"
                '<a href="https://pan.quark.cn/s/example">夸克链接</a>\n'
                "#课程 #资料\n"
                '<a href="https://example.invalid/telegram/channel">频道</a>'
            ),
            encoding="utf-8",
        )
        return temp_dir, image_path, caption_path, metadata_path, details_path

    def test_accepts_quality_gated_outputs(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertTrue(report.passed, report.issues)

    def test_accepts_reviewed_imagegen_cover_without_inventory_metrics(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        generated_source = image.parent / "imagegen-source.png"
        generated_source.write_bytes(image.read_bytes())
        measured = measure_cover_activity(image)
        metadata.write_text(
            json.dumps(
                {
                    "quality_version": 12,
                    "method": "image-gen-output",
                    "font_fallback": False,
                    "font_files": [],
                    "layout": "image-gen",
                    "source_image": str(generated_source),
                    "placeholder_texts": [],
                    "design": {
                        "visual_profile": "clinical",
                        "composition": "image-gen",
                        "layout_strategy": "image-gen",
                        "fullness": {
                            "source_coverage": 1.0,
                            "occupied_ratio": measured["activity_ratio"],
                            "rendered_activity_ratio": measured["activity_ratio"],
                            "rendered_left_activity_ratio": measured["left_activity_ratio"],
                            "rendered_right_activity_ratio": measured["right_activity_ratio"],
                            "title_line_count": 1,
                            "support_line_count": 1,
                            "keyword_line_count": 1,
                            "metric_count": 0,
                        },
                        "information_tiers": ["title", "keywords", "visual"],
                        "title_display": "示例课程",
                        "content_anchors": ["电子病历", "临床预测模型"],
                        "metrics": [],
                        "semantic_basis": {
                            "selected_profile": "clinical",
                            "scores": {"clinical": 10},
                            "matched_signals": ["title:临床"],
                        },
                        "palette": {
                            "background": "#0b1f33",
                            "accent": "#2a9d8f",
                            "secondary": "#e07a5f",
                            "basis": "imagegen-project-derived",
                            "semantic_reason": "clinical 语义基础色",
                            "semantic_palette": {
                                "background": "#0b1f33",
                                "accent": "#2a9d8f",
                                "secondary": "#e07a5f",
                            },
                        },
                        "generation": {
                            "tool": "imagegen",
                            "prompt_contract": "factual-social-cover-v1",
                            "prompt": "医学编辑风临床数据封面",
                            "visual_direction": "把病历与统计模型组织成一个连贯研究场景",
                            "palette_reason": "根据临床研究的可信与克制感选择低饱和配色",
                            "displayed_title": "示例课程",
                            "content_anchors": ["电子病历", "临床预测模型"],
                            "checks": {
                                "subject_relevant": True,
                                "palette_compliant": True,
                                "text_readable": True,
                                "uncluttered_composition": True,
                                "no_fabricated_content": True,
                            },
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertTrue(report.passed, report.issues)
        self.assertTrue(report.checks["imagegen_visual_review"])
        self.assertTrue(report.checks["imagegen_no_inventory_metrics"])

    def test_accepts_adaptive_portrait_cover_from_a_real_document_preview(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        source = image.parent / "source-preview.png"
        source_image = Image.new("RGB", (900, 1200), (241, 243, 246))
        source_draw = ImageDraw.Draw(source_image)
        source_draw.rectangle((45, 45, 855, 1155), outline=(28, 65, 108), width=10)
        source_draw.line((110, 220, 790, 220), fill=(40, 40, 40), width=12)
        source_draw.line((110, 340, 790, 340), fill=(90, 90, 90), width=8)
        source_image.save(source, format="PNG")

        portrait = Image.new("RGB", (1080, 1920), (225, 231, 238))
        portrait.paste(source_image.resize((900, 1200)), (90, 360))
        portrait.save(image, format="PNG")
        measured = measure_cover_activity(image)

        metadata.write_text(
            json.dumps(
                {
                    "quality_version": 12,
                    "method": "document-cover-adaptive",
                    "font_fallback": False,
                    "font_files": [],
                    "layout": "document-cover-adaptive",
                    "source_image": str(source),
                    "source_render_mode": "fit-document-page",
                    "placeholder_texts": [],
                    "design": {
                        "composition": "document-cover-adaptive",
                        "layout_strategy": "document-cover-adaptive",
                        "source_kind": "document-preview",
                        "document_inventory_count": 1,
                        "original_size": [900, 1200],
                        "source_aspect_ratio": 0.75,
                        "canvas_size": [1080, 1920],
                        "orientation": "portrait",
                        "aspect_ratio": "9:16",
                        "content_box": [90, 360, 990, 1560],
                        "background_mode": "blurred-source-fill",
                        "overlay_text": False,
                        "fullness": {"rendered_activity_ratio": measured["activity_ratio"]},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "document-preview", "source_path": str(source)},
                    "summary": {"file_count": 1, "extension_counts": {".pdf": 1}},
                    "items": [{"type": "file", "name": "讲义.pdf", "extension": ".pdf"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertTrue(report.passed, report.issues)

    def test_rejects_legacy_cover_metadata(self):
        temp_dir, image, caption, metadata, details = self._fixture(
            metadata={"method": "local-information-card"}
        )
        self.addCleanup(temp_dir.cleanup)

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("质量元数据" in issue for issue in report.issues))
        self.assertTrue(any("字体回退" in issue for issue in report.issues))

    def test_rejects_placeholder_layout_and_caption(self):
        temp_dir, image, caption, metadata, details = self._fixture(
            metadata={
                "quality_version": 6,
                "font_fallback": False,
                "font_files": [str(Path(__file__).resolve())],
                "layout": "legacy-placeholder",
                "placeholder_texts": ["项目主题"],
            },
            caption="<b>示例课程</b> 来源飞书页面已识别",
        )
        self.addCleanup(temp_dir.cleanup)

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("旧版或未知布局" in issue for issue in report.issues))
        self.assertTrue(any("占位文案" in issue for issue in report.issues))
        self.assertTrue(any("占位介绍" in issue for issue in report.issues))

    def test_rejects_text_cover_when_project_media_exists(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)

        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "video-frame", "source_path": "source-preview.png"},
                    "summary": {"file_count": 1, "extension_counts": {".mp4": 1}},
                    "items": [{"type": "file", "name": "lesson.mp4", "extension": ".mp4"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("可预览文件" in issue for issue in report.issues))

    def test_rejects_cover_with_incomplete_information_hierarchy(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["design"]["information_tiers"] = ["title"]
        payload["design"]["metrics"] = []
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("信息层级不完整" in issue for issue in report.issues))
        self.assertTrue(any("资料数量信息" in issue for issue in report.issues))

    def test_rejects_fake_format_metric_used_only_to_fill_a_bar(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["design"]["metrics"] = [{"label": "格式", "count": 1}]
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("无意义凑数指标" in issue for issue in report.issues))

    def test_rejects_video_cover_when_text_zone_intrudes_into_source(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        source = image.parent / "source-preview.png"
        Image.new("RGB", (1280, 720), (70, 100, 145)).save(source, format="PNG")

        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload.update(
            {
                "layout": "source-image",
                "source_image": str(source),
                "source_render_mode": "fit-media",
            }
        )
        design = payload["design"]
        design.update(
            {
                "composition": "media-focus-split",
                "layout_strategy": "media-focus-split",
                "overlay_mode": "separate-zones",
                "layout_basis": {
                    "title_units": 4,
                    "title_length_class": "short",
                    "source_kind": "video-frame",
                    "source_aspect_ratio": 1.778,
                    "metric_count": 1,
                    "reason": "真实视频画面与课程信息分区呈现",
                },
                "layout_geometry": {
                    "text_zone": [62, 70, 800, 903],
                    "source_zone": [760, 56, 1624, 867],
                    "minimum_gap": -40,
                    "text_over_source": False,
                    "title_support_gap": 32,
                },
                "information_tiers": ["topic", "title", "support", "keywords", "metrics"],
                "support_text": "3 节视频课程",
                "support_source": "project.summary",
                "content_spine": ["课程导入", "方法训练", "案例复盘"],
                "content_spine_source": "project.files",
                "content_regions": [{"name": "left-rail", "indices": [0, 1, 2]}],
                "metrics": [{"label": "视频", "count": 3}],
                "metric_presentation": "support-inline",
            }
        )
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {
                        "kind": "video-frame",
                        "source_path": str(source),
                        "source_name": "课程导入.mp4",
                        "evaluated_frames": 4,
                        "frame_quality_score": 30.0,
                    },
                    "summary": {"file_count": 3, "extension_counts": {".mp4": 3}},
                    "items": [
                        {"type": "file", "name": "课程导入.mp4", "extension": ".mp4"},
                        {"type": "file", "name": "方法训练.mp4", "extension": ".mp4"},
                        {"type": "file", "name": "案例复盘.mp4", "extension": ".mp4"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("文字区与真实画面" in issue for issue in report.issues))

        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["design"]["layout_geometry"] = {
            "text_zone": [62, 70, 712, 903],
            "source_zone": [760, 56, 1624, 867],
            "minimum_gap": 48,
            "text_over_source": False,
            "title_support_gap": 8,
        }
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        spacing_report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )
        self.assertFalse(spacing_report.passed)
        self.assertTrue(any("主标题与课程数量信息间距不足" in issue for issue in spacing_report.issues))

    def test_rejects_cover_without_semantic_style_evidence_or_with_title_orphan(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["design"].pop("semantic_basis")
        payload["design"]["title_lines"] = ["完整标题", "词"]
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("如何由当前项目内容推导" in issue for issue in report.issues))
        self.assertTrue(any("汉字的孤行" in issue for issue in report.issues))

    def test_rejects_listing_noise_and_dirty_course_spine_labels(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["design"]["title_display"] = "WorkBuddy多场景AI办公实战(3)"
        payload["design"]["title_lines"] = ["WorkBuddy多场景A", "I办公实战"]
        payload["design"]["content_spine"] = ["自媒体发展现状与趋势 1", "课程，"]
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("英文缩写或单词" in issue for issue in report.issues))
        self.assertTrue(any("列表序号" in issue for issue in report.issues))
        self.assertTrue(any("课程脉络残留编号" in issue for issue in report.issues))

    def test_accepts_cover_that_uses_a_real_project_image(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        source = image.parent / "source-preview.png"
        Image.new("RGB", (320, 180), (80, 140, 210)).save(source, format="PNG")
        measured = measure_cover_activity(image)

        metadata.write_text(
            json.dumps(
                {
                    "quality_version": 12,
                    "font_fallback": False,
                    "font_files": [str(Path(__file__).resolve())],
                    "layout": "source-image",
                    "source_image": str(source),
                    "source_render_mode": "fit-media",
                    "placeholder_texts": [],
                    "design": {
                        "visual_profile": "modern",
                        "composition": "source-dominant-poster",
                        "layout_strategy": "source-dominant-poster",
                        "layout_basis": {
                            "title_units": 4,
                            "title_length_class": "short",
                            "source_kind": "project-image",
                            "source_aspect_ratio": 1.778,
                            "metric_count": 1,
                            "reason": "短标题且存在真实支持信息，使用素材主导海报",
                        },
                        "fullness": {
                            "source_coverage": 1.0,
                            "occupied_ratio": measured["activity_ratio"],
                            "rendered_activity_ratio": measured["activity_ratio"],
                            "rendered_left_activity_ratio": measured["left_activity_ratio"],
                            "rendered_right_activity_ratio": measured["right_activity_ratio"],
                            "title_line_count": 1,
                            "support_line_count": 1,
                            "keyword_line_count": 1,
                            "metric_count": 1,
                        },
                        "overlay_mode": "solid-stage",
                        "layout_geometry": {},
                        "metric_presentation": "single-badge",
                        "content_regions": [],
                        "information_tiers": ["topic", "title", "support", "keywords", "metrics"],
                        "topic_text": "专题学习",
                        "title_display": "示例课程",
                        "title_display_source": "示例课程",
                        "title_display_basis": "完整显示清洗后的项目标题",
                        "keyword_text": "系统课程 · 方法整理",
                        "support_text": "项目图片",
                        "support_source": "project.files",
                        "title_lines": ["示例课程"],
                        "metrics": [{"label": "图片", "count": 1}],
                        "semantic_basis": {
                            "selected_profile": "modern",
                            "scores": {"modern": 0},
                            "matched_signals": [],
                        },
                        "typography_basis": {
                            "title_family": "sans",
                            "eyebrow_family": "sans",
                            "body_family": "sans",
                            "reason": "根据现代课程语义选择字体角色",
                        },
                        "palette": {
                            "background": "#0a192a",
                            "accent": "#4ac4d6",
                            "secondary": "#987ae0",
                            "basis": "project-media-dominant",
                            "source_weight": 0.68,
                            "semantic_reason": "现代课程语义基础色",
                            "semantic_palette": {
                                "background": "#0a192a",
                                "accent": "#4ac4d6",
                                "secondary": "#987ae0",
                            },
                            "source_palette": {
                                "background": "#143052",
                                "accent": "#4a8cd2",
                                "secondary": "#d7b060",
                            },
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "project-image", "source_path": str(source), "source_name": "项目图片.png"},
                    "summary": {"file_count": 1, "extension_counts": {".png": 1}},
                    "items": [{"type": "file", "name": "项目图片.png", "extension": ".png"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertTrue(report.passed, report.issues)

    def test_rejects_underfilled_short_title_split_layout(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        source = image.parent / "source-preview.png"
        Image.new("RGB", (320, 180), (80, 140, 210)).save(source, format="PNG")

        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload.update(
            {
                "layout": "source-image",
                "source_image": str(source),
                "source_render_mode": "fit-media",
            }
        )
        payload["design"].update(
            {
                "composition": "asymmetric-split",
                "layout_strategy": "asymmetric-split",
                "layout_basis": {
                    "title_units": 4,
                    "title_length_class": "short",
                    "source_kind": "project-image",
                    "source_aspect_ratio": 1.778,
                    "metric_count": 1,
                    "reason": "错误复用了长标题分栏",
                },
                "fullness": {
                    "source_coverage": 0.48,
                    "occupied_ratio": 0.51,
                    "title_line_count": 1,
                    "support_line_count": 0,
                    "keyword_line_count": 1,
                    "metric_count": 1,
                },
                "overlay_mode": "localized-fade",
            }
        )
        metadata.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "project-image", "source_path": str(source), "source_name": "项目图片.png"},
                    "summary": {"file_count": 1, "extension_counts": {".png": 1}},
                    "items": [{"type": "file", "name": "项目图片.png", "extension": ".png"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("饱满度不足" in issue for issue in report.issues))
        self.assertTrue(any("短标题仍在使用长标题分栏" in issue for issue in report.issues))

    def test_rejects_large_text_only_course_without_real_content_spine(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "no-project-media", "source_path": None},
                    "summary": {"file_count": 19, "extension_counts": {".mp4": 19}},
                    "top_level": [
                        {"name": "01 先导课程.mp4"},
                        {"name": "02 核心方法.mp4"},
                        {"name": "03 实战答疑.mp4"},
                    ],
                    "items": [
                        {"type": "file", "name": "01 先导课程.mp4"},
                        {"type": "file", "name": "02 核心方法.mp4"},
                        {"type": "file", "name": "03 实战答疑.mp4"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("真实课程脉络" in issue for issue in report.issues))

    def test_rejects_preview_failure_instead_of_treating_it_as_no_media(self):
        temp_dir, image, caption, metadata, details = self._fixture()
        self.addCleanup(temp_dir.cleanup)
        details.write_text(
            json.dumps(
                {
                    "media_policy_version": 6,
                    "media": {"kind": "media-preview-required", "source_path": None},
                    "summary": {"file_count": 19, "extension_counts": {".mp4": 19}},
                    "items": [{"type": "file", "name": "课程.mp4", "extension": ".mp4"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = inspect_telegram_outputs(
            image_path=image,
            caption_path=caption,
            asset_metadata_path=metadata,
            details_path=details,
            title="示例课程",
            link="https://pan.quark.cn/s/example",
        )

        self.assertFalse(report.passed)
        self.assertTrue(any("发布阻断项" in issue for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
