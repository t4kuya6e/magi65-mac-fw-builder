# IQUNIX Magi65 USB OTA プロトコル

| | |
|---|---|
| 対象機種 | IQUNIX Magi65（ANSI、型番 CSF6C4）。USB VID `0x320F` / PID `0x5055` |
| 対象ファイル | 公式 updater `MG65-CSF6C4-V0120-20260120.exe`、`MG65-CS0164-V0121-20260302.exe` |
| 根拠 | updater（.NET）の逆コンパイル、デバイス側ファーム（V0121）の静的解析、実機での書き込み |

本リポジトリには updater・ファーム本体・逆コンパイル結果を同梱しない。各自が公式 updater から取得・抽出する。

> **信頼度の表記**: ［確定］＝コードから直接読み取れる、または実機で確認した事実 ／［推定］＝コードのロジックからの推論で、実機では確かめていない。

---

## 0. 要点

- Telink チップ（RISC-V）の **USB HID OTA**。通信は暗号化なしの平文［確定］。コアは Andes V5 系［推定］
- OTA は **Usage Page `0xFFEF`（ベンダー定義）** の HID インターフェースで行う［確定］
- コマンドはバージョン照会と OTA（START / DATA / END）の 2 系統。ACK 駆動の同期転送［確定］
- コマンド値と結果コードは Telink 標準の OTA 定義と一致する［確定］
- **デュアルバンク方式**。新しいイメージは END の確定処理まで起動対象にならず、転送が途中で止まっても旧ファームで起動する［確定］
- 古い版への書き戻し（ダウングレード）は拒否されない［確定］

---

## 1. updater の構成 ［確定］

- .NET Framework 4.0 の WinForms アプリ（内部名 `USB_OTA`）。Win32 の `setupapi.dll` / `hid.dll` / `kernel32.dll` を P/Invoke で呼ぶ
- 埋め込みリソース `WindowsFormsApplication1.Properties.Resources.resources`（`.resources` 形式、マジック `0xBEEFCACE`）に次の 4 エントリがある

| リソース名 | 型 | サイズ | 内容 |
|---|---|---|---|
| `code_2M` | ByteArray | 2,097,152 | ファーム（2MB 枠。実データは約 126KB） |
| `param_128K` | ByteArray | 131,072 | 識別パラメータ（実データは約 90B） |
| `right` / `wrong` | Bitmap | — | 成功・失敗アイコン |

- デバイスに書き込むのは `code_2M` の本体だけ。`param_128K` は識別に使うだけで送信しない
- 処理（IL）は V0120 と V0121 で同一。違うのは埋め込みのファームだけ

---

## 2. デバイス識別 ［確定］

### updater の識別値（`param_128K`）

| 項目 | オフセット | 値 | 用途 |
|---|---|---|---|
| enc_key | 48–63 | `11 22 … ff 00` | OTA の送信経路では使わない |
| VID | 64–67 | `"320F"` | `0x320F` |
| PID | 68–71 | `"5055"` | `0x5055` |
| ReportID | 72–73 | `"05"` | `5` |
| UsagePage | 80–（`0xFF` 終端） | `"FFEF"` | `0xFFEF` |
| IID | 256–（`0xFF` 終端） | `"Mouse_USB_OTA"` | 使わない |

updater は `VendorID == 0x320F && ProductID == 0x5055 && UsagePage == 0xFFEF` の HID を開く。
識別値は型番違い（CSF6C4 / CS0164）でも同一で、型番は updater のファイル名にしか現れない。

### 実機の HID 構成（macOS）

| インターフェース | Usage Page / Usage | レポート長 | 用途 |
|---|---|---|---|
| 0 | `0x0001/0x0006` | 入力 8 | キーボード（システムが排他で保持） |
| 1 | `0xFF60/0x61` | 32 | VIA の raw HID |
| 2 | `0x0001/0x0006`、`0x0001/0x0080`、**`0xFFEF/0x00`**、`0x000C/0x01`、`0x0001/0x0002`、`0x0001/0x0001` | 入出力・Feature とも 64 | **OTA**（キーボード・consumer・マウス等と同居） |
| — | `0xFF1C/0x92` | 64 | 用途未確認 |

- Product は "IQUNIX MG65 Mechanical Keyboard"、Manufacturer は "RDR"。シリアル番号は無い
- bcdDevice はファームの版を表す（V0120 は `0x0120`、V0121 は `0x0121`）。型番は表さない

### macOS からのアクセス

- hidapi（cython-hidapi）は使えない。既定で排他（seize）オープンするため、キーボードと同居する OTA インターフェースでは `IOHIDDeviceOpen` が `kIOReturnNotPrivileged`（`0xE00002C1`）になる
- **IOKit を直接呼び、`kIOHIDOptionsTypeNone`（非排他）で開く**。root は要らない（`magi65_fw_builder/iokit_hid.py`）
- レポートの送受信には、ツールを起動するアプリに TCC「入力監視」の権限が要る。無いと `IOHIDDeviceSetReport` が `kIOReturnNotPermitted`（`0xE00002E2`）になる

---

## 3. ファーム本体のレイアウト ［確定］

```
size = code_2M[48..51]（ビッグエンディアン）
body = code_2M[256 .. 256+size]           # 先頭 48 バイトは 0x56 のフィラー
crc  = body[size-4 .. size]（リトルエンディアン）
送信用 = body + 0xFF を 16 バイト境界まで  # 16 バイト = 1 チャンク
```

- updater の簡易チェックは `crc == 0` と `crc == 0xFFFFFFFF` を弾くだけ
- body[0x20..0x23] は Telink の起動フラグ `"KNLT"`。デバイスはこれが無いイメージを拒否する（§9）

| | V0120 | V0121 |
|---|---|---|
| size | 128,628（`0x1F674`） | 128,596 |
| チャンク数 | 8,040 | 8,038 |
| 末尾 CRC | `0x01020FA4` | `0x55EA5AC6` |

---

## 4. レポート構造（ホスト → デバイス） ［確定］

レポートは常に出力レポート長（実機では 64 バイト）で送る。先頭は report_id `0x05`。

```
[05] [cmd] [len] [00] [payload …] [パディング]
      cmd: 1=バージョン照会, 2=OTA
      len: payload の有効バイト数
```

- OTA（START / DATA / END）のパディングは `0xFF`
- updater はバージョン照会で 32 バイトだけをバッファへコピーするため、33 バイト目以降は `0x00` になる
- DATA は最大 3 パケット（1 + 3 + 60 = 64 バイト）なので、出力レポートは 64 バイト以上が要る

### 4.1 バージョン照会

```
05 | 01 00 00 | FF … | 00 …
```

### 4.2 START

```
05 | 02 02 00 | 01 FF | FF …          # 0xFF01（LE）= CMD_OTA_START
```

### 4.3 DATA

1 レポートに 20 バイトのパケットを最大 3 個入れる。

```
05 | 02 <len=20/40/60> 00 | <pkt0><pkt1><pkt2> | FF …

pkt = index（LE 16bit） + body[index*16 .. +16] + CRC16（先頭 18 バイトに対して, LE）
```

index は 0 から 1 ずつ増やし、最終チャンクまで送る。

### 4.4 END

```
05 | 02 06 00 | 02 FF | last（LE 16bit） | (0x10000 - last) & 0xFFFF（LE 16bit） | FF …
                 # 0xFF02（LE）= CMD_OTA_END、last = 最終 index
```

---

## 5. CRC16 ［確定］

多項式 `0xA001`（IBM CRC16 の反射形、Modbus と同じ）、初期値 `0xFFFF`、最終 XOR なし。

```python
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc ^ b) & 1 else (crc >> 1)
            crc &= 0xFFFF
            b >>= 1
    return crc
```

---

## 6. 応答（デバイス → ホスト） ［確定］

入力レポートは report_id 込みで届く（先頭バイトが `0x05`）。1 回の送信に対して入力レポートが 1 つ返る。

### 6.1 バージョン照会の応答

```
05 01 08 00 | version（LE 32bit） | crc（LE 32bit）
```

- version は V0120・V0121 とも `0`。使えるのは crc（書き込まれているファーム本体の末尾 CRC）だけ
- 書き込み直後の再接続では、旧ファームの crc が 1 回返ることがある

### 6.2 ACK（START / DATA）

- デバイスは受け取ったレポートをそのまま返す
- 例外が 1 つある。DATA で body[0x20]（起動フラグ `"KNLT"` の先頭 `0x4B`）を含むパケットは、そのバイトを `0xFF` にして返す。デバイスが起動フラグを無効にして書いた内容を返している（§9）［推定］
- updater は ACK の中身を検査せず、受信そのものを次の送信の合図にしている

### 6.3 結果応答（END の完了、および失敗）

```
05 02 03 00 | 06 FF | <code>            # 0xFF06（LE）= CMD_OTA_RESULT
```

| code | 名前 | デバイスが返す条件 |
|---|---|---|
| 0 | SUCCESS | |
| 1 | DATA_PACKET_SEQ_ERR | DATA の index が前回 + 1 でない |
| 2 | PACKET_INVALID | index が最終 index を超える、未知のコマンド |
| 3 | DATA_CRC_ERR | パケットの CRC16 不一致 |
| 4 | WRITE_FLASH_ERR | flash に書いたあと読み返して不一致 |
| 5 | DATA_UNCOMPLETE | END の最終 index が受信済みの index と不一致 |
| 6 | FLOW_ERR | START 前の DATA、転送中の START など |
| 7 | FW_CHECK_ERR | イメージ全体の CRC 不一致 |
| 8 | VERSION_COMPARE_ERR | START_EXT で版の比較に失敗 |
| 9 | PDU_LEN_ERR | パケット長が不正 |
| 10 | FIRMWARE_MARK_ERR | body[0x20..0x23] に `"KNLT"` が無い |
| 11 | FW_SIZE_ERR | イメージサイズが `0x4000` 未満、または上限を超える |

- 成功（code 0）は実機で確認済み。失敗の応答は実機では観測しておらず、デバイス側ファームのコードから読んだもの
- updater は `05 02 03 00 06 FF` に続く code が 0 なら成功、それ以外なら失敗と表示する

---

## 7. 転送シーケンス

```
open HID (VID=0x320F, PID=0x5055, UsagePage=0xFFEF)   # 非排他で開く
send START                → ACK を待つ
for each 3 チャンク:
    send DATA              → ACK を待つ（中身を照合する）
send END                  → 結果応答を待つ（code 0 で成功）
再接続後にバージョン照会し、crc が送ったイメージの末尾 CRC と一致することを確かめる
```

---

## 8. 検証用テストベクタ（V0120 の `code_2M` から算出） ［確定］

body の先頭 16 バイト: `25 a0 00 00 00 00 5d 02 00 00 00 00 00 00 00 00`

| index | CRC16 | 20 バイトのパケット（hex） |
|---|---|---|
| 0 | `0xCC80` | `000025a0000000005d020000000000000000 80cc` |
| 1 | `0x11B1` | `0100000000000000000074f6010000000000 b111` |
| 8039 | `0xC487` | `671fa40f0201ffffffffffffffffffffffff 87c4` |

- END のペイロード: `02 FF 67 1F 99 E0`（last = `0x1F67`、inv = `0xE099`）
- index 8039 のデータの先頭に本体の末尾 CRC `a4 0f 02 01`（`0x01020FA4`）が現れる

---

## 9. デバイス側の OTA 処理（V0121 の静的解析） ［確定］

Ghidra で、言語 `RISCV:LE:32:AndeStar_v5`、ロードアドレス `0x20000000` として解析した。関数アドレスは V0121 のもの。

| 関数 | 役割 |
|---|---|
| `0x20017d58` | OTA パケットの処理。index が `0xFF00` 未満なら DATA、以上ならコマンド |
| `0x20016370` | DATA の flash 書き込みと読み返し |
| `0x2000f952` | END 後の確定処理 |
| `0x20015484` / `0x20018e44` | 失敗の記録と結果応答の送信 |

### コマンド

| 値 | 名前 | 公式 updater / 本ツール |
|---|---|---|
| `0xFF00` | VERSION | 使わない |
| `0xFF01` | START（legacy） | 使う |
| `0xFF02` | END | 使う |
| `0xFF03` | START_EXT（版の比較あり） | 使わない |
| `0xFF04` | FW_VERSION_REQ | 使わない |
| `0xFF06` | RESULT（デバイス → ホスト） | 受信する |

### デュアルバンクと起動フラグ

- DATA の書き込みでは、body[0x20] を含むチャンクで `"KNLT"` を確かめ（無ければ code 10）、先頭 1 バイトを `0xFF` にしてから書き込み先のバンクへ書く
- END 後の確定処理で `"KNLT"` と全長を確かめ、書き込み先のバンクの +0x20 に `0x4B`（`'K'`）を書いて起動フラグを有効にする
- このため、確定処理が終わるまで新しいイメージは起動対象にならない。転送が途中で止まっても旧ファームで起動する。DFU のような専用のブートローダは無い

### 版の比較

版の比較は START_EXT（`0xFF03`）と FW_VERSION_REQ（`0xFF04`）の経路にだけある。legacy START（`0xFF01`）では比較しないので、古い版への書き戻しは拒否されない。

### 失敗後の状態

失敗を記録すると、以降の OTA パケットは処理されない。再試行は、キーボードを抜き差し（再起動）してから行う［推定］。

---

## 10. 前提条件・注意

- キーボードを USB 有線モードにする（公式手順: `FN + T` / `FN + 5`）［確定］
- 書き込むとキーマップは初期化される。事前に VIA で保存しておく［確定］
- 書き込み中に電源やケーブルを切らない。デュアルバンク方式なので旧ファームで起動する見込みだが、中断を実機では試していない［推定］

---

## 11. 未確認事項

- 失敗の結果応答（code 1〜11）を実機では観測していない
- バンクのアドレスは実行時に決まる値で、静的には読めていない
- 失敗後、抜き差しせずに再試行できるか
- `0xFF1C/0x92` のインターフェースの用途

---

## 出典

- Telink `ota.h`（コマンド値と結果コード）: https://android.googlesource.com/platform/hardware/telink/atv/refDesignRcu/+/refs/heads/master/stack/ble/service/ota/ota.h
- jbonadiman/telink-usb-ota（同系統の USB HID OTA。デュアルバンクと起動フラグの扱い）: https://github.com/jbonadiman/telink-usb-ota
