# magi65-mac-fw-builder 設計

IQUNIX Magi65 に、macOS から USB HID OTA でファームを書き込む CLI ツールの設計。
プロトコルの仕様は `docs/OTA_PROTOCOL.md` にある。

## 1. 目的と対象外

### 目的

macOS 標準の `python3` だけで動く、ソース公開の CLI ツール。ユーザーは自分の機種の公式 updater（`.exe`）を IQUNIX から入手し、ツールがそこからファームを取り出して Magi65 に書き込む。

### 対象外

- コード署名・notarization（ソース公開のため不要）
- GUI
- ファーム本体（`code_2M`）のリポジトリ同梱（権利上の理由で行わない）
- Magi65 以外の機種。Magi65 の固定識別値（VID / PID / UsagePage / ReportID）と一致しない updater・デバイスは拒否し、汎用の書き込みツールにしない

## 2. 構成

| ファイル | 役割 |
|---|---|
| `magi65_ota.py` | CLI。抽出 → 検証 → ドライラン / `--check` / `--flash` |
| `magi65_fw_builder/constants.py` | Magi65 の固定識別値、レポート定数、書き込みを許す型番と版 |
| `magi65_fw_builder/firmware.py` | updater からの抽出、レポートを組み立てる純粋関数、検証ゲート |
| `magi65_fw_builder/iokit_hid.py` | IOKit（ctypes）の共有層。列挙、open、SetReport、入力レポート待ち |
| `magi65_fw_builder/transfer.py` | 転送の制御（バージョン照会 → START → DATA → END）と応答の検証 |
| `tests/` | 実機を使わないテスト |
| `README.md` / `README_ja.md` | 前提・手順・リスク（英語版 / 日本語版。内容は同一） |
| `LICENSE` | MIT |

依存はゼロ。列挙も IOKit の `DeviceUsagePairs` プロパティで行い、pip や venv を使わない。

## 3. モジュール

### 3.1 `iokit_hid.py`

- `find_ota_devices(usage_page)`: VID / PID が一致するデバイスの `DeviceUsagePairs` を走査し、指定の UsagePage を持つものをすべて返す（RegistryEntryID で重複を除く）
- `OtaDevice`: `open()`（`kIOHIDOptionsTypeNone` で非排他）、`send_and_wait(report)`（出力レポートを送り、report_id が 5 の入力レポートを 1 つ待つ。それ以外の入力は無視）、`close()`。`max_output_report` / `max_input_report` を持つ

### 3.2 `firmware.py`

- `extract_from_exe(path)`: `.exe` または `.exe.zip` から `code_2M` と `param_128K` を取り出す。.NET の `.resources` ストリームを構造としてパースし、2 つのエントリが名前・型・長さとも一意に揃うときだけ受け付ける。ZIP 内に `.exe` が複数あれば拒否する
- `parse_param(param)`: `param_128K` から VID / PID / ReportID / UsagePage を読む。識別値の照合にだけ使い、送信値の置き換えには使わない
- レポートを組み立てる純粋関数: `crc16` / `source_bin_size` / `extract_firmware` / `data_packet` / `start_report` / `data_report` / `end_report` / `version_query_report`
- 検証ゲート（すべて書き込み開始前）
  - `validate_identity`: `param_128K` の識別値が Magi65 の固定値と一致すること
  - `validate_firmware`: 本体サイズが 4 以上、宣言サイズと実データ長が整合、チャンク数が 65536 以下（16-bit index）、本体の末尾 CRC が `0x00000000` / `0xFFFFFFFF` でない
  - `header_filler_ok`: ヘッダ `[0:48]` が `0x56` のフィラーか。外れても警告だけにする（将来の正規 updater で過剰に拒否しないため）
  - `validate_model`（`--flash` のときだけ）: updater の `.exe` 名（ZIP なら中の `.exe` 名）の型番と版が `constants.VERIFIED_MODELS` にあること。識別値は型番違いでも同一なので、型番はファイル名でしか判別できない。`--allow-unverified-model` で明示的に通せる

### 3.3 `magi65_ota.py`

- 入力: `--exe <path>`（必須）
- モード
  - 既定 = ドライラン。抽出・検証・送信予定のレポート表示だけで、デバイスに触れない
  - `--check` = バージョン照会で、書き込まれているファームの CRC を表示する。書き込みはしない
  - `--flash` = 書き込み。`--i-understand-brick-risk` と、対話での大文字 `FLASH` 入力の両方が要る
- 安全策
  - OTA の候補デバイスがちょうど 1 台であること。0 台・複数台なら中止し、複数台なら RegistryEntryID / LocationID / シリアルを表示する
  - 開いたデバイスの VID / PID が Magi65 の固定値と一致すること
  - `--flash` では、実デバイスの `MaxOutputReportSize` / `MaxInputReportSize` が `--report-len` と一致すること。取得できない場合も中止する
  - 書き込み中は `caffeinate` でスリープを抑止する
  - `SetReport` が `kIOReturnNotPermitted` を返したら、入力監視の権限付与を案内する

### 3.4 `transfer.py`

- START の前にバージョン照会を 1 往復し、report_id 5 の正しい応答が返らなければ START を送らずに中止する
- START / DATA の ACK は送信レポートのエコーであることを検証し、一致しなければ中止する。DATA のデータ部に限り `0xFF` への置き換えを許す（デバイスが起動フラグの 1 バイトをマスクして返すため。`OTA_PROTOCOL.md` §6.2）。置き換えがあれば位置と合計バイト数をログに出す
- END は結果応答 `05 02 03 00 06 FF <code>` の形を検証し、`code == 0` で成功とする。それ以外は code を表示して失敗とする
- 書き込み後は旧ハンドルを閉じ、期限付き（10 秒）で再列挙・再 open・バージョン照会を繰り返す。CRC が抽出したファームの末尾 CRC と一致した時点で成功とする。再接続の直後は旧ファームの CRC が返ることがあるため、1 回の不一致では失敗にしない

## 4. データフロー

```
--exe <公式ファイル>
  → リソース抽出（code_2M / param_128K を一意に特定）
  → param の識別値が Magi65 の固定値と一致するか
  → code_2M から本体と末尾 CRC を取り出し、検証
  → ドライラン: 送信予定のレポートを表示して終了
  → --check / --flash: デバイス列挙（1 台であること）→ open → VID / PID の確認
      --check: バージョン照会 → CRC を表示
      --flash: 型番・版の確認 → 二重確認 → レポート長の確認
               → バージョン照会 → START → DATA × N → END（各 ACK を検証）
               → 再列挙して CRC を照合
```

## 5. テスト（実機不要）

- 抽出: 公式 updater からの一意抽出（環境変数 `MAGI65_TEST_EXE` があるときだけ）、曖昧な入力と複数 `.exe` の ZIP の拒否
- レポートの組み立て: `OTA_PROTOCOL.md` §8 のテストベクタ（index 0 / 1 / 8039 の CRC、START / DATA / END）と、全パケットの addr / data / CRC の照合
- 検証ゲート: サイズ < 4、切り詰め、末尾 CRC が 0 / `0xFFFFFFFF`、16-bit 超過、識別値の不一致、型番・版の未確認（ZIP は中の名前で判定、`--allow-unverified-model` で通る、ドライランと `--check` には掛からない）
- 転送の制御: 擬似デバイスで START 1 回 → 全チャンクを昇順で過不足なく → END → 完了判定。ACK の不一致・応答なし・不正な応答での中止、起動フラグのマスクの許容、START 前のバージョン照会での中止
- レポート長の判定: 一致 / 不一致 / 取得できない

## 6. リスク

- 書き込み中に止まった場合の挙動は、デュアルバンク方式なので旧ファームで起動する見込み（`OTA_PROTOCOL.md` §9）。ただし実機で中断を試してはいない
- 送出データはプロトコル解析と実機での書き込みに基づくが、全機体・全状況での安全は保証しない。自己責任で使う
- 本体の整合性は、公式ツールと同じく末尾 CRC が 0 / `0xFFFFFFFF` でないことしか確かめられない。有効な値を持つ破損イメージは書き込み前には検出できない（書き込み中は、デバイスがパケットごとの CRC16 を検査する）

## 7. 配布

リポジトリ `magi65-mac-fw-builder` を GitHub で公開する。ライセンスは MIT（ファームを同梱しないため）。
