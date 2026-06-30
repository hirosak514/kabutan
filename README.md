# 株探 銘柄探検 分析アプリ

株探（kabutan.jp / 米国株版 us.kabutan.jp）の「銘柄探検」ページから銘柄リストを
取得し、各銘柄についてGemini APIで企業概要・決算・PER/PBR/ROE・配当利回り・
アナリスト目標株価を要約し、日足/週足/月足のローソク足チャートと合わせて
一覧表示するStreamlitアプリです。

## 日本株・米国株 両対応について

入力したURLのドメインを見て自動的に「日本株版（kabutan.jp）」か
「米国株版（us.kabutan.jp）」かを判定し、それぞれ異なる仕組み
（コードの形式、チャートデータ取得APIのURL）を使い分けます。

| | 日本株版 (kabutan.jp) | 米国株版 (us.kabutan.jp) |
|---|---|---|
| コード形式 | 数字始まり4文字（例: `1325`, `143A`） | アルファベットのティッカー（例: `NNBR`） |
| 個別銘柄ページ | `/stock/?code=XXXX` | `/stocks/{ティッカー}/chart` |
| チャートデータAPI | `/stock/read?c=...&m=...` | `/stocks/read.php?c=...&m=...` |

## チャートの取得方式について

チャートは画像をスクレイピングするのではなく、株探の内部API
`https://kabutan.jp/stock/read?c={コード}&m={1=日足,2=週足,3=月足}&k=1&{timestamp}`
から株価データ（日付・始値・高値・安値・終値・出来高）を取得し、
matplotlibでローソク足チャートを自前で描画しています。
これは実際にブラウザの開発者ツールで確認した挙動を元に実装しているため、
画像URLを直接推測する方式よりも安定して動作するはずです。

ただし、このAPIの仕様（パラメータの意味、レスポンス形式）が将来変更される
可能性はあります。動作しない場合は `fetch_kabutan_series()` 関数を見直して
ください。

## ⚠️ 注意（未検証の箇所）

- `parse_company_list()`：銘柄一覧テーブルの取得ロジックは銘柄探検ページの
  実際のテーブル構造（クラス名など）までは検証していません。コードリンク
  （`code=XXXX` を含む `<a>` タグ）を総当たりで拾う実装なので、ある程度の
  揺らぎには耐性がありますが、取得件数が想定とずれる場合は調整してください。
- ページ送り（2ページ目）のURLパラメータ名（`page=2`）も未検証です。

## セットアップ（ローカル実行）

```bash
git clone <このリポジトリのURL>
cd kabutan-analyzer
pip install -r requirements.txt
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。
サイドバーにGemini APIキーを入力し、「更新」→「分析」の順にボタンを押してください。

### 日本語フォントについて（ローカル実行時）

チャートのタイトルや軸ラベルに日本語を使っているため、IPAフォント等の
日本語フォントがインストールされていないと文字化け（豆腐表示）します。

```bash
# Ubuntu/Debian系の場合
sudo apt-get install -y fonts-ipafont-gothic fonts-ipafont-mincho

# macOSの場合は標準で日本語フォント（Hiragino Sans等）が使えるため
# 通常は追加インストール不要です
```

## GitHub + Streamlit Community Cloudでの公開手順

1. このフォルダの中身をGitHubの新しいリポジトリにpushする
   ```bash
   git init
   git add .
   git commit -m "initial commit"
   git branch -M main
   git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
   git push -u origin main
   ```
2. https://share.streamlit.io にアクセスし、GitHubアカウントでログイン
3. 「New app」から、pushしたリポジトリ・ブランチ・`app.py` を指定してデプロイ
4. アプリ管理画面の「Settings」→「Secrets」に以下を追加
   ```toml
   GEMINI_API_KEY = "あなたのGemini APIキー"
   ```
5. デプロイされたURLにアクセスすれば、サイドバーにAPIキーを入力しなくても
   自動的にSecretsの値が使われます。

`packages.txt` に日本語フォント（fonts-ipafont-gothic等）を指定しているので、
Streamlit Community Cloud上でも自動的に日本語フォントがインストールされ、
チャートの文字化けを防げます。

## ファイル構成

```
kabutan-analyzer/
├── app.py                          # Streamlitアプリ本体
├── requirements.txt                # 依存パッケージ（Pythonライブラリ）
├── packages.txt                    # 依存パッケージ（OSレベル、日本語フォント等）
├── .streamlit/secrets.toml.example # Secretsのサンプル（実ファイルはgitignore対象）
├── .gitignore
└── README.md
```

## 使い方

1. サイドバーに「対象URL（日本株版）」「対象URL（米国株版）」の2つの入力欄が
   あります。それぞれデフォルト値が入っており、日本株版は
   `https://kabutan.jp/tansaku/?mode=2_0870`（ゴールデンクロス銘柄一覧）、
   米国株版は `https://us.kabutan.jp/tanken/gc_ma5x25` です
2. 「米国株版（us.kabutan.jp）を使う」チェックボックスで、どちらのURLを
   使うか選択します（チェックを外すと日本株版が使われます）
3. 「🔄 更新」ボタンを押すと、選択した方のURLの1〜2ページ目から
   銘柄コード・銘柄名を取得
4. 「🔍 分析」ボタンを押すと、各銘柄についてGeminiが下記5項目を要約し、
   日足・週足・月足のローソク足チャートとあわせて画面に縦スクロール表示
   されます
   1. どのような会社か
   2. 直近の決算日と決算内容
   3. PER・PBR・ROEの水準と評価
   4. 配当利回り
   5. アナリスト予想の適正株価と乖離率

## 既知の制約

- kabutan.jpはbot対策が入っている場合があり、サーバーやクラウド環境からの
  アクセスがブロックされることがあります。ブロックされる場合は、ローカルPC
  からの実行を試してください。
- Gemini APIの回答はあくまでAIによる要約であり、投資判断の根拠として
  そのまま使用しないでください。最終的な投資判断はご自身の責任で行って
  ください。
- 株探の内部API仕様は公式に公開されたものではなく、ブラウザの挙動観察に
  基づく実装です。将来的に仕様変更でデータ取得できなくなる可能性があります。

