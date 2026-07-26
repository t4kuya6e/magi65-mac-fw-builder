# IQUNIX Magi65 USB OTA 仕様分析ドキュメント

| | |
|---|---|
| 対象 | `MG65-CSF6C4-V0120-20260120.exe`（IQUNIX Magi65 ファーム更新ツール） |
| 目的 | Windows 専用ツールの通信仕様を解明し、macOS ネイティブ実装の根拠とする |
| 解析手法 | .NET アセンブリの静的解析のみ（`monodis` で IL、`ilspycmd 8.2` で C# 逆コンパイル）。**実機への書き込みは未実施** |
| 生成物 | 逆コンパイル C#（約3163行）と抽出ファーム（`code_2M` / `param_128K`）。※逆コンパイル成果物・ファーム本体は本リポジトリには同梱しない（各自が公式 updater から取得・抽出する） |
| 作成日 | 2026-07-11 |

> **信頼度の表記**: 各項に［確定］＝逆コンパイル済みコードから直接読み取れる事実 ／［推定］＝コードのロジックからの推論で実機未検証、を付す。

---

## 0. TL;DR

- 実体は Telink チップの **USB HID OTA**。通信は暗号化なしの平文［確定］。
- OTA は **Usage Page `0xFFEF`（ベンダー独自ページ）** のHIDインターフェース経由［確定］。macOS はベンダーページを制限しないため、`hidapi` でネイティブ実装可能［推定・信頼度高］。
- 4種のコマンド（バージョン照会 / START / DATA / END）と ACK 駆動の同期転送で成立［確定］。
- 文鎮化リスクと復旧手段は実機依存で**未確認**。

---

## 1. アセンブリ構成

- .NET Framework 4.0 WinForms（内部名 `USB_OTA`、PDBパス `...\usb ota\KM_USB_mode_ota_pc_v5.0.2\ota_app\obj\x86\Release\USB_OTA.pdb`）。
- Win32 API を P/Invoke: `setupapi.dll`(SetupDi*), `hid.dll`(HidD_*/HidP_*), `kernel32.dll`(CreateFile/ReadFile/WriteFile 等)。
- 埋め込み .NET リソース `WindowsFormsApplication1.Properties.Resources.resources`（2.26MB）に4エントリ:

| リソース名 | 型 | サイズ | 内容 |
|---|---|---|---|
| `code_2M` | ByteArray | 2,097,152 | メインファーム（2MB枠。実データ ~126KB） |
| `param_128K` | ByteArray | 131,072 | 設定パラメータ（VID/PID等。実データ ~90B） |
| `right` | Bitmap | — | 成功アイコン |
| `wrong` | Bitmap | — | 失敗アイコン |

抽出は `.resources` 形式（マジック `0xBEEFCACE`）を直接パースして実施。

---

## 2. デバイス識別（オープン条件） ［確定］

`load_param()`（decompiled.cs:1279付近）が `param_128K` から ASCII 文字列として読む:

| 項目 | param オフセット | バイト | 解釈 |
|---|---|---|---|
| enc_key | 48–63 (16B) | `11 22 33 44 55 66 77 88 99 aa bb cc dd ee ff 00` | 16バイト鍵。**OTA送信経路では未使用**（`enc_key` は代入のみで参照なし。別機能の名残） |
| VID | 64–67 | `"320F"` | `0x320F` |
| PID | 68–71 | `"5055"` | `0x5055` |
| ReportID | 72–73 | `"05"` | `5`（`usb_Form_Load` で `report_id = Convert.ToByte("05")`。フィールド初期値6は上書きされる） |
| UsagePage | 80–（0xFF終端） | `"FFEF"` | `0xFFEF`（`interface_textBox` 経由で usagePage に） |
| IID | 256–（0xFF終端） | `"Mouse_USB_OTA"` | バイナリ上は存在するが**コードは長さを数えるだけで未使用**（decompiled.cs:1296-1298）。画面の `IID=` ラベルは実際には interface_textBox＝UsagePage 文字列から生成される（decompiled.cs:1303-1306）。デバイス選択には**使われない** |

デバイス検索 `findDevice(vid,pid,usagePage,usage=0,...)`（decompiled.cs:446）の一致条件:

```
HIDAttrib.VendorID == 0x320F && HIDAttrib.ProductID == 0x5055 && HIDP_CAPS.UsagePage == 0xFFEF
```

- 読み・書き同一ハンドル。`InputReportByteLength` / `OutputReportByteLength` / `FeatureReportByteLength` は HID caps から取得（**実機依存の実行時値**。exe 静的解析では不明）。
- macOS 対応上の含意: Usage Page 0xFFEF はベンダー定義領域(0xFF00–0xFFFF)。macOS の HID アクセス制限（汎用デスクトップのキーボード/マウスを保護）に該当しないため、IOKit/hidapi から開ける見込み［推定・信頼度高。VIA/QMK Toolbox が同種インターフェースを Mac で扱える事実が傍証］。

---

## 3. ファーム本体（code_2M）のレイアウトと取り出し ［確定］

`load_param()`（decompiled.cs:1307–1321）:

```csharp
source_bin_size = code_bin[48]*256^3 + code_bin[49]*256^2 + code_bin[50]*256 + code_bin[51];  // ビッグエンディアン
for (l=0; l<source_bin_size; l++) source_binchar[l] = code_bin[256 + l];                       // 本体は offset 256 以降
for (m=0; m<16; m++) source_binchar[source_bin_size + m] = 0xFF;                                // 末尾を0xFFで16バイト分パディング
bin_crc = BitConverter.ToUInt32(source_binchar, source_bin_size - 4);                           // 本体末尾4バイト=CRC
```

抽出結果:

| 項目 | 値 |
|---|---|
| ヘッダ長 | 256 バイト（offset 0–255。うち先頭~48Bは 0x56 フィラー） |
| サイズフィールド | `code_2M[48..51]` = `00 01 F6 74`（BE）= **128628 バイト (0x1F674)** |
| 本体 | `code_2M[256 .. 256+128628]` |
| 本体末尾CRC | `0x01020FA4`（本体の最後4バイト。LE） |
| 16B境界パディング後 | 128640 バイト → **8040 チャンク**（16バイト/チャンク、index 0..8039） |

`check_bin_is_ok()`（decompiled.cs:1737）は `bin_crc==0 || bin_crc==0xFFFFFFFF` を弾くだけの簡易チェック（転送の検証ではない）。

> 注: `param_128K` は識別情報の読み出し専用で、**書き込み対象ではない**（送信経路に param を流すコードは存在しない）。書き込むのは `code_2M` の本体のみ。

---

## 4. レポート構造（ホスト→デバイス） ［確定］

送信は `user_sendDataToDevice(sendType, buf, len, ...)`（decompiled.cs:1571）で行う。`sendReportDataBuf` を組み立て:

```
Array.Clear(sendReportDataBuf, 0, OutputReportByteLength);   // 0クリア
sendReportDataBuf[0] = report_id;                            // = 5
for (i=0; i<len; i++) sendReportDataBuf[i+1] = buf[i];       // buf(=sen) を [1] 以降へコピー
```

送信方式は3種（`SENDTYPE`）。OTA では全て `WRITE`（HID出力ストリーム書き込み `hidDevice.Write(sendReportDataBuf, 0, OutputReportByteLength)`）を使用。FEATURE(`HidD_SetFeature`)/OUTPUT(`HidD_SetOutputReport`)は未使用経路。

`sen` バッファ（＝ペイロード）の共通ヘッダ:

```
sen[0] = コマンド種別（1=バージョン照会, 2=OTA）
sen[1] = 有効ペイロード長
sen[2] = 0x00
sen[3..] = 各コマンド固有のペイロード（オフセット num=3 から）
```

最終的にデバイスへ渡るレポート = `[report_id] + sen のコピー`（送信は常に `OutputReportByteLength` バイト固定）。

> **パディングの実体（重要）**: `user_sendDataToDevice` は `sendReportDataBuf` を **0 クリア**した後 `[0]=report_id`、`[1..len]=sen[0..len-1]` をコピーする（decompiled.cs:1581-1586）。埋め値は「0」ではなく **`sen` の中身**で決まる:
> - **OTA（START/DATA/END）**: `sen` を事前に **0xFF 全埋め**し（decompiled.cs:1653-1656）、`len=OutputReportByteLength` で丸ごとコピーする（decompiled.cs:1733）。→ 末尾パディングは **0xFF**。
> - **バージョン照会**: `len=32` しかコピーしない（decompiled.cs:1821）。→ `sen` 由来の 0xFF は途中まで、それ以降（32バイト目以降）は 0 クリアのまま **0x00**。
>
> **最小レポート長の要件**: DATA は最大 3 パケット＝ report_id(1)+ヘッダ(3)+パケット(60) = **最低 64 バイト**の出力レポートが必要。バージョン応答は **最低 12 バイト**の入力レポートが必要。コードは HID caps を取得するだけでこの下限を検証しないので、macOS 実装側で確認すること。

### 4.1 バージョン照会（読み取り検証で使用） ［確定］
`getFwVersionToolStripMenuItem_Click`（decompiled.cs:1809）:
```
sen を 0xFF で埋め → sen[0]=1, sen[1]=0, sen[2]=0 → user_sendDataToDevice(WRITE, sen, 32)
```
実際にデバイスへ書くレポート（**常に OutputReportByteLength バイト**）:
```
[05] [01 00 00] [FF×29] [00 … 00]
 ^rid ^payload   ^sen由来  ^32バイト目以降は0クリア
```
- **注意**: 引数の `32` は「`sen` から送信バッファへコピーするバイト数」であって USB 書き込み長ではない。実書き込み長は `OutputReportByteLength`（decompiled.cs:1618-1620）。macOS で `hid_write(..., 32)` としない。レポート全長で書くこと。

### 4.2 START ［確定］
`ota_write()` の `start_ota_flag==1` 分岐:
```
sen[0]=2, sen[1]=2, sen[2]=0, sen[3]=1, sen[4]=0xFF
```
レポート: `05 | 02 02 00 | 01 FF | FF...(OutputReportByteLength まで pad)`
（ペイロード `01 FF` = リトルエンディアン `0xFF01` = OTA開始）

### 4.3 DATA ［確定］
`ota_write()` の `start_ota_flag==2` 分岐。1レポートに **20バイトパケット×最大3個** を格納。

各20バイトパケット:
```
[0..1]   addr = ota_index（LE, 16bit）
[2..17]  firmware[ota_index*16 .. +16]（16バイト。末尾チャンクは0xFFパディング済み）
[18..19] CRC16（先頭18バイト = addr(2)+data(16) に対して, LE）
```
- `sen[0]=2, sen[1]=有効バイト数(20/40/60), sen[2]=0, sen[3..]=パケット列`
- `ota_index` は 0 から +1。`ota_index*16 >= source_bin_size+16` になる直前で停止（末尾の余剰1パケットは `sen[1]` に計上されず破棄 → 実送信は index 0..8039）。

レポート: `05 | 02 <len> 00 | <pkt0><pkt1><pkt2> | FF...`

### 4.4 END ［確定］
DATA ループで送るデータが尽きた（`sen[1]==0`）時:
```
sen[0]=2, sen[1]=6, sen[2]=0
sen[3]=2, sen[4]=0xFF                       // 0xFF02 = OTA終了
num3 = ota_index-1                           // 最終index = 8039
sen[5..6] = num3 (LE)
num4 = (0x10000 - num3) & 0xFFFF             // num3 の2の補数
sen[7..8] = num4 (LE)
```
レポート: `05 | 02 06 00 | 02 FF <last_lo><last_hi> <inv_lo><inv_hi> | FF...`

---

## 5. CRC16 ［確定］

`crc16(byte[] pD, int len)`（decompiled.cs:1631）:
- テーブル `{0x0000, 0xA001}`（多項式 0xA001＝reflected 0x8005 / IBM-CRC16）
- 初期値 `0xFFFF`、最終XORなし、入出力とも反射（reflected）

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

## 6. ハンドシェイク（ACK駆動ペーシング） ［確定］

転送は Windows 側の連続非同期読み取り（`BeginAsyncRead`→`ReadCompleted`→`Read_File_Data_Process_YKQ`, decompiled.cs:1441/1511）で駆動:

1. `OtaStart_button_Click`: `start_ota_flag=1` にして `ota_write()`（START送信）。
2. デバイスが入力レポートを返す（＝ACK）。
3. `Read_File_Data_Process_YKQ`: 失敗応答でなく `start_ota_flag!=0` なら `ota_write()` を再実行（次DATA送信）。以降 2–3 を全チャンク分繰り返す。
4. 最終的に END を送信。
5. 完了応答を受信。

> ［推定・信頼度高］この設計は「1レポート送信につきデバイスが入力レポート1つを返す」ことを前提とする。ACKの中身はDATA中は検査されず、受信イベント自体がペーシングのトリガ。Mac実装では「WRITE→入力レポートを1つread（タイムアウト付き）→次WRITE」の同期ループで再現するのが忠実。

### 完了応答（デバイス→ホスト, report_id=5） ［確定］
`Read_File_Data_Process_YKQ`（decompiled.cs:1521）:
```
readFileDataBuf[0..5] == {05, 02, 03, 00, 06, FF}
readFileDataBuf[6] == 0  → "OTA Success"
readFileDataBuf[6] != 0  → "OTA Fail=<code>"
```

### バージョン照会応答 ［確定］
```
readFileDataBuf[0..3] == {05, 01, 08, 00}
readFileDataBuf[4..7]  = version (LE uint32)
readFileDataBuf[8..11] = crc (LE uint32)
```

---

## 7. 転送シーケンス（擬似コード）

```
open HID (VID=0x320F, PID=0x5055, UsagePage=0xFFEF)   # report_id=5
send  [05, 02,02,00, 01,FF, pad...]                    # START
wait  input report (ACK)
idx = 0
body = code_2M[256:256+size]; body += 0xFF * ((-size)%16)   # 16B境界へパディング
n_chunks = len(body)//16                                # = 8040
while idx < n_chunks:
    pkts = []
    for _ in range(min(3, n_chunks-idx)):
        a = u16le(idx); d = body[idx*16:idx*16+16]
        pkts += a + d + u16le(crc16(a+d)); idx += 1
    send [05, 02, len(pkts), 00] + pkts + pad
    wait input report (ACK)
last = n_chunks - 1                                     # = 8039
inv  = (0x10000 - last) & 0xFFFF
send [05, 02,06,00, 02,FF, u16le(last), u16le(inv), pad]  # END
wait completion [05,02,03,00,06,FF, result]; result==0 → 成功
```

---

## 8. 検証用テストベクタ（`code_2M.bin` から算出） ［確定］

本体先頭16バイト = `25 a0 00 00 00 00 5d 02 00 00 00 00 00 00 00 00`

| index | CRC16 | 20バイトパケット(hex) |
|---|---|---|
| 0 | `0xCC80` | `0000 25a0000000005d02000000000000000 0 80cc` → `000025a0000000005d02000000000000000080cc` |
| 1 | `0x11B1` | `010000000000000000 0074f6010000000000 b111` → `0100000000000000000074f6010000000000b111` |
| 8039 | `0xC487` | `671f a40f0201ffffffffffffffffffff ffff 87c4` → `671fa40f0201ffffffffffffffffffffffff87c4` |

- 総サイズ 128628 / パディング後 128640 / チャンク 8040 / 最終index 8039(0x1F67)。
- END ペイロード: `02 FF 67 1F 99 E0`（last=0x1F67, inv=0xE099）。
- index 8039 のデータ末尾に本体CRC `a4 0f 02 01`(=0x01020FA4) が現れる（本体末尾4バイトと一致）。

---

## 9. 前提条件・注意 ［確定/公式手順］

- キーボードを **USB 有線モード**にする（公式手順: `FN + T` / `FN + 5`）。
- 転送中断はファーム破損の恐れ。**復旧用ブートローダの有無は未確認**。
- 書き込むのは `code_2M` 本体のみ。`param_128K` は読み出し専用。

---

## 10. macOS 検証ツール計画（ステップ①: バージョン照会のみ）

> **正確な位置づけ**: これは「ファーム書き込みを行わない」ツールであって「デバイスへ一切書き込まない」ツールではない。バージョン照会は **HID 出力レポートを実際に送信する**（decompiled.cs:1821→1618）。OTA 転送（フラッシュ書き換え）はしないので文鎮化リスクは無いが、「完全無害・読み取り専用」ではなく「**非フラッシュ・バージョン照会のみ**」と呼ぶのが正確。

手順:

1. `hidapi` で VID=0x320F / PID=0x5055 / **UsagePage=0xFFEF** のインターフェースを開く。
   - UsagePage 一致のみでは複数トップレベルコレクションを一意に選べない可能性がある（`usage` は元コードでも未使用）。列挙結果ごとに usage / report 長 / path / serial を記録し一意性を確認する。
   - 出力レポート長が最低 64B、入力レポート長が最低 12B あることを確認する。
2. バージョン照会レポートを送信（全長 = 出力レポート長で書く）: `[05][01 00 00][FF×29][00…]`。**`hid_write` の長さは 32 でなくレポート全長**。
3. 応答 `[05 01 08 00 <ver4> <crc4>]` を受信できるか確認（タイムアウト・最大応答件数・切断時処理を実装）。
   - **report_id の扱い**: Windows 受信バッファは先頭 `0x05`。macOS/hidapi では read 結果に report_id が含まれるか否かが API 依存。両解釈を曖昧に自動受理せず、実測で先頭バイト構成を記録して判定すること。

このツールで**実証できること**: デバイス選択が正しい／出力レポート送信が通る／バージョン応答を受信でき、そのバイト配置（`05 01 08 00 …`）が読解どおり。
このツールで**実証できないこと**: START/DATA の ACK 頻度・内容・遅延、END 完了応答（`05 02 03 00 06 FF 00`）の挙動。これらは②実装時に別途検証が要る。
（注: バージョン応答は 8B ペイロードを持つ「応答」であり、OTA データ転送時の「ACK」とは別物。）

---

## 11. 未確定事項・要検証

1. `OutputReportByteLength` / `InputReportByteLength` の実値（実機HID caps依存。レポートの総長・パディング量に影響）。
2. ACK が「1送信=1入力レポート」で返る前提の妥当性（DATA中のACK内容は未検査）。
3. `report_id` が出力・入力で同一(5)か。入力レポートの先頭バイトがreport_idか否か（hidapi ではreport_id有無で読み取りバッファ解釈が変わる）。
4. START ペイロード `0xFF01`（一般的Telinkは0xFF00の例が多い）の差異が機種固有仕様か。
5. 末尾チャンクのパディング（0xFF）と `sen[1]` 未計上の余剰パケット破棄ロジックの解釈が正しいか。
6. バージョン照会 `WRITE(len=32)` と OTA `WRITE(len=OutputReportByteLength)` で len 指定が異なる点の影響。
7. UsagePage一致のみで対象インターフェースを一意に選べるか（同一VID/PIDで複数コレクションがある場合）。

---

## 12. 独立検証の結果（2026-07-11）

逆コンパイル済み C# とバイナリを用いて独立に再照合した。**Critical 指摘なし。核心は全て一致で確認済み。**

### 再計算で一致を確認（テストベクタは正しい）
- `source_bin_size = 128628 (0x1F674)`、パディング後チャンク数 `8040`
- CRC: index 0=`0xCC80` / index 1=`0x11B1` / index 8039=`0xC487` … 仕様書と一致
- END payload `02 FF 67 1F 99 E0`（last=0x1F67, inv=0xE099）… 一致
- 本体末尾CRC `A4 0F 02 01` = LE `0x01020FA4` … 一致

### 指摘を受けて本ドキュメントに反映済みの修正
- §4/§4.1: 「0埋め」は誤り。OTA は 0xFF 埋め、バージョン照会は途中まで0xFF＋以降0。`len=32` はコピー長でありUSB書込長ではない（High）。
- §4: 最小レポート長要件（出力≥64B / 入力≥12B）を明記（High）。
- §2: IID `Mouse_USB_OTA` は未使用、画面の IID ラベルは UsagePage 由来（Medium）。
- §10: ステップ①は「非フラッシュ・バージョン照会のみ」であり出力レポートは実送信する／report_id の hidapi 表現差／複数コレクション曖昧性／実証できること・できないこと、を明確化（Medium）。

### 実装時に留意（設計へ反映する事項）
- **ACK 前提の危険性（High）**: 元コードは `start_ota_flag!=0` の間、**入力レポートの内容（report_id・コマンド・長さ・順序）を検証せず**、失敗応答以外なら次パケットを送る（decompiled.cs:1560-1563）。単純な「WRITE→次read」を実装すると、古い応答・別用途の入力・重複レポートでも転送が進む。②実装では応答の妥当性（少なくとも report_id と形状）を検証してから進めること。
- **コマンド階層（Low）**: 最上位コマンドは `1=バージョン照会` / `2=OTA` の2種。START/DATA/END は「OTA(=2)」内の形式・サブコマンド（START/END は sen[3..]=0xFF01/0xFF02 で区別、decompiled.cs:1663-1664/1716-1717）。「4コマンド」は便宜表現。
- **macOS で開ける前提（Low）**: UsagePage 0xFFEF は確定だが、macOS の権限・排他・ドライバ取得・hidapi バックエンド挙動は Windows 逆コンパイルからは確定できない［推定］。ステップ①で実機確認する。

---

## 13. ステップ①実機検証の結果（2026-07-12・IQUNIX MG65 実機で確認） ［確定・実機］

有線モードの実機に対し macOS から検証。**プロトコル読解・デバイス選択・出力レポート送信・応答受信のすべてを実機で裏取り済み**。§10/§11 の未確定事項を以下のとおり解消した。

### デバイス識別（実測）
- OTA インターフェースは **`DevSrvsID:4295829249`（IORegistryEntryID=4295829249）**、UsagePage=0xFFEF。物理的には **interface 2** で、キーボード(0x0001/0x0006)・consumer(0x000C) など複数トップレベルコレクションと**同一インターフェースを共有**（同一 RegID）。
- VIA が使う raw HID は別インターフェース（UsagePage=0xFF60, interface 1, 単独）。OTA とは別物。

### macOS アクセス方式（§11-7／§12「macOS で開ける前提」への確定回答）
- **hidapi(cython-hidapi) は使えない**: mac 既定で seize(排他)オープンするため、キーボード同居インターフェースで `IOHIDDeviceOpen(SeizeDevice)` が `kIOReturnNotPrivileged(0xE00002C1)` となり「open failed」。これが当初の誤診の原因だった。
- **正解は IOKit 直叩き + `kIOHIDOptionsTypeNone`（非 seize）でオープン**。root 不要。システムが排他保持しているのは別インターフェース(interface 0, RegID …245)で、OTA インターフェース(RegID …249)は seize せず開ける。
- **レポート送受信には TCC「入力監視(Input Monitoring)」権限が必須**。無いと `IOHIDDeviceSetReport` が `kIOReturnNotPermitted(0xE00002E2)`。ツールを起動するアプリ（Terminal.app 等）に入力監視を付与すれば非 root で送受信可能。**Ghostty など未付与のアプリからは送信不可**。
- 実装は `version_query_iokit.py` を参照（IOHIDManager 列挙→RegID一致でデバイス特定→open(None)→SetReport(output,id=5)→InputReportCallback+RunLoop で受信）。

### バージョン照会 応答（実測・§11-3「report_id の表現」への確定回答）
```
送信: SetReport(output, reportID=5, [05 01 00 00 FF×28 00...], 64B) -> 0x00000000 OK
受信(input report): id=5, len=64, data = 05 01 08 00 00 00 00 00 f2 4b 1e 39 ff ff ff ff ...
```
- **入力バッファは report_id 込み表現**（先頭バイト=0x05）。§6 の `[05 01 08 00 <ver4> <crc4>]` に完全一致。
- 現在デバイスに載っている FW: **Version=0x00000000 / CRC=0x391E4BF2**（.exe 同梱 `code_2M` の CRC 0x01020FA4 とは別ビルドなので不一致は正常）。

### ステップ②実機書き込み 成功（2026-07-12・IQUNIX MG65 実機） ［確定・実機］
- 動機: VIA 最新版でエラーが出るため V0120 へ更新。
- `magi65_ota.py --flash` で全 8040 チャンクを送信し完走。**書き込み前 CRC=0x391E4BF2 → 書き込み後 CRC=0x01020FA4**（V0120 本体CRCと一致）を `--check` で確認し、更新成功を確定。
- **ACK 挙動（実機観測）**: デバイスは受信レポートをそのままエコーバックする。START ACK=送信 START（`05 02 02 00 01 FF…`）、DATA#0 ACK=送信 DATA#0（`05 02 3C 00 …`）。「1送信=1入力レポート」のペーシング前提は実機で正しく機能。
  - **注記（2026-07-26 追記）**: この完全一致エコーは**旧ファーム（CRC=0x391E4BF2）での挙動**である。書き込み後の V0120 では一部バイトがマスクされる（後述「V0120 での ACK 挙動の変化」）。
- **END 完了応答（実機確認）**: `05 02 03 00 06 FF 00`（result=index6=0 → OTA Success）。§6 の読解と完全一致。
- 上記により、以下「未実証」だった ACK・END 完了応答の挙動は実機で確認済み（NAK 形式は今回エラーが出なかったため依然未観測）。in-place/staged の別は、今回正常完了したため実害なく決着。

### V0120 での ACK 挙動の変化（2026-07-26・同一実機） ［確定・実機］

V0120 が載った状態（CRC=0x01020FA4）で同一イメージの `--flash` を再実行したところ、**DATA#0 の ACK エコー不一致で中止（code=11）**した。観測用スクリプトで生バイトを取得した結果は以下。

```
DATA#0 送信 offset 46: 4b     ← body[32]。Telink ブートマジック "KNLT" の先頭バイト
DATA#0 応答 offset 46: ff
```

- 応答は 7.3ms で返っており、タイムアウトではない。**64 バイト中この 1 バイトのみが `0xFF` に置換**され、他 63 バイトは完全一致。
- START の ACK は完全一致。version 照会・START・DATA#0 のいずれでも余分な入力レポートは観測されず、「1送信=1入力レポート」の前提は維持されている。
- 解釈［推定・信頼度高］: OTA 完走まで新イメージを起動対象と認識させないため、ブートマジックを未書き込み（`0xFF`）のまま保持し、格納内容をそのままエコーしている。
- **OTA 応答はデバイス側ファームの実装であり、版によって変わる**。上記 2026-07-12 の完全一致エコーは旧ファームでの観測であって、V0120 には当てはまらない。
- 公式ツールは ACK 内容を一切検証しない（本節「ACK 前提の危険性（High）」参照）ため、この差異の影響を受けない。厳密なエコー照合を行う本ツールだけが停止した。
- **対応**: `ack_is_echo` に `maskable_ranges` を追加し、DATA のデータ部（report offset `6+20k` から `CHUNK` バイト、k=パケット番号）に限り `0xFF` への置換を許容。フレームヘッダ・パケット index・パケット CRC は厳密照合を維持し、古い応答・重複レポート・順序ずれの検出能力は保つ。
- **検証（2026-07-26・同一実機で書き込み完走）**: 上記対応を入れて `--flash` を再実行し、V0120 から V0120 への同一イメージ上書きが完走した。
  - マスクは**全 2680 レポート中 1 バイトのみ**（`DATA idx=0 offset=46(body[32])`）。ブートマジック以外はマスクされない。
  - END 完了応答は V0120 でも `05 02 03 00 06 FF 00`（`[PASS] OTA Success`）。旧ファームから変わっていない。
  - 書き込み後の再列挙・CRC 照合も通過（`0x01020FA4`）。
  - これにより、V0120 で変わっていたのは **DATA ACK のブートマジック 1 バイトのみ**と確定した。
- **CRC 照合の限界（この検証について）**: 書き込み前後とも CRC は `0x01020FA4` であり、同一イメージ上書きでは CRC 一致は「書けたこと」の証明にならない。実際の証拠は、全 8040 チャンクの ACK 一致と END の完了応答である。

### 未実証（②書き込み実装で検証が要る事項・据え置き）
- START/DATA/END の ACK 頻度・内容・遅延、END 完了応答 `05 02 03 00 06 FF 00` の挙動（§10 記載どおり①では実証不可）。
- `OutputReportByteLength`/`InputReportByteLength` の実値（今回 64B 固定で送受信は成立したが、DATA 最大3パケット時の下限確認は②で）。
- **文鎮化リスクは②で初めて発生する**（①はフラッシュ非書換）。復旧用ブートローダの有無は依然未確認。

### ステップ②書き込みツールの実装状況（2026-07-12・ドライランまで）
- 本ツールは §7 のシーケンス（START→DATA→END）を IOKit 直叩き（§13 の open(None) 方式）で送信する。デバイス選択は IOKit の `DeviceUsagePairs` 列挙で 0xFFEF を特定して open する。
- ペイロード/レポート組み立ては純粋関数化し、ビルダーのテスト が §8 の既知ベクタ（CRC・addr・START/DATA/END・パディング）に一致することを検証。さらに全 8040 パケットの addr/data/CRC を網羅照合（全 PASS）。
- 逆コンパイル C# の `ota_write()` ループと突き合わせ、境界（index 8039 で停止・超過パケット破棄）と END（last=0x1F67/inv=0xE099）が byte 単位で一致することを確認。
- 転送ループを `run_transfer()` に分離し、擬似デバイスで制御フロー（START 1回→DATA 2680レポート=全8040チャンクを昇順で過不足なく→END→完了判定、ACK 不正時の即中止）を 転送のテスト で検証（実機不要・全 PASS）。
- `--flash` は `caffeinate` を内蔵起動し転送中のスリープ/ディスプレイ休止を抑止する。
- **安全ゲート**: 既定はドライラン（デバイス非接触）。`--check` は非フラッシュ疎通確認。`--flash` は `--i-understand-brick-risk` フラグ＋対話で大文字 `FLASH` 入力の二重確認が必須。
- **実書き込みは未実行**（ユーザーの明示 Go 待ち）。高強度コードレビューを実施し、CONFIRMED 正確性バグ（破損/切り詰めファームのサイレント受理、report_len<64 のサイレント肥大化、size=0 での START 後クラッシュ）を修正済み。回帰テスト追加済み。
- **ACK 検証の既知の限界**: DATA 転送中の ACK/NAK 内容フォーマットは未解析（実機観測でのみ判明）。実書き込み時に観測し NAK 形式が判明したら判定を厳格化すること。
  - **注記（2026-07-26 追記）**: ここで予定していた「START/DATA ACK と END 応答の生バイトダンプ」は実装されなかった。代わりに、`run_transfer` が ACK のデータ部で 0xFF にマスクされたバイトを検出し、初回位置と合計バイト数をログに出す（「V0120 での ACK 挙動の変化」を参照）。NAK 形式は依然として未観測。

### 実 HID レポート長（§11-1 の未確定点の確定・2026-07-12 実機実測）
- OTA デバイス（RegID 4295829249）の IOKit プロパティ: **MaxOutputReportSize=64 / MaxInputReportSize=64 / MaxFeatureReportSize=64**（open 不要のプロパティ読みで取得）。
- 既定 report_len=64 が実機と一致。`magi65_ota.py` は `--flash` 時に report_len と MaxOutputReportSize の一致を検証し、不一致なら書き込みを中止する。

### 独立検証（第2回）の結果（2026-07-12・実装＋解析の再検証）
逆コンパイル C# と code_2M.bin を用いて独立に再照合した。**§3〜§8・crc16・8040パケット境界（index0=0xCC80/index1=0x11B1/index8039=0xC487）・END 値・独立再計算値はすべて「一致」で確認。Critical ゼロ。** ビルダー純粋関数も一致判定。

指摘（いずれも「START 送信後に転送が中断して未完了化する」経路の防御。実装済み）:
- High: 16-bit index を超える巨大イメージを START 前に拒否（`extract_firmware` でチャンク数>65536 を例外化）。
- High: 本体末尾CRC が 0/0xFFFFFFFF のイメージを START 前に拒否（`check_bin_is_ok` 相当を再現）。
- High: ACK 待機が keyboard 同居インターフェース由来の無関係な入力レポート（キー入力等）で誤終了しないよう、report_id=5 以外は無視して待機継続（コールバックでフィルタ）。
- Medium: report_len を実 MaxOutputReportSize と照合し不一致ならフラッシュ中止。

これらの回帰テストは `test_ota_builder.py`（末尾CRC無効・16-bit超過の拒否）に追加済み。

**再レビュー（同日・上記修正の検証）**: 4修正はすべて有効・退行なし、解析(§3〜§8)とビルダーの一致も維持と確認。追加で 2 件の START 前検証の穴を指摘・修正:
- High: `size < 4` のイメージは末尾CRCスライスがヘッダに食い込むため無条件拒否（High#2 修正の詰め残し）。
- Medium: `MaxOutputReportSize` が取得不能(None/0)な場合も「検証不能」として書き込み中止（`flash_report_len_ok()` に集約、取得失敗＝不許可）。

いずれも異常入力・異常環境のみに関わり正常運用パス（128628 byte・正規CRC・64byte レポート）には影響しない。回帰テスト追加済み（size<4 拒否、report長判定）。
