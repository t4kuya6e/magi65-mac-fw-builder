import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from magi65_fw_builder import firmware as fw

def make_body(n_chunks):
    return (bytes(range(256)) * ((n_chunks * 16) // 256 + 1))[:n_chunks * 16]

class BuilderTest(unittest.TestCase):
    def test_crc16_self_consistent(self):
        self.assertEqual(fw.crc16(b"\x00\x00" + b"\x00" * 16), fw.crc16(bytes(18)))

    def test_data_packet_structure(self):
        body = make_body(3)
        pkt = fw.data_packet(body, 1)
        self.assertEqual(len(pkt), 20)
        self.assertEqual(pkt[0] | (pkt[1] << 8), 1)               # addr = index (LE)
        self.assertEqual(pkt[2:18], body[16:32])                  # data
        self.assertEqual(pkt[18] | (pkt[19] << 8), fw.crc16(pkt[:18]))  # crc

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
