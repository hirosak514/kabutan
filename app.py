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
    # ブラウザに近い完全なヘッダーセットでbot検知を回避する
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}
REQUEST_TIMEOUT = 20

# ドメインごとにrequests.Sessionを保持することでクッキーを引き継ぎbot検知を回避する
_sessions: dict = {}


def _get_session(domain: str) -> requests.Session:
    """ドメインごとのrequests.Sessionを返す（なければ作成してトップページを取得）"""
    if domain not in _sessions:
        session = requests.Session()
        try:
            # トップページを先に取得してクッキーを確立する
            session.get(
                f"https://{domain}/",
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception:
            pass  # クッキー取得失敗は無視して続行
        _sessions[domain] = session
    return _sessions[domain]


# ----------------------------------------------------------------------
# セッション状態の初期化
# ----------------------------------------------------------------------
if "companies" not in st.session_state:
    st.session_state.companies = []  # [{code, name, raw}]
if "analysis" not in st.session_state:
    st.session_state.analysis = {}   # code -> dict
if "charts" not in st.session_state:
    st.session_state.charts = {}     # code -> {day, week, month}
if "daily_series" not in st.session_state:
    st.session_state.daily_series = {}  # code -> [{date, open, high, low, close, volume}, ...]
if "selected_codes" not in st.session_state:
    st.session_state.selected_codes = set()  # チェックされた銘柄コードのセット
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
    """URLのHTMLをセッション経由で取得する（クッキーを維持してbot検知を回避）"""
    domain = urlparse(url).netloc
    session = _get_session(domain)
    res = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
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

        # コードセルの後ろに「アイコンのみの空セル」が挟まる場合があるため、
        # コードの次セルから順に「空でなく、コードと完全一致しない」最初のセルを
        # 銘柄名として採用する（例: コード→アイコン→アイコン→銘柄名 という構造に対応）
        name = ""
        for next_idx in range(code_idx + 1, len(cells)):
            candidate = cells[next_idx].get_text(strip=True)
            if candidate and candidate.upper() != code.upper():
                name = candidate
                break

        if not name:
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
        # 米国株版: ドメインは chart.us.kabutan.jp、パスは /chart/read.php
        # （実際のNetworkログから確認済み）
        url = f"https://chart.us.kabutan.jp/chart/read.php?c={code}&m={m}&k=1&{ts}"
        referer = f"https://us.kabutan.jp/stocks/{code}/chart"
    else:
        url = f"https://kabutan.jp/stock/read?c={code}&m={m}&k=1&{ts}"
        referer = f"https://kabutan.jp/stock/chart?code={code}&ashi=1&tech=1_1,2_5"

    headers = dict(HEADERS)
    headers["Referer"] = referer
    headers["Sec-Fetch-Site"] = "same-origin"
    headers["Sec-Fetch-Dest"] = "empty"
    headers["X-Requested-With"] = "XMLHttpRequest"

    domain = urlparse(url).netloc
    session = _get_session(domain)
    res = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
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

        # 日本株版のAPIは価格を「0.1円単位（実際の10倍）」で返すため÷10が必要。
        # 米国株版のAPIはドル建ての実際の株価をそのまま返すため補正不要。
        # 例（日本株）: 実際2,748円 → API返却値27480 → ÷10で補正
        # 例（米国株）: 実際$3.65  → API返却値3.65  → そのまま使用
        if market != "us":
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


def fetch_series_from_yfinance(code: str, market: str, tf_key: str) -> list:
    """
    Yahoo Finance から株価データ（OHLCV）を取得して
    [{"date":..,"open":..,"high":..,"low":..,"close":..,"volume":..}, ...]
    形式のリストを返す。
    市場: "jp" → コード.T (東証)、"us" → ティッカーそのまま
    tf_key: "day"=日足(6ヶ月) / "week"=週足(2年) / "month"=月足(5年)
    """
    import yfinance as yf

    ticker_symbol = f"{code}.T" if market == "jp" else code
    period_map  = {"day": "6mo",  "week": "2y",  "month": "5y"}
    interval_map = {"day": "1d",  "week": "1wk", "month": "1mo"}

    hist = yf.Ticker(ticker_symbol).history(
        period=period_map[tf_key],
        interval=interval_map[tf_key],
    )
    if hist.empty:
        return []

    series = []
    for ts, row in hist.iterrows():
        series.append({
            "date": ts.strftime("%Y%m%d"),
            "open":   float(row["Open"]),
            "high":   float(row["High"]),
            "low":    float(row["Low"]),
            "close":  float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return series


def fetch_chart_images(code: str, name: str, market: str = "jp"):
    """
    日足・週足・月足それぞれのチャートPNG（bytes）を辞書で返す。
    また日足の生データ（OHLCVリスト）も合わせて返す。
    戻り値: (charts_dict, daily_series)
      charts_dict: {"day": png_bytes, "week": png_bytes, "month": png_bytes}
      daily_series: [{"date","open","high","low","close","volume"}, ...]
    1. Yahoo Finance (yfinance) でデータ取得を試みる
    2. 失敗した場合のみ 株探チャートAPI (kabutan.jp) にフォールバック
    """
    TF = {
        "day":   (1, f"{name}（{code}） 日足"),
        "week":  (2, f"{name}（{code}） 週足"),
        "month": (3, f"{name}（{code}） 月足"),
    }
    result = {}
    daily_series = []

    for key, (m_num, title) in TF.items():
        series = None

        # --- 1. Yahoo Finance で取得 ---
        try:
            series = fetch_series_from_yfinance(code, market, key)
        except Exception:
            series = None

        # --- 2. フォールバック: 株探チャートAPI ---
        if not series:
            try:
                series = fetch_kabutan_series(code, m_num, market=market)
            except Exception:
                series = None

        result[key] = render_candlestick_png(series, title) if series else None

        # 日足データは直近出来高テーブル用に保存
        if key == "day" and series:
            daily_series = series

        time.sleep(0.2)
    return result, daily_series


# ----------------------------------------------------------------------
# Gemini連携
# ----------------------------------------------------------------------
ANALYSIS_PROMPT_TEMPLATE = """\
あなたは株式市場の証券アナリストです。
今日の日付は {today} です。

【重要】以下の銘柄についてGoogleで必ず検索し、最新の正確な情報を取得してください。

対象銘柄: {name}（証券コード: {code}）

検索時の注意点:
- 「{code} {name} 決算」「{code} {name} 配当」「{code} {name} 株価」などで検索すること
- 必ず最新（直近6ヶ月以内）の情報を使うこと
- 決算は「通期」「中間期」「四半期」のいずれか最新のものを使うこと
- 会社の決算月（3月期・9月期など）を正確に確認すること
- 配当金は最新の予想または実績を使うこと
- 株価は本日（{today}）または直近の終値を使うこと

以下の5項目を具体的な数値付きで、簡潔な日本語でまとめてください。
不明・未確認の項目は「情報不足のため不明」と記載してください。

出力は必ず以下のJSON形式のみで返してください。前後に説明文やコードブロックの
記号(```)は付けないでください。

{{
  "company_overview": "どのような会社か（主要事業・業界での位置づけ・主な顧客層）",
  "latest_earnings": "直近の決算期名（例:2026年9月期 第2四半期）・発表日・売上高・営業利益・純利益の数値と前年同期比",
  "valuation": "本日株価（円）・PER（倍）・PBR（倍）・ROE（%）の数値と割安/割高の評価",
  "dividend_yield": "年間配当金（円）・配当利回り（%）・増減配の状況とその評価",
  "analyst_target": "アナリスト平均目標株価（円）と現在株価からの乖離率（%）。カバーなしの場合は理論株価の参考値を記載"
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
# Claude API連携
# ----------------------------------------------------------------------
CLAUDE_ANALYSIS_PROMPT_TEMPLATE = """\
あなたは株式市場の証券アナリストです。
今日の日付は {today} です。

【重要】以下の銘柄についてウェブ検索で最新情報を調べたうえで、
次の5項目を具体的な数値付きで、簡潔な日本語でまとめてください。

対象銘柄: {name}（証券コード: {code}）

検索する際は以下を確認してください:
- 「{code} {name} 決算」「{code} {name} 配当」「{code} {name} 株価」で検索
- 必ず直近6ヶ月以内の情報を使うこと
- 決算は「通期」「中間期」「四半期」のいずれか最新のものを使うこと
- 会社の決算月（3月期・9月期など）を正確に確認すること
- 配当金は最新の予想または実績を使うこと
- 株価は本日（{today}）または直近の終値を使うこと
- ⑤のアナリスト予想目標株価が不明な場合は「みんかぶ（minkabu.jp）の予想株価」を
  必ず検索して記載してください

出力は必ず以下のJSON形式のみで返してください。前後に説明文やコードブロックの
記号(```)は付けないでください。

{{
  "company_overview": "どのような会社か（主要事業・業界での位置づけ・主な顧客層）",
  "latest_earnings": "直近の決算期名（例:2026年9月期 第2四半期）・発表日・売上高・営業利益・純利益の数値と前年同期比",
  "valuation": "本日株価（円）・PER（倍）・PBR（倍）・ROE（%）の数値と割安/割高の評価",
  "dividend_yield": "年間配当金（円）・配当利回り（%）・増減配の状況とその評価",
  "analyst_target": "アナリスト平均目標株価（円）と現在株価からの乖離率（%）。アナリストカバーがない場合はみんかぶ予想株価（円）と現在株価からの乖離率（%）を記載"
}}
"""


def init_claude(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def analyze_company_with_claude(client, code: str, name: str) -> dict:
    import datetime
    today = datetime.date.today().strftime("%Y年%m月%d日")
    prompt = CLAUDE_ANALYSIS_PROMPT_TEMPLATE.format(
        code=code, name=name, today=today
    )

    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    try:
        import anthropic as _anthropic
        # web_searchツールを使って最新情報を検索しながら分析
        # stop_reason が "tool_use" の場合はClaudeが内部でツールを使用している
        # end_turn になるまでループ
        while True:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                tools=tools,
                messages=messages,
            )

            # アシスタントのメッセージをhistoryに追加
            messages.append({
                "role": "assistant",
                "content": response.content,
            })

            if response.stop_reason == "end_turn":
                break

            # tool_use ブロックがあれば tool_result を返す（web_searchはサーバー側処理）
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",  # web_searchはサーバー側で処理済み
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            else:
                break  # ツール結果が空の場合は終了

        # 最終的なテキストを抽出
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        text = text.strip()
        text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        data = json.loads(text)
        return data

    except Exception as e:
        return {
            "company_overview": f"取得失敗: {e}",
            "latest_earnings": "-",
            "valuation": "-",
            "dividend_yield": "-",
            "analyst_target": "-",
        }



# ----------------------------------------------------------------------
# Grok API連携（xAI / OpenAI互換）
# ----------------------------------------------------------------------
GROK_ANALYSIS_PROMPT_TEMPLATE = """\
あなたは株式市場の証券アナリストです。
今日の日付は {today} です。

【重要】以下の銘柄についてウェブ検索（web_search）で最新情報を調べたうえで、
次の5項目を具体的な数値付きで、簡潔な日本語でまとめてください。

対象銘柄: {name}（証券コード: {code}）

検索する際は以下を確認してください:
- 「{code} {name} 決算」「{code} {name} 配当」「{code} {name} 株価」で検索
- 必ず直近6ヶ月以内の情報を使うこと
- 決算は「通期」「中間期」「四半期」のいずれか最新のものを使うこと
- 会社の決算月（3月期・9月期など）を正確に確認すること
- 配当金は最新の予想または実績を使うこと
- 株価は本日（{today}）または直近の終値を使うこと
- ⑤のアナリスト予想目標株価が不明な場合は「みんかぶ（minkabu.jp）の予想株価」を
  必ず検索して記載してください

出力は必ず以下のJSON形式のみで返してください。前後に説明文やコードブロックの
記号(```)は付けないでください。

{{
  "company_overview": "どのような会社か（主要事業・業界での位置づけ・主な顧客層）",
  "latest_earnings": "直近の決算期名（例:2026年9月期 第2四半期）・発表日・売上高・営業利益・純利益の数値と前年同期比",
  "valuation": "本日株価（円）・PER（倍）・PBR（倍）・ROE（%）の数値と割安/割高の評価",
  "dividend_yield": "年間配当金（円）・配当利回り（%）・増減配の状況とその評価",
  "analyst_target": "アナリスト平均目標株価（円）と現在株価からの乖離率（%）。アナリストカバーがない場合はみんかぶ予想株価（円）と現在株価からの乖離率（%）を記載"
}}
"""


def init_grok(api_key: str):
    from openai import OpenAI
    return OpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )


def analyze_company_with_grok(client, code: str, name: str) -> dict:
    import datetime
    today = datetime.date.today().strftime("%Y年%m月%d日")
    prompt = GROK_ANALYSIS_PROMPT_TEMPLATE.format(
        code=code, name=name, today=today
    )

    try:
        # Responses API（web_searchツール付き）で最新情報を取得
        response = client.responses.create(
            model="grok-4.3",
            input=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search"}],
        )
        text = response.output_text.strip()
    except Exception:
        # Responses APIが使えない場合はChat Completions APIにフォールバック
        try:
            response = client.chat.completions.create(
                model="grok-4.3",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            text = response.choices[0].message.content.strip()
        except Exception as e:
            return {
                "company_overview": f"取得失敗: {e}",
                "latest_earnings": "-",
                "valuation": "-",
                "dividend_yield": "-",
                "analyst_target": "-",
            }

    try:
        text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        return json.loads(text)
    except Exception as e:
        return {
            "company_overview": text if text else f"解析失敗: {e}",
            "latest_earnings": "-",
            "valuation": "-",
            "dividend_yield": "-",
            "analyst_target": "-",
        }


# ----------------------------------------------------------------------
# PDF生成
# ----------------------------------------------------------------------
IPA_FONT_PATH = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
IPA_FONT_PATH_FALLBACK = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"


def _get_ipa_font_path() -> str:
    """利用可能なIPAGothicフォントのパスを返す"""
    import os
    for path in [IPA_FONT_PATH, IPA_FONT_PATH_FALLBACK]:
        if os.path.exists(path):
            return path
    return None


def generate_analysis_pdf(companies, analysis, charts, daily_series=None) -> bytes:
    """
    分析結果（直近7営業日テーブル＋テキスト5項目＋日足・週足・月足チャート）を
    A4縦のPDFにまとめてバイト列で返す。
    会社ごとにセクションを区切り、縦スクロールと同じ順序で配置。
    """
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image,
        HRFlowable, PageBreak, Table, TableStyle,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # --- フォント登録 ---
    font_path = _get_ipa_font_path()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("IPAGothic", font_path))
            font_name = "IPAGothic"
        except Exception:
            font_name = "Helvetica"
    else:
        font_name = "Helvetica"

    # --- スタイル定義 ---
    def style(name, font=font_name, size=10, bold=False, color=colors.black,
              spaceBefore=4, spaceAfter=4, leading=16):
        return ParagraphStyle(
            name,
            fontName=font,
            fontSize=size,
            textColor=color,
            spaceBefore=spaceBefore,
            spaceAfter=spaceAfter,
            leading=leading,
        )

    s_title    = style("title",    size=16, color=colors.HexColor("#1a237e"),
                       spaceBefore=10, spaceAfter=6, leading=22)
    s_label    = style("label",    size=10, color=colors.HexColor("#1565c0"),
                       spaceBefore=8, spaceAfter=2, leading=14)
    s_body     = style("body",     size=9,  color=colors.HexColor("#212121"),
                       spaceBefore=0, spaceAfter=4, leading=14)
    s_chart    = style("chart",    size=10, color=colors.HexColor("#37474f"),
                       spaceBefore=10, spaceAfter=2, leading=14)
    s_header   = style("header",   size=9,  color=colors.HexColor("#546e7a"),
                       spaceBefore=0, spaceAfter=6, leading=13)

    LABELS = {
        "company_overview": "① どのような会社か",
        "latest_earnings":  "② 直近の決算日と決算内容",
        "valuation":        "③ PER・PBR・ROEの水準と評価",
        "dividend_yield":   "④ 配当利回り",
        "analyst_target":   "⑤ アナリスト予想の適正株価と乖離率",
    }
    CHART_LABELS = {"day": "日足チャート", "week": "週足チャート", "month": "月足チャート"}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="株探 銘柄探検 分析レポート",
    )

    import datetime
    today_str = datetime.date.today().strftime("%Y年%m月%d日")

    story = []
    story.append(Paragraph("株探 銘柄探検 分析レポート", s_title))
    story.append(Paragraph(f"作成日: {today_str}　　銘柄数: {len(companies)}社", s_header))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#1a237e"), spaceAfter=8))

    page_w = A4[0] - 30 * mm  # 利用可能な幅

    for i, company in enumerate(companies):
        code, name = company["code"], company["name"]
        if code not in analysis and code not in (charts or {}):
            continue

        # 会社名ヘッダー
        story.append(Paragraph(f"{name}（{code}）", s_title))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                 color=colors.HexColor("#90caf9"), spaceAfter=4))

        # 直近7営業日の株価・出来高テーブル
        ds = (daily_series or {}).get(code, [])
        if ds:
            recent7 = ds[-7:][::-1]
            # ヘッダー行
            is_jp = len(recent7) > 0 and recent7[0]["close"] > 10
            price_label = "終値（円）" if is_jp else "終値（$）"
            table_data = [["日付", price_label, "出来高（株）"]]

            # 騰落率（最新終値 vs 7営業日前終値）
            latest_close = recent7[0]["close"]
            oldest_close = recent7[-1]["close"]
            if oldest_close and oldest_close != 0:
                change_pct = (latest_close - oldest_close) / oldest_close * 100
                arrow = "▲" if change_pct >= 0 else "▼"
                change_str = f" {arrow}{abs(change_pct):.2f}%"
            else:
                change_str = ""

            for idx, d in enumerate(recent7):
                date_str = f"{d['date'][:4]}/{d['date'][4:6]}/{d['date'][6:]}"
                close = d["close"]
                volume = int(d["volume"])
                price_str = f"{close:,.0f}" if is_jp else f"{close:.2f}"
                # 最新行のみ騰落率を追記
                if idx == 0:
                    price_str += change_str
                table_data.append([date_str, price_str, f"{volume:,}"])

            tbl = Table(
                table_data,
                colWidths=[35*mm, 40*mm, 55*mm],
                hAlign="LEFT",
            )
            tbl.setStyle(TableStyle([
                ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#1565c0")),
                ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
                ("FONTNAME",    (0, 0), (-1, -1), font_name),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.HexColor("#f5f5f5"), colors.white]),
                ("ALIGN",       (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN",       (0, 0), (0, -1),  "LEFT"),
                ("GRID",        (0, 0), (-1, -1), 0.3, colors.HexColor("#bdbdbd")),
                ("TOPPADDING",  (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 4*mm))

        # 分析テキスト5項目
        if code in analysis:
            data = analysis[code]
            for key, label in LABELS.items():
                story.append(Paragraph(label, s_label))
                value = data.get(key, "-") or "-"
                # 特殊文字（<>&）をエスケープしてParagraphクラッシュを防ぐ
                value = (value.replace("&", "&amp;")
                              .replace("<", "&lt;")
                              .replace(">", "&gt;"))
                story.append(Paragraph(value, s_body))

        # チャート3種
        company_charts = charts.get(code, {})
        for tf_key, tf_label in CHART_LABELS.items():
            png_bytes = company_charts.get(tf_key)
            if not png_bytes:
                continue
            story.append(Paragraph(tf_label, s_chart))
            img_buf = io.BytesIO(png_bytes)
            # アスペクト比を保ちながら幅に合わせてリサイズ
            img = Image(img_buf, width=page_w, height=page_w * 0.55)
            story.append(img)
            story.append(Spacer(1, 4 * mm))

        # 会社間の区切り（最終社は不要）
        if i < len(companies) - 1:
            story.append(PageBreak())

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


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

    st.divider()
    st.subheader("🤖 AI分析エンジン")
    api_choice = st.radio(
        "使用するAI",
        options=["Claude API（推奨）", "Grok API", "Gemini API"],
        index=0,
        help="Claude: Web検索＋みんかぶ参照で精度高い。Grok: リアルタイム検索＋X投稿も参照可、無料クレジットあり。Gemini: Googleグラウンディング。",
    )

    if api_choice == "Claude API（推奨）":
        claude_api_key = st.text_input(
            "Claude APIキー", type="password",
            help="Streamlit CloudのSecretsに CLAUDE_API_KEY として登録しておけば自動取得されます。",
        )
        if not claude_api_key:
            claude_api_key = st.secrets.get("CLAUDE_API_KEY", "")
        gemini_api_key = ""
        grok_api_key = ""
    elif api_choice == "Grok API":
        grok_api_key = st.text_input(
            "Grok APIキー（xAI）", type="password",
            help="console.x.ai で取得。Streamlit CloudのSecretsに GROK_API_KEY として登録可。データ共有プログラムで最大$175/月の無料クレジットあり。",
        )
        if not grok_api_key:
            grok_api_key = st.secrets.get("GROK_API_KEY", "")
        claude_api_key = ""
        gemini_api_key = ""
    else:
        gemini_api_key = st.text_input(
            "Gemini APIキー", type="password",
            help="Streamlit CloudのSecretsに GEMINI_API_KEY として登録しておけば自動取得されます。",
        )
        if not gemini_api_key:
            gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
        claude_api_key = ""
        grok_api_key = ""

    st.divider()
    analyze_count = st.slider(
        "分析する会社数",
        min_value=1,
        max_value=30,
        value=30,
        step=1,
        help="「更新」で取得した銘柄リストの上から何社を分析するか指定します。",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        update_clicked = st.button("🔄 更新", use_container_width=True)
    with col2:
        analyze_clicked = st.button("🔍 分析", use_container_width=True)
    with col3:
        chart_only_clicked = st.button("📊 グラフのみ", use_container_width=True,
                                       help="APIキー不要。チャートデータの取得と描画のみ行います。")

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
    st.session_state.daily_series = {}
    st.session_state.selected_codes = set()
    if "company_editor" in st.session_state:
        del st.session_state["company_editor"]
    if companies:
        st.success(f"{market_label}として{len(companies)}件の銘柄を取得しました。")
    else:
        st.error(
            "銘柄の自動取得に失敗しました。\n\n"
            "原因: Streamlit CloudのサーバーIPがkabutan.jpにブロックされている可能性があります（405エラー）。\n\n"
            "👇 **手動入力モード**で銘柄コードを直接入力して分析できます。"
        )

# 手動入力フォールバック（スクレイピングが失敗した場合に表示）
if not st.session_state.companies:
    with st.expander("📝 手動入力モード（スクレイピングが失敗した場合はこちら）", expanded=not st.session_state.companies):
        market_for_manual = detect_market(url_input)
        if market_for_manual == "jp":
            placeholder = (
                "かぶたんの銘柄一覧表をそのままコピー&ペーストしてください。\n"
                "例:\n"
                "1417\tミライトワン\t東Ｐ\t\n"
                "3,873\t\t+51\t+1.33%\t...\n"
                "1419\tタマホーム\t東Ｐ\t\n"
                "2,950\t\t+47\t+1.62%\t...\n\n"
                "または手入力形式: コード,銘柄名 （1行1社）\n"
                "例: 1325,野村ボベスパ"
            )
            help_text = "かぶたんの表をCtrl+Aで全選択してコピーしたものをそのまま貼り付けられます。コードと銘柄名の行だけ自動抽出します。"
        else:
            placeholder = (
                "ティッカー,銘柄名 の形式で1行1社。\n"
                "例:\nNNBR,NN Inc.\nFRSH,Freshworks\nLCID,Lucid Group"
            )
            help_text = "ティッカー,銘柄名 の形式で1行1社。銘柄名を省略するとティッカーをそのまま名前として使います。"

        manual_input = st.text_area(
            "銘柄コードを入力（1行1社、コンマ区切りで銘柄名も指定可）",
            height=200,
            placeholder=placeholder,
            help=help_text,
        )
        if st.button("✅ この銘柄リストで設定", use_container_width=False):
            companies = []
            seen = set()
            # かぶたんからコピーした形式（タブ区切り）と
            # 従来の手入力形式（コンマ区切り）の両方に対応する
            # かぶたんコピー形式:
            #   コード\t銘柄名\t市場\t  ← この行を使う
            #   株価\t\t前日比\t...     ← この行はスキップ
            # 手入力形式:
            #   1325,野村ボベスパ
            jp_code_pat = re.compile(r"^[0-9][0-9A-Z]{3}$")
            us_code_pat = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")

            for line in manual_input.strip().splitlines():
                line = line.strip()
                if not line:
                    continue

                # タブが含まれている → かぶたんコピー形式として解析
                if "\t" in line:
                    parts = [p.strip() for p in line.split("\t")]
                    code = parts[0] if parts else ""
                    name = parts[1] if len(parts) > 1 else ""
                    # コードらしくない行（株価行など）はスキップ
                    if not (jp_code_pat.fullmatch(code) or us_code_pat.fullmatch(code)):
                        continue
                    if not name:
                        name = code
                else:
                    # カンマ区切りの手入力形式
                    parts = [p.strip() for p in line.split(",", 1)]
                    code = parts[0]
                    name = parts[1] if len(parts) > 1 and parts[1] else code

                if code and code not in seen:
                    seen.add(code)
                    companies.append({"code": code, "name": name})
            if companies:
                st.session_state.companies = companies
                st.session_state.market = market_for_manual
                st.session_state.analysis = {}
                st.session_state.charts = {}
                st.success(f"{len(companies)}件の銘柄を手動設定しました。「分析」ボタンを押してください。")
            else:
                st.warning("銘柄が入力されていません。")

# 現在の銘柄リストをチェックボックス付きで表示
if st.session_state.companies:
    st.subheader("取得した銘柄リスト")

    # チェックボックス付きテーブル（data_editor）
    # スライダーで指定した件数のみ表示対象とする
    visible = st.session_state.companies[:analyze_count]
    df_rows = [
        {"選択": True, "コード": c["code"], "銘柄名": c["name"]}
        for c in visible
    ]
    col_all, col_none, _ = st.columns([1, 1, 6])
    with col_all:
        if st.button("✅ 全選択", use_container_width=True):
            # セッションキーを削除してリセット（次レンダリングで全チェック）
            if "company_editor" in st.session_state:
                del st.session_state["company_editor"]
            st.rerun()
    with col_none:
        if st.button("☐ 全解除", use_container_width=True):
            # 全解除状態を強制セット
            st.session_state["company_editor"] = {
                "edited_rows": {i: {"選択": False} for i in range(len(df_rows))},
                "added_rows": [],
                "deleted_rows": [],
            }
            st.rerun()

    edited = st.data_editor(
        df_rows,
        column_config={
            "選択": st.column_config.CheckboxColumn(
                "選択", default=True,
                help="チェックを入れた銘柄のみ「分析」「グラフのみ」の対象となります"
            ),
            "コード": st.column_config.TextColumn("コード", disabled=True),
            "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
        },
        disabled=["コード", "銘柄名"],
        hide_index=True,
        use_container_width=True,
        key="company_editor",
    )

    # チェック済みコードをセッションに保存（ボタン処理で参照）
    st.session_state.selected_codes = {
        row["コード"] for row in edited if row["選択"]
    }
    checked_count = len(st.session_state.selected_codes)
    st.caption(f"{checked_count} / {len(visible)} 社が選択されています")

# ---- 分析ボタン処理 ----
if analyze_clicked:
    if not st.session_state.companies:
        st.warning("先に「更新」ボタンで銘柄リストを取得してください。")
    elif api_choice == "Claude API（推奨）" and not claude_api_key:
        st.warning("Claude APIキーを入力してください。")
    elif api_choice == "Grok API" and not grok_api_key:
        st.warning("Grok APIキー（xAI）を入力してください。")
    elif api_choice == "Gemini API" and not gemini_api_key:
        st.warning("Gemini APIキーを入力してください。")
    else:
        if api_choice == "Claude API（推奨）":
            ai_client = init_claude(claude_api_key)
            ai_label = "Claude"
        elif api_choice == "Grok API":
            ai_client = init_grok(grok_api_key)
            ai_label = "Grok"
        else:
            ai_client = init_gemini(gemini_api_key)
            ai_label = "Gemini"

        progress = st.progress(0.0, text=f"{ai_label}で分析中...")
        # チェック済みの銘柄のみ対象（スライダーで表示された中からチェックされたもの）
        selected = st.session_state.get(
            "selected_codes",
            {c["code"] for c in st.session_state.companies[:analyze_count]}
        )
        target_companies = [
            c for c in st.session_state.companies[:analyze_count]
            if c["code"] in selected
        ]
        total = len(target_companies)
        for i, company in enumerate(target_companies):
            code, name = company["code"], company["name"]

            if code not in st.session_state.analysis:
                if api_choice == "Claude API（推奨）":
                    st.session_state.analysis[code] = analyze_company_with_claude(
                        ai_client, code, name
                    )
                elif api_choice == "Grok API":
                    st.session_state.analysis[code] = analyze_company_with_grok(
                        ai_client, code, name
                    )
                else:
                    st.session_state.analysis[code] = analyze_company_with_gemini(
                        ai_client, code, name
                    )

            # チャート取得（未取得の場合のみ実行）
            if code not in st.session_state.charts:
                charts, daily = fetch_chart_images(
                    code, name, market=st.session_state.get("market", "jp")
                )
                st.session_state.charts[code] = charts
                st.session_state.daily_series[code] = daily

            progress.progress((i + 1) / total, text=f"{ai_label}で分析中... ({i+1}/{total}) {name}")
        progress.empty()
        st.success("分析が完了しました。下にスクロールして確認してください。")

# ---- グラフのみボタン処理 ----
if chart_only_clicked:
    if not st.session_state.companies:
        st.warning("先に「更新」ボタンまたは手動入力で銘柄リストを取得してください。")
    else:
        selected = st.session_state.get(
            "selected_codes",
            {c["code"] for c in st.session_state.companies[:analyze_count]}
        )
        target_companies = [
            c for c in st.session_state.companies[:analyze_count]
            if c["code"] in selected
        ]
        total = len(target_companies)
        progress = st.progress(0.0, text="チャートデータを取得中...")
        for i, company in enumerate(target_companies):
            code, name = company["code"], company["name"]
            if code not in st.session_state.charts:
                charts, daily = fetch_chart_images(
                    code, name, market=st.session_state.get("market", "jp")
                )
                st.session_state.charts[code] = charts
                st.session_state.daily_series[code] = daily
            progress.progress(
                (i + 1) / total,
                text=f"チャート取得中... ({i+1}/{total}) {name}"
            )
        progress.empty()
        st.success("チャートの取得が完了しました。下にスクロールして確認してください。")

# ----------------------------------------------------------------------
# 結果表示（縦スクロールで全銘柄）
# 「分析」実行済み or「グラフのみ」実行済みの場合に表示
# ----------------------------------------------------------------------
has_analysis = bool(st.session_state.analysis)
has_charts   = bool(st.session_state.charts)

if has_analysis or has_charts:
    st.divider()

    # 表示する会社リスト（分析またはチャートがある会社）
    display_companies = [
        c for c in st.session_state.companies
        if c["code"] in st.session_state.analysis
        or c["code"] in st.session_state.charts
    ]

    # --- ヘッダーとPDFダウンロードボタンを横並びに配置 ---
    col_header, col_pdf = st.columns([3, 1])
    with col_header:
        mode_label = "分析結果" if has_analysis else "グラフ一覧"
        st.header(mode_label)
    with col_pdf:
        st.write("")  # 垂直位置調整
        with st.spinner("PDF生成中..."):
            try:
                pdf_bytes = generate_analysis_pdf(
                    display_companies,
                    st.session_state.analysis,
                    st.session_state.charts,
                    daily_series=st.session_state.daily_series,
                )
                import datetime
                suffix = "分析" if has_analysis else "グラフ"
                filename = f"株探{suffix}_{datetime.date.today().strftime('%Y%m%d')}.pdf"
                st.download_button(
                    label="📄 PDFをダウンロード",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"PDF生成失敗: {e}")

    LABELS = {
        "company_overview": "① どのような会社か",
        "latest_earnings":  "② 直近の決算日と決算内容",
        "valuation":        "③ PER・PBR・ROEの水準と評価",
        "dividend_yield":   "④ 配当利回り",
        "analyst_target":   "⑤ アナリスト予想の適正株価と乖離率",
    }
    CHART_LABELS = {"day": "日足", "week": "週足", "month": "月足"}

    for company in display_companies:
        code, name = company["code"], company["name"]
        market = st.session_state.get("market", "jp")

        st.subheader(f"{name}（{code}）")

        # ── 直近7営業日の株価・出来高テーブル（赤枠部分）──
        daily = st.session_state.daily_series.get(code, [])
        if daily:
            recent7 = daily[-7:][::-1]  # 直近7件を新しい順に
            is_jp = (market == "jp")

            # 騰落率を計算（最新終値 vs 7営業日前の終値）
            latest_close = recent7[0]["close"]
            oldest_close = recent7[-1]["close"]
            if oldest_close and oldest_close != 0:
                change_pct = (latest_close - oldest_close) / oldest_close * 100
                arrow = "▲" if change_pct >= 0 else "▼"
                change_str = f"{arrow}{abs(change_pct):.2f}%"
            else:
                change_str = ""

            rows = []
            for idx, d in enumerate(recent7):
                date_str = f"{d['date'][:4]}/{d['date'][4:6]}/{d['date'][6:]}"
                close = d["close"]
                volume = int(d["volume"])

                # 最新行（1行目）のみ終値の右に騰落率を表示
                if is_jp:
                    close_disp = f"{close:,.0f}  {change_str}" if idx == 0 else f"{close:,.0f}"
                    rows.append({
                        "日付": date_str,
                        "終値（円）": close_disp,
                        "出来高（株）": f"{volume:,}",
                    })
                else:
                    close_disp = f"{close:.2f}  {change_str}" if idx == 0 else f"{close:.2f}"
                    rows.append({
                        "日付": date_str,
                        "終値（$）": close_disp,
                        "出来高（株）": f"{volume:,}",
                    })
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("直近出来高データを取得できませんでした。")

        # AI分析テキスト（「分析」実行済みの場合のみ表示）
        if code in st.session_state.analysis:
            data = st.session_state.analysis[code]
            for key, label in LABELS.items():
                st.markdown(f"**{label}**")
                st.write(data.get(key, "-"))

        # チャート（「分析」「グラフのみ」どちらでも表示）
        charts = st.session_state.charts.get(code, {})
        for tf_key, tf_label in CHART_LABELS.items():
            st.markdown(f"**{tf_label}チャート**")
            png_bytes = charts.get(tf_key)
            if png_bytes:
                st.image(png_bytes, use_container_width=True)
            else:
                st.info(f"{tf_label}チャートのデータを取得できませんでした。")

        st.divider()
