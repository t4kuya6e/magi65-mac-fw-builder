# magi65-mac-fw-builder 設計ドキュメント

| | |
|---|---|
| 対象 | IQUNIX Magi65 の macOS 向け OTA ファーム書き込みツールを、ソース公開できる形に再構成する |
| 作成日 | 2026-07-12 |
| 前提資料 | `docs/OTA_PROTOCOL.md`（プロトコル仕様・実機検証結果） |
| 状態 | 設計承認済み。本ドキュメントのレビュー後、実装計画（writing-plans）へ |

## 1. 目的と非対象

### 目的
macOS 標準の `python3` だけで動く、ソース公開の CLI ツールを作る。ユーザーは自分の機種の公式ファーム更新 `.exe` を IQUNIX から入手し、そこからファームを抽出して Magi65 に USB HID OTA で書き込む。

### 非対象（YAGNI）
- コード署名・notarization（ソース公開のため不要）
- GUI
- ファームウェア本体（`code_2M`）のリポジトリ同梱（権利上の理由で行わない）
- Magi65 以外の機種対応。安全のため Magi65 固定識別値（VID/PID/UsagePage/ReportID）と一致しない updater・デバイスは明示的に拒否する（他機種への汎用フラッシャー化を避ける）

## 2. 全体構成

現行プロトタイプは診断用に 3 スクリプト（`probe_open.py` / `version_query_iokit.py` / `ota_flash.py`）へ IOKit バインディングが重複している。配布版ではこれを共有モジュールへ集約する。

| ファイル | 役割 |
|---|---|
| `iokit_hid.py` | IOKit(ctypes) 共有層。デバイス列挙・open(None)・SetReport・入力レポート待ち（report_id フィルタ）・レポート長取得 |
| `firmware.py` | `.exe`/`.exe.zip` からのファーム抽出、ビルダー純粋関数、検証ゲート |
| `magi65_ota.py` | CLI 本体。抽出→検証→check/dry-run/flash と安全ゲート |
| `tests/` | 実機不要の純粋ロジックテスト |
| `README.md` / `README_ja.md` | 前提・手順・リスクと復旧の注意（英語版 / 日本語版。内容は同一） |
| `LICENSE` | MIT |

### 2.1 依存関係
ゼロ依存とする。現行が列挙にのみ使う `hidapi`（pip）を廃止し、列挙も IOKit の `DeviceUsagePairs` プロパティ解析で行う。ユーザーは `git clone` 後に `python3 magi65_ota.py` で即実行できる（pip/venv 不要）。

## 3. モジュール詳細

### 3.1 `iokit_hid.py`
- IOKit/CoreFoundation の ctypes シグネチャを一元定義（現行で 3 箇所に重複していたものを 1 箇所へ）。
- `find_ota_devices(usage_page)`: VID/PID 一致デバイスの `DeviceUsagePairs`（CFArray of CFDictionary）を走査し、指定 UsagePage を含むコレクションの `IOHIDDevice` を**すべて**返す（RegID で重複排除）。**一意性の担保（レビュー指摘 Medium#4）**: 呼び出し側は候補が 0 件ならエラー、2 件以上（例: Magi65 を複数接続）なら serial/LocationID/RegID を表示して flash 不可とし、一意になる再接続を促す。ちょうど 1 件のときのみ続行。
- `OtaDevice`: `open()`（`kIOHIDOptionsTypeNone`）、`send_and_wait(report)`（SetReport 出力→入力レポート待ち。report_id≠5 の入力は無視して待機継続）、`close()`（unschedule 込み）、`max_output_report`/`max_input_report` を保持。

### 3.2 `firmware.py`
- `extract_from_exe(path)`: `.exe` または `.exe.zip` を受け取り `code_2M`・`param_128K` を取り出す。**抽出の堅牢性（レビュー指摘 Medium#6）**: magic `0xBEEFCACE` の単純検索は別リソースや偶然一致を拾う危険があるため、.NET マネージドリソース（`.resources` ストリーム）を構造的にパースし、名前 `code_2M`/`param_128K` の 2 エントリが型・妥当な長さ込みで**一意に揃う場合のみ**受理する。曖昧な場合、および ZIP 内に複数 EXE がある場合は明示的に拒否する。
- `parse_param(param)`: `param_128K` から VID/PID/ReportID/UsagePage を読む。ただし**識別値の置換には使わない**（下記ゲート参照）。
- ビルダー純粋関数: `crc16` / `source_bin_size` / `extract_firmware` / `data_packet` / `start_report` / `data_report` / `end_report` / `version_query_report`（現行 `ota_flash.py` から移設）。
- 検証ゲート（すべて書き込み開始前）:
  - **Magi65 固定識別条件をハードゲートにする（レビュー指摘 High#1）**: VID=0x320F / PID=0x5055 / UsagePage=0xFFEF / ReportID=5 を既知定数として保持し、抽出した `param_128K` の値がこれと一致することを必須化。不一致（＝別機種の updater を渡した等）は明示拒否する。**param 由来化は安全性を下げるため採らない**（他機種 updater が自己整合して汎用フラッシャー化するのを防ぐ）。
  - 本体サイズ ≥ 4、宣言サイズと実データ長の整合、チャンク数 ≤ 65536（16-bit index）。
  - **本体整合性の限界（レビュー指摘 High#3）**: 本体末尾 CRC が `0x00000000`/`0xFFFFFFFF` でないことを確認する（元ツール `check_bin_is_ok` 相当）。ただし**元ツール自身が bin_crc を本体から再計算していない**（decompiled.cs は 0/0xFFFFFFFF 判定のみ）ため、これ以上の CRC 再計算による破損検出は原理的に不可能。
  - **ヘッダ検証（レビュー指摘 Medium#2・実測に基づき具体化）**: `code_2M` ヘッダは 256 バイト、本体は offset 256 以降。**ハードゲート**とするのは (i) ヘッダ長 256 の構造、(ii) サイズフィールド `[48:52]` の BE 解釈が上記サイズ検証を満たすこと、の 2 点のみ。加えて `[0:48]` が実測で `0x56` フィラー 48 バイトである点は **WARN レベルの健全性表示**に留める（将来の正規 updater でフィラーが変わった場合に過剰拒否しないため、hard reject にしない）。`[52:256]` は用途未解明のため検証対象にしない。破損検出のハードゲートは「named-resource 一意抽出＋サイズ/16-bit/bin_crc≠0,0xFFFFFFFF＋Magi65 識別値一致」に限定し、この限界を README に明記する。

### 3.3 `magi65_ota.py`
- 入力: `--exe <path>`（必須。抽出元の公式ファイル）。
- モード:
  - 既定（引数なし）= ドライラン。抽出・検証・送信予定シーケンス表示のみ。デバイスに触れない。
  - `--check` = 非フラッシュ。バージョン照会で現 CRC を表示。
  - `--flash` = 実書き込み。`--i-understand-brick-risk` フラグと対話での大文字 `FLASH` 入力の二重確認が必須。
- 安全策: 接続デバイスの VID/PID が**Magi65 固定値**と一致することを確認、候補一意性の確認、実 `MaxOutputReportSize` と report 長の一致確認、`caffeinate` 起動、`SetReport` が `kIOReturnNotPermitted` の場合は入力監視権限の付与を案内。
- **ReportID 能力の実地確認（レビュー指摘 High#1 残・tuple 4要素目）**: 接続デバイスの ReportID=5 対応を列挙プロパティだけで断定せず、`--flash` では **START 送信前に内部でバージョン照会（report_id=5 の出力→入力往復）を実行し、正常な report_id=5 応答が得られなければ START 前に中止**する。これで ReportID=5 の入出力能力と生存性を実地に確認してから不可逆操作へ進む（照会は非フラッシュ）。
- **ACK 検証（レビュー指摘 High#2）**: 実機で ACK は直前送信レポートのエコーバックと確認済み（`docs/OTA_PROTOCOL.md` §6.2）。START/DATA は「受信入力レポートが直前送信レポートと一致（受信長・内容）」を正常 ACK の条件とし、一致しなければ中止する。ただし DATA のデータ部のみ `0xFF` への置換を許容する（V0120 以降はブートマジックをマスクして返すため。`docs/OTA_PROTOCOL.md` §6.2）。END のみ完了応答形式 `05 02 03 00 06 FF <result>` を検証し `result==0` で成功。report_id=5 の遅延応答・エラー応答で次パケットへ進まないようにする。
- **書き込み後の検証ライフサイクル（レビュー指摘 Medium#5）**: END 成功後にデバイスがリセット・再列挙する可能性があるため、旧ハンドルを close し、切断を許容したうえで期限付きで再列挙・再 open を試行してから、CRC を抽出ファームの末尾 CRC と照合して成否を確定する（旧ハンドルへの即時照会だけで失敗扱いしない）。

## 4. データフロー

```
--exe <公式ファイル>
  → リソース抽出 (code_2M / param_128K を一意に特定)
  → param の VID/PID/ReportID/UsagePage が Magi65 固定値と一致するか検証（不一致は拒否）
  → code_2M から本体・末尾CRC
  → 検証（サイズ≥4 / 整合 / 末尾CRC≠0,FFFFFFFF / 16-bit / ヘッダ長256・サイズ場所。フィラーはWARN）
  → デバイス列挙（候補が一意か。0/複数は拒否）→ 接続デバイス VID・PID が Magi65 固定値と一致
  → --check（現CRC表示） → --flash（二重確認）
      → START 前に内部バージョン照会（report_id=5 往復）で ReportID 能力・生存性を確認、不正なら中止
      → START → DATA×N → END
        （各 ACK は直前送信のエコー一致を検証、END は完了応答形式を検証）
  → END 後: 旧ハンドル close → 再列挙・再open（期限付き）→ CRC を抽出ファーム末尾CRCと照合し成否確定
```

## 5. テスト（実機不要・純粋ロジック）
- 抽出: 既知の公式 `.exe` から `code_2M`/`param_128K` を一意抽出し、`source_bin_size=128628`・末尾 CRC `0x01020FA4`、param の VID/PID/ReportID/UsagePage が Magi65 固定値に一致。曖昧な入力・複数 EXE の ZIP を拒否。
- ビルダー: `OTA_PROTOCOL.md` §8 の既知ベクタ（index 0/1/8039 の CRC・START/DATA/END）と、全 8040 パケットの addr/data/CRC 網羅照合。
- 検証ゲート: サイズ<4 / 切り詰め / 末尾CRC 0・0xFFFFFFFF / 16-bit 超過 / **param が Magi65 固定値と不一致** の各拒否。ヘッダ長256・サイズ場所の構造確認、`[0:48]==0x56*48` の正例（フィラー不一致は WARN で拒否しないことも確認）。
- 転送制御フロー: 擬似デバイスで START 1 回→DATA 2680 レポート（全チャンクを昇順で過不足なく）→END→完了判定。**ACK エコー検証**（受信が直前送信と一致すれば継続、不一致・遅延・エラー応答なら即中止）。**START 前バージョン照会ゲート**（擬似デバイスが不正な version 応答を返す場合は START を送らず中止）。
- report 長判定: `flash_report_len_ok` の一致/不一致/未取得。

## 6. 実機で 1 回だけ必要な確認
- 列挙を IOKit 化したため、実機（Magi65）で `--check` が従来どおり通ること（デバイス特定→open→バージョン応答）を 1 回確認する。書き込みは伴わない。

## 7. リスクと免責（README に明記）
- OTA 書き込みは不可逆。中断・失敗でキーボードが文鎮化する恐れがある。
- 復旧の容易な手段（ユーザー操作の DFU 等）は確認されていない。ハード（Telink BDT・基板端子）での救済は可能性があるが未確認で、分解と専用機材を要する。
- ツールの送出データはプロトコル解析と実機 1 台での成功に基づくが、全機体・全状況での安全を保証しない。**自己責任での使用**とする。
- 機種変種の不一致は文鎮化に直結する。本ツールは Magi65 固定識別値と一致しない updater/デバイスを拒否するが、これは同一 VID/PID を持つ変種違いまでは判別できない。必ず自分の機種の公式ファイルを使うこと。
- **本体整合性検証の限界**: 元の公式ツールは本体末尾 CRC を再計算せず 0/0xFFFFFFFF のみ拒否する。本ツールも同水準までしか検証できず、有効値を持つ破損イメージは検出できない。抽出の一意性・ヘッダ不変条件・識別値一致で補うが、完全な破損検出ではない。

## 8. 配布形態
自己完結した 1 ディレクトリ `magi65-mac-fw-builder/` を新規 GitHub リポジトリとして公開できる形にする。ライセンスは MIT（ファーム非同梱のため問題なし）。
