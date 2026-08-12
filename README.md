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

## 今後の拡張(ロードマップ)

- Phase 1: 本リポジトリ(収集・一次スクリーニング) ← 現在ここ
- Phase 2: 軽量LLMによる訂正理由の一次分類
- Phase 3: 監査基準・過去事例のRAG
- Phase 4: kabu-dashboardへの統合
- Phase 5: マルチエージェント協働
