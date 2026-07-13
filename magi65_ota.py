#!/usr/bin/env python3
"""Magi65 OTA CLI（spec §4 準拠）。

--exe から抽出・検証を行い、モードに応じて動作する。
デフォルト（フラグなし）はドライラン専用で、実機には一切触れない。
--check / --flash は実機接続が必要（Task 8 で実地検証）。
"""
import argparse
import os
import subprocess
import sys
import time

from magi65_fw_builder import constants as C
from magi65_fw_builder import firmware as fw
from magi65_fw_builder import iokit_hid as hid
from magi65_fw_builder import transfer as T

_NOT_PERMITTED_HEX = "0xE00002E2"
_PERMISSION_HINT = (
    "[HINT] システム設定 > プライバシーとセキュリティ > 入力監視 で"
    "本スクリプトの実行環境（ターミナル/Python）に権限を付与してください。"
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Magi65 OTA CLI")
    p.add_argument("--exe", required=True, help="ファームウェア入り .exe/.exe.zip のパス")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="実機に接続してバージョン照会のみ行う")
    mode.add_argument("--flash", action="store_true", help="実機にファームウェアを書き込む")
    p.add_argument(
        "--i-understand-brick-risk", action="store_true", dest="i_understand_brick_risk",
        help="--flash 実行の前提となる同意フラグ",
    )
    p.add_argument("--report-len", type=int, default=64, dest="report_len")
    p.add_argument("--timeout", type=float, default=2.0)
    return p.parse_args(argv)


def _hex(b):
    return b.hex(" ")


def load_and_validate(exe_path):
    """--exe を抽出・検証し (body, expected_crc) を返す。実機には触れない。

    expected_crc は body[size-4:size] の LE 値（validate_firmware が検証した
    本体末尾CRCと同一の位置）。flash 後の成否照合に使う。
    """
    extracted = fw.extract_from_exe(exe_path)
    code_2m, param_128k = extracted["code_2m"], extracted["param_128k"]
    param = fw.parse_param(param_128k)
    fw.validate_identity(param)
    fw.validate_firmware(code_2m)
    if not fw.header_filler_ok(code_2m):
        print("[WARN] code_2M ヘッダの filler(0x56 x 48) が想定と不一致です。続行します。")
    size = fw.source_bin_size(code_2m)
    body = fw.extract_firmware(code_2m)
    expected_crc = int.from_bytes(body[size - 4:size], "little")
    return body, expected_crc


def dry_run(body, report_len):
    n_chunks = len(body) // C.CHUNK
    start = fw.start_report(report_len)
    end = fw.end_report(n_chunks, report_len)

    idx = 0
    n_data_reports = 0
    first_data = None
    last_data = None
    while idx < n_chunks:
        rep, count = fw.data_report(body, idx, report_len)
        if first_data is None:
            first_data = rep
        last_data = rep
        idx += count
        n_data_reports += 1

    print("[DRY-RUN] デバイスには接続していません。送信予定シーケンスのみ表示します。")
    print(f"[DRY-RUN] body={len(body)}B chunks={n_chunks} DATAレポート数={n_data_reports}")
    print(f"[DRY-RUN] START ({len(start)}B): {_hex(start)}")
    if first_data is not None:
        print(f"[DRY-RUN] DATA#0 ({len(first_data)}B): {_hex(first_data)}")
    if last_data is not None and last_data is not first_data:
        print(f"[DRY-RUN] DATA末 ({len(last_data)}B): {_hex(last_data)}")
    print(f"[DRY-RUN] END ({len(end)}B): {_hex(end)}")
    return 0


def select_unique_device(usage_page):
    candidates = hid.find_ota_devices(usage_page)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        print("[FAIL] OTA対象デバイスが検出されません。")
    else:
        print(f"[FAIL] OTA対象デバイスが{len(candidates)}件検出されました（1件である必要があります）。")
        for c in candidates:
            print(f"    regid={c['regid']} location={c['location']} serial={c['serial']}")
    return None


def verify_connected_identity(dev):
    """open 済みデバイスの実 VID/PID が MAGI65_TUPLE と一致するかを確認する。"""
    vid = dev.vendor_id()
    pid = dev.product_id()
    if vid != C.VID or pid != C.PID:
        raise ValueError(
            f"接続デバイスの VID/PID が不一致: ({vid!r},{pid!r}) != "
            f"(0x{C.VID:04X},0x{C.PID:04X})"
        )


def do_check(args, body):
    cand = select_unique_device(C.USAGE_PAGE)
    if cand is None:
        return 30
    dev = hid.OtaDevice(cand["dev"], timeout=args.timeout)
    try:
        dev.open(args.report_len)
        verify_connected_identity(dev)
        print(
            f"[*] HID report length: max_output_report={dev.max_output_report} "
            f"max_input_report={dev.max_input_report} (指定 --report-len={args.report_len})"
        )
        if not fw.flash_report_len_ok(args.report_len, dev.max_output_report):
            print("[WARN] 出力側 HID レポート長（max_output_report）が --report-len と不一致です。")
        if not fw.flash_report_len_ok(args.report_len, dev.max_input_report):
            print("[WARN] 入力側 HID レポート長（max_input_report）が --report-len と不一致です。")
        resp = dev.send_and_wait(fw.version_query_report(args.report_len))
        if not resp or resp[0] != C.REPORT_ID:
            print("[FAIL] バージョン照会に失敗しました（応答なし、または report_id 不一致）。")
            return 31
        parsed = T.parse_version(resp[1])
        if parsed is None:
            print(f"[FAIL] バージョン応答を解析できません: {_hex(resp[1][:12])}")
            return 32
        version, crc = parsed
        print(f"[OK] Version=0x{version:08X} CRC=0x{crc:08X}")
        return 0
    finally:
        try:
            dev.close()
        except Exception:
            pass


def _post_flash_verify(args, expected_crc, retry_seconds=10.0, interval=1.0):
    """書込後の再列挙・CRC 照合を期限内リトライで確認する。

    再起動直後の一瞬に旧ファーム側の整合応答が観測されるケースがあるため、
    CRC 不一致は即 FAIL にせず、期限（retry_seconds）内は再列挙→再open→
    再照会を繰り返す。一度でも期待CRCと一致すれば即成功。期限切れまで
    一度も一致しなければ FAIL とし、最後に観測した CRC を提示する。
    （retry_seconds/interval の既定値は Task 8 の実機検証で調整の余地あり）
    """
    print(f"[*] 転送成功。デバイス再列挙で CRC を照合します（期待値=0x{expected_crc:08X}）。")
    deadline = time.time() + retry_seconds
    last_err = None
    last_seen_crc = None
    while time.time() < deadline:
        try:
            cands = hid.find_ota_devices(C.USAGE_PAGE)
        except Exception as e:
            last_err = e
            time.sleep(interval)
            continue
        if len(cands) == 1:
            v = hid.OtaDevice(cands[0]["dev"], timeout=args.timeout)
            try:
                v.open(args.report_len)
                resp = v.send_and_wait(fw.version_query_report(args.report_len))
                if resp and resp[0] == C.REPORT_ID:
                    parsed = T.parse_version(resp[1])
                    if parsed is not None:
                        _version, crc = parsed
                        last_seen_crc = crc
                        if crc == expected_crc:
                            print(f"[PASS] 書き込み後のバージョン照会で CRC 一致を確認（0x{crc:08X}）。")
                            return 0
                        print(
                            f"[*] CRC 不一致（再列挙直後の一時応答の可能性）: "
                            f"実機=0x{crc:08X} 期待=0x{expected_crc:08X}。リトライを継続します。"
                        )
            except Exception as e:
                last_err = e
            finally:
                try:
                    v.close()
                except Exception:
                    pass
        time.sleep(interval)
    if last_seen_crc is not None:
        print(
            f"[FAIL] {retry_seconds:.0f} 秒以内に期待CRCを確認できませんでした。"
            f"最後に観測: 0x{last_seen_crc:08X} / 期待: 0x{expected_crc:08X}"
        )
    else:
        suffix = f"（直前のエラー: {last_err}）" if last_err else ""
        print(f"[FAIL] {retry_seconds:.0f} 秒以内に再列挙後のバージョン照会で確認できませんでした。{suffix}")
    return 45


def do_flash(args, body, expected_crc):
    if not args.i_understand_brick_risk:
        print("[FAIL] --flash には --i-understand-brick-risk が必要です。")
        return 40
    print("[WARN] ファームウェア書き込み中は絶対に電源を切らないでください。失敗するとデバイスが起動しなくなる可能性があります。")
    try:
        answer = input("続行するには大文字で FLASH と入力してください: ")
    except EOFError:
        print("[FAIL] 確認入力を取得できません（EOF）。中止します。")
        return 41
    if answer != "FLASH":
        print("[FAIL] 確認文字列が一致しないため中止します。")
        return 41

    cand = select_unique_device(C.USAGE_PAGE)
    if cand is None:
        return 42
    dev = hid.OtaDevice(cand["dev"], timeout=args.timeout)
    caffeinate = None
    try:
        caffeinate = subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())])
        try:
            dev.open(args.report_len)
            verify_connected_identity(dev)
            print(f"[*] max_output_report={dev.max_output_report} max_input_report={dev.max_input_report}")
            if not fw.flash_report_len_ok(args.report_len, dev.max_output_report):
                print(
                    f"[FAIL] --report-len({args.report_len}) がデバイスの出力側 "
                    f"max_output_report({dev.max_output_report}) と不一致。中止。"
                )
                return 43
            if not fw.flash_report_len_ok(args.report_len, dev.max_input_report):
                print(
                    f"[FAIL] --report-len({args.report_len}) がデバイスの入力側 "
                    f"max_input_report({dev.max_input_report}) と不一致。"
                    "START送信後のACKエコーが受信バッファ切り詰めで不一致になり"
                    "転送中断（文鎮化リスク）につながるため中止。"
                )
                return 44
            rc = T.run_transfer(dev, body, args.report_len, log=print)
            if rc != 0:
                print(f"[FAIL] 転送が失敗しました（code={rc}）。")
                return rc
        finally:
            try:
                dev.close()
            except Exception:
                pass

        return _post_flash_verify(args, expected_crc)
    finally:
        if caffeinate is not None:
            caffeinate.terminate()


def main(argv=None):
    args = parse_args(argv)
    if args.report_len < C.MIN_REPORT_LEN:
        print(f"[FAIL] --report-len は {C.MIN_REPORT_LEN} 以上である必要があります: {args.report_len}")
        return 1
    try:
        body, expected_crc = load_and_validate(args.exe)
        if args.flash:
            return do_flash(args, body, expected_crc)
        if args.check:
            return do_check(args, body)
        return dry_run(body, args.report_len)
    except Exception as e:
        print(f"[FAIL] {e}")
        if _NOT_PERMITTED_HEX in str(e):
            print(_PERMISSION_HINT)
        return 2


if __name__ == "__main__":
    sys.exit(main())
