# edinet-fraud-screening

EDINET(金融庁の電子開示システム)から日次で提出書類一覧を取得し、
「訂正報告書」に該当する書類を抽出してローカル(CSV/SQLite)に蓄積するツール。

不適切会計スクリーニングの一次データ収集フェーズを想定した最小構成です。
クラウドは使わず、ローカル実行・無料枠のみで完結します。

## 前提: EDINET APIキーの取得

EDINET API (v2) は無料ですが、利用にはAPIキー(Subscription-Key)の発行が必要です。

1. [EDINET](https://disclosure2.edinet-fsa.go.jp/) で利用者登録
2. マイページからAPIキーを発行
3. 本リポジトリ直下に `.env` を作成し、以下を記載(`.env.example` を参照)

```
EDINET_API_KEY=発行されたキー
```

`.env` は `.gitignore` 対象なのでコミットされません。

## セットアップ

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows(Git Bash)の場合
pip install -r requirements.txt
```

## 使い方

直近7日分を取得(デフォルト):

```bash
python src/fetch_documents.py --days 7
```

期間を指定:

```bash
python src/fetch_documents.py --start 2026-08-01 --end 2026-08-12
```

出力形式を指定(`csv` / `sqlite` / `both`、デフォルトは `both`):

```bash
python src/fetch_documents.py --days 7 --format sqlite
```

## 出力

- `data/amendments_<start>_<end>.csv`: 訂正報告書のみのCSV
- `data/edinet.db`: SQLite (`amended_documents` テーブル、`docID` で重複排除)

いずれも `data/` 配下に出力されますが、生データはリポジトリにコミットしません(`.gitignore` 参照)。

## 「訂正報告書」の判定方法

EDINETの `docTypeCode` は訂正版ごとに個別のコードが振られており
(例: 130=訂正有価証券報告書, 150=訂正四半期報告書 等)、種別ごとに列挙すると漏れが出やすいため、
本ツールでは `docDescription`(書類概要)に「訂正」という文字列を含むかどうかで判定しています。

## Phase 2: ローカルLLMによる訂正理由の一次分類

[LM Studio](https://lmstudio.ai/) でモデル(例: Qwen3-14B)をロードし、Developerタブでローカルサーバー
(デフォルト `http://localhost:1234`)を起動した状態で実行する。外部APIは使わず、完全ローカル・無料。

```bash
python src/classify_amendments.py --limit 10
python src/classify_amendments.py --limit 10 --model qwen3-14b
```

- 入力: `data/edinet.db` の `amended_documents`
- 出力: `data/classified_amendments.csv` に **追記**(`docID`で重複判定、分類済みはスキップ)
- 分類軸:
  - `importance`: "重要"(決算数値・会計処理に関わる) / "軽微"(誤字・形式的)
  - `reason`: 分類理由の一言
- 判断がつかない場合は安全側("重要")に倒す設計

### 既知の限界

`docDescription`(書類概要)は「訂正有価証券届出書（内国投資信託受益証券）」のような定型タイトルのみで、
訂正内容の詳細が書かれていないことが多い。そのため現状は大半が"重要"判定になりやすい。
件数を拡大する前に、書類本文(XBRL/PDF)まで読ませる、または"要確認"ラベルを追加するなどの改善を検討中。

## 今後の拡張(ロードマップ)

- Phase 1: 収集・一次スクリーニング(EDINET訂正報告書の日次取得) ← 完了
- Phase 2: 軽量LLMによる訂正理由の一次分類 ← 進行中(10件サンプルで検証済み)
- Phase 3: 監査基準・過去事例のRAG
- Phase 4: kabu-dashboardへの統合
- Phase 5: マルチエージェント協働
