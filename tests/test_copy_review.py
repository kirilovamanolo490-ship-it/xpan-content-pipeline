import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from xpan_auto.copy_review import (
    CopyReviewError,
    record_review,
    validate_review,
    validate_review_batch,
)


class CopyReviewTests(unittest.TestCase):
    description = "介绍商品上架、客户引流与实际成交的课程"

    def _asset(self, root: Path) -> Path:
        asset = root / "0001"
        asset.mkdir()
        link = "https://pan.quark.cn/s/example"
        details = {
            "row_index": 1,
            "title": "闲鱼虚拟资源变现",
            "source_share_link": link,
            "summary": {"file_count": 2, "truncated": False},
            "items": [
                {"type": "file", "name": "01如何发布商品.mp4", "path": "项目/01如何发布商品.mp4"},
                {"type": "file", "name": "02微信引流.mp4", "path": "项目/02微信引流.mp4"},
            ],
        }
        (asset / "telegram-project-details.json").write_text(
            json.dumps(details, ensure_ascii=False), encoding="utf-8"
        )
        (asset / "telegram-caption.html").write_text(
            "闲鱼虚拟资源变现\n\n卖虚拟资源，收入来自商品成交。先看上架流程，再看客户怎么来。"
            f"\n\n🔗 {link}\n\n#闲鱼 #虚拟资源\n\n"
            '𝕏 <a href="https://example.invalid/x/profile">X</a>  '
            '📣<a href="https://example.invalid/telegram/channel">频道</a>',
            encoding="utf-8",
        )
        (asset / "x.txt").write_text(
            "闲鱼卖虚拟资源，钱从哪来？商品上架成交是第一步，微信承接后续客户。"
            f"\n\n{link}", encoding="utf-8"
        )
        return asset

    def _record(self, asset: Path):
        return record_review(
            asset,
            category="commercial",
            style_label="疑问／观点型",
            primary_angle="讲清虚拟资源上架与成交路径",
            key_phrase="虚拟资源",
            description=self.description,
            source_note="简介与目录都有商品上架和客户引流，收入来自实际成交。",
            source_evidence=["01如何发布商品.mp4", "02微信引流.mp4"],
            offer="虚拟资源", audience="闲鱼买家", revenue="商品成交", support="supported",
        )

    def test_record_and_validate_source_backed_commercial_copy(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            self._record(asset)
            checked = validate_review(
                asset, serial=1, title="闲鱼虚拟资源变现",
                description=self.description,
                link="https://pan.quark.cn/s/example",
            )
            self.assertEqual(checked["style_label"], "疑问／观点型")
            self.assertEqual(checked["layout"], "blocks-1")

    def test_x_link_must_be_the_only_standalone_final_line_after_a_blank_line(self):
        link = "https://pan.quark.cn/s/example"
        invalid_copies = (
            f"闲鱼卖虚拟资源，钱从哪来？商品上架成交是第一步，微信承接后续客户。{link}",
            f"闲鱼卖虚拟资源，钱从哪来？商品上架成交是第一步，微信承接后续客户。\n\n{link}\n链接在这里",
            f"闲鱼卖虚拟资源，钱从哪来？商品上架成交是第一步，微信承接后续客户。\n\n链接：{link}",
        )
        for copy in invalid_copies:
            with self.subTest(copy=copy), TemporaryDirectory() as temp:
                asset = self._asset(Path(temp))
                (asset / "x.txt").write_text(copy, encoding="utf-8")
                with self.assertRaisesRegex(CopyReviewError, "末行"):
                    self._record(asset)

        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            self._record(asset)

    def test_edit_after_review_blocks_publish(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            self._record(asset)
            (asset / "x.txt").write_text(
                (asset / "x.txt").read_text(encoding="utf-8") + "\n再加一句", encoding="utf-8"
            )
            with self.assertRaisesRegex(CopyReviewError, "发生变化"):
                validate_review(
                    asset, serial=1, title="闲鱼虚拟资源变现",
                    description=self.description,
                    link="https://pan.quark.cn/s/example",
                )

    def test_description_change_blocks_publish(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            self._record(asset)
            with self.assertRaisesRegex(CopyReviewError, "项目介绍"):
                validate_review(
                    asset, serial=1, title="闲鱼虚拟资源变现",
                    description="简介后来改了", link="https://pan.quark.cn/s/example",
                )

    def test_generic_shared_phrase_is_not_a_project_key_point(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            for name in ("telegram-caption.html", "x.txt"):
                path = asset / name
                path.write_text(path.read_text(encoding="utf-8") + "\n资料", encoding="utf-8")
            with self.assertRaisesRegex(CopyReviewError, "项目关键点"):
                record_review(
                    asset, category="commercial", style_label="疑问／观点型",
                    primary_angle="讲清虚拟资源上架与成交路径", key_phrase="资料",
                    description=self.description,
                    source_note="简介与目录都有商品上架和客户引流，收入来自实际成交。",
                    source_evidence=["01如何发布商品.mp4"], offer="虚拟资源",
                    audience="闲鱼买家", revenue="商品成交", support="supported",
                )

    def test_old_template_cannot_be_approved(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            x_path = asset / "x.txt"
            x_path.write_text(
                "🔥 闲鱼虚拟资源变现｜这份真的值得认真看\n\n"
                "https://pan.quark.cn/s/example\n\n#学习资料 #资源分享 #实战教程 #技能提升",
                encoding="utf-8",
            )
            with self.assertRaises(CopyReviewError):
                self._record(asset)
            self.assertFalse((asset / "copy-review.json").exists())

    def test_unreviewed_seed_marker_cannot_be_approved(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            x_path = asset / "x.txt"
            x_path.write_text("【待审初稿】\n" + x_path.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(CopyReviewError, "旧模板套话"):
                self._record(asset)

    def test_commercial_title_requires_route_review(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            with self.assertRaisesRegex(CopyReviewError, "商业路径"):
                record_review(
                    asset,
                    category="tool", style_label="工具流水线型",
                    primary_angle="从商品上架到客户成交",
                    key_phrase="虚拟资源", description=self.description,
                    source_note="目录有上架和引流两节，商业路径仍需核对。",
                    source_evidence=["01如何发布商品.mp4"],
                )

    def test_directory_monetization_signal_requires_commercial_review(self):
        with TemporaryDirectory() as temp:
            asset = self._asset(Path(temp))
            details_path = asset / "telegram-project-details.json"
            details = json.loads(details_path.read_text(encoding="utf-8"))
            details["title"] = "闲鱼运营教程"
            details["items"][0]["name"] = "01如何赚钱.mp4"
            details["items"][0]["path"] = "项目/01如何赚钱.mp4"
            details_path.write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")
            caption_path = asset / "telegram-caption.html"
            caption_path.write_text(caption_path.read_text(encoding="utf-8").replace("闲鱼虚拟资源变现", "闲鱼运营教程"), encoding="utf-8")
            with self.assertRaisesRegex(CopyReviewError, "商业路径"):
                record_review(
                    asset, category="course", style_label="疑问／观点型",
                    primary_angle="拆解闲鱼店铺的内容运营步骤", key_phrase="虚拟资源",
                    description="闲鱼运营基础教程", source_note="目录出现如何赚钱的章节，需要继续核对收入路径。",
                    source_evidence=["01如何赚钱.mp4"],
                )

    def test_eight_item_batch_requires_style_and_layout_variety(self):
        reviews = [
            {"style_label": f"style-{i}", "opening": f"opening-{i}", "layout": f"blocks-{i % 3}"}
            for i in range(8)
        ]
        validate_review_batch(reviews)
        reviews[-1]["layout"] = "blocks-0"
        for review in reviews:
            review["layout"] = "blocks-1"
        with self.assertRaisesRegex(CopyReviewError, "三种版式"):
            validate_review_batch(reviews)

    def test_adjacent_x_openings_must_differ_even_in_short_batch(self):
        with self.assertRaisesRegex(CopyReviewError, "相同开头"):
            validate_review_batch([
                {"style_label": "指定人群型", "opening": "同一个开头", "layout": "blocks-1"},
                {"style_label": "疑问／观点型", "opening": "同一个开头", "layout": "blocks-2"},
            ])


if __name__ == "__main__":
    unittest.main()
