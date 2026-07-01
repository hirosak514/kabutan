# -*- coding: utf-8 -*-
"""
株探 銘柄探検ページ 分析アプリ
- 「更新」: 指定URLの1ページ目・2ページ目から銘柄リストを取得
- 「分析」: 各銘柄についてGemini APIで5項目の情報を要約し、
            日足・週足・月足チャートを取得して画面に表示

注意:
  この環境(Claude)からは kabutan.jp に直接アクセスできないため、
  このコードは実際の株探サイト構造を検証せずに作成しています。
  CSSセレクタやURLパターンは「よくある構造」を仮定したものなので、
  実際に動かして取得が失敗する場合は、下記の `# ---- 要調整 ----` の
  コメントが付いている箇所を、ブラウザの開発者ツールで実際のHTMLを
  確認しながら調整してください。
"""

import re
import time
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
import streamlit as st

# google-generativeai (Gemini)
import google.generativeai as genai

# ----------------------------------------------------------------------
# 基本設定
# ----------------------------------------------------------------------
st.set_page_config(page_title="株探 銘柄探検 分析アプリ", layout="wide")

DEFAULT_URL_JP = "https://kabutan.jp/tansaku/?mode=2_0870"
DEFAULT_URL_US = "https://us.kabutan.jp/tanken/gc_ma5x25"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15

# ----------------------------------------------------------------------
# セッション状態の初期化
# ----------------------------------------------------------------------
if "companies" not in st.session_state:
    st.session_state.companies = []  # [{code, name, raw}]
if "analysis" not in st.session_state:
    st.session_state.analysis = {}   # code -> dict
if "charts" not in st.session_state:
    st.session_state.charts = {}     # code -> {day, week, month}
if "market" not in st.session_state:
    st.session_state.market = "jp"   # "jp" または "us"


# ----------------------------------------------------------------------
# スクレイピング関連
# ----------------------------------------------------------------------
def detect_market(url: str) -> str:
    """
    URLのドメインから 'jp'（日本株版 kabutan.jp）か
    'us'（米国株版 us.kabutan.jp）かを判定する。
    """
    host = urlparse(url).netloc.lower()
    if host.startswith("us."):
        return "us"
    return "jp"


def build_page_url(base_url: str, page: int) -> str:
    """株探の探検ページのページ番号付きURLを作る"""
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def fetch_html(url: str) -> str:
    res = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    return res.text


def parse_company_list(html: str, market: str = "jp"):
    """
    株探の銘柄探検ページのテーブルから 銘柄コード・銘柄名 を抽出する。

    market:
      "jp" -> kabutan.jp（日本株）。コードは数字始まり4桁の英数字、
              URLは "?code=XXXX" というクエリ形式。指数（日経平均など）は
              コードが "0" 始まりなので除外する。
      "us" -> us.kabutan.jp（米国株）。コードはアルファベットのティッカー
              （例: AAPL, NNBR）で、URLは "/stocks/AAPL/..." という
              パス形式。

    実際のテーブルは1行(<tr>)の中に <td>コード</td><td>銘柄名</td>... という
    構造になっており、銘柄名側はリンクではなく単なるテキストであることが多い。
    そのため「コードを含むセルの次のセル」を銘柄名として抽出する（方式1）。
    これがうまくいかない場合は、リンクのテキストから推測する従来方式
    （方式2・3）にフォールバックする。
    """
    soup = BeautifulSoup(html, "lxml")

    if market == "us":
        # 例: href="/stocks/NNBR/chart" や href="/stocks/NNBR" からティッカーを抽出
        code_pattern = re.compile(r"/stocks/([A-Z][A-Z0-9.\-]{0,5})(?:[/?]|$)")
        code_text_pattern = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")

        def is_excluded(code: str) -> bool:
            # 米国株版は指数行が一覧に混ざらない想定だが、念のため
            # 既知の指数っぽいティッカー（^で始まるなど）は除外
            return code.startswith("^")
    else:
        # 例: href="...?code=1325" や href="...?code=143A" からコードを抽出
        code_pattern = re.compile(r"code=([0-9][0-9A-Z]{3})")
        code_text_pattern = re.compile(r"^[0-9][0-9A-Z]{3}$")

        def is_excluded(code: str) -> bool:
            # 日経平均・NYダウ・上海総合・米ドル円などの「指数」はコードが0始まり
            # → 株式銘柄ではないので除外
            return code.startswith("0")

    def is_code_like(text: str) -> bool:
        return bool(code_text_pattern.fullmatch(text.strip()))

    # ---- 方式1: 「コードを含むセル」を探し、その次のセルを銘柄名とする ----
    # 1列目が必ずしもコード列とは限らない（チェックボックス列などがある場合）ため、
    # 列の位置に依存せず「コードらしき値を含むセル」を基準に判定する。
    companies = []
    seen_codes = set()
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        code = None
        code_idx = None
        for idx, cell in enumerate(cells):
            a = cell.find("a", href=True)
            if a:
                m = code_pattern.search(a["href"])
                if m:
                    code = m.group(1)
                    code_idx = idx
                    break
            cell_text = cell.get_text(strip=True)
            if is_code_like(cell_text):
                code = cell_text
                code_idx = idx
                break

        if code is None or code_idx is None:
            continue
        if is_excluded(code):
            continue
        if code in seen_codes:
            continue
        if code_idx + 1 >= len(cells):
            continue

        name = cells[code_idx + 1].get_text(strip=True)
        # 銘柄名が「コードそのものの繰り返し」である場合のみ無効とする。
        # （"NN"のようにコードらしい形式と偶然一致する短い社名を
        #  誤って除外しないよう、is_code_like ではなく完全一致で判定）
        if not name or name.upper() == code.upper():
            continue

        seen_codes.add(code)
        companies.append({"code": code, "name": name})

    if companies:
        return companies

    # ---- 方式2: tr単位でリンクのテキストから推測（方式1が失敗した場合） ----
    companies = []
    seen_codes = set()
    for row in soup.find_all("tr"):
        anchors = row.find_all("a", href=True)
        if not anchors:
            continue

        code = None
        name = None
        for a in anchors:
            href = a["href"]
            m = code_pattern.search(href)
            text = a.get_text(strip=True)
            if m and code is None:
                code = m.group(1)
                if text and not is_code_like(text):
                    name = text
            elif text and not is_code_like(text) and name is None:
                name = text

        if not code or is_excluded(code) or code in seen_codes:
            continue
        if not name:
            continue  # 銘柄名が取れない行は除外（行全体テキストは使わない）

        seen_codes.add(code)
        companies.append({"code": code, "name": name})

    if companies:
        return companies

    # ---- 方式3: 最終フォールバック。リンクの総当たり ----
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = code_pattern.search(href)
        if not m:
            continue
        code = m.group(1)
        if is_excluded(code) or code in seen_codes:
            continue
        name = a.get_text(strip=True)
        if not name:
            continue
        seen_codes.add(code)
        companies.append({"code": code, "name": name})

    return companies


def scrape_company_list(base_url: str, max_pages: int = 2):
    """1ページ目・2ページ目をスクレイピングして銘柄リストを返す"""
    market = detect_market(base_url)
    all_companies = []
    for page in range(1, max_pages + 1):
        url = base_url if page == 1 else build_page_url(base_url, page)
        try:
            html = fetch_html(url)
        except Exception as e:
            st.warning(f"{page}ページ目の取得に失敗しました: {e}")
            continue
        companies = parse_company_list(html, market=market)
        all_companies.extend(companies)
        time.sleep(1)  # サーバー負荷軽減のためのウェイト

    # 重複除去（コード基準）
    uniq = {}
    for c in all_companies:
        uniq[c["code"]] = c
    return list(uniq.values())


def _setup_japanese_font():
    """
    日本語が文字化け（豆腐表示）しないよう、利用可能な日本語フォントを
    matplotlibに設定する。
    Streamlit Community Cloud（Linux）では packages.txt 経由で
    fonts-ipafont-gothic 等をインストールしておく必要がある。
    """
    import matplotlib
    import matplotlib.font_manager as fm

    candidates = [
        "IPAexGothic", "IPAGothic", "Noto Sans CJK JP",
        "Hiragino Sans", "Yu Gothic", "Meiryo", "TakaoGothic",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            matplotlib.rcParams["font.family"] = name
            return name
    # 見つからない場合はデフォルトのまま（日本語は文字化けする可能性あり）
    return None


def fetch_kabutan_series(code: str, m: int, market: str = "jp"):
    """
    株探の内部API (read?c=...&m=...) から株価データ(CSV風テキスト)を取得し、
    [{"date": "20260630", "open":..,"high":..,"low":..,"close":..,"volume":..}, ...]
    のリストを返す。
    m: 1=日足, 2=週足, 3=月足
    market: "jp"=kabutan.jp（日本株）, "us"=us.kabutan.jp（米国株）
    """
    ts = int(time.time() * 1000)
    if market == "us":
        # 米国株版: パスが "/stocks/read.php" で、ティッカーはアルファベット
        url = f"https://us.kabutan.jp/stocks/read.php?c={code}&m={m}&k=1&{ts}"
        referer = f"https://us.kabutan.jp/stocks/{code}/chart"
    else:
        url = f"https://kabutan.jp/stock/read?c={code}&m={m}&k=1&{ts}"
        referer = f"https://kabutan.jp/stock/chart?code={code}&ashi=1&tech=1_1,2_5"

    headers = dict(HEADERS)
    headers["Referer"] = referer

    res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    text = res.text

    # 日付(8桁数字)に続いて始値,高値,安値,終値,出来高,... というレコードを抽出。
    # 当日分など最新データは日付に時刻が付く場合がある（例: 20260701#10:04）
    # → #以降を無視して日付8桁だけを取り出す。
    # カンマの前後にスペースが入る場合もあるため \s* で対応。
    pat = re.compile(
        r"(\d{8})(?:#\d{2}:\d{2})?,\s*"   # 日付（時刻オプション）
        r"([\d.]+),\s*([\d.]+),\s*"        # 始値, 高値
        r"([\d.]+),\s*([\d.]+),\s*"        # 安値, 終値
        r"([\d.]+)"                         # 出来高
    )
    series = []
    for m in pat.finditer(text):
        date = m.group(1)
        try:
            o = float(m.group(2))
            h = float(m.group(3))
            l = float(m.group(4))
            c = float(m.group(5))
            v = float(m.group(6))
        except ValueError:
            continue

        # 株探の内部APIは価格を「0.1円単位（実際の10倍）」で返す。
        # 例: 実際の株価 2,748円 → API返却値 27480
        # → すべての価格を 1/10 に補正する。
        o, h, l, c = o / 10, h / 10, l / 10, c / 10

        series.append({"date": date, "open": o, "high": h, "low": l,
                        "close": c, "volume": v})

    # レコードは新しい日付が先頭に来ているので、古い→新しい順に並び替え
    series.sort(key=lambda r: r["date"])
    return series


def render_candlestick_png(series, title: str, max_bars: int = 150):
    """
    series（日付昇順のOHLCVリスト）からローソク足+出来高チャートのPNGバイト列を作る。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import date2num
    from matplotlib.patches import Rectangle
    import datetime as dt
    import io

    if not series:
        return None

    _setup_japanese_font()

    data = series[-max_bars:]  # 直近N本のみ表示（描画負荷軽減）
    dates = [dt.datetime.strptime(d["date"], "%Y%m%d") for d in data]
    xs = list(range(len(data)))  # 等間隔の連番をX軸に使う（土日の隙間を詰める）

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10, 6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    for x, d in zip(xs, data):
        color = "red" if d["close"] >= d["open"] else "blue"
        ax1.plot([x, x], [d["low"], d["high"]], color=color, linewidth=1)
        lower = min(d["open"], d["close"])
        height = abs(d["close"] - d["open"]) or 0.01
        ax1.add_patch(Rectangle((x - 0.3, lower), 0.6, height,
                                 facecolor=color, edgecolor=color))

    ax1.set_title(title)
    ax1.set_ylabel("価格(円)")
    ax1.grid(alpha=0.3)

    vol_colors = ["red" if d["close"] >= d["open"] else "blue" for d in data]
    ax2.bar(xs, [d["volume"] for d in data], color=vol_colors, width=0.6)
    ax2.set_ylabel("出来高")
    ax2.grid(alpha=0.3)

    # X軸ラベルは間引いて表示
    step = max(1, len(xs) // 8)
    tick_pos = xs[::step]
    tick_labels = [dates[i].strftime("%Y/%m/%d") for i in tick_pos]
    ax2.set_xticks(tick_pos)
    ax2.set_xticklabels(tick_labels, rotation=45, ha="right")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def fetch_chart_images(code: str, name: str, market: str = "jp"):
    """
    日足・週足・月足それぞれのチャートPNG（bytes）を辞書で返す。
    """
    TF = {"day": (1, f"{name}（{code}） 日足"),
          "week": (2, f"{name}（{code}） 週足"),
          "month": (3, f"{name}（{code}） 月足")}
    result = {}
    for key, (m, title) in TF.items():
        try:
            series = fetch_kabutan_series(code, m, market=market)
            png = render_candlestick_png(series, title)
            result[key] = png
        except Exception as e:
            result[key] = None
        time.sleep(0.3)
    return result


# ----------------------------------------------------------------------
# Gemini連携
# ----------------------------------------------------------------------
ANALYSIS_PROMPT_TEMPLATE = """\
あなたは株式市場の証券アナリストです。
今日の日付は {today} です。
銘柄コード {code}（{name}）について、必ずGoogleで最新情報を検索したうえで、
次の5項目を具体的な数値付きで、簡潔な日本語でまとめてください。
古い情報（1年以上前のデータ）は使わず、できるだけ直近のデータを使ってください。
不明な項目は「情報不足のため不明」と記載してください。

出力は必ず以下のJSON形式のみで返してください。前後に説明文やコードブロックの
記号(```)は付けないでください。

{{
  "company_overview": "どのような会社か（事業内容・業界での位置づけなど）",
  "latest_earnings": "直近の決算日と決算内容の要約（売上高・営業利益・純利益の数値と前年比も含める）",
  "valuation": "現在のPER, PBR, ROEの数値とその評価（割安/割高の判断も含める）",
  "dividend_yield": "現在の配当利回り（%）と年間配当金額、その評価",
  "analyst_target": "アナリスト予想の目標株価と現在株価、乖離率(%)。アナリストカバーがない場合は理論株価や参考値を記載"
}}
"""


def init_gemini(api_key: str, model_name: str = "gemini-2.5-flash"):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def analyze_company_with_gemini(model, code: str, name: str) -> dict:
    import datetime
    today = datetime.date.today().strftime("%Y年%m月%d日")
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(code=code, name=name, today=today)

    # Google検索グラウンディングを有効にして最新情報を取得する
    # これによりブラウザ版Geminiと同等の最新データが得られる
    try:
        search_tool = genai.protos.Tool(
            google_search=genai.protos.GoogleSearch()
        )
        response = model.generate_content(
            prompt,
            tools=[search_tool],
        )
    except Exception:
        # グラウンディングが使えない場合（APIプランの制限など）は通常モードで実行
        try:
            response = model.generate_content(prompt)
        except Exception as e:
            return {
                "company_overview": f"取得失敗: {e}",
                "latest_earnings": "-",
                "valuation": "-",
                "dividend_yield": "-",
                "analyst_target": "-",
            }

    try:
        text = response.text.strip()
        # ```json ... ``` で囲まれて返ってきた場合の除去
        text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        # グラウンディング使用時はJSON以外のテキストが混入する場合があるため
        # { } の範囲だけを抜き出す
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        data = json.loads(text)
        return data
    except Exception as e:
        return {
            "company_overview": response.text if hasattr(response, "text") else f"解析失敗: {e}",
            "latest_earnings": "-",
            "valuation": "-",
            "dividend_yield": "-",
            "analyst_target": "-",
        }


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
st.title("📈 株探 銘柄探検 分析アプリ")

with st.sidebar:
    st.header("設定")

    use_us = st.checkbox(
        "米国株版（us.kabutan.jp）を使う",
        value=False,
        help="チェックを外すと日本株版（kabutan.jp）のURLが使われます。",
    )

    url_input_jp = st.text_input(
        "対象URL（日本株版 kabutan.jp）",
        value=DEFAULT_URL_JP,
        disabled=use_us,
    )
    url_input_us = st.text_input(
        "対象URL（米国株版 us.kabutan.jp）",
        value=DEFAULT_URL_US,
        disabled=not use_us,
    )

    # チェックボックスの状態に応じて、実際に使うURLを決定
    url_input = url_input_us if use_us else url_input_jp

    gemini_api_key = st.text_input(
        "Gemini APIキー", type="password",
        help="Streamlit Cloudで使う場合は Secrets に GEMINI_API_KEY として"
             "登録しておけば、ここは空欄のままでも自動的に使われます。",
    )
    if not gemini_api_key:
        gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")

    col1, col2 = st.columns(2)
    with col1:
        update_clicked = st.button("🔄 更新", use_container_width=True)
    with col2:
        analyze_clicked = st.button("🔍 分析", use_container_width=True)

# ---- 更新ボタン処理 ----
if update_clicked:
    market = detect_market(url_input)
    st.session_state.market = market
    market_label = "米国株版 (us.kabutan.jp)" if market == "us" else "日本株版 (kabutan.jp)"
    with st.spinner(f"株探（{market_label}）から銘柄リストを取得中..."):
        companies = scrape_company_list(url_input, max_pages=2)
    st.session_state.companies = companies
    st.session_state.analysis = {}
    st.session_state.charts = {}
    if companies:
        st.success(f"{market_label}として{len(companies)}件の銘柄を取得しました。")
    else:
        st.error(
            "銘柄を取得できませんでした。サイト構造が想定と異なる可能性が"
            "あります。app.py 内の parse_company_list のセレクタを"
            "確認・調整してください。"
        )

# 現在の銘柄リストを表示
if st.session_state.companies:
    st.subheader("取得した銘柄リスト")
    st.dataframe(
        [{"コード": c["code"], "銘柄名": c["name"]} for c in st.session_state.companies],
        use_container_width=True,
    )

# ---- 分析ボタン処理 ----
if analyze_clicked:
    if not st.session_state.companies:
        st.warning("先に「更新」ボタンで銘柄リストを取得してください。")
    elif not gemini_api_key:
        st.warning("Gemini APIキーを入力してください。")
    else:
        model = init_gemini(gemini_api_key)
        progress = st.progress(0.0, text="分析中...")
        total = len(st.session_state.companies)
        for i, company in enumerate(st.session_state.companies):
            code, name = company["code"], company["name"]

            # Gemini分析（未取得の場合のみ実行）
            if code not in st.session_state.analysis:
                st.session_state.analysis[code] = analyze_company_with_gemini(
                    model, code, name
                )

            # チャート取得（未取得の場合のみ実行）
            if code not in st.session_state.charts:
                st.session_state.charts[code] = fetch_chart_images(
                    code, name, market=st.session_state.get("market", "jp")
                )

            progress.progress((i + 1) / total, text=f"分析中... ({i+1}/{total}) {name}")
        progress.empty()
        st.success("分析が完了しました。下にスクロールして確認してください。")

# ----------------------------------------------------------------------
# 結果表示（縦スクロールで全銘柄）
# ----------------------------------------------------------------------
if st.session_state.analysis:
    st.divider()
    st.header("分析結果")

    LABELS = {
        "company_overview": "① どのような会社か",
        "latest_earnings": "② 直近の決算日と決算内容",
        "valuation": "③ PER・PBR・ROEの水準と評価",
        "dividend_yield": "④ 配当利回り",
        "analyst_target": "⑤ アナリスト予想の適正株価と乖離率",
    }
    CHART_LABELS = {"day": "日足", "week": "週足", "month": "月足"}

    for company in st.session_state.companies:
        code, name = company["code"], company["name"]
        if code not in st.session_state.analysis:
            continue

        st.subheader(f"{name}（{code}）")

        data = st.session_state.analysis[code]
        for key, label in LABELS.items():
            st.markdown(f"**{label}**")
            st.write(data.get(key, "-"))

        charts = st.session_state.charts.get(code, {})
        for tf_key, tf_label in CHART_LABELS.items():
            st.markdown(f"**{tf_label}チャート**")
            png_bytes = charts.get(tf_key)
            if png_bytes:
                st.image(png_bytes, use_container_width=True)
            else:
                st.info(
                    f"{tf_label}チャートの取得に失敗しました。"
                    "fetch_kabutan_series 関数のAPI仕様を確認してください。"
                )

        st.divider()
