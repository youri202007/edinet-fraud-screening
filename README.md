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
python src/classify_amendments.py --limit 10 --no-pdf   # PDF本文を読まず、書類概要のみで分類(旧方式)
```

- 入力: `data/edinet.db` の `amended_documents`
- 出力: `data/classified_amendments.csv` に **追記**(`docID`で重複判定、分類済みはスキップ)
- 分類軸:
  - `importance`: "重要"(決算数値・会計処理に関わる) / "軽微"(誤字・形式的)
  - `reason`: 分類理由の一言
- 判断がつかない場合は安全側("重要")に倒す設計

### PDF本文の取得と抽出

`docDescription`(書類概要)だけでは「訂正有価証券届出書（内国投資信託受益証券）」のような定型タイトルしか
分からず、訂正内容の詳細が書かれていない。そこでEDINETの書類取得API(`type=2`, PDF)から本文を取得し、
「【○○の提出理由】」のような角括弧見出しを検出して、その周辺(訂正前後の数値対比表を含む)を抜粋してLLMに渡す。

- PDFは `data/documents/{docID}.pdf` にキャッシュ(再実行時は再取得しない、`.gitignore`対象)
- 見出しが見つからない場合は先頭3000文字にフォールバック(短い書類は元々全文がこの範囲に収まる)
- 出力CSVの `bodyExcerptPreview` 列で、実際にどのテキストを根拠に分類したか確認できる

10件サンプルでの検証結果: 軽微11件・重要6件と、書類概要のみの分類(全件"重要")より大幅に精度が向上。
自己資本比率の数値訂正やリース取引の金額修正など、具体的な数値変更を伴う理由も正しく抽出・分類できている。

### 思考モード(Qwen3) vs 非思考モード

Qwen3は思考(reasoning)ブロックを出力するが、本タスクは複雑な多段推論を要さない読解・分類タスクのため、
思考なし(`/no_think`)でも精度がほぼ落ちないのではという指摘があり検証した。

17件で比較した結果:

| | 平均所要時間/件 | importance一致率 |
|---|---|---|
| 思考あり | 約10.5秒 | - |
| 思考なし | 約2.8秒 | 15件中14件が思考ありと一致(**約3.7倍高速**) |

唯一の不一致も、同一書類が別の実行(思考あり)では逆の判定になったこともあり、
「思考の有無による系統差」というより温度0.1でも生じる揺らぎの範囲と判断。
そのため **`classify_amendments.py` は非思考モードをデフォルト**にしている。
思考モードで実行したい場合は `--thinking` を付ける。

```bash
python src/classify_amendments.py --limit 10              # 非思考モード(デフォルト、速い)
python src/classify_amendments.py --limit 10 --thinking    # 思考モード
```

## 今後の拡張(ロードマップ)

- Phase 1: 収集・一次スクリーニング(EDINET訂正報告書の日次取得) ← 完了
- Phase 2: ローカルLLM(Qwen3, LM Studio)による訂正理由の一次分類(PDF本文抜粋ベース) ← 完了(101件全件、軽微65件・重要36件、失敗0件)
- Phase 3: 監査基準・過去事例のRAG
- Phase 4: kabu-dashboardへの統合
- Phase 5: マルチエージェント協働
