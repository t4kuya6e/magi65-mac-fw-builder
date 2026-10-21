"""Magi65 固定識別値とレポート定数（spec Global Constraints）。"""
VID = 0x320F
PID = 0x5055
USAGE_PAGE = 0xFFEF
REPORT_ID = 0x05
MAGI65_TUPLE = (VID, PID, USAGE_PAGE, REPORT_ID)

# 公式 updater のファイル名（MG65-<型番>-V<版>-<日付>.exe）で、Magi65 ANSI（CSF6C4）への書き込みを許す型番と版。
# None は全版を許す。CSF6C4 は自機種。CS0164 は別型番の流用で、確認したのは V0121 のみ
# （配列・ディスクリプタが CSF6C4 と同一であることを解析で確かめ、CSF6C4 実機に書き込んだ。2026-10-21）。
VERIFIED_MODELS = {"CSF6C4": None, "CS0164": {"0121"}}

HEADER_LEN = 256          # code_2M ヘッダ長。本体は offset 256 以降
CHUNK = 16                # 1チャンク=16バイト
MAX_PKTS_PER_REPORT = 3   # 1レポート最大3パケット
MIN_REPORT_LEN = 64       # spec: 出力/入力とも最低 64
