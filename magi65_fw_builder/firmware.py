"""ビルダー純粋関数（firmware builder pure functions）。
Task 2: ポート from mac_ota/ota_flash.py
"""
from .constants import REPORT_ID, HEADER_LEN, CHUNK, MAX_PKTS_PER_REPORT, MIN_REPORT_LEN

def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc ^ b) & 1 else crc >> 1
            crc &= 0xFFFF
            b >>= 1
    return crc

def source_bin_size(code_2m: bytes) -> int:
    return int.from_bytes(code_2m[48:52], "big")

def extract_firmware(code_2m: bytes) -> bytes:
    size = source_bin_size(code_2m)
    body = bytearray(code_2m[HEADER_LEN:HEADER_LEN + size])
    body += b"\xff" * ((-size) % CHUNK)
    return bytes(body)

def data_packet(body: bytes, index: int) -> bytes:
    head = index.to_bytes(2, "little") + body[index * CHUNK:index * CHUNK + CHUNK]
    return head + crc16(head).to_bytes(2, "little")

def _frame(payload: bytes, report_len: int) -> bytes:
    if report_len < MIN_REPORT_LEN:
        raise ValueError(f"report_len must be >= {MIN_REPORT_LEN}: {report_len}")
    if len(payload) > report_len - 1:
        raise ValueError(f"payload {len(payload)}B exceeds report_len-1")
    sen = bytearray(b"\xff" * (report_len - 1))
    sen[:len(payload)] = payload
    return bytes([REPORT_ID]) + bytes(sen)

def start_report(report_len=64) -> bytes:
    return _frame(bytes.fromhex("0202000 1ff".replace(" ", "")), report_len)

def data_report(body: bytes, start_index: int, report_len=64):
    n_chunks = len(body) // CHUNK
    count = min(MAX_PKTS_PER_REPORT, n_chunks - start_index)
    pkts = b"".join(data_packet(body, start_index + i) for i in range(count))
    return _frame(bytes([0x02, count * 20, 0x00]) + pkts, report_len), count

def end_report(n_chunks, report_len=64) -> bytes:
    last = n_chunks - 1
    inv = (0x10000 - last) & 0xFFFF
    payload = bytes([0x02, 0x06, 0x00, 0x02, 0xFF]) + last.to_bytes(2, "little") + inv.to_bytes(2, "little")
    return _frame(payload, report_len)

def version_query_report(report_len=64) -> bytes:
    if report_len < MIN_REPORT_LEN:
        raise ValueError(f"report_len must be >= {MIN_REPORT_LEN}")
    buf = bytearray(report_len)
    buf[0] = REPORT_ID; buf[1] = 0x01
    for i in range(4, 32):
        buf[i] = 0xFF
    return bytes(buf)

def flash_report_len_ok(report_len, max_output) -> bool:
    return bool(max_output) and report_len == max_output
