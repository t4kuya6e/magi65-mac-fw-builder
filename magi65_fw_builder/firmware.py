"""ビルダー純粋関数（firmware builder pure functions）。
Task 2: ポート from mac_ota/ota_flash.py
Task 3: .exe/.exe.zip からの .NET マネージドリソース抽出（extract_from_exe/parse_param）
"""
import struct
import zipfile
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


# ---------------------------------------------------------------------------
# Task 3: .exe/.exe.zip から .NET マネージドリソース(.resources)を抽出する
# ---------------------------------------------------------------------------

_RESOURCES_MAGIC = b"\xce\xca\xef\xbe"  # 0xBEEFCACE (LE)
BYTEARRAY = 0x20   # ResourceTypeCode.ByteArray
_STREAM = 0x21     # ResourceTypeCode.Stream（ByteArray と同じ長さ表現）


def _iter_exes(path):
    """path が ZIP なら内部の .exe を（ちょうど1個であることを確認して）取り出す。
    ZIP でなければそのままファイル全体を返す。
    """
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(path) as z:
            exes = [n for n in z.namelist() if n.lower().endswith(".exe")]
            if len(exes) != 1:
                raise ValueError(f"ZIP 内 EXE が {len(exes)} 個（1 個であること）")
            with z.open(exes[0]) as fh:
                return [fh.read()]
    with open(path, "rb") as f:
        return [f.read()]


def _read_u32(buf, pos):
    return struct.unpack_from("<i", buf, pos)[0]


def _read_7bit_int(buf, pos):
    """.NET BinaryReader.Read7BitEncodedInt() 相当。(値, 読み終わり位置) を返す。"""
    val = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return val, pos


def _read_resource_manager(blob, start):
    """.resources ストリーム1個（先頭 magic が blob[start:start+4]）をパースし
    [(name, type_code, data_or_None), ...] を返す。

    内部オフセット（padding判定・nameSection/dataSectionOffset 等）はすべて
    「ストリーム先頭(start)を 0 とした相対位置」で計算する。.NET ResourceWriter が
    書き込み時に用いる Stream 上の位置が、そのままこの相対位置に対応するため。

    注: 名前セクションの dataOffset は 7-bit encoded int ではなく固定4バイトの
    Int32（.NET ResourceReader は `_store.ReadInt32()` で読む）。型コード自体は
    7-bit encoded int だが、配列長のエンコードとは別物のため取り違えないこと。
    """
    pos = start + 4  # magic 分をスキップ（呼び出し側で存在確認済み）

    res_mgr_header_version = _read_u32(blob, pos); pos += 4
    if res_mgr_header_version != 1:
        raise ValueError(f"ResourceManager header version 不正: {res_mgr_header_version}")

    num_bytes_to_skip = _read_u32(blob, pos); pos += 4
    pos += num_bytes_to_skip  # ReaderTypeName/ResourceSetTypeName はそのままスキップ

    reader_version = _read_u32(blob, pos); pos += 4
    if reader_version != 2:
        raise ValueError(f"ResourceReader version 不正: {reader_version}")

    num_resources = _read_u32(blob, pos); pos += 4
    num_types = _read_u32(blob, pos); pos += 4
    for _ in range(num_types):
        type_name_len, pos = _read_7bit_int(blob, pos)
        pos += type_name_len

    # 名前ハッシュ配列は 8 バイト境界にアライメントされる（相対位置基準）
    relpos = pos - start
    pad = (8 - (relpos % 8)) % 8
    pos += pad

    pos += 4 * num_resources  # nameHashes（探索専用の値のため未使用）

    name_offsets = []
    for _ in range(num_resources):
        off = _read_u32(blob, pos); pos += 4
        name_offsets.append(off)

    data_section_offset = _read_u32(blob, pos); pos += 4
    name_section_start = pos

    out = []
    for off in name_offsets:
        p = name_section_start + off
        name_len, p = _read_7bit_int(blob, p)
        name = blob[p:p + name_len].decode("utf-16-le")
        p += name_len
        data_off = _read_u32(blob, p)

        dpos = start + data_section_offset + data_off
        type_code, dpos = _read_7bit_int(blob, dpos)
        if type_code in (BYTEARRAY, _STREAM):
            length = _read_u32(blob, dpos); dpos += 4
            data = blob[dpos:dpos + length]
        else:
            data = None
        out.append((name, type_code, data))
    return out


def _parse_dotnet_resources(blob):
    """.resources(magic 0xBEEFCACE) を構造的にパースし [(name, type_code, bytes), ...] を返す。

    複数の .resources ストリームがあり得るため、辞書統合せず全エントリを list で返す
    （後段で全候補横断の一意性を判定するため）。
    """
    out = []
    idx = 0
    while True:
        pos = blob.find(_RESOURCES_MAGIC, idx)
        if pos < 0:
            break
        idx = pos + 4
        try:
            out.extend(_read_resource_manager(blob, pos))
        except Exception:
            continue
    return out


def extract_from_exe(path):
    """.exe/.exe.zip から名前 code_2M(ByteArray,2097152B)/param_128K(ByteArray,131072B) の
    2 エントリが一意に揃う場合のみ受理し、{"code_2m": bytes, "param_128k": bytes} を返す。
    """
    # _iter_exes は ZIP 内複数 EXE を既に拒否済み。実質 1 個の blob。
    for blob in _iter_exes(path):
        entries = _parse_dotnet_resources(blob)  # [(name, type_code, data), ...]
        # 1) まず名前単位で各ちょうど1件であることを確認する。
        #    型・長さで先に絞ると、同名の不正型/不正長エントリ併存を見逃すため。
        code = [(t, d) for (n, t, d) in entries if n == "code_2M"]
        param = [(t, d) for (n, t, d) in entries if n == "param_128K"]
        if len(code) == 0 and len(param) == 0:
            continue  # この blob に対象リソースなし
        if len(code) != 1 or len(param) != 1:
            raise ValueError(f"code_2M/param_128K が一意でない（code={len(code)}, param={len(param)}）。拒否。")
        # 2) 一意に確定した各エントリの型・長さを検証する。
        (ct, cd), (pt, pd) = code[0], param[0]
        if ct != BYTEARRAY or len(cd) != 2097152:
            raise ValueError(f"code_2M の型/長さ不正: type=0x{ct:02X} len={len(cd) if cd else 0}")
        if pt != BYTEARRAY or len(pd) != 131072:
            raise ValueError(f"param_128K の型/長さ不正: type=0x{pt:02X} len={len(pd) if pd else 0}")
        return {"code_2m": cd, "param_128k": pd}
    raise ValueError("code_2M/param_128K を抽出できない（対象/バージョン不一致の疑い）")


def parse_param(param_128k):
    def s(a, b):
        return param_128k[a:b].split(b"\xff")[0].decode("ascii", "replace").strip("\x00")
    return {
        "vid": int(s(64, 68), 16), "pid": int(s(68, 72), 16),
        "report_id": int(s(72, 74), 16), "usage_page": int(s(80, 84), 16),
    }
