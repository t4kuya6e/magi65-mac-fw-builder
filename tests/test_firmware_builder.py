import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from magi65_fw_builder import firmware as fw

def make_body(n_chunks):
    return (bytes(range(256)) * ((n_chunks * 16) // 256 + 1))[:n_chunks * 16]

class BuilderTest(unittest.TestCase):
    def test_crc16_known_vectors(self):
        # OTA_PROTOCOL.md §8: index0 の addr(0000)+data(16) 18バイトに対する CRC16
        self.assertEqual(fw.crc16(bytes.fromhex("000025a0000000005d020000000000000000")), 0xCC80)
        # index1 の addr(0100)+data(16)
        self.assertEqual(fw.crc16(bytes.fromhex("0100000000000000000074f6010000000000")), 0x11B1)

    def test_data_packet_structure(self):
        body = make_body(3)
        pkt = fw.data_packet(body, 1)
        self.assertEqual(len(pkt), 20)
        self.assertEqual(pkt[0] | (pkt[1] << 8), 1)               # addr = index (LE)
        self.assertEqual(pkt[2:18], body[16:32])                  # data
        self.assertEqual(pkt[18] | (pkt[19] << 8), fw.crc16(pkt[:18]))  # crc

    def test_data_packet_known_vectors(self):
        body = bytes.fromhex("25a0000000005d020000000000000000"
                             "000000000000000074f6010000000000")  # index0,1 の32バイト
        self.assertEqual(fw.data_packet(body, 0),
                         bytes.fromhex("000025a0000000005d02000000000000000080cc"))
        self.assertEqual(fw.data_packet(body, 1),
                         bytes.fromhex("0100000000000000000074f6010000000000b111"))

    def test_source_bin_size_and_extract(self):
        size = 100
        code = bytearray(256 + size)
        code[48:52] = size.to_bytes(4, "big")            # BE サイズフィールド
        for i in range(size):
            code[256 + i] = i & 0xFF
        self.assertEqual(fw.source_bin_size(bytes(code)), size)
        body = fw.extract_firmware(bytes(code))
        self.assertEqual(len(body), size + ((-size) % 16))   # 16B境界パディング
        self.assertEqual(body[:size], bytes(code[256:256 + size]))
        self.assertEqual(body[size:], b"\xff" * ((-size) % 16))  # 末尾は 0xFF パディング

    def test_start_report(self):
        r = fw.start_report(64)
        self.assertEqual(r[:6], bytes.fromhex("050202000 1ff".replace(" ", "")))
        self.assertEqual(r[6:], b"\xff" * 58)

    def test_end_report(self):
        self.assertEqual(fw.end_report(8040, 64)[:10], bytes.fromhex("0502060002ff671f99e0"))

    def test_data_report_three_packets(self):
        rep, count = fw.data_report(make_body(6), 0, 64)
        self.assertEqual(count, 3)
        self.assertEqual(len(rep), 64)
        self.assertEqual(rep[:4], bytes.fromhex("05023c00"))

    def test_version_query_form(self):
        r = fw.version_query_report(64)
        self.assertEqual(r[:4], bytes.fromhex("05010000"))
        self.assertEqual(r[4:32], b"\xff" * 28)
        self.assertEqual(r[32:], b"\x00" * 32)

    def test_flash_report_len_ok(self):
        self.assertTrue(fw.flash_report_len_ok(64, 64))
        self.assertFalse(fw.flash_report_len_ok(65, 64))
        self.assertFalse(fw.flash_report_len_ok(64, None))
        self.assertFalse(fw.flash_report_len_ok(64, 0))

if __name__ == "__main__":
    unittest.main()
