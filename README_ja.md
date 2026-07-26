# magi65-mac-fw-builder

*[English version](README.md)*

IQUNIX Magi65（ANSI/CSF6C4）向けの macOS ネイティブ OTA ファームウェア書き込みツール。

macOS 標準の `python3` と `ctypes`（IOKit 直叩き）のみで動作し、追加パッケージのインストール（pip/venv）を必要としません（ゼロ依存）。

## 前提

- macOS。
- `python3`。macOS 標準の `/usr/bin/python3`（Command Line Tools 同梱、Python 3.9 以降）で動作します。`python3` が PATH に無く `command not found` になる場合は、以下のコマンド例のように絶対パス `/usr/bin/python3` を使ってください（pyenv/Homebrew の python3 でも可）。
- 実行するターミナルアプリ（Terminal.app など）に「システム設定 > プライバシーとセキュリティ > 入力監視（Input Monitoring）」の権限を付与していること。権限が無いと HID レポート送信が `kIOReturnNotPermitted` で失敗します。
- キーボードを **USB 有線モード**にしていること（`FN + T` または `FN + 5`）。無線（Bluetooth/2.4GHz）接続では OTA インターフェースが出てきません。

## 実行手順

以下は上から順に実行する想定の手順です。コマンド例の `python3` が `command not found` になる場合は `/usr/bin/python3` を使ってください（前提参照）。

### 0. 取得とセットアップ

```
git clone https://github.com/t4kuya6e/magi65-mac-fw-builder.git
cd magi65-mac-fw-builder
```

続いて、実際にコマンドを実行するターミナルアプリ（Terminal.app 等）へ **入力監視（Input Monitoring）権限を付与**します。

1. 「システム設定 > プライバシーとセキュリティ > 入力監視」を開く。
2. リストに使用するターミナルアプリを追加してトグルを ON にする。
3. 権限を反映するため、そのターミナルアプリを一度終了して起動し直す。

さらに、キーボードを **USB 有線モード**にして Mac に直接接続します（`FN + T` または `FN + 5`。無線接続では OTA インターフェースが現れません）。

### 1. 公式ファームウェア更新ファイルを入手して `exe_here/` に置く

本ツールにファームウェア本体は同梱していません。IQUNIX 公式サイトから、お使いの機種（Magi65 ANSI/CSF6C4）向けの更新ツール `.exe` をダウンロードし、リポジトリ直下の `exe_here/` に置いてください。`.zip` でダウンロードした場合は展開して、中の `.exe` を置きます。

```
magi65-mac-fw-builder/
├── exe_here/
│   └── Magi65_xxxx.exe   ← 公式 .exe を 1 個だけ置く
├── magi65_ota.py
└── ...
```

**`exe_here/` に置く `.exe` は必ず 1 個だけにしてください。** 以降のコマンド例はこのファイルを `exe_here/*.exe` で参照するため、ファイル名に書き換えずそのままコピー&ペーストで実行できます。`.exe` が 2 個以上あるとコマンドは usage エラーで止まり、1 個も無い場合は `no matches found` になります。どちらもデバイスには一切触れずに終了します。

`exe_here/` の中身は `.gitignore` で除外されるため、誤ってコミットされることはありません。

### 2. ドライランで送信予定を確認する

デバイスに一切接続せず（`--check`/`--flash` を付けない既定動作）、抽出したファームウェアの検証と送信予定シーケンス（START/DATA/END レポートの内容）を表示します。まずここで抽出・検証が通ることを確認してください。

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe
```

### 3. 疎通確認（非フラッシュ）

実機に接続し、バージョン照会のみを行います。書き込み（フラッシュ）は行いません。

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe --check
```

現在デバイスに載っているファームウェアの Version/CRC が表示されれば、デバイス選択・通信経路・権限が正しく機能しています（`kIOReturnNotPermitted` で失敗する場合は入力監視権限を再確認）。書き込み後（手順 5）にこの CRC が変わることで成否を判断できるので、ここでの値を控えておくとよいです。

### 4. 書き込み（フラッシュ）

**不可逆操作です。下記「リスクと免責」を必ず読んでから実行してください。**

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe --flash --i-understand-brick-risk
```

- 実行後、大文字で `FLASH` と入力することを求められます（誤操作防止の二重確認）。
- 書き込み中はスリープ・ディスプレイ休止を抑止するため `caffeinate` を内蔵起動します。
- **書き込み中はキーボードやケーブルに触れない**でください。中断はファームウェア破損の恐れがあります。
- 成功すると `OTA Success` と表示され、続いて自動でファームウェア CRC を照合します。

### 5. 書き込み後の確認

手順 4 の完了後、CRC が入手した公式ファームのものに変わっていることを確認します（`--flash` 内でも自動照合されますが、手動でも確認できます）。

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe --check
```

表示された CRC が公式ファーム本体末尾の CRC と一致していれば、書き込みは成功しています。

## コマンド一覧

| オプション | 説明 |
|---|---|
| `--exe <path>` | （必須）ファームウェア入り `.exe`/`.exe.zip` のパス。`exe_here/` に `.exe` を 1 個だけ置いた場合は `exe_here/*.exe` と書ける |
| `--check` | 実機に接続してバージョン照会のみ行う（非フラッシュ） |
| `--flash` | 実機にファームウェアを書き込む（フラッシュ） |
| `--i-understand-brick-risk` | `--flash` 実行の前提となる同意フラグ |
| `--report-len <int>` | HID レポート長（既定 64） |
| `--timeout <float>` | デバイス応答待ちのタイムアウト秒数（既定 2.0） |

## リスクと免責

- OTA によるファームウェア書き込みは**不可逆**です。書き込み中の中断・失敗により、キーボードが**文鎮化（起動不能）**する恐れがあります。
- ユーザー操作による簡単な復旧手段（DFU 等）は確認されていません。ハードウェアレベルでの救済（Telink BDT・基板端子経由の再書き込みなど）は可能性がありますが未確認であり、分解と専用機材を要します。
- 本ツールが送出するデータは、公式更新ツールのプロトコル解析（逆コンパイル）と実機 1 台での書き込み成功に基づいています。**全機体・全状況における安全性は保証しません。使用は自己責任で行ってください。**
- 本ツールは Magi65 固定識別値（VID=`0x320F` / PID=`0x5055` / UsagePage=`0xFFEF` / ReportID=`5`）と一致しない updater ファイル・デバイスを拒否します。ただし、これは**同一 VID/PID を持つ機種変種の違いまでは判別できません**。必ず自分の機種向けの公式ファイルを使用してください。

### 本体整合性検証の限界

元の公式ツール（IQUNIX 製）自体が、ファームウェア本体末尾の CRC を再計算せず、値が `0x00000000` または `0xFFFFFFFF` でないことのみを確認しています。本ツールも同水準の検証にとどまり、以下で補完しますが、**これは完全な破損検出ではありません**。

- リソース抽出時に `code_2M`/`param_128K` が名前・型・サイズ込みで一意に確定すること
- 宣言サイズと実データ長の整合、チャンク数が 16-bit index の範囲内であること
- 本体末尾 CRC が `0x00000000`/`0xFFFFFFFF` でないこと
- 抽出した識別値（VID/PID/UsagePage/ReportID）が Magi65 固定値と一致すること

有効な値を持つ破損イメージ（上記チェックをすべて通過するが内容が壊れているもの）は検出できません。

## テスト

実機不要の純粋ロジックテストのみで実行できます。

```
/usr/bin/python3 -m unittest discover -s tests -v
```

公式 `.exe` を使った抽出テストは、環境変数 `MAGI65_TEST_EXE` に実ファイルのパスを設定したときのみ実行されます（未設定の場合は自動的に skip されます）。

```
MAGI65_TEST_EXE=$(echo exe_here/*.exe) /usr/bin/python3 -m unittest discover -s tests -v
```

## ドキュメント

- [`docs/OTA_PROTOCOL.md`](docs/OTA_PROTOCOL.md): USB HID OTA プロトコルの解析結果（逆コンパイル・実機検証ベース）
- [`docs/design.md`](docs/design.md): 本ツールの設計ドキュメント

## ライセンス

MIT。詳細は [`LICENSE`](LICENSE) を参照してください。
