import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from magi65_fw_builder import transfer as T
from magi65_fw_builder import firmware as fw

def make_body(n_chunks):
    return bytes((i * 7 + 3) & 0xFF for i in range(n_chunks * 16))

def classify(r):
    if r[0] == 5 and r[1] == 1:
        return "VERSION"
    if r[:6] == bytes.fromhex("050202000 1ff".replace(" ", "")):
        return "START"
    if r[:6] == bytes.fromhex("0502060002ff"):
        return "END"
    if r[1] == 0x02 and r[2] in (20, 40, 60):
        return "DATA"
    return "?"

class FakeDevice:
    def __init__(self, bad_version=False, fail_at=None,
                 wrong_version_rid=False, wrong_end_rid=False):
        self.bad_version = bad_version; self.fail_at = fail_at
        self.wrong_version_rid = wrong_version_rid; self.wrong_end_rid = wrong_end_rid
        self.sent = []; self.addrs = []; self.packets = []; self._n = 0
    def send_and_wait(self, report):
        self._n += 1
        k = classify(report); self.sent.append(k)
        if k == "VERSION":
            if self.bad_version:
                return None
            # report_id 込みの完全な固定ヘッダ 05 01 08 00 <ver4> <crc4>
            rid = 0x99 if self.wrong_version_rid else 5
            return (rid, bytes.fromhex("0501080000000000a40f0201") + b"\x00" * 52)
        if k == "DATA":
            cnt = report[2] // 20
            for j in range(cnt):
                base = 4 + j * 20
                pkt = bytes(report[base:base + 20])
                self.packets.append(pkt)                       # 20B パケット全体を記録
                self.addrs.append(pkt[0] | (pkt[1] << 8))
        if self._n == self.fail_at:
            return (5, b"\x05" + b"\x00" * 63)  # エコー不一致（全長だが内容違い）
        if k == "END":
            rid = 0x99 if self.wrong_end_rid else 5
            return (rid, bytes.fromhex("0502030006ff00") + b"\x00" * 57)
        return (5, bytes(report))       # 正常 ACK = 送信レポート全体のエコー

class ParseVersionTest(unittest.TestCase):
    def test_embedded_form_valid(self):
        # report_id 込み: 05 01 08 00 <ver4LE> <crc4LE>
        ver, crc = 1234, 5678
        data = bytes([0x05, 0x01, 0x08, 0x00]) + ver.to_bytes(4, "little") + crc.to_bytes(4, "little")
        self.assertEqual(T.parse_version(data), (ver, crc))

    def test_stripped_form_valid(self):
        # report_id 剥がし: 01 08 00 <ver4LE> <crc4LE>
        ver, crc = 1234, 5678
        data = bytes([0x01, 0x08, 0x00]) + ver.to_bytes(4, "little") + crc.to_bytes(4, "little")
        self.assertEqual(T.parse_version(data), (ver, crc))

    def test_broken_fixed_byte_returns_none(self):
        # index3 が 0x00 でない（embedded 判定も stripped 判定も外れる）
        ver, crc = 1234, 5678
        data = bytes([0x05, 0x01, 0x08, 0x01]) + ver.to_bytes(4, "little") + crc.to_bytes(4, "little")
        self.assertIsNone(T.parse_version(data))

    def test_too_short_returns_none(self):
        data = bytes([0x05, 0x01, 0x08, 0x00, 0x01, 0x02, 0x03])
        self.assertIsNone(T.parse_version(data))

    def test_unrelated_bytes_returns_none(self):
        data = bytes(range(20))
        self.assertIsNone(T.parse_version(data))


class ParseCompletionTest(unittest.TestCase):
    def test_embedded_form_valid(self):
        # report_id 込み: 05 02 03 00 06 FF <result>
        data = bytes([0x05, 0x02, 0x03, 0x00, 0x06, 0xFF, 0x07])
        self.assertEqual(T.parse_completion(data), 7)

    def test_stripped_form_valid(self):
        # report_id 剥がし: 02 03 00 06 FF <result>
        data = bytes([0x02, 0x03, 0x00, 0x06, 0xFF, 0x07])
        self.assertEqual(T.parse_completion(data), 7)

    def test_broken_fixed_byte_returns_none(self):
        # index4 が 0x06 でない（embedded 判定も stripped 判定も外れる）
        data = bytes([0x05, 0x02, 0x03, 0x00, 0x07, 0xFF, 0x07])
        self.assertIsNone(T.parse_completion(data))

    def test_too_short_returns_none(self):
        data = bytes([0x05, 0x02, 0x03])
        self.assertIsNone(T.parse_completion(data))


class TransferTest(unittest.TestCase):
    def test_normal_flow(self):
        dev = FakeDevice()
        rc = T.run_transfer(dev, make_body(9), 64, log=lambda *a: None)
        self.assertEqual(rc, 0)
        self.assertEqual(dev.sent[0], "VERSION")
        self.assertEqual(dev.sent[1], "START")
        self.assertEqual(dev.sent.count("END"), 1)
        self.assertEqual(dev.addrs, list(range(9)))

    def test_bad_version_aborts_before_start(self):
        dev = FakeDevice(bad_version=True)
        rc = T.run_transfer(dev, make_body(9), 64, log=lambda *a: None)
        self.assertNotEqual(rc, 0)
        self.assertNotIn("START", dev.sent)

    def test_ack_echo_mismatch_aborts(self):
        dev = FakeDevice(fail_at=3)  # VERSION,START の後の DATA でエコー不一致
        rc = T.run_transfer(dev, make_body(9), 64, log=lambda *a: None)
        self.assertNotEqual(rc, 0)

    def test_truncated_ack_rejected(self):
        # 全長未満の切り詰め ACK は不合格（レビュー指摘 High#1）
        s = b"\x05\x02\x02\x00\x01\xff" + b"\xff" * 58
        self.assertFalse(T.ack_is_echo(s, (5, b"\x05\x02\x02\x00")))

    def test_wrong_rid_ack_rejected(self):
        # rid が 5 以外の ACK は内容が一致しても不合格（レビュー指摘 3巡#Medium2）
        s = b"\x05\x02\x02\x00\x01\xff" + b"\xff" * 58
        self.assertFalse(T.ack_is_echo(s, (0x99, s)))

    def test_wrong_version_rid_aborts_before_start(self):
        # バージョン応答の rid が 5 以外だと START を送らず中止する
        dev = FakeDevice(wrong_version_rid=True)
        rc = T.run_transfer(dev, make_body(9), 64, log=lambda *a: None)
        self.assertEqual(rc, 20)
        self.assertNotIn("START", dev.sent)

    def test_wrong_end_rid_aborts(self):
        # END 応答の rid が 5 以外だと該当エラーコードで中止する
        dev = FakeDevice(wrong_end_rid=True)
        rc = T.run_transfer(dev, make_body(9), 64, log=lambda *a: None)
        self.assertEqual(rc, 15)

    def test_unpadded_body_raises_before_any_send(self):
        # 16 の倍数でない body は ValueError で、デバイスには何も送信しない
        dev = FakeDevice()
        body = make_body(9) + b"\x00"  # 9*16+1 バイト
        with self.assertRaises(ValueError):
            T.run_transfer(dev, body, 64, log=lambda *a: None)
        self.assertEqual(dev.sent, [])

    def test_full_coverage_8040(self):
        body = make_body(8040)
        dev = FakeDevice()
        rc = T.run_transfer(dev, body, 64, log=lambda *a: None)
        self.assertEqual(rc, 0)
        self.assertEqual(dev.sent.count("DATA"), 2680)
        # addr だけでなく全 8040 パケットの data/CRC まで照合（レビュー指摘 3巡#Medium3）
        self.assertEqual(len(dev.packets), 8040)
        for i, pkt in enumerate(dev.packets):
            self.assertEqual(pkt, fw.data_packet(body, i))

if __name__ == "__main__":
    unittest.main()
