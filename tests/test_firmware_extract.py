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
    #
    # 例外の型だけでなくメッセージ部分文字列でも判別することで、パーサが壊れて別理由の
    # ValueError（例: 「抽出できない」）にすり替わっても検出できるようにする。
    def test_reject_duplicate_and_wrong_type(self):
        from tests.helpers import make_resources  # 実装時に用意する合成ヘルパ
        dup = make_resources([("code_2M", 0x20, b"\x00" * 2097152),
                              ("code_2M", 0x20, b"\x00" * 2097152),
                              ("param_128K", 0x20, b"\x00" * 131072)])
        with self.assertRaisesRegex(ValueError, "一意でない"):
            fw.extract_from_exe(self._tmp("dup.exe", b"MZ" + dup))
        wrongtype = make_resources([("code_2M", 0x01, b"\x00" * 2097152),
                                    ("param_128K", 0x20, b"\x00" * 131072)])
        with self.assertRaisesRegex(ValueError, "型/長さ"):
            fw.extract_from_exe(self._tmp("wt.exe", b"MZ" + wrongtype))

    def test_roundtrip_extract_from_synthetic(self):
        # 実機 exe が無くても、合成 .resources ラウンドトリップでパーサ成功パスを守る。
        # ここが壊れれば（例: _read_resource_manager のオフセット計算ミス）検出できる。
        from tests.helpers import make_resources
        res = make_resources([("code_2M", 0x20, b"\xAB" * 2097152),
                              ("param_128K", 0x20, b"\xCD" * 131072)])
        got = fw.extract_from_exe(self._tmp("ok.exe", b"MZ" + res))
        self.assertEqual(got["code_2m"], b"\xAB" * 2097152)
        self.assertEqual(got["param_128k"], b"\xCD" * 131072)

    def test_zip_single_exe_ignores_appledouble(self):
        # macOS 由来の __MACOSX/._<name>.exe ゴーストエントリを無視し、
        # 実体の .exe 1個として抽出できることを確認する（Critical#1 の回帰防止）。
        from tests.helpers import make_resources
        res = make_resources([("code_2M", 0x20, b"\xAB" * 2097152),
                              ("param_128K", 0x20, b"\xCD" * 131072)])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("__MACOSX/._x.exe", b"junk")   # ゴースト（無視されるべき）
            z.writestr("x.exe", b"MZ" + res)
        got = fw.extract_from_exe(self._tmp("ok.zip", buf.getvalue()))
        self.assertEqual(len(got["code_2m"]), 2097152)

def _mk(size, tail_crc=b"\x01\x02\x03\x04", total=None):
    total = total or (C.HEADER_LEN + max(size, 4) + 16)
    b = bytearray(total)
    b[0:48] = b"\x56" * 48
    b[48:52] = size.to_bytes(4, "big")
    if size >= 4:
        b[C.HEADER_LEN + size - 4:C.HEADER_LEN + size] = tail_crc
    return bytes(b)

class ValidateTest(unittest.TestCase):
    def test_rejects_size_lt4(self):
        self.assertRaises(ValueError, fw.validate_firmware, _mk(2))

    def test_rejects_truncated(self):
        self.assertRaises(ValueError, fw.validate_firmware, _mk(128628, total=C.HEADER_LEN + 100))

    def test_rejects_bincrc_zero(self):
        self.assertRaises(ValueError, fw.validate_firmware, _mk(64, tail_crc=b"\x00\x00\x00\x00"))

    def test_rejects_bincrc_ffff(self):
        self.assertRaises(ValueError, fw.validate_firmware, _mk(64, tail_crc=b"\xff\xff\xff\xff"))

    def test_rejects_over_16bit(self):
        self.assertRaises(ValueError, fw.validate_firmware, _mk(0x110000))

    def test_identity_mismatch(self):
        self.assertRaises(ValueError, fw.validate_identity,
                          {"vid": 0x1234, "pid": 0x5055, "usage_page": 0xFFEF, "report_id": 5})

    def test_header_filler_ok(self):
        self.assertTrue(fw.header_filler_ok(_mk(64)))
        bad = bytearray(_mk(64)); bad[0] = 0x00
        self.assertFalse(fw.header_filler_ok(bytes(bad)))

if __name__ == "__main__":
    unittest.main()
