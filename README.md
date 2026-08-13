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

### 既知の重大事案での検証(回帰テスト的な位置づけ)

実際に不適切会計が発覚した株式会社オルツ(2025年7月、循環取引による売上過大計上が発覚し東証上場廃止)の
訂正有価証券報告書(docID: `S100XDHY`, 2025年12月26日提出)を分類器にかけたところ、
`重要`(理由: 「売上高過大計上の可能性により決算訂正」)と正しく判定された。
今回収集した101件の週次サンプルには同種の重大事案は含まれていなかったが、
パイプラインが実際の不正会計ケースを正しく拾えることは確認できている。

## Phase 3: 監査基準・過去事例のRAG

完全ローカル・外部API課金なしで、事例照会(軸A・自動連動)と実務相談(軸B・Web UI)の2種類のRAGを構築。
LLM/埋め込みモデルの呼び出しは `config/config.json` で切り替え可能(現状はLM Studioのみ対応)。

### 構成

```
config/config.json          # LLM/埋め込み/Chromaの設定(プロバイダ切替はここ)
config/jicpa_sources.json   # JICPA監基報等の書誌情報(番号・タイトル・URL)
src/app_config.py           # config.json読み込み
src/llm_provider.py         # chat_complete/embed_textsの共通クライアント
src/vector_store.py         # ChromaDBラッパー
src/download_jicpa_standards.py  # JICPA監基報PDFのダウンロード
src/ingest_cases.py         # classified_amendments.csv → ChromaDB(事例コレクション)
src/ingest_standards.py     # JICPA監基報PDF → ChromaDB(基準コレクション)
src/find_similar_cases.py   # 軸A: 新規取得分の類似事例をログに残す
src/rag_answer.py           # 軸B: 質問の意図判定・回答生成ロジック
src/rag_app.py              # 軸B: Streamlit UI
```

PDF本文・ベクトルDBの実体(`data/knowledge_base/`, `data/chroma/`, `data/logs/`)はいずれもgitignore対象。
JICPA監基報は著作物のため、書誌情報のみをコミットし本文はローカル保存に留めている。

### セットアップ

1. [JICPA監査実務指針等一覧](https://jicpa.or.jp/specialized_field/publication/kansa/)から監基報等45件を取得
   ```bash
   python src/download_jicpa_standards.py
   ```
2. LM Studioで埋め込みモデル(`text-embedding-nomic-embed-text-v1.5`)をロードし、サーバーを起動
3. ChromaDBに事例・基準を投入
   ```bash
   python src/ingest_cases.py       # Phase2の分類結果101件
   python src/ingest_standards.py   # 監基報45件・2474チャンク
   ```

### 軸A: 事例照会(Phase1と自動連動、UI不要)

`fetch_documents.py`の出力(`data/amendments_*.csv`)を対象に、ChromaDBの過去事例から類似事例を検索し、
`data/logs/similar_cases_<日付>.md`(人間可読)と`.csv`(集計用)にログを残す。

```bash
python src/fetch_documents.py --days 7
python src/find_similar_cases.py   # 最新のamendments_*.csvを自動検出
```

### 軸B: 実務相談(ローカルWeb UI)

```bash
streamlit run src/rag_app.py
```

質問を1つのフォームに入力すると、LLMが「過去事例照会」か「実務手続の相談」かを自動判定し、
- 事例照会 → ChromaDBの事例コレクションから類似事例を提示
- 実務相談 → 関連する監基報の抜粋を検索し、出典(基準名)を明示した参照形式で回答を生成
  (「〜すべき」という断定は避け、最終判断は利用者に委ねる設計)

いずれもLM Studio上のQwen3のみで完結し、外部API呼び出しは発生しない。

知識ベースは監基報45件に加え、実務指針・実務ガイダンス・研究文書57件(計103文書・3471チャンク)まで拡大済み。
JICPA公式サイトの[監査実務指針等一覧](https://jicpa.or.jp/specialized_field/publication/kansa/)ページのうち、
「実務指針」「実務ガイダンス」「研究文書」の3セクションを対象とし、「周知文書」「お知らせ」は対象外としている。

#### 実務相談の検索方式(2段階検索)

LM Studioのコンテキスト長設定(8192トークン)は環境によっては変更してもモデル再ロード時に反映されないことがある。
この制約下でも実質的な検索範囲を広げるため、以下の2段階方式にしている。

1. まず候補25件をChromaDBから広く取得
2. 候補を短い抜粋(各220文字程度)のみでLLMに見せ、質問に本当に関連しそうなものを最大5件に絞り込む
3. 絞り込んだ5件だけ全文を渡して最終回答を生成する

これにより、`top_k`を直接大きくしてコンテキスト超過エラーになることなく、意味的にやや離れた
(だが内容的には的確な)具体例まで拾える可能性が上がる。ただし、埋め込みモデルの類似度計算上、
非常に具体的な物語調の設例(例: 特定の勘定科目・取引を使った計算例)は、抽象的な質問文とは
距離が離れて評価されることがあり、必ずしも毎回同じ具体例がヒットするとは限らない。
見つからない場合は「明示されていません」と回答し、該当しそうな箇所(付録番号等)を示すに留める設計。

#### クエリ拡張・用語の精緻化(ユーザーフィードバックによる改善)

実運用でのフィードバックを受け、以下を追加した。

- **知識ベースにJ-SOX関連の金融庁基準を追加**: 「25件サンプリングすれば90%の信頼度」といった
  実務でよく参照される数値の根拠は、JICPAの監基報ではなく金融庁の
  「財務報告に係る内部統制の評価及び監査の基準・実施基準」および「内部統制報告制度に関するＱ＆Ａ」に
  記載されている。両方を`data/knowledge_base/jicpa/`に追加(計105文書・3608チャンク)。
- **検索クエリ拡張**: ユーザーの自然文の質問をそのまま埋め込み検索にかけるのではなく、
  `expand_query()`でLLMに関連する専門用語(統制の逸脱、許容逸脱率、信頼上限、UPL、J-SOX等)を
  補ったテキストに展開してから検索する。検索距離が平均0.42台→0.32台まで改善。
- **用語の正確さ**: 「統制の逸脱」(J-SOX・属性サンプリング、件数ベース)と「誤謬・虚偽表示」
  (財務諸表監査の実証手続、金額ベース)を混同しないよう、プロンプトで明示的に区別。
  サンプリングリスクの説明も「評価が過大に傾く可能性がある」という曖昧な言い方ではなく、
  「観測された逸脱率ではなく統計的な信頼上限(UPL)で判断する」という正確な理屈で説明するよう変更。
  抜粋にない具体的な追加サンプル数(「17件追加」等)は生成しない。
- **実務ブログの知識ベース化(`config/web_sources.json` + `src/ingest_web_sources.py`)**:
  公式基準だけでは「25件不備1件→追加17件で計42件」のような実務でよく使われる具体的な計算目安まで
  拾いきれないため、監査・内部統制系の解説ブログ5本を追加した(エイアイエムコンサルティング、
  木暮仁「監査とサンプリング」、note記事2本、内部統制ツール比較・選び方ナビ)。
  一部サイトはJavaScriptで本文を描画するため、静的HTML取得ではなくブラウザでレンダリング後の
  テキストを保存する方式にしている。ブログは`category="参考ブログ(非公式)"`として公式基準と
  区別し、回答生成時も「実務では〜という考え方が紹介されています」という言い方に留め、
  公式基準の明文規定であるかのように見せない設計にしている。

### 動作確認結果

- 軸A: 週次サンプル104件全件で類似事例3件ずつを検索し、ログ出力を確認(同一ファンドの定型訂正が距離0.09〜0.19で正しく近傍にヒット)
- 軸B: ブラウザで実際にUIを操作し、以下のパターンの動作を確認
  - 「サンプリングで逸脱が見つかった場合、サンプル数を拡大すべきか」→ 監基報530を出典明記の上で参照形式回答
  - 「三菱UFJアセットマネジメントの投資信託でよくある訂正理由は？」→ 事例照会として類似事例を提示
  - 「サンプル25件で属性サンプリングをしていたら1件不備が生じた、追加サンプルの必要性は」→
    2段階検索により「発見サンプリング(300件)」等の具体的な数値例を引用した回答を確認(実データで検証済み)

## 今後の拡張(ロードマップ)

- Phase 1: 収集・一次スクリーニング(EDINET訂正報告書の日次取得) ← 完了
- Phase 2: ローカルLLM(Qwen3, LM Studio)による訂正理由の一次分類(PDF本文抜粋ベース) ← 完了(101件全件、軽微65件・重要36件、失敗0件)
- Phase 3: 監査基準・過去事例のRAG ← 完了(軸A・軸Bともに動作確認済み)
- Phase 4: kabu-dashboardへの統合
- Phase 5: マルチエージェント協働
