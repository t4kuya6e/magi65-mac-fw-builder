"""Magi65 固定識別値とレポート定数（spec Global Constraints）。"""
VID = 0x320F
PID = 0x5055
USAGE_PAGE = 0xFFEF
REPORT_ID = 0x05
MAGI65_TUPLE = (VID, PID, USAGE_PAGE, REPORT_ID)

HEADER_LEN = 256          # code_2M ヘッダ長。本体は offset 256 以降
CHUNK = 16                # 1チャンク=16バイト
MAX_PKTS_PER_REPORT = 3   # 1レポート最大3パケット
MIN_REPORT_LEN = 64       # spec: 出力/入力とも最低 64
