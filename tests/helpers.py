"""テスト補助: .NET .resources(v2) 最小構造のビルダー。

`_read_resource_manager`（magi65_fw_builder/firmware.py）の逆操作。
拒否テスト（同名重複・非ByteArray型）およびラウンドトリップ検証に使う。
"""
import struct


def _write_7bit_int(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _write_string_utf8(s: str) -> bytes:
    b = s.encode("utf-8")
    return _write_7bit_int(len(b)) + b


def make_resources(entries):
    """.NET .resources v2 の最小構造を組み立てて bytes で返す。

    entries: [(name, type_code, data), ...]
    - type_code が ByteArray(0x20)/Stream(0x21) の場合、データセクションに
      4バイト LE 長 + 生バイトを書く（.NET ResourceWriter と同じ）。
    - 他の型コードは長さ無しで data をそのまま書く（本ヘルパでは payload の
      正確な型別エンコードは再現しない。呼び出し側は type_code の不一致検知
      テストにのみ使う想定）。
    - 同名エントリを複数渡すことも可能（重複拒否テスト用）。
    """
    reader_type = (
        "System.Resources.ResourceReader, mscorlib, Version=4.0.0.0, "
        "Culture=neutral, PublicKeyToken=b77a5c561934e089"
    )
    resset_type = "System.Resources.RuntimeResourceSet"
    skip_bytes = _write_string_utf8(reader_type) + _write_string_utf8(resset_type)

    num_res = len(entries)

    # データセクション: 各エントリの (type_code, payload) を連結し、開始オフセットを記録
    data_section = bytearray()
    data_offsets = []
    for (_name, type_code, data) in entries:
        data_offsets.append(len(data_section))
        data_section += _write_7bit_int(type_code)
        if type_code in (0x20, 0x21):
            data_section += struct.pack("<i", len(data))
            data_section += data
        else:
            data_section += data

    # 名前セクション: 各エントリの UTF16LE 名 + データオフセット(データセクション先頭相対)。
    # dataOffset は 7-bit encoded int ではなく固定4バイトの Int32
    # （_read_resource_manager の _read_u32 での読み取りに合わせる）。
    name_section = bytearray()
    name_hashes = [0] * num_res  # ハッシュは二分探索専用で本パーサは使わないため 0 固定
    name_offsets = []
    for (name, _type_code, _data), doff in zip(entries, data_offsets):
        name_offsets.append(len(name_section))
        nb = name.encode("utf-16-le")
        name_section += _write_7bit_int(len(nb))
        name_section += nb
        name_section += struct.pack("<i", doff)

    buf = bytearray()
    buf += b"\xce\xca\xef\xbe"                      # magic (0xBEEFCACE, LE)
    buf += struct.pack("<i", 1)                      # ResourceManager header version
    buf += struct.pack("<i", len(skip_bytes))        # numBytesToSkip
    buf += skip_bytes
    buf += struct.pack("<i", 2)                      # ResourceReader version
    buf += struct.pack("<i", num_res)                # リソース数
    buf += struct.pack("<i", 0)                       # 型テーブル数（本ヘルパでは常に0）

    pad = (8 - (len(buf) % 8)) % 8
    buf += (b"PADPADP" * ((pad // 7) + 1))[:pad]

    for h in name_hashes:
        buf += struct.pack("<i", h)
    for noff in name_offsets:
        buf += struct.pack("<i", noff)

    name_section_start = len(buf) + 4  # dataSectionOffset フィールド分を加味
    data_section_offset = name_section_start + len(name_section)
    buf += struct.pack("<i", data_section_offset)
    buf += bytes(name_section)
    buf += bytes(data_section)
    return bytes(buf)
