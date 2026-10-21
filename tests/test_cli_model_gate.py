import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import magi65_ota as cli


class ModelGateWiringTest(unittest.TestCase):
    """型番の拒否は --flash だけに掛かり、デバイスに触れる前に止まる。"""

    def setUp(self):
        self.exe = os.path.join(tempfile.mkdtemp(), "firmware.exe")  # 型番を読めない名前
        with open(self.exe, "wb") as f:
            f.write(b"MZ")
        patches = {
            "load_and_validate": mock.patch.object(cli, "load_and_validate", return_value=(b"", 0)),
            "do_flash": mock.patch.object(cli, "do_flash", return_value=0),
            "do_check": mock.patch.object(cli, "do_check", return_value=0),
            "dry_run": mock.patch.object(cli, "dry_run", return_value=0),
        }
        self.m = {k: p.start() for k, p in patches.items()}
        self.addCleanup(mock.patch.stopall)

    def test_flash_rejected_before_device(self):
        self.assertEqual(cli.main(["--exe", self.exe, "--flash", "--i-understand-brick-risk"]), 2)
        self.m["do_flash"].assert_not_called()

    def test_flash_override_proceeds(self):
        cli.main(["--exe", self.exe, "--flash", "--i-understand-brick-risk", "--allow-unverified-model"])
        self.m["do_flash"].assert_called_once()

    def test_dry_run_and_check_not_gated(self):
        self.assertEqual(cli.main(["--exe", self.exe]), 0)
        self.assertEqual(cli.main(["--exe", self.exe, "--check"]), 0)


if __name__ == "__main__":
    unittest.main()
