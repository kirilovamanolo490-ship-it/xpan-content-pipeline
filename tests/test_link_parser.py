import unittest

from xpan_auto.link_parser import extract_quark_links


class LinkParserTests(unittest.TestCase):
    def test_extracts_passcode_and_deduplicates_share_subdirectory(self):
        text = (
            "资料一 https://pan.quark.cn/s/abc123 提取码：A1B2\n"
            "重复 https://pan.quark.cn/s/abc123?pwd=A1B2\n"
            "子目录 https://pan.quark.cn/s/abc123#/list/share/fid2 密码 C3D4\n"
        )

        links = extract_quark_links(text)

        self.assertEqual(len(links), 2)
        self.assertEqual(links[0].passcode, "A1B2")
        self.assertTrue(links[1].normalized_url.endswith("#/list/share/fid2"))
        self.assertEqual(links[1].passcode, "C3D4")

    def test_extracts_pwd_query_parameter(self):
        links = extract_quark_links("https://pan.quark.cn/s/xyz789?pwd=QWER")

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].passcode, "QWER")

    def test_does_not_attach_adjacent_other_provider_password(self):
        text = (
            "夸克 https://pan.quark.cn/s/abc123\n"
            "百度 https://pan.baidu.com/s/example?pwd=r6x8"
        )

        links = extract_quark_links(text)

        self.assertEqual(len(links), 1)
        self.assertIsNone(links[0].passcode)
