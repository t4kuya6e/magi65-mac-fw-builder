import os, sys, io, zipfile, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from magi65_fw_builder import firmware as fw
from magi65_fw_builder import constants as C

EXE = os.environ.get("MAGI65_TEST_EXE")
HAS_EXE = bool(EXE and os.path.exists(EXE))

class ExtractRealTest(unittest.TestCase):
    @unittest.skipUnless(HAS_EXE, "MAGI65_TEST_EXE 未設定")
    def test_extract_code_and_param(self):
        res = fw.extract_from_exe(EXE)
        self.assertEqual(fw.source_bin_size(res["code_2m"]), 128628)
        body = fw.extract_firmware(res["code_2m"])
        self.assertEqual(int.from_bytes(body[128628 - 4:128628], "little"), 0x01020FA4)

    @unittest.skipUnless(HAS_EXE, "MAGI65_TEST_EXE 未設定")
    def test_param_matches_magi65(self):
        p = fw.parse_param(fw.extract_from_exe(EXE)["param_128k"])
        self.assertEqual((p["vid"], p["pid"], p["usage_page"], p["report_id"]), C.MAGI65_TUPLE)

class ExtractRejectTest(unittest.TestCase):
    def _tmp(self, name, data):
        d = tempfile.mkdtemp()
        path = os.path.join(d, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_reject_non_resource_bytes(self):
        # リソース無し
        with self.assertRaises(Exception):
            fw.extract_from_exe(self._tmp("x.exe", b"MZ" + b"\x00" * 1000))

    def test_reject_zip_multiple_exe(self):
        # ZIP 内に EXE が2個 → 拒否（レビュー指摘 Medium#7）
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.exe", b"MZ")
            z.writestr("b.exe", b"MZ")
        with self.assertRaises(Exception):
            fw.extract_from_exe(self._tmp("m.zip", buf.getvalue()))

    # 注: 「同名 code_2M/param_128K が複数」「正しい名前・長さだが非 ByteArray 型」の
    # 拒否は、_read_resource_manager を使った合成 .resources を組み立てて検証する。
    # 実装時に、既知の 1 リソース分のバイト列を生成するヘルパ（下記 make_resources）を用意し、
    # 同名2エントリ／type_code!=0x20 の各ケースで extract_from_exe が raise することを確認する。
    def test_reject_duplicate_and_wrong_type(self):
        from tests.helpers import make_resources  # 実装時に用意する合成ヘルパ
        dup = make_resources([("code_2M", 0x20, b"\x00" * 2097152),
                              ("code_2M", 0x20, b"\x00" * 2097152),
                              ("param_128K", 0x20, b"\x00" * 131072)])
        with self.assertRaises(Exception):
            fw.extract_from_exe(self._tmp("dup.exe", b"MZ" + dup))
        wrongtype = make_resources([("code_2M", 0x01, b"\x00" * 2097152),
                                    ("param_128K", 0x20, b"\x00" * 131072)])
        with self.assertRaises(Exception):
            fw.extract_from_exe(self._tmp("wt.exe", b"MZ" + wrongtype))

if __name__ == "__main__":
    unittest.main()
