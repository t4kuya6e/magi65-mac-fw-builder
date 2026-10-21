"""転送制御（transfer control flow）。
Task 5: START/DATA/END の送受信と ACK 検証、バージョン照会ゲート。
"""
from .constants import REPORT_ID, CHUNK
from .firmware import (start_report, data_report, end_report, version_query_report,
                       data_payload_ranges)

def parse_version(data):
    # 完全な固定ヘッダを要求（レビュー指摘 High#5）。report_id 込み: 05 01 08 00 <ver4> <crc4>
    if len(data) >= 12 and data[0] == 0x05 and data[1] == 0x01 and data[2] == 0x08 and data[3] == 0x00:
        return int.from_bytes(data[4:8], "little"), int.from_bytes(data[8:12], "little")
    # report_id 剥がし: 01 08 00 <ver4> <crc4>
    if len(data) >= 11 and data[0] == 0x01 and data[1] == 0x08 and data[2] == 0x00:
        return int.from_bytes(data[3:7], "little"), int.from_bytes(data[7:11], "little")
    return None

def parse_completion(data):
    # 確定形式の固定バイトをすべて検証（レビュー指摘 High#4）: 05 02 03 00 06 FF <result>
    if len(data) >= 7 and data[0] == 0x05 and data[1] == 0x02 and data[2] == 0x03 \
            and data[3] == 0x00 and data[4] == 0x06 and data[5] == 0xFF:
        return data[6]
    # report_id 剥がし: 02 03 00 06 FF <result>
    if len(data) >= 6 and data[0] == 0x02 and data[1] == 0x03 \
            and data[2] == 0x00 and data[3] == 0x06 and data[4] == 0xFF:
        return data[5]
    return None

def ack_is_echo(sent: bytes, resp, maskable_ranges=()) -> bool:
    # ACK は送信レポート全体のエコー（OTA_PROTOCOL.md §6.2）。
    # rid==5（レビュー指摘 Medium2, END/version-gate と対称）、送信全長が一致（レビュー指摘 High#1）を要求。
    # maskable_ranges（DATA のデータ部）に限り、デバイスが 0xFF を返すことを許容する。
    # OTA 完走までブートマジックを未書き込み（0xFF）のまま保持する挙動への対応
    # （V0120 以降の実機挙動。OTA_PROTOCOL.md §6.2 と §9 を参照）。
    # フレームヘッダ・パケット index・パケット CRC は厳密照合を維持し、
    # 古い応答・重複レポート・順序ずれは従来どおり検出する。
    if resp is None:
        return False
    rid, data = resp
    if rid != REPORT_ID or len(data) < len(sent):
        return False
    for i in range(len(sent)):
        if data[i] == sent[i]:
            continue
        if data[i] == 0xFF and any(s <= i < e for s, e in maskable_ranges):
            continue
        return False
    return True

def masked_offsets(sent: bytes, resp, maskable_ranges=()) -> list:
    """ACK のうち maskable_ranges 内で 0xFF に置換されて返った offset を返す。

    ack_is_echo が許容した差分を可視化するためのもの。緩和が想定どおり
    ブートマジックだけに効いているかを操作者が確認できるようにする。
    """
    if resp is None:
        return []
    _rid, data = resp
    return [i for i in range(min(len(sent), len(data)))
            if data[i] != sent[i] and data[i] == 0xFF
            and any(s <= i < e for s, e in maskable_ranges)]

def run_transfer(dev, body, report_len, log=print):
    if len(body) % CHUNK != 0:
        # 16 の倍数でない body は末尾を無警告で切り捨てると書込不足が成功扱いになる。
        # デバイスに一切送信する前に中止する。
        raise ValueError(f"body length {len(body)} is not a multiple of CHUNK({CHUNK})")
    n_chunks = len(body) // CHUNK
    # ReportID 能力の実地確認（spec High#1 残）: START 前にバージョン照会往復。
    # rid==5 かつ完全な固定ヘッダの応答のみ合格（レビュー指摘 High#5）。
    vq = version_query_report(report_len)
    vresp = dev.send_and_wait(vq)
    if not vresp or vresp[0] != REPORT_ID or parse_version(vresp[1]) is None:
        log("[FAIL] START 前バージョン照会に失敗。正常な report_id=5 応答なし。中止。")
        return 20
    log("[*] START 送信")
    s = start_report(report_len)
    if not ack_is_echo(s, dev.send_and_wait(s)):
        log("[FAIL] START の ACK がエコー不一致。中止。")
        return 10
    idx = 0
    n_masked = 0
    while idx < n_chunks:
        rep, count = data_report(body, idx, report_len)
        ranges = data_payload_ranges(count)
        resp = dev.send_and_wait(rep)
        if not ack_is_echo(rep, resp, ranges):
            log(f"[FAIL] DATA idx={idx} の ACK がエコー不一致。中止。")
            return 11
        masked = masked_offsets(rep, resp, ranges)
        if masked:
            if n_masked == 0:
                spots = ", ".join(
                    f"offset={o}(body[{(idx + (o - 6) // 20) * CHUNK + (o - 6) % 20}])"
                    for o in masked)
                log(f"[*] ACK マスク検出（デバイスが 0xFF を返した）: DATA idx={idx} {spots}")
            n_masked += len(masked)
        idx += count
        if idx % 300 == 0 or idx >= n_chunks:
            log(f"    {idx}/{n_chunks} チャンク送信")
    if n_masked:
        log(f"[*] ACK マスクは合計 {n_masked} バイト。想定はブートマジック 1 バイトのみ。")
    log("[*] END 送信")
    resp = dev.send_and_wait(end_report(n_chunks, report_len))
    if not resp:
        log("[FAIL] END 応答なし。")
        return 12
    if resp[0] != REPORT_ID:                       # version-gate と対称に rid を検証（レビュー指摘 Medium#3）
        log(f"[FAIL] END 応答の report_id が不正: {resp[0]}")
        return 15
    result = parse_completion(resp[1])
    if result is None:
        log(f"[WARN] 完了応答が想定外: {resp[1][:8].hex(' ')}")
        return 14
    if result == 0:
        log("[PASS] OTA Success")
        return 0
    log(f"[FAIL] OTA Fail code={result}")
    return 13
