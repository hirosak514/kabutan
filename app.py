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
from datetime import date as _date, timedelta as _timedelta
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

# 急騰モードのフォールバック用デフォルト銘柄リスト
# スクレイピングが失敗した場合にこのリストを対象として出来高急騰分析を実行する
NIKKEI225_STOCKS = [
    ("1332","ニッスイ"),("1333","マルハニチロ"),("1605","INPEX"),("1721","コムシスHD"),
    ("1801","大成建設"),("1802","大林組"),("1803","清水建設"),("1808","長谷工コーポ"),
    ("1812","鹿島建設"),("1925","大和ハウス工業"),("1928","積水ハウス"),("1963","日揮HD"),
    ("2002","日清製粉G本社"),("2269","明治HD"),("2282","日本ハム"),("2413","エムスリー"),
    ("2432","DeNA"),("2501","サッポロHD"),("2502","アサヒグループHD"),("2503","キリンHD"),
    ("2531","宝HD"),("2768","双日"),("2801","キッコーマン"),("2802","味の素"),
    ("2871","ニチレイ"),("2914","JT"),("3086","Jフロント リテイリング"),("3092","ZOZO"),
    ("3099","三越伊勢丹HD"),("3382","セブン＆アイHD"),("3401","帝人"),("3402","東レ"),
    ("3405","クラレ"),("3407","旭化成"),("3436","SUMCO"),("3481","三菱地所物流REIT投資法人"),
    ("3産業","産業"),("3863","日本製紙"),("3865","北越コーポ"),("3893","紀州製紙"),
    ("4004","レゾナック・HD"),("4005","住友化学"),("4021","日産化学"),("4042","東ソー"),
    ("4043","トクヤマ"),("4061","デンカ"),("4063","信越化学工業"),("4151","協和キリン"),
    ("4183","三井化学"),("4188","三菱ケミカルG"),("4208","UBE"),("4324","電通グループ"),
    ("4385","メルカリ"),("4452","花王"),("4502","武田薬品工業"),("4503","アステラス製薬"),
    ("4506","住友ファーマ"),("4507","塩野義製薬"),("4519","中外製薬"),("4523","エーザイ"),
    ("4543","テルモ"),("4568","第一三共"),("4578","大塚HD"),("4631","DIC"),
    ("4689","LINEヤフー"),("4704","トレンドマイクロ"),("4751","サイバーエージェント"),
    ("4755","楽天グループ"),("4901","富士フイルムHD"),("4902","コニカミノルタ"),
    ("4911","資生堂"),("5019","出光興産"),("5020","ENEOSホールディングス"),
    ("5101","横浜ゴム"),("5105","TOYO TIRES"),("5108","ブリヂストン"),
    ("5201","AGC"),("5214","日本電気硝子"),("5232","住友大阪セメント"),
    ("5233","太平洋セメント"),("5301","東海カーボン"),("5332","TOTO"),
    ("5333","日本ガイシ"),("5401","日本製鉄"),("5406","神戸製鋼所"),
    ("5411","JFEホールディングス"),("5541","大平洋金属"),("5631","日本製鋼所"),
    ("5706","三井金属鉱業"),("5707","東邦亜鉛"),("5711","三菱マテリアル"),
    ("5713","住友金属鉱山"),("5714","DOWAホールディングス"),("5802","住友電気工業"),
    ("5803","フジクラ"),("5831","りそなHD"),("6098","リクルートHD"),
    ("6103","オークマ"),("6178","日本郵政"),("6273","SMC"),
    ("6301","コマツ"),("6302","住友重機械工業"),("6305","日立建機"),
    ("6326","クボタ"),("6361","荏原製作所"),("6367","ダイキン工業"),
    ("6471","日本精工"),("6472","NTN"),("6473","ジェイテクト"),
    ("6501","日立製作所"),("6503","三菱電機"),("6504","富士電機"),
    ("6506","安川電機"),("6586","マキタ"),("6594","ニデック"),
    ("6645","オムロン"),("6647","メイコー"),("6674","GSユアサ"),
    ("6701","日本電気"),("6702","富士通"),("6703","OKI"),
    ("6724","セイコーエプソン"),("6752","パナソニックHD"),("6753","シャープ"),
    ("6758","ソニーグループ"),("6762","TDK"),("6770","アルプスアルパイン"),
    ("6857","アドバンテスト"),("6861","キーエンス"),("6902","デンソー"),
    ("6952","カシオ計算機"),("6954","ファナック"),("6971","京セラ"),
    ("6976","太陽誘電"),("6988","日東電工"),("7003","三井E&S"),
    ("7011","三菱重工業"),("7012","川崎重工業"),("7013","IHI"),
    ("7201","日産自動車"),("7202","いすゞ自動車"),("7203","トヨタ自動車"),
    ("7205","日野自動車"),("7211","三菱自動車工業"),("7261","マツダ"),
    ("7267","本田技研工業"),("7269","スズキ"),("7270","SUBARU"),
    ("7272","ヤマハ発動機"),("7309","シマノ"),("7733","オリンパス"),
    ("7741","HOYA"),("7747","朝日インテック"),("7751","キヤノン"),
    ("7752","リコー"),("7762","シチズン時計"),("7832","バンダイナムコHD"),
    ("7951","ヤマハ"),("7974","任天堂"),("8001","伊藤忠商事"),
    ("8002","丸紅"),("8003","東洋紡"),("8015","豊田通商"),
    ("8031","三井物産"),("8035","東京エレクトロン"),("8053","住友商事"),
    ("8058","三菱商事"),("8113","ユニ・チャーム"),("8233","高島屋"),
    ("8252","丸井グループ"),("8267","イオン"),("8306","三菱UFJフィナンシャルG"),
    ("8308","りそなHD"),("8309","三井住友トラストHD"),("8316","三井住友フィナンシャルG"),
    ("8411","みずほフィナンシャルグループ"),("8591","オリックス"),
    ("8601","大和証券グループ本社"),("8604","野村HD"),("8630","SOMPOホールディングス"),
    ("8697","日本取引所グループ"),("8725","MS&ADインシュアランスG HD"),
    ("8750","第一生命HD"),("8766","東京海上HD"),("8795","T&DホールディングスHD"),
    ("8801","三井不動産"),("8802","三菱地所"),("8830","住友不動産"),
    ("9001","東武鉄道"),("9005","東急"),("9007","相鉄HD"),
    ("9008","京王電鉄"),("9009","京成電鉄"),("9020","東日本旅客鉄道"),
    ("9021","西日本旅客鉄道"),("9022","東海旅客鉄道"),("9064","ヤマトHD"),
    ("9101","日本郵船"),("9104","商船三井"),("9107","川崎汽船"),
    ("9201","日本航空"),("9202","ANAホールディングス"),("9301","三菱倉庫"),
    ("9432","日本電信電話"),("9433","KDDI"),("9434","ソフトバンク"),
    ("9501","東京電力HD"),("9502","中部電力"),("9503","関西電力"),
    ("9531","東京ガス"),("9532","大阪ガス"),("9602","東宝"),
    ("9613","NTTデータグループ"),("9735","セコム"),("9766","コナミグループ"),
    ("9983","ファーストリテイリング"),("9984","ソフトバンクグループ"),
]

# 米国株急騰モード・ニュース検索のデフォルト対象（S&P500主要100社 + NASDAQ主要銘柄）
DOW30_STOCKS = [
    # ダウ30
    ("AAPL","Apple"),("AMGN","Amgen"),("AXP","American Express"),
    ("BA","Boeing"),("CAT","Caterpillar"),("CRM","Salesforce"),
    ("CSCO","Cisco"),("CVX","Chevron"),("DIS","Disney"),
    ("DOW","Dow"),("GS","Goldman Sachs"),("HD","Home Depot"),
    ("HON","Honeywell"),("IBM","IBM"),("JNJ","Johnson & Johnson"),
    ("JPM","JPMorgan Chase"),("KO","Coca-Cola"),("MCD","McDonald's"),
    ("MMM","3M"),("MRK","Merck"),("MSFT","Microsoft"),("NKE","Nike"),
    ("PG","Procter & Gamble"),("TRV","Travelers"),("UNH","UnitedHealth"),
    ("V","Visa"),("VZ","Verizon"),("WMT","Walmart"),
    # NASDAQ / テクノロジー
    ("NVDA","NVIDIA"),("META","Meta"),("GOOGL","Alphabet"),("GOOG","Alphabet C"),
    ("AMZN","Amazon"),("TSLA","Tesla"),("AVGO","Broadcom"),
    ("AMD","AMD"),("QCOM","Qualcomm"),("NFLX","Netflix"),
    ("ADBE","Adobe"),("COST","Costco"),("PEP","PepsiCo"),
    ("INTC","Intel"),("AMAT","Applied Materials"),("MU","Micron"),
    ("LRCX","Lam Research"),("KLAC","KLA Corp"),("SNPS","Synopsys"),
    ("CDNS","Cadence"),("MRVL","Marvell"),("MCHP","Microchip"),
    ("ON","ON Semiconductor"),("TXN","Texas Instruments"),("ADI","Analog Devices"),
    ("PANW","Palo Alto"),("CRWD","CrowdStrike"),("FTNT","Fortinet"),
    ("ORCL","Oracle"),("SAP","SAP"),("NOW","ServiceNow"),
    ("INTU","Intuit"),("TEAM","Atlassian"),("WDAY","Workday"),
    ("ZM","Zoom"),("UBER","Uber"),("LYFT","Lyft"),
    ("ABNB","Airbnb"),("DASH","DoorDash"),("SHOP","Shopify"),
    # ヘルスケア・製薬
    ("LLY","Eli Lilly"),("PFE","Pfizer"),("ABBV","AbbVie"),
    ("TMO","Thermo Fisher"),("DHR","Danaher"),("ABT","Abbott"),
    ("MDT","Medtronic"),("BMY","Bristol-Myers"),("GILD","Gilead"),
    ("REGN","Regeneron"),("BIIB","Biogen"),("VRTX","Vertex"),
    ("MRNA","Moderna"),("ISRG","Intuitive Surgical"),
    # 金融
    ("BRK-B","Berkshire Hathaway"),("BAC","Bank of America"),
    ("WFC","Wells Fargo"),("MS","Morgan Stanley"),("BLK","BlackRock"),
    ("SPGI","S&P Global"),("MCO","Moody's"),("ICE","ICE"),
    ("CME","CME Group"),("CB","Chubb"),("PGR","Progressive"),
    # 一般消費財・小売
    ("AMZN","Amazon"),("TGT","Target"),("LOW","Lowe's"),
    ("TJX","TJX Companies"),("BKNG","Booking Holdings"),("MAR","Marriott"),
    ("HLT","Hilton"),("MO","Altria"),("PM","Philip Morris"),
    # エネルギー・素材
    ("XOM","ExxonMobil"),("COP","ConocoPhillips"),("SLB","Schlumberger"),
    ("LIN","Linde"),("APD","Air Products"),("ECL","Ecolab"),
    ("NEM","Newmont"),("FCX","Freeport-McMoRan"),
    # 通信・公益
    ("T","AT&T"),("TMUS","T-Mobile"),("NEE","NextEra Energy"),
    ("DUK","Duke Energy"),("SO","Southern Company"),
    # 不動産・インフラ
    ("PLD","Prologis"),("AMT","American Tower"),("EQIX","Equinix"),
    ("CCI","Crown Castle"),("PSA","Public Storage"),
    # その他注目銘柄
    ("COIN","Coinbase"),("SQ","Block"),("PYPL","PayPal"),
    ("SOFI","SoFi"),("HOOD","Robinhood"),("PLTR","Palantir"),
    ("ARM","Arm Holdings"),("SMCI","Super Micro"),
]

# TOPIX Core30構成銘柄（埋め込みリスト）
TOPIX_CORE30_STOCKS = [
    ("7203","トヨタ自動車"),("8306","三菱UFJフィナンシャルG"),("9984","ソフトバンクグループ"),
    ("6758","ソニーグループ"),("8316","三井住友フィナンシャルG"),("6861","キーエンス"),
    ("7974","任天堂"),("6098","リクルートHD"),("4063","信越化学工業"),("9432","日本電信電話"),
    ("8031","三井物産"),("6367","ダイキン工業"),("8058","三菱商事"),("6857","アドバンテスト"),
    ("9983","ファーストリテイリング"),("4502","武田薬品工業"),("8001","伊藤忠商事"),
    ("6501","日立製作所"),("7267","本田技研工業"),("4568","第一三共"),
    ("8411","みずほフィナンシャルグループ"),("9433","KDDI"),("8766","東京海上HD"),
    ("6762","TDK"),("7741","HOYA"),("4543","テルモ"),("9434","ソフトバンク"),
    ("6594","ニデック"),("8802","三菱地所"),("4519","中外製薬"),
]

# NASDAQ100・S&P500フォールバック用埋め込みリスト
NASDAQ100_FALLBACK = [
    ("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),
    ("META","Meta"),("GOOGL","Alphabet A"),("GOOG","Alphabet C"),("TSLA","Tesla"),
    ("AVGO","Broadcom"),("COST","Costco"),("NFLX","Netflix"),("AMD","AMD"),
    ("ADBE","Adobe"),("QCOM","Qualcomm"),("INTU","Intuit"),("AMAT","Applied Materials"),
    ("TXN","Texas Instruments"),("MU","Micron"),("LRCX","Lam Research"),
    ("KLAC","KLA"),("MRVL","Marvell"),("PANW","Palo Alto"),("CRWD","CrowdStrike"),
    ("SNPS","Synopsys"),("CDNS","Cadence"),("ASML","ASML"),("MCHP","Microchip"),
    ("ADI","Analog Devices"),("ON","ON Semiconductor"),("FTNT","Fortinet"),
    ("ORCL","Oracle"),("NOW","ServiceNow"),("WDAY","Workday"),("TEAM","Atlassian"),
    ("ABNB","Airbnb"),("BKNG","Booking Holdings"),("PCAR","PACCAR"),("PAYX","Paychex"),
    ("CTAS","Cintas"),("FAST","Fastenal"),("VRSK","Verisk"),("DXCM","DexCom"),
    ("ADP","ADP"),("CHTR","Charter Comm"),("CMCSA","Comcast"),("TMUS","T-Mobile"),
    ("GILD","Gilead"),("AMGN","Amgen"),("REGN","Regeneron"),("BIIB","Biogen"),
    ("ISRG","Intuitive Surgical"),("VRTX","Vertex"),("ILMN","Illumina"),
    ("PEP","PepsiCo"),("MDLZ","Mondelez"),("KDP","Keurig Dr Pepper"),
    ("MNST","Monster Beverage"),("CSX","CSX"),("EA","Electronic Arts"),
    ("EBAY","eBay"),("PYPL","PayPal"),("ZS","Zscaler"),("CPRT","Copart"),
    ("GEHC","GE HealthCare"),("IDXX","IDEXX"),("EXC","Exelon"),("XEL","Xcel Energy"),
    ("AEP","AEP"),("ODFL","Old Dominion"),("ROST","Ross Stores"),("SBUX","Starbucks"),
    ("DLTR","Dollar Tree"),("TTWO","Take-Two"),("WBD","Warner Bros"),
    ("MRNA","Moderna"),("SMCI","Super Micro"),("ARM","Arm Holdings"),
    ("APP","AppLovin"),("CEG","Constellation Energy"),("GFS","GlobalFoundries"),
]

SP500_FALLBACK = [
    ("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),
    ("META","Meta"),("GOOGL","Alphabet"),("TSLA","Tesla"),("BRK-B","Berkshire"),
    ("AVGO","Broadcom"),("JPM","JPMorgan"),("LLY","Eli Lilly"),("V","Visa"),
    ("UNH","UnitedHealth"),("XOM","ExxonMobil"),("MA","Mastercard"),
    ("JNJ","J&J"),("PG","P&G"),("HD","Home Depot"),("ABBV","AbbVie"),
    ("BAC","Bank of America"),("COST","Costco"),("NFLX","Netflix"),
    ("CRM","Salesforce"),("WMT","Walmart"),("AMD","AMD"),("MRK","Merck"),
    ("CVX","Chevron"),("KO","Coca-Cola"),("PEP","PepsiCo"),("ADBE","Adobe"),
    ("TMO","Thermo Fisher"),("LIN","Linde"),("ACN","Accenture"),
    ("QCOM","Qualcomm"),("WFC","Wells Fargo"),("TXN","Texas Instruments"),
    ("GS","Goldman Sachs"),("INTU","Intuit"),("SPGI","S&P Global"),
    ("MS","Morgan Stanley"),("ISRG","Intuitive Surgical"),("AMGN","Amgen"),
    ("DHR","Danaher"),("BKNG","Booking"),("C","Citigroup"),
    ("CAT","Caterpillar"),("IBM","IBM"),("NOW","ServiceNow"),("GE","GE"),
    ("UBER","Uber"),("BLK","BlackRock"),("AXP","AmEx"),("GILD","Gilead"),
    ("PLD","Prologis"),("CMG","Chipotle"),("VRTX","Vertex"),("MDT","Medtronic"),
    ("RTX","RTX"),("BA","Boeing"),("MMM","3M"),("HON","Honeywell"),
    ("T","AT&T"),("VZ","Verizon"),("NEE","NextEra"),("DUK","Duke Energy"),
    ("MU","Micron"),("LRCX","Lam Research"),("AMAT","Applied Materials"),
    ("FCX","Freeport"),("NEM","Newmont"),("SLB","SLB"),("COP","ConocoPhillips"),
    ("EOG","EOG Resources"),("PSX","Phillips 66"),("MPC","Marathon Petroleum"),
    ("DE","Deere"),("UPS","UPS"),("FDX","FedEx"),("CSX","CSX"),("NSC","Norfolk Southern"),
    ("REGN","Regeneron"),("BIIB","Biogen"),("BMY","BMS"),("PFE","Pfizer"),
    ("ABT","Abbott"),("ELV","Elevance"),("CI","Cigna"),("HUM","Humana"),
    ("LOW","Lowe's"),("TGT","Target"),("TJX","TJX"),("NKE","Nike"),
    ("SBUX","Starbucks"),("MCD","McDonald's"),("YUM","Yum Brands"),
    ("AMT","American Tower"),("EQIX","Equinix"),("CCI","Crown Castle"),
    ("SBA","SBA Comm"),("O","Realty Income"),("PSA","Public Storage"),
]


def fetch_index_from_wikipedia(index_name: str) -> list:
    """
    WikipediaからS&P500またはNASDAQ100の構成銘柄を取得する。
    失敗した場合は埋め込みフォールバックリストを返す。
    戻り値: [(ticker, name), ...]
    """
    import requests
    from bs4 import BeautifulSoup

    urls = {
        "SP500":    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "NASDAQ100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    }
    url = urls.get(index_name)
    if not url:
        return []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        if index_name == "SP500":
            table = soup.find("table", {"id": "constituents"})
            if not table:
                raise ValueError("table not found")
            rows = table.find_all("tr")[1:]
            results = []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    ticker = cells[0].get_text(strip=True).replace(".", "-")
                    name   = cells[1].get_text(strip=True)
                    if ticker and name:
                        results.append((ticker, name))
            return results if results else SP500_FALLBACK

        elif index_name == "NASDAQ100":
            table = soup.find("table", {"id": "constituents"})
            if not table:
                tables = soup.find_all("table", class_="wikitable")
                table = tables[0] if tables else None
            if not table:
                raise ValueError("table not found")
            rows = table.find_all("tr")[1:]
            results = []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    ticker = cells[1].get_text(strip=True) if len(cells) > 1 else cells[0].get_text(strip=True)
                    name   = cells[0].get_text(strip=True)
                    if ticker and name:
                        results.append((ticker, name))
            return results if results else NASDAQ100_FALLBACK

    except Exception:
        return SP500_FALLBACK if index_name == "SP500" else NASDAQ100_FALLBACK


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
if "surge_ranking" not in st.session_state:
    st.session_state.surge_ranking = []      # 急増率ランキング結果
if "surge_top20_codes" not in st.session_state:
    st.session_state.surge_top20_codes = set()  # 急騰上位20社のコードセット
if "trend_ranking" not in st.session_state:
    st.session_state.trend_ranking = []         # AIトレンド判定結果
if "trend_sort_active" not in st.session_state:
    st.session_state.trend_sort_active = False  # トレンドソート有効フラグ
if "price_targets" not in st.session_state:
    st.session_state.price_targets = {}         # 強い上昇銘柄の株価・目標株価情報
if "news_event_info" not in st.session_state:
    st.session_state.news_event_info = {}       # ニュース検索から追加した銘柄のイベント情報
if "idx_results" not in st.session_state:
    st.session_state.idx_results = []           # インデックス検索の抽出結果
if "numerical_scores" not in st.session_state:
    st.session_state.numerical_scores = {}      # 数値スコア {code: {score, details}}
if "numerical_passed_codes" not in st.session_state:
    st.session_state.numerical_passed_codes = set()  # 数値フィルタ通過銘柄コード
if "auto_trend_active" not in st.session_state:
    st.session_state.auto_trend_active = False   # 「AIトレンド判定まで自動で行う」の実行中フラグ
if "market" not in st.session_state:
    st.session_state.market = "jp"   # "jp" または "us"


# ----------------------------------------------------------------------
# スクレイピング関連
# ----------------------------------------------------------------------
def gemini_generate_with_search(model, prompt, contents_extra=None):
    """
    Geminiでウェブ検索グラウンディングを使ってcontentを生成する共通ヘルパー。

    重要: 旧パッケージ google-generativeai はサポート終了しており、
    最新版でも search grounding 用の `google_search` ツールが正しく機能しない
    （AttributeError、またはサーバー側が旧方式 google_search_retrieval を拒否）。
    そのため、新しい google-genai パッケージ（`from google import genai`）を
    最優先で使用する。model引数には init_gemini 等で `_api_key` 属性を
    付与した旧SDKのGenerativeModelインスタンスを渡す（api_key取得のため）。

    戻り値: (response_text, warning_message or None)
    """
    api_key = getattr(model, "_api_key", None)
    contents = [prompt] if contents_extra is None else contents_extra + [prompt]
    _attempt_log = []

    # ── 方式1（最優先）: 新パッケージ google-genai ──
    if api_key:
        try:
            from google import genai as _new_genai
            from google.genai import types as _new_types

            client = _new_genai.Client(api_key=api_key)
            search_tool = _new_types.Tool(google_search=_new_types.GoogleSearch())
            config = _new_types.GenerateContentConfig(tools=[search_tool])
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config,
            )
            if resp.text:
                return resp.text, None
            _attempt_log.append("方式1(google-genai): 空のレスポンス")
        except Exception as e:
            _attempt_log.append(f"方式1(google-genai): {type(e).__name__} {e}")
    else:
        _attempt_log.append("方式1(google-genai): api_keyが取得できずスキップ")

    # ── 方式2（フォールバック）: 旧パッケージ google-generativeai ──
    import google.generativeai as _genai
    try:
        search_tool = _genai.protos.Tool(
            google_search=_genai.protos.GoogleSearch()
        )
        resp = model.generate_content(contents, tools=[search_tool])
        return resp.text, None
    except Exception as e:
        _attempt_log.append(f"方式2(旧SDK google_search): {type(e).__name__} {e}")

    # すべて失敗 → 検索なしにフォールバックしつつ、診断情報を残す
    try:
        _installed_ver = _genai.__version__
    except Exception:
        _installed_ver = "不明"
    reason = (
        f"インストール済み google-generativeai バージョン: {_installed_ver} ／ "
        + " / ".join(_attempt_log)
    )
    return _gemini_fallback_no_search(model, contents, reason)


def _gemini_fallback_no_search(model, contents, reason: str):
    """検索グラウンディングが一切使えない場合、検索なしで生成する最終フォールバック"""
    try:
        resp = model.generate_content(contents)
        return resp.text, (
            f"Web検索(グラウンディング)が利用できずフォールバックしました。"
            f"結果は最新情報を反映していない可能性があります。［診断情報: {reason}］"
        )
    except Exception as e2:
        return "", f"{type(e2).__name__}: {e2}"


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
    # 英字のみのコード（例: MBLY, SOFI）は market 設定に関わらず米国株として扱う
    effective_market = "us" if re.fullmatch(r"[A-Z]{1,6}", code.upper()) else market
    if effective_market == "us":
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
        # 英字のみのコードは米国株として補正をスキップする。
        if effective_market != "us":
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



def calc_volume_surge_ratio(series: list) -> float:
    """
    直近7日間の平均出来高 ÷ 過去23日間の平均出来高 を返す。
    データが30日未満の場合は 0 を返す。
    """
    if len(series) < 30:
        return 0.0
    recent7 = series[-7:]
    prev23  = series[-30:-7]
    avg_recent = sum(d["volume"] for d in recent7) / len(recent7)
    avg_prev   = sum(d["volume"] for d in prev23)  / len(prev23)
    if avg_prev == 0:
        return 0.0
    return avg_recent / avg_prev

def fetch_series_from_yfinance(
    code: str, market: str, tf_key: str, lookback_date=None
) -> list:
    """
    Yahoo Finance から株価データ（OHLCV）を取得して
    [{"date":..,"open":..,"high":..,"low":..,"close":..,"volume":..}, ...]
    形式のリストを返す。
    市場: "jp" → コード.T (東証)、"us" → ティッカーそのまま

    ※ 画像読み取りなどでmarket="jp"のままUS株コード（英字）が混入した場合でも
      コード形式を自動判定して正しいティッカーに変換する。
      英字のみで構成されるコード（例: MBLY, SOFI）は米国株として扱う。
    tf_key: "day"=日足(6ヶ月) / "week"=週足(2年) / "month"=月足(5年)
    lookback_date: 指定した場合、この日付以前のデータのみを返す
                   （チャートルックバック機能。Noneの場合は本日まで全件）
    """
    import yfinance as yf

    # コード形式で市場を自動判定
    # 英字のみ（1〜6文字）→ 米国株ティッカーとして扱う
    # 数字始まり or 英数字混合4文字 → 日本株として".T"を付ける
    if re.fullmatch(r"[A-Z]{1,6}", code.upper()):
        ticker_symbol = code.upper()        # 米国株: そのまま
    elif market == "jp":
        ticker_symbol = f"{code}.T"         # 日本株: .T付き
    else:
        ticker_symbol = code.upper()        # 米国株: そのまま

    period_map   = {"day": "6mo",  "week": "2y",  "month": "5y"}
    interval_map = {"day": "1d",   "week": "1wk", "month": "1mo"}

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

    # チャートルックバック：指定日以降のデータを切り捨てる
    if lookback_date is not None:
        cutoff_str = lookback_date.strftime("%Y%m%d")
        series = [d for d in series if d["date"] <= cutoff_str]

    return series


def fetch_chart_images(code: str, name: str, market: str = "jp", lookback_date=None):
    """
    日足・週足・月足それぞれのチャートPNG（bytes）を辞書で返す。
    また日足の生データ（OHLCVリスト）も合わせて返す。
    戻り値: (charts_dict, daily_series)
      charts_dict: {"day": png_bytes, "week": png_bytes, "month": png_bytes}
      daily_series: [{"date","open","high","low","close","volume"}, ...]
    lookback_date: 指定した場合、この日付以前のデータのみで分析する
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
            series = fetch_series_from_yfinance(code, market, key, lookback_date=lookback_date)
        except Exception:
            series = None

        # --- 2. フォールバック: 株探チャートAPI ---
        if not series:
            try:
                series = fetch_kabutan_series(code, m_num, market=market)
                # 株探APIフォールバック時もルックバックを適用
                if series and lookback_date is not None:
                    cutoff_str = lookback_date.strftime("%Y%m%d")
                    series = [d for d in series if d["date"] <= cutoff_str]
            except Exception:
                series = None

        if lookback_date is not None:
            title = f"{title}（{lookback_date.strftime('%Y/%m/%d')}時点）"

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
    model = genai.GenerativeModel(model_name)
    model._api_key = api_key  # 検索グラウンディング用に新SDK呼び出し時に使う
    return model


def analyze_company_with_gemini(model, code: str, name: str) -> dict:
    import datetime
    today = datetime.date.today().strftime("%Y年%m月%d日")
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(code=code, name=name, today=today)

    # Google検索グラウンディングを有効にして最新情報を取得する
    # これによりブラウザ版Geminiと同等の最新データが得られる
    response_text, _warn = gemini_generate_with_search(model, prompt)
    if not response_text:
        return {
            "company_overview": f"取得失敗: {_warn or '不明なエラー'}",
            "latest_earnings": "-",
            "valuation": "-",
            "dividend_yield": "-",
            "analyst_target": "-",
        }

    try:
        text = response_text.strip()
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


def generate_analysis_pdf(companies, analysis, charts, daily_series=None,
                           trend_ranking=None) -> bytes:
    """
    分析結果（直近7営業日テーブル＋テキスト5項目＋日足・週足・月足チャート）を
    A4縦のPDFにまとめてバイト列で返す。
    trend_rankingが渡された場合はランキング表を冒頭に追加し、
    各社セクションにもトレンド判定情報を挿入する。
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
    has_trend = bool(trend_ranking)
    trend_map = {item["code"]: item for item in (trend_ranking or [])}
    title_suffix = "（AIトレンド判定付き）" if has_trend else ""
    story.append(Paragraph(f"株探 銘柄探検 分析レポート{title_suffix}", s_title))
    story.append(Paragraph(f"作成日: {today_str}　　銘柄数: {len(companies)}社", s_header))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#1a237e"), spaceAfter=8))

    # ── AIトレンド判定ランキング表（冒頭） ──
    if has_trend:
        story.append(Paragraph("📊 AIトレンド判定ランキング", s_label))
        story.append(Paragraph(
            "数値スコア（MA・価格動向）でまず絞り込み、上位銘柄をVision AIが詳細判定。",
            s_header
        ))
        story.append(Spacer(1, 2*mm))

        rank_data = [["順位", "銘柄名（コード）", "総合判定", "日足", "週足", "月足", "確信度"]]
        overall_order = {"強い上昇": 5, "上昇": 4, "横ばい": 3, "下降": 2, "強い下降": 1}
        for rank_i, item in enumerate(trend_ranking, 1):
            icon, _ = TREND_LABELS.get(item["overall"], ("⚪", 3))
            d = item["details"]
            rank_data.append([
                str(rank_i),
                f"{item['name']}（{item['code']}）",
                f"{icon} {item['overall']}",
                f"{_score_to_symbol(d['day'])} {item.get('day_trend','')}",
                f"{_score_to_symbol(d['week'])} {item.get('week_trend','')}",
                f"{_score_to_symbol(d['month'])} {item.get('month_trend','')}",
                "★" * item["confidence"] + "☆" * (5 - item["confidence"]),
            ])

        rank_tbl = Table(
            rank_data,
            colWidths=[12*mm, 55*mm, 28*mm, 22*mm, 22*mm, 22*mm, 22*mm],
            hAlign="LEFT",
        )
        rank_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#1a237e")),
            ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",     (0, 0), (-1, -1), font_name),
            ("FONTSIZE",     (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.HexColor("#f5f5f5"), colors.white]),
            ("ALIGN",        (0, 0), (0, -1),  "CENTER"),
            ("ALIGN",        (2, 0), (-1, -1), "CENTER"),
            ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#bdbdbd")),
            ("TOPPADDING",   (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
        ]))
        story.append(rank_tbl)
        story.append(Spacer(1, 6*mm))
        story.append(PageBreak())

    page_w = A4[0] - 30 * mm  # 利用可能な幅

    for i, company in enumerate(companies):
        code, name = company["code"], company["name"]
        if code not in analysis and code not in (charts or {}):
            continue

        # 会社名ヘッダー（ランキング順位付き）
        rank_prefix = ""
        trend_item  = trend_map.get(code)
        if has_trend and trend_item:
            rank_pos = next((j for j, t in enumerate(trend_ranking, 1)
                             if t["code"] == code), None)
            if rank_pos:
                icon, _ = TREND_LABELS.get(trend_item["overall"], ("⚪", 3))
                rank_prefix = f"[{rank_pos}位 {icon} {trend_item['overall']}] "
        story.append(Paragraph(f"{rank_prefix}{name}（{code}）", s_title))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                 color=colors.HexColor("#90caf9"), spaceAfter=4))

        # トレンド判定サマリー（判定済みの場合）
        if has_trend and trend_item:
            d = trend_item["details"]
            conf_str = "★" * trend_item["confidence"] + "☆" * (5 - trend_item["confidence"])
            trend_summary = (
                f"【AIトレンド判定】 "
                f"日足: {_score_to_symbol(d['day'])}{trend_item.get('day_trend','')}　"
                f"週足: {_score_to_symbol(d['week'])}{trend_item.get('week_trend','')}　"
                f"月足: {_score_to_symbol(d['month'])}{trend_item.get('month_trend','')}　"
                f"確信度: {conf_str}"
            )
            if trend_item.get("comment"):
                trend_summary += f"　コメント: {trend_item['comment']}"
            story.append(Paragraph(trend_summary, s_header))
            story.append(Spacer(1, 2*mm))

            # 価格情報（「強い上昇」銘柄のみ）
            if trend_item.get("overall") == "強い上昇":
                pt = (daily_series or {}).get(f"__price_target_{code}")
                # price_targetsはdaily_seriesではなく別途渡す必要があるため
                # companies内にprice_target_keyとして埋め込む
                pt = company.get("_price_target")
                if pt:
                    is_jp_pt = len(str(code)) == 4 and code.isdigit()
                    price_str = format_price_target_str(pt, is_jp=is_jp_pt)
                    if price_str:
                        story.append(Paragraph(f"【価格情報】 {price_str}", s_label))
                        story.append(Spacer(1, 2*mm))

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
# 画像から銘柄抽出（Vision API）
# ----------------------------------------------------------------------
IMAGE_EXTRACT_PROMPT = """\
この画像から銘柄コードと銘柄名を全て抽出してください。
- 日本株: 4桁の数字コード（例: 1693, 7203）と銘柄名
- 米国株: 英字ティッカー（例: AAPL, NVDA）と銘柄名
- 重複は除いてください
- コードと銘柄名のペアのみ抽出し、株価・数量・損益などの数値は不要です

出力は以下のJSON形式のみで返してください（前後に説明文・コードブロック記号は不要）：
{"stocks": [{"code": "1693", "name": "銅ETF"}, {"code": "1615", "name": "NF銀行業"}]}
"""


def _detect_media_type(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/png"  # デフォルト


def _parse_stock_json(text: str) -> list:
    """AIの返答からJSONを取り出してstocksリストを返す"""
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return data.get("stocks", [])
        except Exception:
            pass
    return []


def extract_stocks_from_image_claude(image_bytes: bytes, api_key: str) -> list:
    import anthropic, base64
    client = anthropic.Anthropic(api_key=api_key)
    media_type = _detect_media_type(image_bytes)
    img_b64 = base64.standard_b64encode(image_bytes).decode()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": img_b64}},
            {"type": "text", "text": IMAGE_EXTRACT_PROMPT},
        ]}],
    )
    return _parse_stock_json(response.content[0].text)


def extract_stocks_from_image_grok(image_bytes: bytes, api_key: str) -> list:
    from openai import OpenAI
    import base64
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    media_type = _detect_media_type(image_bytes)
    img_b64 = base64.standard_b64encode(image_bytes).decode()
    response = client.chat.completions.create(
        model="grok-4.3",
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:{media_type};base64,{img_b64}"}},
            {"type": "text", "text": IMAGE_EXTRACT_PROMPT},
        ]}],
    )
    return _parse_stock_json(response.choices[0].message.content)


def extract_stocks_from_image_gemini(image_bytes: bytes, api_key: str) -> list:
    import google.generativeai as genai
    import base64
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    media_type = _detect_media_type(image_bytes)
    img_b64 = base64.standard_b64encode(image_bytes).decode()
    response = model.generate_content([
        {"mime_type": media_type, "data": img_b64},
        IMAGE_EXTRACT_PROMPT,
    ])
    return _parse_stock_json(response.text)


def extract_stocks_from_image(
    image_bytes: bytes,
    api_choice: str,
    claude_api_key: str = "",
    grok_api_key: str = "",
    gemini_api_key: str = "",
) -> list:
    """選択中のAIエンジンで画像から銘柄を抽出する"""
    if api_choice == "Claude API（推奨）":
        return extract_stocks_from_image_claude(image_bytes, claude_api_key)
    elif api_choice == "Grok API":
        return extract_stocks_from_image_grok(image_bytes, grok_api_key)
    else:
        return extract_stocks_from_image_gemini(image_bytes, gemini_api_key)


# ----------------------------------------------------------------------
# AIトレンド判定（数値スコアリング + Vision API）
# ----------------------------------------------------------------------
TREND_LABELS = {
    "強い上昇": ("🟢", 5), "上昇": ("🟡", 4),
    "横ばい":   ("⚪", 3), "下降": ("🔴", 2), "強い下降": ("🔴", 1),
}
TF_LABEL = {"day": "日足", "week": "週足", "month": "月足"}


def calc_trend_score(series_day: list, series_week: list, series_month: list):
    """
    数値データからトレンドスコアを計算する（0〜7点）。
    日足・週足・月足それぞれ2点満点（計6点、既存ロジックを完全踏襲）に加え、
    さらに厳しい追加条件（直近25営業日の新高値更新）を満たした場合のみ7点目を加点する。
    戻り値: (total_score, {"day": 0-2, "week": 0-2, "month": 0-2, "extra": 0-1})
    """
    score = 0
    details = {"day": 0, "week": 0, "month": 0, "extra": 0}

    # ── 日足（既存ロジックを完全踏襲） ──
    if len(series_day) >= 25:
        closes = [d["close"] for d in series_day]
        ma5  = sum(closes[-5:]) / 5
        ma25 = sum(closes[-25:]) / 25
        if closes[-1] > ma25:   score += 1; details["day"] += 1  # 終値 > MA25
        if ma5 > ma25:          score += 1; details["day"] += 1  # MA5 > MA25（GC状態）

    # ── 週足（既存ロジックを完全踏襲） ──
    if len(series_week) >= 4:
        wc = [d["close"] for d in series_week[-4:]]
        rising = sum(1 for i in range(1, len(wc)) if wc[i] >= wc[i - 1])
        if rising >= 2:         score += 1; details["week"] += 1  # 4週中2週以上上昇
        if wc[-1] > wc[0]:     score += 1; details["week"] += 1  # 4週前より高値

    # ── 月足（既存ロジックを完全踏襲） ──
    if len(series_month) >= 3:
        mc = [d["close"] for d in series_month[-3:]]
        if mc[-1] > mc[-2]:    score += 1; details["month"] += 1  # 前月より上昇
        if mc[-1] > mc[0]:     score += 1; details["month"] += 1  # 3ヶ月前より高値

    # ── 追加条件（7点目）：直近25営業日の終値ベース新高値更新 ──
    # 1〜6点の基準を満たした上で、さらに直近の値動きが特に強い銘柄のみ加点する
    # （日足・週足・月足すべてで満点=6点を取得していることが前提条件）
    if score == 6 and len(series_day) >= 25:
        closes = [d["close"] for d in series_day]
        recent_25_high = max(closes[-25:-1]) if len(closes) >= 25 else None
        if recent_25_high is not None and closes[-1] > recent_25_high:
            score += 1
            details["extra"] = 1

    return score, details


def _score_to_symbol(s: int) -> str:
    return {2: "◎", 1: "○", 0: "△"}[s]


def judge_trend_vision(
    code: str, name: str, charts: dict,
    api_choice: str,
    claude_api_key: str = "", grok_api_key: str = "", gemini_api_key: str = "",
) -> dict | None:
    """
    チャート画像（日足・週足・月足）をVision APIに送りトレンドを判定する。
    戻り値: {"day_trend":..,"week_trend":..,"month_trend":..,"overall":..,"confidence":1-5,"comment":...}
    """
    import base64

    images = [
        (charts[tf], TF_LABEL[tf])
        for tf in ("day", "week", "month")
        if charts.get(tf)
    ]
    if not images:
        return None

    prompt = (
        f"{name}（コード: {code}）の株価チャートです。"
        f"{'・'.join(lbl for _, lbl in images)}の順に提示します。\n\n"
        "各チャートのトレンドを判定し、必ず以下のJSON形式のみで返してください"
        "（前後の説明文・コードブロック記号不要）：\n"
        '{"day_trend":"上昇|横ばい|下降",'
        '"week_trend":"上昇|横ばい|下降",'
        '"month_trend":"上昇|横ばい|下降",'
        '"overall":"強い上昇|上昇|横ばい|下降|強い下降",'
        '"confidence":1から5の整数,'
        '"comment":"判定理由を1文で"}'
    )

    def parse(text: str) -> dict | None:
        text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

    try:
        if api_choice == "Claude API（推奨）":
            import anthropic as _anth
            content = []
            for png, _ in images:
                b64 = base64.standard_b64encode(png).decode()
                content.append({"type": "image",
                                 "source": {"type": "base64",
                                            "media_type": "image/png", "data": b64}})
            content.append({"type": "text", "text": prompt})
            resp = _anth.Anthropic(
                api_key=claude_api_key, timeout=60.0
            ).messages.create(
                model="claude-sonnet-4-6", max_tokens=600,
                messages=[{"role": "user", "content": content}],
            )
            return parse(resp.content[0].text)

        elif api_choice == "Grok API":
            from openai import OpenAI as _OAI
            content = []
            for png, _ in images:
                b64 = base64.standard_b64encode(png).decode()
                content.append({"type": "image_url",
                                 "image_url": {"url": f"data:image/png;base64,{b64}"}})
            content.append({"type": "text", "text": prompt})
            resp = _OAI(
                api_key=grok_api_key,
                base_url="https://api.x.ai/v1",
                timeout=60.0,
            ).chat.completions.create(
                model="grok-4.3", max_tokens=600,
                messages=[{"role": "user", "content": content}],
            )
            return parse(resp.choices[0].message.content)

        else:  # Gemini
            import google.generativeai as _genai
            _genai.configure(api_key=gemini_api_key)
            parts = []
            for png, _ in images:
                b64 = base64.standard_b64encode(png).decode()
                parts.append({"mime_type": "image/png", "data": b64})
            parts.append(prompt)
            resp = _genai.GenerativeModel("gemini-2.5-flash").generate_content(
                parts,
                request_options={"timeout": 60},
            )
            return parse(resp.text)

    except Exception:
        return None



# ----------------------------------------------------------------------
# 価格・アナリスト目標株価の取得
# ----------------------------------------------------------------------
def fetch_price_target_yfinance(code: str, market: str) -> dict:
    """
    yfinanceからアナリスト目標株価を取得する。
    戻り値: {"target_mean": ..., "target_low": ..., "target_high": ...,
             "analyst_count": ...}
    """
    import yfinance as yf
    symbol = (f"{code}.T"
              if (market == "jp" and not re.fullmatch(r"[A-Z]{1,6}", code.upper()))
              else code.upper())
    try:
        info = yf.Ticker(symbol).info
        return {
            "target_mean":    info.get("targetMeanPrice"),
            "target_low":     info.get("targetLowPrice"),
            "target_high":    info.get("targetHighPrice"),
            "analyst_count":  info.get("numberOfAnalystOpinions"),
        }
    except Exception:
        return {}


def fetch_price_target_minkabu(
    code: str, name: str,
    api_choice: str,
    claude_api_key: str = "", grok_api_key: str = "", gemini_api_key: str = "",
) -> dict:
    """
    AIのWeb検索でminkabu.jpの予想株価を取得するフォールバック。
    戻り値: {"target_mean": ..., "target_low": ..., "target_high": ...}
    """
    import anthropic as _anth

    prompt = (
        f"minkabu.jp で証券コード {code}（{name}）の"
        "「みんかぶ予想株価」または「みんかぶAI理論株価」を検索してください。\n"
        "出力は以下のJSONのみで（前後に説明文不要）：\n"
        '{"target_mean": 数値またはnull, '
        '"target_low": 数値またはnull, '
        '"target_high": 数値またはnull}'
    )

    def _parse(text: str) -> dict:
        text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {}

    try:
        if api_choice == "Claude API（推奨）":
            tools = [{"type": "web_search_20250305", "name": "web_search"}]
            messages = [{"role": "user", "content": prompt}]
            client = _anth.Anthropic(api_key=claude_api_key)
            while True:
                resp = client.messages.create(
                    model="claude-sonnet-4-6", max_tokens=500,
                    tools=tools, messages=messages,
                )
                messages.append({"role": "assistant", "content": resp.content})
                if resp.stop_reason == "end_turn":
                    break
                tr = [{"type": "tool_result", "tool_use_id": b.id, "content": ""}
                      for b in resp.content if b.type == "tool_use"]
                if tr:
                    messages.append({"role": "user", "content": tr})
                else:
                    break
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            return _parse(text)

        elif api_choice == "Grok API":
            from openai import OpenAI as _OAI
            resp = _OAI(api_key=grok_api_key,
                        base_url="https://api.x.ai/v1").responses.create(
                model="grok-4.3",
                input=[{"role": "user", "content": prompt}],
                tools=[{"type": "web_search"}],
            )
            return _parse(resp.output_text)

        else:  # Gemini
            import google.generativeai as _genai
            _genai.configure(api_key=gemini_api_key)
            model = _genai.GenerativeModel("gemini-2.5-flash")
            model._api_key = gemini_api_key
            text, _warn = gemini_generate_with_search(model, prompt)
            return _parse(text) if text else {}
    except Exception:
        return {}


def get_price_target(
    code: str, name: str, market: str, current_price: float,
    api_choice: str,
    claude_api_key: str = "", grok_api_key: str = "", gemini_api_key: str = "",
) -> dict:
    """
    アナリスト目標株価と乖離率をまとめて返す。
    yfinanceで取得できなければAI+みんかぶで補完。
    戻り値: {"current": ..., "target_mean": ..., "target_low": ...,
             "target_high": ..., "divergence": ..., "source": ...}
    """
    result = {
        "current":    current_price,
        "target_mean": None, "target_low": None, "target_high": None,
        "divergence": None, "source": "なし",
    }

    # ① yfinanceから試みる
    yf_data = fetch_price_target_yfinance(code, market)
    if yf_data.get("target_mean"):
        result.update({
            "target_mean":  yf_data["target_mean"],
            "target_low":   yf_data.get("target_low"),
            "target_high":  yf_data.get("target_high"),
            "source": f"アナリスト予想（{yf_data.get('analyst_count','?')}名）",
        })

    # ② 取得できなければみんかぶをAIで検索
    if not result["target_mean"] and (claude_api_key or grok_api_key or gemini_api_key):
        mk_data = fetch_price_target_minkabu(
            code, name, api_choice,
            claude_api_key, grok_api_key, gemini_api_key,
        )
        if mk_data.get("target_mean"):
            result.update({
                "target_mean":  mk_data["target_mean"],
                "target_low":   mk_data.get("target_low"),
                "target_high":  mk_data.get("target_high"),
                "source": "みんかぶ予想",
            })

    # ③ 乖離率計算（プラス=割安、マイナス=割高）
    if result["target_mean"] and current_price and current_price > 0:
        div = (result["target_mean"] - current_price) / current_price * 100
        result["divergence"] = div

    return result


def format_price_target_str(pt: dict, is_jp: bool) -> str:
    """価格情報を表示用文字列に整形する"""
    unit = "円" if is_jp else "$"
    cur = pt.get("current")
    tmean = pt.get("target_mean")
    tlow  = pt.get("target_low")
    thigh = pt.get("target_high")
    div   = pt.get("divergence")
    src   = pt.get("source", "")

    if cur is None:
        return ""
    if is_jp:
        cur_str = f"{cur:,.0f}{unit}"
    else:
        cur_str = f"{cur:.2f}{unit}"

    parts = [f"現在株価：{cur_str}"]
    if tmean:
        if is_jp:
            if tlow and thigh and tlow != thigh:
                parts.append(f"目標株価（{src}）：{tlow:,.0f}〜{thigh:,.0f}{unit}")
            else:
                parts.append(f"目標株価（{src}）：{tmean:,.0f}{unit}")
        else:
            if tlow and thigh and tlow != thigh:
                parts.append(f"目標株価（{src}）：{tlow:.2f}〜{thigh:.2f}{unit}")
            else:
                parts.append(f"目標株価（{src}）：{tmean:.2f}{unit}")
        if div is not None:
            sign = "+" if div >= 0 else ""
            parts.append(f"（乖離率 {sign}{div:.1f}%）")
    return "　　".join(parts)


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

    surge_mode = st.checkbox(
        "📈 出来高急騰銘柄２０",
        value=False,
        help=(
            "チェックを入れると急騰銘柄探索モードになります。\n"
            "「更新」ボタンを押すと、銘柄リストを取得後に自動で全銘柄の\n"
            "出来高を取得し、直近7日間の平均出来高 ÷ 過去23日間の平均\n"
            "出来高の比率が高い上位20銘柄を自動選定して表示します。\n"
            "「米国株版」と組み合わせて使えます。"
        ),
    )
    if surge_mode:
        st.caption("🔍 急騰モード有効：「更新」を押すと自動で上位20社を選定します")

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

    # 「分析する会社数」のデフォルト値を取得済み銘柄数に動的に連動させる。
    # 銘柄リストが更新された（件数が変わった）タイミングでのみ既定値を更新し、
    # ユーザーが手動でスライダーを動かした後の値は保持する。
    # ※ st.slider の key と同名の session_state を widget生成前に更新する必要があるため、
    #   ここでの代入は st.slider() 呼び出しより必ず前に置くこと。
    _current_company_count = len(st.session_state.companies)
    if "analyze_count_last_synced_total" not in st.session_state:
        st.session_state.analyze_count_last_synced_total = -1
    if "analyze_count" not in st.session_state:
        st.session_state["analyze_count"] = 30

    if _current_company_count != st.session_state.analyze_count_last_synced_total:
        # 銘柄数が変化した→デフォルト値を「取得件数」（上限1000）に合わせて更新
        default_count = min(max(_current_company_count, 1), 1000) if _current_company_count > 0 else 30
        st.session_state["analyze_count"] = default_count
        st.session_state.analyze_count_last_synced_total = _current_company_count

    analyze_count = st.slider(
        "分析する会社数",
        min_value=1,
        max_value=1000,
        step=1,
        help="対象銘柄数。デフォルトは取得した銘柄リストの件数に自動追従します。30超の場合はフェーズ1（数値判定）で絞り込んだ後にAPIを使います。急騰モード時は全銘柄が対象。",
        key="analyze_count",
    )

    score_threshold = st.slider(
        "数値スコア閾値（API節約フィルター）",
        min_value=1, max_value=7, value=5, step=1,
        help=(
            "7点満点（基本6点＋直近25営業日の新高値更新で+1点）。"
            "この点数以上の銘柄のみAI（Vision）判定へ進みます。高いほどAPI費用を節約できます。\n"
            "7点は基本6点を満たした上でさらに直近高値を更新している、特に厳しい基準です。"
        ),
    )

    use_divergence_filter = st.checkbox(
        "適正株価乖離率フィルター",
        value=True,
        help=(
            "「🔍 AIトレンド判定」ボタンを押した時、数値スコア閾値を通過した銘柄について"
            "アナリスト予想の適正株価との乖離率を確認し、指定値以上のもののみを"
            "Vision AI判定の対象にします（この確認にはAPI/Web検索を使用します）。\n"
            "OFFの場合はこれまで通り乖離率チェックなしで判定します。"
        ),
        key="use_divergence_filter",
    )
    divergence_threshold = st.number_input(
        "適正株価までの上昇余地（%）以上",
        min_value=0.0,
        value=5.0,
        step=1.0,
        disabled=not use_divergence_filter,
        help=(
            "現在株価からアナリスト予想の適正株価までの上昇余地が、この値（%）以上の"
            "銘柄のみをVision AI判定対象とします。適正株価はまずyfinanceのアナリスト予想"
            "平均値を取得し、取得できない場合はAIでみんかぶの予想株価を検索します。"
        ),
        key="divergence_threshold",
    )

    # チャートルックバック：基準日をN日前にずらして分析する（バックテスト用途）
    lookback_date = st.date_input(
        "チャートルックバック（基準日）",
        value=_date.today(),
        max_value=_date.today(),
        help=(
            "分析の基準日をカレンダーから選択します。デフォルトは本日（ルックバック0日）。\n"
            "過去の日付を選ぶと、その日時点のチャート・数値判定・AIトレンド判定・"
            "価格情報を再現します（その日以降のデータは使用しません）。"
        ),
        key="lookback_date",
    )
    lookback_days = (_date.today() - lookback_date).days
    if lookback_days > 0:
        st.caption(f"📅 {lookback_days}日前（{lookback_date.strftime('%Y/%m/%d')}）を基準に分析します。")

    col1, col2, col3 = st.columns(3)
    with col1:
        update_clicked = st.button("🔄 更新", use_container_width=True)
    with col2:
        analyze_clicked = st.button("🔍 分析", use_container_width=True)
    with col3:
        chart_only_clicked = st.button("📊 グラフのみ", use_container_width=True,
                                       help="APIキー不要。チャートデータの取得と描画のみ行います。")

    # フェーズ1+2：チャート取得＋数値判定（APIなし）
    _sm_running_pre = st.session_state.get("auto_trend_active", False)
    numerical_clicked = st.button(
        "📈 チャート取得＋数値判定（APIなし）",
        use_container_width=True,
        disabled=_sm_running_pre,
        help=(
            "フェーズ1：全銘柄のチャートをyfinanceで取得\n"
            "フェーズ2：MA・週足・月足の数値スコアで上昇銘柄を自動フィルタ\n"
            "→ 閾値以上の銘柄のみを残してAI判定待ちにします（APIコストゼロ）"
        ),
    )

    # APIキーが入力されているときのみ有効な全自動ボタン
    active_key_for_auto = claude_api_key or grok_api_key or gemini_api_key
    _auto_running = st.session_state.get("auto_trend_active", False)
    auto_trend_clicked = st.button(
        "🚀 AIトレンド判定まで自動で行う",
        use_container_width=True,
        disabled=(not bool(active_key_for_auto)) or _auto_running,
        help=(
            "フェーズ1（チャート取得）→フェーズ2（数値フィルタ）→"
            "フェーズ3（Vision AI判定）を一括実行します。\n"
            "APIキーが入力されている場合に有効になります。\n"
            "処理中は少量ずつバッチ処理を繰り返すため、画面を開いたままお待ちください。"
        ),
    )
    if _auto_running:
        _stage_label = {
            "chart":       "STEP 1/4 グラフ取得中",
            "score":       "STEP 2/4 数値スコア計算中",
            "divergence":  "STEP 2.5/4 適正株価の乖離率を確認中",
            "vision":      "STEP 3/4 Vision AI判定中",
            "price":       "STEP 4/4 目標株価取得中",
            "done":        "仕上げ処理中",
            "done_numerical": "仕上げ処理中",
            "done_numerical_empty": "仕上げ処理中",
        }.get(st.session_state.get("auto_trend_stage"), "処理中")
        st.caption(f"⏳ 処理実行中：{_stage_label}（このまま画面を開いたままお待ちください）")

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
    st.session_state.surge_ranking = []
    st.session_state.surge_top20_codes = set()
    st.session_state.trend_ranking = []
    st.session_state.trend_sort_active = False
    st.session_state.pop("_numerical_score_rows_cache", None)
    st.session_state.price_targets = {}
    if "company_editor" in st.session_state:
        del st.session_state["company_editor"]
    if companies:
        st.success(f"{market_label}として{len(companies)}件の銘柄を取得しました。")
        # 急騰モードが有効な場合は自動で出来高解析を実行
        if surge_mode:
            progress = st.progress(0.0, text="急騰銘柄を探索中... 全銘柄の出来高データを取得しています")
            for i, company in enumerate(companies):
                code, name = company["code"], company["name"]
                try:
                    series = fetch_series_from_yfinance(code, market, "day", lookback_date=get_effective_lookback_date())
                    st.session_state.daily_series[code] = series
                except Exception:
                    st.session_state.daily_series[code] = []
                progress.progress(
                    (i + 1) / len(companies),
                    text=f"出来高データ取得中... ({i+1}/{len(companies)}) {name}"
                )

            # 急増率でランキング
            surge_ranking = []
            for company in companies:
                code = company["code"]
                series = st.session_state.daily_series.get(code, [])
                ratio = calc_volume_surge_ratio(series)
                surge_ranking.append({"company": company, "ratio": ratio})
            surge_ranking.sort(key=lambda x: x["ratio"], reverse=True)
            top20 = surge_ranking[:20]
            top20_codes = {item["company"]["code"] for item in top20}

            # 上位20社のチャートを取得
            progress2 = st.progress(0.0, text="上位20社のチャートを描画中...")
            for i, item in enumerate(top20):
                code = item["company"]["code"]
                name = item["company"]["name"]
                charts, daily = fetch_chart_images(code, name, market=market, lookback_date=get_effective_lookback_date())
                st.session_state.charts[code] = charts
                if daily:
                    st.session_state.daily_series[code] = daily
                progress2.progress(
                    (i + 1) / 20,
                    text=f"チャート描画中... ({i+1}/20) {name}"
                )

            progress.empty()
            progress2.empty()
            st.session_state.surge_ranking = surge_ranking
            st.session_state.surge_top20_codes = top20_codes
            st.success(f"急騰銘柄探索完了。{len(companies)}社中、出来高急騰上位20社を表示します。")
    else:
        if surge_mode:
            # 急騰モード時はデフォルトリストで自動実行
            default_list = DOW30_STOCKS if market == "us" else NIKKEI225_STOCKS
            companies = [{"code": code, "name": name} for code, name in default_list]
            st.session_state.companies = companies
            label = "NYダウ30＋NASDAQ主要銘柄" if market == "us" else "日経225銘柄"
            st.warning(
                f"kabutan.jpへのアクセスに失敗しました。"
                f"**{label}**（{len(companies)}社）を対象として出来高急騰銘柄を探索します。"
            )
            progress = st.progress(0.0, text=f"{label}の出来高データを取得中...")
            for i, company in enumerate(companies):
                code, name = company["code"], company["name"]
                try:
                    series = fetch_series_from_yfinance(code, market, "day", lookback_date=get_effective_lookback_date())
                    st.session_state.daily_series[code] = series
                except Exception:
                    st.session_state.daily_series[code] = []
                progress.progress(
                    (i + 1) / len(companies),
                    text=f"出来高データ取得中... ({i+1}/{len(companies)}) {name}"
                )
            surge_ranking = []
            for company in companies:
                series = st.session_state.daily_series.get(company["code"], [])
                surge_ranking.append({"company": company, "ratio": calc_volume_surge_ratio(series)})
            surge_ranking.sort(key=lambda x: x["ratio"], reverse=True)
            top20 = surge_ranking[:20]
            top20_codes = {item["company"]["code"] for item in top20}
            progress2 = st.progress(0.0, text="上位20社のチャートを描画中...")
            for i, item in enumerate(top20):
                code, name = item["company"]["code"], item["company"]["name"]
                charts, daily = fetch_chart_images(code, name, market=market, lookback_date=get_effective_lookback_date())
                st.session_state.charts[code] = charts
                if daily:
                    st.session_state.daily_series[code] = daily
                progress2.progress((i + 1) / 20, text=f"チャート描画中... ({i+1}/20) {name}")
            progress.empty()
            progress2.empty()
            st.session_state.surge_ranking = surge_ranking
            st.session_state.surge_top20_codes = top20_codes
            st.success(f"完了。{label}中、出来高急騰上位20社を表示します。")
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
                st.session_state.daily_series = {}
                st.session_state.surge_ranking = []
                st.session_state.surge_top20_codes = set()
                if surge_mode:
                    st.success(f"{len(companies)}件の銘柄を手動設定しました。急騰銘柄探索を開始します...")
                    prog = st.progress(0.0, text="出来高データを取得中...")
                    for i, company in enumerate(companies):
                        code, name = company["code"], company["name"]
                        try:
                            series = fetch_series_from_yfinance(code, market_for_manual, "day", lookback_date=get_effective_lookback_date())
                            st.session_state.daily_series[code] = series
                        except Exception:
                            st.session_state.daily_series[code] = []
                        prog.progress((i + 1) / len(companies),
                                      text=f"取得中... ({i+1}/{len(companies)}) {name}")
                    surge_ranking = []
                    for company in companies:
                        series = st.session_state.daily_series.get(company["code"], [])
                        surge_ranking.append({"company": company, "ratio": calc_volume_surge_ratio(series)})
                    surge_ranking.sort(key=lambda x: x["ratio"], reverse=True)
                    top20 = surge_ranking[:20]
                    top20_codes = {item["company"]["code"] for item in top20}
                    prog2 = st.progress(0.0, text="上位20社のチャートを描画中...")
                    for i, item in enumerate(top20):
                        code, name = item["company"]["code"], item["company"]["name"]
                        charts, daily = fetch_chart_images(code, name, market=market_for_manual, lookback_date=get_effective_lookback_date())
                        st.session_state.charts[code] = charts
                        if daily:
                            st.session_state.daily_series[code] = daily
                        prog2.progress((i + 1) / 20, text=f"チャート... ({i+1}/20) {name}")
                    prog.empty()
                    prog2.empty()
                    st.session_state.surge_ranking = surge_ranking
                    st.session_state.surge_top20_codes = top20_codes
                    st.success(f"完了。{len(companies)}社中、急騰上位20社を表示します。")
                else:
                    st.success(f"{len(companies)}件の銘柄を手動設定しました。「分析」または「グラフのみ」ボタンを押してください。")
            else:
                st.warning("銘柄が入力されていません。")

# ----------------------------------------------------------------------
# 📷 画像から銘柄を取得
# ----------------------------------------------------------------------
with st.expander("📷 画像から銘柄を取得（証券会社の保有一覧画面などに対応）", expanded=False):
    # APIキーチェック
    active_key = claude_api_key or grok_api_key or gemini_api_key
    if not active_key:
        st.warning("サイドバーでいずれかのAI APIキーを入力してください。")
    else:
        st.caption(f"使用AI: **{api_choice}** ／ SBI証券・楽天証券・マネックスなどのスクリーンショットに対応")

        uploaded_img = st.file_uploader(
            "画像ファイルを選択（PNG / JPEG）",
            type=["png", "jpg", "jpeg"],
            key="vision_uploader",
        )

        if uploaded_img is not None:
            st.image(uploaded_img, caption="アップロードされた画像", use_container_width=True)
            if st.button("🤖 AIで銘柄を読み取る", use_container_width=False):
                with st.spinner(f"{api_choice} で画像を解析中..."):
                    try:
                        image_bytes = uploaded_img.read()
                        stocks = extract_stocks_from_image(
                            image_bytes,
                            api_choice=api_choice,
                            claude_api_key=claude_api_key,
                            grok_api_key=grok_api_key,
                            gemini_api_key=gemini_api_key,
                        )
                        st.session_state["vision_stocks"] = stocks
                    except Exception as e:
                        st.error(f"画像解析に失敗しました: {e}")
                        st.session_state["vision_stocks"] = []

        # 抽出結果の表示・選択
        vision_stocks = st.session_state.get("vision_stocks", [])
        if vision_stocks:
            st.success(f"{len(vision_stocks)}件の銘柄を検出しました。追加する銘柄にチェックを入れてください。")
            vision_rows = [
                {"追加": True, "コード": s["code"], "銘柄名": s["name"]}
                for s in vision_stocks
            ]
            edited_vision = st.data_editor(
                vision_rows,
                column_config={
                    "追加": st.column_config.CheckboxColumn("追加", default=True),
                    "コード": st.column_config.TextColumn("コード", disabled=True),
                    "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
                },
                disabled=["コード", "銘柄名"],
                hide_index=True,
                use_container_width=True,
                key="vision_editor",
            )
            if st.button("➕ チェックした銘柄をリストに追加", key="vision_add_btn"):
                to_add = [
                    {"code": r["コード"], "name": r["銘柄名"]}
                    for r in edited_vision if r["追加"]
                ]
                if to_add:
                    existing = {c["code"] for c in st.session_state.companies}
                    added = []
                    for c in to_add:
                        if c["code"] not in existing:
                            st.session_state.companies.append(c)
                            existing.add(c["code"])
                            added.append(c["name"])
                    if "company_editor" in st.session_state:
                        del st.session_state["company_editor"]
                    st.session_state["vision_stocks"] = []
                    if added:
                        st.success(f"追加しました: {', '.join(added)}")
                    else:
                        st.info("選択した銘柄はすでにリストに含まれています。")
                else:
                    st.warning("追加する銘柄にチェックを入れてください。")
        elif "vision_stocks" in st.session_state and st.session_state["vision_stocks"] == []:
            if uploaded_img:
                st.warning("銘柄を検出できませんでした。別の画像を試してください。")

# ----------------------------------------------------------------------
# 📰 ニュース銘柄検索（yfinance決算カレンダー + AI Web検索）
# ----------------------------------------------------------------------
def get_effective_lookback_date():
    """
    セッションに保存されたルックバック日付を返す。
    本日が選択されている場合はNone（フィルタ処理不要）を返す。
    """
    ld = st.session_state.get("lookback_date")
    if ld is None or ld >= _date.today():
        return None
    return ld


def get_upcoming_earnings_yfinance(
    start_days: int = 0, end_days: int = 3, target: str = "both"
) -> list:
    """
    yfinanceで指定期間内に決算がある銘柄を返す。
    calendar（予定）とearnings_dates（実績含む）を両方チェック。
    """
    import yfinance as yf
    from datetime import date, timedelta

    today      = date.today()
    start_date = today + timedelta(days=start_days)
    end_date   = today + timedelta(days=end_days)
    results    = {}

    candidates = []
    if target in ("jp", "both"):
        candidates += [(code, name, "jp") for code, name in NIKKEI225_STOCKS]
    if target in ("us", "both"):
        candidates += [(code, name, "us") for code, name in DOW30_STOCKS]

    def _in_range(d):
        return start_date <= d <= end_date

    def _label(d):
        return "決算発表（実績）" if d < today else "決算発表（予定）"

    for code, name, mkt in candidates:
        symbol = f"{code}.T" if mkt == "jp" else code
        ticker = yf.Ticker(symbol)
        try:
            cal = ticker.calendar
            if cal is not None:
                earn_dates = []
                if isinstance(cal, dict):
                    raw = cal.get("Earnings Date", [])
                    earn_dates = raw if isinstance(raw, list) else [raw]
                elif hasattr(cal, "get"):
                    raw = cal.get("Earnings Date", [])
                    earn_dates = raw if isinstance(raw, list) else [raw]
                for ed in earn_dates:
                    if hasattr(ed, "date"):
                        ed = ed.date()
                    if isinstance(ed, date) and _in_range(ed):
                        results[code] = {
                            "code": code, "name": name, "event": _label(ed),
                            "date": ed.strftime("%Y/%m/%d"),
                            "market": mkt, "source": "yfinance",
                        }
                        break
        except Exception:
            pass

        if code in results:
            continue

        try:
            ed_df = ticker.earnings_dates
            if ed_df is None or ed_df.empty:
                continue
            for ts in ed_df.index:
                try:
                    d = ts.date() if hasattr(ts, "date") else ts
                    if _in_range(d):
                        results[code] = {
                            "code": code, "name": name, "event": _label(d),
                            "date": d.strftime("%Y/%m/%d"),
                            "market": mkt, "source": "yfinance",
                        }
                        break
                except Exception:
                    continue
        except Exception:
            continue

    return list(results.values())


def get_upcoming_events_ai(
    start_days: int = 0, end_days: int = 3, api_choice: str = "",
    claude_api_key: str = "", grok_api_key: str = "",
    gemini_api_key: str = "", target: str = "both",
) -> list:
    """
    AIのWeb検索を使って指定期間内の重要企業イベント銘柄を取得する。
    """
    from datetime import date, timedelta
    import anthropic as _anthropic

    today      = date.today()
    start_date = today + timedelta(days=start_days)
    end_date   = today + timedelta(days=end_days)
    start_en   = start_date.strftime("%B %d, %Y")
    end_en     = end_date.strftime("%B %d, %Y")
    start_jp   = start_date.strftime("%Y年%m月%d日")
    end_jp     = end_date.strftime("%Y年%m月%d日")
    date_ex    = today.strftime("%Y/%m/%d")
    past_note_en = (
        "\nNote: The search range includes past dates — also include events "
        "that have ALREADY been announced within this period."
        if start_days < 0 else ""
    )
    past_note_jp = (
        "\n※検索期間に過去の日付が含まれるため、発表済みのイベントも含めてください。"
        if start_days < 0 else ""
    )

    # 米国株向け英語プロンプト（決算カレンダー専門サイトを明示）
    us_prompt = f"""Search for US stocks (NYSE/NASDAQ listed) with important corporate events scheduled between {start_en} and {end_en}.{past_note_en}

Search these sources specifically:
1. EarningsWhispers (earningswhispers.com) earnings calendar
2. Yahoo Finance earnings calendar (finance.yahoo.com/calendar/earnings)
3. Nasdaq earnings calendar (nasdaq.com/market-activity/earnings)
4. Seeking Alpha earnings calendar
5. MarketWatch earnings calendar

Event types to find:
- Quarterly/annual earnings releases and revenue reports
- EPS/revenue guidance updates (raised or lowered)
- M&A announcements, mergers, spin-offs, acquisitions
- Major new product launches or partnerships
- FDA approvals/Complete Response Letters (biotech/pharma)
- Investor Day / Analyst Day events
- Share buyback announcements or special dividends
- Major regulatory decisions

Return ONLY this JSON (no explanation, no markdown):
{{"us_events": [
  {{"code": "NVDA", "name": "NVIDIA Corp", "event": "Q2 FY2026 Earnings Release", "date": "{date_ex}"}},
  {{"code": "AAPL", "name": "Apple Inc.", "event": "Q3 2026 Earnings Report", "date": "{date_ex}"}}
]}}"""

    # 日本株向け日本語プロンプト（株予報の決算スケジュールページを明示的に指定）
    jp_prompt = f"""本日は{today.strftime('%Y年%m月%d日')}です。
{start_jp}から{end_jp}までの間に、日本株（東証上場企業）で
以下のような株価に影響しうる重要なイベント・発表が予定されている銘柄を、
できるだけ多く漏れなくリストアップしてください。{past_note_jp}

【最優先で参照すべき情報源】
以下の「株予報」決算スケジュールページを必ず確認してください。
このページは日単位で決算発表予定銘柄を網羅的に一覧できます：
- kabuyoho.ifis.co.jp/index.php?id=100 （決算スケジュール トップ）
- 対象期間の各日付について、「{start_jp.replace('年','/').replace('月','/').replace('日','')}」
  から「{end_jp.replace('年','/').replace('月','/').replace('日','')}」までの日付を
  順にたどり、各日の「主な発表予定銘柄」および全件リストを確認してください

【その他の参照先（補完用）】
- 日本経済新聞 決算発表スケジュール
- 各証券会社（SBI証券・楽天証券等）の決算スケジュールページ
- 適時開示情報（TDnet）

【対象とするイベント】
- 決算発表・四半期決算・通期決算（最優先）
- 業績予想・ガイダンスの修正・上方修正・下方修正
- M&A・合併・買収・資本業務提携
- 新製品・新サービスの発表
- 重要な規制当局の承認・却下

株予報のページには1日あたり数百件の決算発表が掲載されていることがあります。
可能な限り多くの銘柄（最低でも数十件程度）を拾ってください。1件のみといった
極端に少ない結果は情報源を十分確認できていない可能性が高いため避けてください。

出力は必ず以下のJSON形式のみ（前後に説明文不要）：
{{"jp_events": [
  {{"code": "7203", "name": "トヨタ自動車", "event": "通期決算発表", "date": "{date_ex}"}}
]}}"""

    def _call_ai(prompt_text: str) -> tuple:
        """戻り値: (text, error_message or None)"""
        if not prompt_text:
            return "", None
        try:
            if api_choice == "Claude API（推奨）":
                client = _anthropic.Anthropic(api_key=claude_api_key)
                tools = [{"type": "web_search_20250305", "name": "web_search"}]
                messages = [{"role": "user", "content": prompt_text}]
                while True:
                    resp = client.messages.create(
                        model="claude-sonnet-4-6", max_tokens=3000,
                        tools=tools, messages=messages,
                    )
                    messages.append({"role": "assistant", "content": resp.content})
                    if resp.stop_reason == "end_turn":
                        break
                    tr = [{"type": "tool_result", "tool_use_id": b.id, "content": ""}
                          for b in resp.content if b.type == "tool_use"]
                    if tr:
                        messages.append({"role": "user", "content": tr})
                    else:
                        break
                return "".join(b.text for b in resp.content if hasattr(b, "text")), None
            elif api_choice == "Grok API":
                from openai import OpenAI as _OAI
                resp = _OAI(api_key=grok_api_key,
                            base_url="https://api.x.ai/v1").responses.create(
                    model="grok-4.3",
                    input=[{"role": "user", "content": prompt_text}],
                    tools=[{"type": "web_search"}],
                )
                return resp.output_text, None
            else:
                import google.generativeai as _genai
                _genai.configure(api_key=gemini_api_key)
                model = _genai.GenerativeModel("gemini-2.5-flash")
                model._api_key = gemini_api_key
                return gemini_generate_with_search(model, prompt_text)
        except Exception as e:
            return "", f"{type(e).__name__}: {e}"

    def _parse(text: str, market: str, key: str) -> list:
        text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
            events = data.get(key) or data.get("events") or []
            for ev in events:
                ev.setdefault("market", market)
            return events
        except Exception:
            return []

    all_events = []
    _debug_errors = []
    if target in ("us", "both"):
        _us_text, _us_err = _call_ai(us_prompt)
        if _us_err:
            _debug_errors.append(f"米国株検索エラー: {_us_err}")
        all_events.extend(_parse(_us_text, "us", "us_events"))
    if target in ("jp", "both"):
        _jp_text, _jp_err = _call_ai(jp_prompt)
        if _jp_err:
            _debug_errors.append(f"日本株検索エラー: {_jp_err}")
        all_events.extend(_parse(_jp_text, "jp", "jp_events"))

    return all_events, _debug_errors



def merge_news_results(yf_results: list, ai_results: list) -> list:
    """yfinanceとAIの結果を統合・重複除去する"""
    merged = {}
    for item in yf_results:
        code = item["code"]
        if code not in merged:
            merged[code] = item.copy()
            merged[code]["events"] = [f"{item['event']}（{item['date']}）"]
        else:
            merged[code]["events"].append(f"{item['event']}（{item['date']}）")

    for item in ai_results:
        code = item.get("code", "")
        if not code:
            continue
        date_s = item.get("date", "")
        event  = item.get("event", "")
        if code not in merged:
            merged[code] = {
                "code":   code,
                "name":   item.get("name", code),
                "market": item.get("market", ""),
                "source": "AI検索",
                "events": [f"{event}（{date_s}）"],
            }
        else:
            merged[code]["events"].append(f"{event}（{date_s}）")
            if merged[code].get("source") == "yfinance":
                merged[code]["source"] = "yfinance + AI検索"

    return list(merged.values())


def filter_by_avg_volume(events: list, min_volume: int) -> list:
    """
    ニュース検索結果を、直近7日間の平均出来高が min_volume 株以上の
    銘柄のみに絞り込む。yfinanceで出来高を取得できない銘柄は除外する。
    """
    import yfinance as yf

    filtered = []
    for item in events:
        code = item.get("code", "")
        market = item.get("market", "jp")
        if not code:
            continue
        symbol = f"{code}.T" if (market == "jp" and not re.fullmatch(r"[A-Z]{1,6}", code.upper())) else code.upper()
        try:
            hist = yf.Ticker(symbol).history(period="10d", interval="1d")
            if hist.empty or "Volume" not in hist.columns:
                continue
            recent7 = hist["Volume"].dropna().tail(7)
            if recent7.empty:
                continue
            avg_vol = float(recent7.mean())
            if avg_vol >= min_volume:
                item_copy = dict(item)
                item_copy["avg_volume_7d"] = avg_vol
                filtered.append(item_copy)
        except Exception:
            continue
    return filtered


# ── ニュース銘柄検索UI ──
with st.expander("📰 ニュース銘柄検索（今後の重要発表銘柄を自動ピックアップ）", expanded=False):
    active_key = claude_api_key or grok_api_key or gemini_api_key
    if not active_key:
        st.warning("サイドバーでいずれかのAI APIキーを入力してください。")
    else:
        st.caption(
            f"使用AI: **{api_choice}** ／ "
            "yfinanceの決算カレンダー＋AIのWeb検索を組み合わせて検索します"
        )
        nc1, nc2 = st.columns(2)
        with nc1:
            news_target = st.radio(
                "対象市場",
                options=["日本株・米国株 両方", "日本株のみ", "米国株のみ"],
                index=0, horizontal=True, key="news_target",
            )
        with nc2:
            news_range = st.slider(
                "検索範囲（本日=0、過去はマイナス、未来はプラス）",
                min_value=-30, max_value=30,
                value=(0, 3),
                step=1, key="news_range",
            )
        news_start_days, news_end_days = news_range

        from datetime import date as _nd, timedelta as _td
        _today = _nd.today()
        _s = _today + _td(days=news_start_days)
        _e = _today + _td(days=news_end_days)
        def _dlabel(d):
            diff = (d - _today).days
            if diff == 0:  return "本日"
            elif diff > 0: return f"{diff}日後"
            else:          return f"{abs(diff)}日前"
        st.info(
            f"📅 検索期間：**{_s.strftime('%Y/%m/%d')}**（{_dlabel(_s)}）"
            f"　〜　**{_e.strftime('%Y/%m/%d')}**（{_dlabel(_e)}）"
        )

        use_volume_filter = st.checkbox(
            "出来高で絞り込む",
            value=True,
            help="直近7営業日の平均出来高が指定値以上の銘柄のみに絞り込みます。",
            key="news_use_volume_filter",
        )
        min_volume_threshold = st.number_input(
            "直近7日間の平均出来高（株）以上",
            min_value=0,
            value=500_000,
            step=10_000,
            disabled=not use_volume_filter,
            help="この値未満の銘柄は結果から除外されます。出来高の少ない閑散銘柄を除きたい場合に使用します。",
            key="news_min_volume",
        )

        target_map = {
            "日本株・米国株 両方": "both",
            "日本株のみ":          "jp",
            "米国株のみ":          "us",
        }
        target_code = target_map[news_target]

        if st.button("📰 重要発表銘柄を検索", use_container_width=False, key="news_search_btn"):
            with st.spinner("① yfinanceで決算カレンダーを確認中（calendar + earnings_dates）..."):
                yf_results = get_upcoming_earnings_yfinance(
                    start_days=news_start_days, end_days=news_end_days,
                    target=target_code,
                )
            st.caption(f"決算カレンダー: {len(yf_results)}件を取得")

            with st.spinner(f"② {api_choice} でWeb検索中（決算スケジュールページ・M&A・新製品等）..."):
                ai_results, ai_errors = get_upcoming_events_ai(
                    start_days=news_start_days, end_days=news_end_days,
                    api_choice=api_choice,
                    claude_api_key=claude_api_key,
                    grok_api_key=grok_api_key,
                    gemini_api_key=gemini_api_key,
                    target=target_code,
                )
            st.caption(f"AI Web検索: {len(ai_results)}件を取得")
            if ai_errors:
                for _err in ai_errors:
                    st.warning(f"⚠️ {_err}")

            merged = merge_news_results(yf_results, ai_results)

            if use_volume_filter and merged:
                before_count = len(merged)
                with st.spinner(f"③ 出来高でフィルタ中（{min_volume_threshold:,}株以上）..."):
                    merged = filter_by_avg_volume(merged, min_volume_threshold)
                st.caption(
                    f"出来高フィルタ: {before_count}件 → **{len(merged)}件**"
                    f"（直近7日平均{min_volume_threshold:,}株以上）"
                )

            st.session_state["news_results"] = merged

        # 検索結果の表示
        news_results = st.session_state.get("news_results", [])
        if news_results:
            from datetime import date as _date
            st.success(f"合計 **{len(news_results)}件** の重要イベント銘柄を検出しました。")
            news_rows = []
            for item in news_results:
                vol = item.get("avg_volume_7d")
                vol_str = f"{vol:,.0f}" if vol is not None else "-"
                news_rows.append({
                    "追加": True,
                    "コード": item["code"],
                    "銘柄名": item["name"],
                    "市場": "🇯🇵 日本株" if item.get("market") == "jp" else "🇺🇸 米国株",
                    "7日平均出来高": vol_str,
                    "イベント": " / ".join(item.get("events", [])),
                    "情報源": item.get("source", ""),
                })
            edited_news = st.data_editor(
                news_rows,
                column_config={
                    "追加": st.column_config.CheckboxColumn("追加", default=True),
                    "コード": st.column_config.TextColumn("コード", disabled=True),
                    "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
                    "市場": st.column_config.TextColumn("市場", disabled=True),
                    "7日平均出来高": st.column_config.TextColumn("7日平均出来高", disabled=True),
                    "イベント": st.column_config.TextColumn("イベント内容", disabled=True, width="large"),
                    "情報源": st.column_config.TextColumn("情報源", disabled=True),
                },
                disabled=["コード", "銘柄名", "市場", "7日平均出来高", "イベント", "情報源"],
                hide_index=True,
                use_container_width=True,
                key="news_editor",
            )
            if st.button("➕ チェックした銘柄をリストに追加", key="news_add_btn"):
                to_add = [
                    {"code": r["コード"], "name": r["銘柄名"]}
                    for r in edited_news if r["追加"]
                ]
                if to_add:
                    existing = {c["code"] for c in st.session_state.companies}
                    added = []
                    for c in to_add:
                        if c["code"] not in existing:
                            st.session_state.companies.append(c)
                            existing.add(c["code"])
                            added.append(c["name"])
                    if "company_editor" in st.session_state:
                        del st.session_state["company_editor"]
                    st.session_state["news_results"] = []
                    if added:
                        st.success(f"追加しました: {', '.join(added)}")
                    else:
                        st.info("選択した銘柄はすでにリストに含まれています。")
                else:
                    st.warning("追加する銘柄にチェックを入れてください。")

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# 📊 インデックス検索
# ----------------------------------------------------------------------
INDEX_OPTIONS = {
    "🇯🇵 日経225（約220社）":       ("NIKKEI225",  "embedded"),
    "🇯🇵 TOPIX Core30（30社）":     ("TOPIX30",    "embedded"),
    "🇺🇸 NYダウ30（30社）":         ("DOW30",      "embedded"),
    "🇺🇸 NASDAQ100（主要銘柄）":    ("NASDAQ100",  "wikipedia"),
    "🇺🇸 S&P500（大型株）":         ("SP500",      "wikipedia"),
}

with st.expander("📊 インデックス検索（日経225・S&P500などから銘柄を抽出）", expanded=False):
    st.caption("選択したインデックスの構成銘柄を抽出してリストに追加できます。複数選択可・重複は自動除去。")

    selected_indices = []
    for label, (key, src) in INDEX_OPTIONS.items():
        src_badge = "（埋め込み・即時）" if src == "embedded" else "（Wikipedia・最新）"
        if st.checkbox(f"{label} {src_badge}", key=f"idx_{key}"):
            selected_indices.append((key, src))

    if st.button("📊 選択したインデックスから銘柄を抽出", key="idx_extract_btn",
                 disabled=not selected_indices):
        all_stocks = {}

        for key, src in selected_indices:
            if src == "embedded":
                stocks = {
                    "NIKKEI225": NIKKEI225_STOCKS,
                    "TOPIX30":   TOPIX_CORE30_STOCKS,
                    "DOW30":     DOW30_STOCKS,
                }.get(key, [])
                for code, name in stocks:
                    all_stocks[code] = name
            else:
                with st.spinner(f"Wikipediaから {key} の構成銘柄を取得中..."):
                    wiki_stocks = fetch_index_from_wikipedia(key)
                for code, name in wiki_stocks:
                    all_stocks[code] = name

        st.session_state["idx_results"] = [
            {"code": code, "name": name} for code, name in all_stocks.items()
        ]
        st.success(f"合計 **{len(all_stocks)}社** を抽出しました（重複除去済み）。")

    idx_results = st.session_state.get("idx_results", [])
    if idx_results:
        def _is_us(code):
            return bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,5}", code.upper()))

        idx_rows = [
            {
                "追加": True,
                "コード": r["code"],
                "銘柄名": r["name"],
                "市場": "🇺🇸 米国株" if _is_us(r["code"]) else "🇯🇵 日本株",
            }
            for r in idx_results
        ]
        edited_idx = st.data_editor(
            idx_rows,
            column_config={
                "追加": st.column_config.CheckboxColumn("追加", default=True),
                "コード": st.column_config.TextColumn("コード", disabled=True),
                "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
                "市場": st.column_config.TextColumn("市場", disabled=True),
            },
            disabled=["コード", "銘柄名", "市場"],
            hide_index=True,
            use_container_width=True,
            key="idx_editor",
        )
        idx_btn1, idx_btn2 = st.columns([2, 1])
        with idx_btn1:
            if st.button("➕ チェックした銘柄をリストに追加", key="idx_add_btn"):
                to_add = [
                    {"code": r["コード"], "name": r["銘柄名"]}
                    for r in edited_idx if r["追加"]
                ]
                if to_add:
                    existing = {c["code"] for c in st.session_state.companies}
                    added = []
                    for c in to_add:
                        if c["code"] not in existing:
                            st.session_state.companies.append(c)
                            existing.add(c["code"])
                            added.append(c["name"])
                    if "company_editor" in st.session_state:
                        del st.session_state["company_editor"]
                    st.session_state["idx_results"] = []
                    if added:
                        st.success(f"{len(added)}社を追加しました。")
                    else:
                        st.info("選択した銘柄はすでにリストに含まれています。")
                else:
                    st.warning("追加する銘柄にチェックを入れてください。")
        with idx_btn2:
            if st.button("🗑️ この結果を消去", key="idx_clear_btn"):
                st.session_state["idx_results"] = []
                st.rerun()

# 💾 銘柄リストの保存・読み込み
# ----------------------------------------------------------------------
with st.expander("💾 銘柄リストの保存・読み込み", expanded=False):
    save_col, load_col = st.columns(2)

    # ── 保存（CSVダウンロード）──
    with save_col:
        st.subheader("📥 保存")
        if st.session_state.companies:
            import io as _io, csv as _csv, datetime as _dt
            list_name = st.text_input(
                "リスト名（ファイル名に使用）",
                value="銘柄リスト",
                key="csv_save_name",
            )
            # CSV生成
            buf = _io.StringIO()
            writer = _csv.writer(buf)
            # 1行目にメタ情報（リスト名・保存日時・市場）
            writer.writerow([
                f"# {list_name}",
                f"保存日時:{_dt.datetime.now().strftime('%Y/%m/%d %H:%M')}",
                f"市場:{st.session_state.get('market','jp')}",
            ])
            writer.writerow(["code", "name"])
            for c in st.session_state.companies:
                writer.writerow([c["code"], c["name"]])
            csv_str = buf.getvalue()
            filename = f"{list_name}_{_dt.date.today().strftime('%Y%m%d')}.csv"
            st.download_button(
                label=f"📥 CSVをダウンロード（{len(st.session_state.companies)}社）",
                data=csv_str.encode("utf-8-sig"),  # Excel対応のBOM付きUTF-8
                file_name=filename,
                mime="text/csv",
                use_container_width=True,
            )
            st.caption("ExcelやGoogleスプレッドシートでも開けます。")
        else:
            st.info("銘柄リストが空です。先に銘柄を取得・入力してください。")

    # ── 読み込み（CSVアップロード）──
    with load_col:
        st.subheader("📂 読み込み")
        uploaded_csv = st.file_uploader(
            "CSVファイルを選択",
            type=["csv"],
            key="csv_uploader",
            help="このアプリで保存したCSV、またはコード・名前の2列CSVに対応",
        )
        replace_or_add = st.radio(
            "読み込み方式",
            options=["現在のリストを置き換える", "現在のリストに追加する"],
            index=0,
            key="csv_load_mode",
            horizontal=True,
        )
        if uploaded_csv is not None:
            if st.button("📂 このCSVを読み込む", use_container_width=True):
                try:
                    import io as _io, csv as _csv
                    content = uploaded_csv.read().decode("utf-8-sig")
                    reader = _csv.reader(_io.StringIO(content))
                    loaded = []
                    seen = set()
                    market_from_csv = None
                    for row in reader:
                        if not row:
                            continue
                        # メタ行（#で始まる）から市場情報を取得
                        if row[0].startswith("#"):
                            for cell in row:
                                if cell.startswith("市場:"):
                                    market_from_csv = cell.replace("市場:", "").strip()
                            continue
                        # ヘッダー行をスキップ
                        if row[0].lower() in ("code", "コード"):
                            continue
                        code = row[0].strip()
                        name = row[1].strip() if len(row) > 1 else code
                        if code and code not in seen:
                            seen.add(code)
                            loaded.append({"code": code, "name": name})

                    if loaded:
                        if replace_or_add == "現在のリストを置き換える":
                            st.session_state.companies = loaded
                            st.session_state.analysis = {}
                            st.session_state.charts = {}
                            st.session_state.daily_series = {}
                            st.session_state.surge_ranking = []
                            st.session_state.surge_top20_codes = set()
                            if "company_editor" in st.session_state:
                                del st.session_state["company_editor"]
                            if market_from_csv:
                                st.session_state.market = market_from_csv
                            st.success(f"{len(loaded)}件の銘柄を読み込みました。")
                        else:
                            existing = {c["code"] for c in st.session_state.companies}
                            added_count = 0
                            for c in loaded:
                                if c["code"] not in existing:
                                    st.session_state.companies.append(c)
                                    existing.add(c["code"])
                                    added_count += 1
                            if "company_editor" in st.session_state:
                                del st.session_state["company_editor"]
                            st.success(
                                f"{added_count}件を追加しました。"
                                f"（重複{len(loaded) - added_count}件はスキップ）"
                            )
                    else:
                        st.warning("有効な銘柄データが見つかりませんでした。")
                except Exception as e:
                    st.error(f"CSVの読み込みに失敗しました: {e}")

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
    col_all, col_none, col_clear, _ = st.columns([1, 1, 1.5, 4])
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
    with col_clear:
        if st.button("🗑️ リストを削除", use_container_width=True,
                     help="現在の銘柄リストを全件クリアします"):
            st.session_state.companies = []
            st.session_state.analysis = {}
            st.session_state.charts = {}
            st.session_state.daily_series = {}
            st.session_state.selected_codes = set()
            st.session_state.surge_ranking = []
            st.session_state.surge_top20_codes = set()
            st.session_state.trend_ranking = []
            st.session_state.trend_sort_active = False
            st.session_state.price_targets = {}
            st.session_state.news_event_info = {}
            st.session_state.numerical_scores = {}
            st.session_state.numerical_passed_codes = set()
            st.session_state.analyze_count_last_synced_total = -1
            st.session_state.auto_trend_active = False
            for _k in [
                "auto_trend_mode", "auto_trend_stage", "auto_trend_companies", "auto_trend_total",
                "auto_trend_chart_queue", "auto_trend_score_queue",
                "auto_trend_num_scores", "auto_trend_vision_queue",
                "auto_trend_vision_results", "auto_trend_vision_total",
                "auto_trend_price_queue", "auto_trend_price_total",
                "auto_trend_strong_up", "_numerical_score_rows_cache",
                "_vision_results_wip",
                "auto_trend_divergence_queue", "auto_trend_divergence_total",
                "auto_trend_divergence_results",
                "use_divergence_filter_active", "divergence_threshold_active",
            ]:
                st.session_state.pop(_k, None)
            if "company_editor" in st.session_state:
                del st.session_state["company_editor"]
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
                    code, name, market=st.session_state.get("market", "jp"),
                    lookback_date=get_effective_lookback_date(),
                )
                st.session_state.charts[code] = charts
                st.session_state.daily_series[code] = daily

            progress.progress((i + 1) / total, text=f"{ai_label}で分析中... ({i+1}/{total}) {name}")
        progress.empty()
        st.success("分析が完了しました。下にスクロールして確認してください。")
        st.toast("🎉 AI分析が完了しました！", icon="✅")

# ---- グラフのみボタン処理 ----
if chart_only_clicked:
    if not st.session_state.companies:
        st.warning("先に「更新」ボタンまたは手動入力で銘柄リストを取得してください。")
    elif surge_mode:
        # ========== 急騰銘柄探索モード ==========
        market_now = st.session_state.get("market", "jp")
        all_companies = st.session_state.companies  # 全銘柄を対象
        total = len(all_companies)
        progress = st.progress(0.0, text="急騰銘柄を探索中... 全銘柄のデータを取得しています")

        # 全銘柄の日足データ（6ヶ月分）を取得
        for i, company in enumerate(all_companies):
            code, name = company["code"], company["name"]
            if code not in st.session_state.daily_series:
                try:
                    series = fetch_series_from_yfinance(code, market_now, "day", lookback_date=get_effective_lookback_date())
                    st.session_state.daily_series[code] = series
                except Exception:
                    st.session_state.daily_series[code] = []
            progress.progress(
                (i + 1) / total,
                text=f"データ取得中... ({i+1}/{total}) {name}"
            )

        # 急増率を計算してランキング
        surge_ranking = []
        for company in all_companies:
            code, name = company["code"], company["name"]
            series = st.session_state.daily_series.get(code, [])
            ratio = calc_volume_surge_ratio(series)
            surge_ranking.append({
                "company": company,
                "ratio": ratio,
            })
        surge_ranking.sort(key=lambda x: x["ratio"], reverse=True)

        # 上位20社のチャートを取得
        top20 = surge_ranking[:20]
        top20_codes = {item["company"]["code"] for item in top20}
        progress2 = st.progress(0.0, text="上位20社のチャートを描画中...")
        for i, item in enumerate(top20):
            code = item["company"]["code"]
            name = item["company"]["name"]
            if code not in st.session_state.charts:
                charts, daily = fetch_chart_images(code, name, market=market_now, lookback_date=get_effective_lookback_date())
                st.session_state.charts[code] = charts
                if daily:
                    st.session_state.daily_series[code] = daily
            progress2.progress(
                (i + 1) / 20,
                text=f"チャート描画中... ({i+1}/20) {name}"
            )

        progress.empty()
        progress2.empty()

        # ランキング結果をセッションに保存
        st.session_state.surge_ranking = surge_ranking
        st.session_state.surge_top20_codes = top20_codes
        st.success(f"急騰銘柄探索完了。上位20社を表示します。（対象: {total}社中）")

    else:
        # ========== 通常モード ==========
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
                    code, name, market=st.session_state.get("market", "jp"),
                    lookback_date=get_effective_lookback_date(),
                )
                st.session_state.charts[code] = charts
                st.session_state.daily_series[code] = daily
            progress.progress(
                (i + 1) / total,
                text=f"チャート取得中... ({i+1}/{total}) {name}"
            )
        progress.empty()
        st.success("チャートの取得が完了しました。下にスクロールして確認してください。")
        st.toast("📊 グラフの作成が完了しました！", icon="✅")

# ---- チャート取得＋数値判定ボタン処理（フェーズ1+2・APIなし） ----
if numerical_clicked:
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
        # ステートマシンを「数値判定のみで停止するモード」で起動する。
        # chart取得→scoreまでバッチ処理し、Vision AI判定へは進まない（APIコストゼロ）。
        st.session_state.auto_trend_active = True
        st.session_state.auto_trend_mode = "numerical_only"
        st.session_state.auto_trend_stage = "chart"
        st.session_state.auto_trend_companies = target_companies
        st.session_state.auto_trend_total = len(target_companies)
        st.session_state.auto_trend_chart_queue = [c["code"] for c in target_companies]
        st.session_state.auto_trend_score_queue = [c["code"] for c in target_companies]
        st.session_state.auto_trend_num_scores = {}
        st.session_state.auto_trend_vision_queue = []
        st.session_state.auto_trend_vision_results = {}
        st.session_state.auto_trend_price_queue = []
        st.session_state.auto_trend_strong_up = []
        st.rerun()

# ---- AIトレンド判定まで自動で行うボタン処理 ----
# ----------------------------------------------------------------------
# 「AIトレンド判定まで自動で行う」処理
# タイムアウト対策として、1回のスクリプト実行では少量ずつ処理し、
# st.rerun() で自動的に次のバッチへ進むステートマシン方式にしている。
# こうすることで1回の実行時間を短く保ち、Streamlit Cloud側の
# 実行時間制限やネットワークタイムアウトによる強制中断を回避する。
# ----------------------------------------------------------------------
_AUTO_BATCH_CHART  = 5   # 1回の実行で処理するチャート取得件数
_AUTO_BATCH_SCORE  = 20  # 1回の実行で処理する数値スコア計算件数（軽い処理なので多め）
_AUTO_BATCH_VISION = 2   # 1回の実行で処理するVision AI判定件数（重い処理なので少なめ）
_AUTO_BATCH_PRICE  = 3   # 1回の実行で処理する目標株価取得件数

if auto_trend_clicked:
    if not st.session_state.companies:
        st.warning("先に「更新」ボタンまたは手動入力で銘柄リストを取得してください。")
    else:
        # ステートマシンを初期化して開始する
        selected = st.session_state.get(
            "selected_codes",
            {c["code"] for c in st.session_state.companies[:analyze_count]}
        )
        target_companies_auto = [
            c for c in st.session_state.companies[:analyze_count]
            if c["code"] in selected
        ]
        st.session_state.auto_trend_active = True
        st.session_state.auto_trend_stage = "chart"
        st.session_state.auto_trend_companies = target_companies_auto
        st.session_state.auto_trend_total = len(target_companies_auto)
        st.session_state.auto_trend_chart_queue = [c["code"] for c in target_companies_auto]
        st.session_state.auto_trend_score_queue = [c["code"] for c in target_companies_auto]
        st.session_state.auto_trend_num_scores = {}
        st.session_state.auto_trend_vision_queue = []
        st.session_state.auto_trend_vision_results = {}
        st.session_state.auto_trend_price_queue = []
        st.session_state.auto_trend_strong_up = []
        st.session_state.use_divergence_filter_active = use_divergence_filter
        st.session_state.divergence_threshold_active = divergence_threshold
        st.rerun()

# ── ステートマシン本体：アクティブな間は毎回の実行で少量ずつ処理する ──
if st.session_state.get("auto_trend_active"):
    stage = st.session_state.auto_trend_stage
    market_now = st.session_state.get("market", "jp")
    companies_map = {c["code"]: c for c in st.session_state.auto_trend_companies}
    total = st.session_state.auto_trend_total

    try:
        # ══ STEP 1: チャート取得（バッチ処理） ══
        if stage == "chart":
            queue = st.session_state.auto_trend_chart_queue
            done = total - len(queue)
            st.progress(
                done / total if total else 1.0,
                text=f"STEP 1/3 グラフ取得中... {done}/{total}"
            )
            batch = queue[:_AUTO_BATCH_CHART]
            for code in batch:
                if code not in st.session_state.charts:
                    name = companies_map[code]["name"]
                    charts_r, daily_r = fetch_chart_images(
                        code, name, market=market_now,
                        lookback_date=get_effective_lookback_date(),
                    )
                    st.session_state.charts[code] = charts_r
                    st.session_state.daily_series[code] = daily_r
            st.session_state.auto_trend_chart_queue = queue[len(batch):]
            if not st.session_state.auto_trend_chart_queue:
                st.toast(f"📊 STEP 1/3 グラフ取得が完了（{total}社）", icon="✅")
                st.session_state.auto_trend_stage = "score"
            st.rerun()

        # ══ STEP 2: 数値スコア計算（バッチ処理） ══
        elif stage == "score":
            queue = st.session_state.auto_trend_score_queue
            done = total - len(queue)
            st.progress(
                done / total if total else 1.0,
                text=f"STEP 2/3 数値スコア計算中... {done}/{total}"
            )
            batch = queue[:_AUTO_BATCH_SCORE]
            for code in batch:
                c = companies_map[code]
                sd = st.session_state.daily_series.get(code, [])
                sw_a, sm_a = [], []
                for tf_key in ("week", "month"):
                    data = st.session_state.get(f"series_{tf_key}_{code}", [])
                    if not data and st.session_state.charts.get(code):
                        try:
                            data = fetch_series_from_yfinance(
                                code, market_now, tf_key,
                                lookback_date=get_effective_lookback_date(),
                            )
                            st.session_state[f"series_{tf_key}_{code}"] = data
                        except Exception:
                            data = []
                    if tf_key == "week":
                        sw_a = data
                    else:
                        sm_a = data
                score, details = calc_trend_score(sd, sw_a, sm_a)
                st.session_state.auto_trend_num_scores[code] = {
                    "score": score, "details": details, "company": c
                }
            st.session_state.auto_trend_score_queue = queue[len(batch):]
            if not st.session_state.auto_trend_score_queue:
                num_scores_auto = st.session_state.auto_trend_num_scores

                if st.session_state.get("auto_trend_mode") == "numerical_only":
                    # ── 数値判定のみモード：ここで終了し結果を保存 ──
                    passed = {
                        code for code, info in num_scores_auto.items()
                        if info["score"] >= score_threshold
                    }
                    st.session_state.numerical_scores = num_scores_auto
                    st.session_state.numerical_passed_codes = passed
                    st.session_state.auto_trend_stage = "done_numerical"
                    st.rerun()
                else:
                    # 数値スコアリング完了 → Vision判定対象を決定
                    sorted_by_num_auto = sorted(
                        num_scores_auto.items(), key=lambda x: x[1]["score"], reverse=True
                    )
                    vision_targets_auto = [
                        code for code, info in sorted_by_num_auto
                        if info["score"] >= score_threshold
                    ]
                    if not vision_targets_auto:
                        vth = max(3, len(sorted_by_num_auto) // 2)
                        vision_targets_auto = [code for code, _ in sorted_by_num_auto[:vth]]

                    st.toast(
                        f"📈 STEP 2/3 数値判定が完了（{len(vision_targets_auto)}社が通過）",
                        icon="✅"
                    )

                    if st.session_state.get("use_divergence_filter_active"):
                        # 適正株価乖離率フィルターへ進む
                        st.session_state.auto_trend_divergence_queue = list(vision_targets_auto)
                        st.session_state.auto_trend_divergence_total = len(vision_targets_auto)
                        st.session_state.auto_trend_divergence_results = {}
                        st.session_state.auto_trend_stage = "divergence"
                    else:
                        st.session_state.auto_trend_vision_queue = vision_targets_auto
                        st.session_state.auto_trend_vision_total = len(vision_targets_auto)
                        if len(vision_targets_auto) > 60:
                            st.session_state.auto_trend_show_large_warning = True
                        st.session_state.auto_trend_stage = "vision"
            st.rerun()

        # ══ STEP 2.5: 適正株価乖離率フィルター（バッチ処理・use_divergence_filter時のみ） ══
        elif stage == "divergence":
            queue = st.session_state.auto_trend_divergence_queue
            dtotal = st.session_state.get("auto_trend_divergence_total", len(queue))
            done = dtotal - len(queue)
            st.progress(
                done / dtotal if dtotal else 1.0,
                text=f"STEP 2.5/3 適正株価の乖離率を確認中... {done}/{dtotal}"
            )
            threshold = st.session_state.get("divergence_threshold_active", 5.0)
            batch = queue[:_AUTO_BATCH_PRICE]
            for code in batch:
                info = st.session_state.auto_trend_num_scores[code]
                name = info["company"]["name"]
                ds = st.session_state.daily_series.get(code, [])
                current_price = ds[-1]["close"] if ds else None
                pt = get_price_target(
                    code, name, market_now, current_price,
                    api_choice=api_choice,
                    claude_api_key=claude_api_key,
                    grok_api_key=grok_api_key,
                    gemini_api_key=gemini_api_key,
                )
                st.session_state.price_targets[code] = pt
                st.session_state.auto_trend_divergence_results[code] = pt
            st.session_state.auto_trend_divergence_queue = queue[len(batch):]
            if not st.session_state.auto_trend_divergence_queue:
                # 乖離率が閾値以上の銘柄のみVision判定対象として確定（スコア順を維持）
                divergence_results = st.session_state.auto_trend_divergence_results
                num_scores_auto = st.session_state.auto_trend_num_scores
                sorted_codes = sorted(
                    num_scores_auto.items(), key=lambda x: x[1]["score"], reverse=True
                )
                vision_targets_filtered = [
                    code for code, _ in sorted_codes
                    if code in divergence_results
                    and divergence_results[code].get("divergence") is not None
                    and divergence_results[code]["divergence"] >= threshold
                ]

                st.toast(
                    f"💰 STEP 2.5/3 乖離率フィルター完了"
                    f"（{dtotal}社中 {len(vision_targets_filtered)}社が通過、"
                    f"上昇余地{threshold:.1f}%以上）",
                    icon="✅"
                )
                if not vision_targets_filtered:
                    st.warning(
                        f"適正株価乖離率{threshold:.1f}%以上の銘柄が見つかりませんでした。"
                        "AIトレンド判定はスキップされます。フィルターの閾値やチェックを見直してください。"
                    )
                    st.session_state.trend_ranking = []
                    st.session_state.trend_sort_active = False
                    st.session_state.auto_trend_stage = "done_numerical_empty"
                else:
                    st.session_state.auto_trend_vision_queue = vision_targets_filtered
                    st.session_state.auto_trend_vision_total = len(vision_targets_filtered)
                    if len(vision_targets_filtered) > 60:
                        st.session_state.auto_trend_show_large_warning = True
                    st.session_state.auto_trend_stage = "vision"
            st.rerun()

        # ══ STEP 3: Vision AI判定（バッチ処理） ══
        elif stage == "vision":
            queue = st.session_state.auto_trend_vision_queue
            vtotal = st.session_state.get("auto_trend_vision_total", len(queue))
            done = vtotal - len(queue)

            if st.session_state.pop("auto_trend_show_large_warning", False):
                st.warning(
                    f"Vision AI判定の対象が{vtotal}社と多いため、時間がかかります。"
                    "1回の実行につき少量ずつ自動的に処理を進めますので、"
                    "画面を開いたままお待ちください。"
                )

            st.progress(
                done / vtotal if vtotal else 1.0,
                text=f"STEP 3/3 Vision AIでトレンドを判定中... {done}/{vtotal}"
            )
            batch = queue[:_AUTO_BATCH_VISION]
            for code in batch:
                info = st.session_state.auto_trend_num_scores[code]
                name = info["company"]["name"]
                result = judge_trend_vision(
                    code, name, st.session_state.charts.get(code, {}),
                    api_choice=api_choice,
                    claude_api_key=claude_api_key,
                    grok_api_key=grok_api_key,
                    gemini_api_key=gemini_api_key,
                )
                st.session_state.auto_trend_vision_results[code] = result
            st.session_state.auto_trend_vision_queue = queue[len(batch):]
            if not st.session_state.auto_trend_vision_queue:
                # Vision判定完了 → ランキング統合
                num_scores_auto = st.session_state.auto_trend_num_scores
                vision_results_auto = st.session_state.auto_trend_vision_results
                overall_order_auto = {"強い上昇": 5, "上昇": 4, "横ばい": 3, "下降": 2, "強い下降": 1}
                trend_ranking_auto = []
                for code, info in num_scores_auto.items():
                    vr = vision_results_auto.get(code)
                    overall = vr["overall"] if vr else (
                        "上昇" if info["score"] >= 5 else
                        "横ばい" if info["score"] >= 3 else "下降"
                    )
                    trend_ranking_auto.append({
                        "code":        code,
                        "name":        info["company"]["name"],
                        "num_score":   info["score"],
                        "details":     info["details"],
                        "overall":     overall,
                        "confidence":  vr.get("confidence", 3) if vr else info["score"],
                        "comment":     vr.get("comment", "") if vr else "",
                        "day_trend":   vr.get("day_trend",   "") if vr else "",
                        "week_trend":  vr.get("week_trend",  "") if vr else "",
                        "month_trend": vr.get("month_trend", "") if vr else "",
                    })
                trend_ranking_auto.sort(
                    key=lambda x: (
                        overall_order_auto.get(x["overall"], 0),
                        x["confidence"], x["num_score"],
                    ),
                    reverse=True,
                )
                st.session_state.trend_ranking = trend_ranking_auto
                st.session_state.trend_sort_active = True

                strong_up_auto = [t for t in trend_ranking_auto if t["overall"] == "強い上昇"]
                st.session_state.auto_trend_strong_up = strong_up_auto
                st.session_state.auto_trend_price_queue = [t["code"] for t in strong_up_auto]
                st.session_state.auto_trend_price_total = len(strong_up_auto)
                st.toast(f"🔍 STEP 3/3 Vision AI判定が完了", icon="✅")
                st.session_state.auto_trend_stage = "price"
            st.rerun()

        # ══ STEP 4: 強い上昇銘柄の目標株価取得（バッチ処理） ══
        elif stage == "price":
            queue = st.session_state.auto_trend_price_queue
            ptotal = st.session_state.get("auto_trend_price_total", len(queue))
            if ptotal == 0:
                st.session_state.auto_trend_stage = "done"
                st.rerun()
            else:
                done = ptotal - len(queue)
                st.progress(
                    done / ptotal,
                    text=f"「強い上昇」銘柄の目標株価を取得中... {done}/{ptotal}"
                )
                batch = queue[:_AUTO_BATCH_PRICE]
                strong_up_map = {t["code"]: t for t in st.session_state.auto_trend_strong_up}
                for code in batch:
                    item = strong_up_map[code]
                    ds = st.session_state.daily_series.get(code, [])
                    current_price = ds[-1]["close"] if ds else None
                    pt = get_price_target(
                        code, item["name"], market_now, current_price,
                        api_choice=api_choice,
                        claude_api_key=claude_api_key,
                        grok_api_key=grok_api_key,
                        gemini_api_key=gemini_api_key,
                    )
                    st.session_state.price_targets[code] = pt
                st.session_state.auto_trend_price_queue = queue[len(batch):]
                if not st.session_state.auto_trend_price_queue:
                    st.session_state.auto_trend_stage = "done"
                st.rerun()

        # ══ 完了 ══
        # ══ 完了（数値判定のみモード） ══
        elif stage == "done_numerical":
            num_scores_final = st.session_state.get("numerical_scores", {})
            passed_final = st.session_state.get("numerical_passed_codes", set())
            all_count  = len(num_scores_final)
            pass_count = len(passed_final)
            skip_count = all_count - pass_count

            st.success(
                f"フェーズ1+2 完了。{all_count}社中 **{pass_count}社** が"
                f"数値スコア{score_threshold}点以上（{skip_count}社除外）。\n\n"
                f"「🔍 AIトレンド判定」ボタンを押すと通過した{pass_count}社のみVision AIで評価します。"
            )
            st.toast(f"📈 数値判定が完了しました！（{pass_count}社が通過）", icon="✅")

            score_rows = sorted(
                [
                    {
                        "銘柄": f"{info['company']['name']}（{code}）",
                        "スコア": f"{info['score']}/7",
                        "日足": _score_to_symbol(info["details"]["day"]),
                        "週足": _score_to_symbol(info["details"]["week"]),
                        "月足": _score_to_symbol(info["details"]["month"]),
                        "新高値": "🌟" if info["details"].get("extra") else "",
                        "判定": "✅ AI判定へ" if code in passed_final else f"❌ 除外（{score_threshold}点未満）",
                    }
                    for code, info in num_scores_final.items()
                ],
                key=lambda x: int(x["スコア"].split("/")[0]),
                reverse=True,
            )
            st.session_state["_numerical_score_rows_cache"] = score_rows

            # ステートマシンをクリア
            st.session_state.auto_trend_active = False
            for _k in [
                "auto_trend_mode", "auto_trend_stage", "auto_trend_companies", "auto_trend_total",
                "auto_trend_chart_queue", "auto_trend_score_queue",
                "auto_trend_num_scores", "auto_trend_vision_queue",
                "auto_trend_vision_results", "auto_trend_vision_total",
                "auto_trend_price_queue", "auto_trend_price_total",
                "auto_trend_strong_up",
                "auto_trend_divergence_queue", "auto_trend_divergence_total",
                "auto_trend_divergence_results",
            ]:
                st.session_state.pop(_k, None)

        # ══ 完了（乖離率フィルターで該当銘柄0件だった場合） ══
        elif stage == "done_numerical_empty":
            st.session_state.auto_trend_active = False
            for _k in [
                "auto_trend_mode", "auto_trend_stage", "auto_trend_companies", "auto_trend_total",
                "auto_trend_chart_queue", "auto_trend_score_queue",
                "auto_trend_num_scores", "auto_trend_vision_queue",
                "auto_trend_vision_results", "auto_trend_vision_total",
                "auto_trend_price_queue", "auto_trend_price_total",
                "auto_trend_strong_up",
                "auto_trend_divergence_queue", "auto_trend_divergence_total",
                "auto_trend_divergence_results",
            ]:
                st.session_state.pop(_k, None)

        elif stage == "done":
            strong_count = len(st.session_state.get("auto_trend_strong_up", []))
            st.success(
                f"完了。{total}社を分析し、「強い上昇」は{strong_count}社でした。"
                f"グラフはランキング順に並び替えられています。"
            )
            st.toast(f"🎉 全自動処理が完了しました！（強い上昇: {strong_count}社）", icon="🎉")
            # ステートマシンをクリア
            st.session_state.auto_trend_active = False
            for _k in [
                "auto_trend_mode", "auto_trend_stage", "auto_trend_companies", "auto_trend_total",
                "auto_trend_chart_queue", "auto_trend_score_queue",
                "auto_trend_num_scores", "auto_trend_vision_queue",
                "auto_trend_vision_results", "auto_trend_vision_total",
                "auto_trend_price_queue", "auto_trend_price_total",
                "auto_trend_strong_up",
                "auto_trend_divergence_queue", "auto_trend_divergence_total",
                "auto_trend_divergence_results",
            ]:
                st.session_state.pop(_k, None)

    except Exception as _auto_err:
        st.error(
            f"処理中にエラーが発生しました: {_auto_err}\n\n"
            "ここまでの進捗はセッションに保存されています。"
            "もう一度対象のボタンを押すと、続きから再開を試みます"
            "（完全な再開を保証するものではありません）。"
        )
        st.session_state.auto_trend_active = False

# 「📈 チャート取得＋数値判定（APIなし）」の結果テーブル表示
# （ステートマシンの done_numerical ステージでキャッシュされたものを表示）
if st.session_state.get("_numerical_score_rows_cache"):
    st.subheader("📊 数値判定スコア一覧")
    st.dataframe(
        st.session_state["_numerical_score_rows_cache"],
        use_container_width=True, hide_index=True,
    )


# ----------------------------------------------------------------------
# 結果表示（縦スクロールで全銘柄）
# 「分析」実行済み or「グラフのみ」実行済みの場合に表示
# ----------------------------------------------------------------------
has_analysis = bool(st.session_state.analysis)
has_charts   = bool(st.session_state.charts)

if has_analysis or has_charts:
    st.divider()

    # 急騰モードの場合は上位20社のみ・ランキング順で表示、通常は分析/チャートがある会社を表示
    top20_codes   = st.session_state.get("surge_top20_codes", set())
    surge_ranking = st.session_state.get("surge_ranking", [])
    if top20_codes:
        # ランキング順（急増率の高い順）で並べる
        display_companies = [
            item["company"]
            for item in surge_ranking[:20]
            if item["company"]["code"] in top20_codes
        ]
    else:
        display_companies = [
            c for c in st.session_state.companies
            if c["code"] in st.session_state.analysis
            or c["code"] in st.session_state.charts
        ]
    if surge_ranking and top20_codes:
        st.subheader("📈 出来高急騰ランキング（上位20社）")
        st.caption("急増率 = 直近7日間の平均出来高 ÷ 過去23日間の平均出来高")
        ranking_rows = []
        for rank, item in enumerate(surge_ranking[:20], 1):
            c = item["company"]
            ratio = item["ratio"]
            ranking_rows.append({
                "順位": rank,
                "コード": c["code"],
                "銘柄名": c["name"],
                "急増率": f"▲{ratio:.2f}倍" if ratio >= 1 else f"▼{ratio:.2f}倍",
            })
        st.dataframe(ranking_rows, use_container_width=True, hide_index=True)
        st.divider()

    # --- ヘッダー / AIトレンド判定 / CSVボタン / PDF ボタンを横並びに配置 ---
    col_header, col_trend, col_csv, col_pdf = st.columns([3, 1, 1, 1])
    with col_header:
        mode_label = "分析結果" if has_analysis else "グラフ一覧"
        st.header(mode_label)
    with col_trend:
        st.write("")
        _auto_running_2 = st.session_state.get("auto_trend_active", False)
        trend_btn_disabled = (not bool(st.session_state.charts)) or _auto_running_2
        ai_trend_clicked = st.button(
            "🔍 AIトレンド判定",
            use_container_width=True,
            disabled=trend_btn_disabled,
            help="チャート取得済みの銘柄を数値分析+Vision AIで上昇トレンド判定します",
        )
    with col_csv:
        st.write("")
        trend_ranking_now = st.session_state.get("trend_ranking", [])
        strong_up_list_full = [
            item for item in trend_ranking_now
            if item.get("overall") == "強い上昇"
        ]
        # ボタンの有効化条件：ランキングが1件でもあれば開けるようにする
        # （「上位N位」モードでは強い上昇でなくても対象になるため）
        csv_btn_disabled = not bool(trend_ranking_now)

        if not csv_btn_disabled:
            with st.popover("📊 トレンド銘柄CSV", use_container_width=True):
                extract_mode = st.radio(
                    "抽出方法",
                    options=["「強い上昇」のみ", "上位N位まで（判定に関わらず）"],
                    index=0,
                    key="trend_csv_extract_mode",
                    help=(
                        "「強い上昇」のみ：総合判定が強い上昇の銘柄だけを対象にします（従来の仕様）。\n"
                        "上位N位まで：総合判定に関わらず、ランキング上位から指定件数を強制的に対象にします。"
                    ),
                )

                import io as _io, csv as _csv, datetime as _dt
                market_now = st.session_state.get("market", "jp")

                if extract_mode == "「強い上昇」のみ":
                    if not strong_up_list_full:
                        st.info("現在「強い上昇」と判定された銘柄はありません。")
                    else:
                        st.caption(f"「強い上昇」は全{len(strong_up_list_full)}社あります。")
                        save_count = st.number_input(
                            "上位何位まで保存するか",
                            min_value=1,
                            max_value=len(strong_up_list_full),
                            value=min(10, len(strong_up_list_full)),
                            step=1,
                            key="trend_csv_save_count",
                            help="ランキング上位から指定した件数までをCSVに含めます。",
                        )
                        target_list = strong_up_list_full[:save_count]

                        csv_buf = _io.StringIO()
                        writer = _csv.writer(csv_buf)
                        writer.writerow([
                            "# トレンド銘柄（強い上昇）",
                            f"保存日時:{_dt.datetime.now().strftime('%Y/%m/%d %H:%M')}",
                            f"市場:{market_now}",
                        ])
                        writer.writerow(["code", "name"])
                        for item in target_list:
                            writer.writerow([item["code"], item["name"]])
                        csv_bytes = csv_buf.getvalue().encode("utf-8-sig")
                        csv_filename = f"トレンド銘柄_上位{save_count}_{_dt.date.today().strftime('%Y%m%d')}.csv"

                        st.download_button(
                            label=f"📥 上位{save_count}社をダウンロード",
                            data=csv_bytes,
                            file_name=csv_filename,
                            mime="text/csv",
                            use_container_width=True,
                            key="trend_csv_dl_strong",
                        )

                else:  # 上位N位まで（判定に関わらず）
                    st.caption(
                        f"ランキング全体は{len(trend_ranking_now)}社あります"
                        f"（総合判定を問わず、順位のみで抽出します）。"
                    )
                    save_count_all = st.number_input(
                        "上位何位まで保存するか",
                        min_value=1,
                        max_value=len(trend_ranking_now),
                        value=min(10, len(trend_ranking_now)),
                        step=1,
                        key="trend_csv_save_count_all",
                        help="総合判定（強い上昇・上昇・横ばい・下降等）に関わらず、ランキング上位から強制的に指定件数を抽出します。",
                    )
                    target_list_all = trend_ranking_now[:save_count_all]

                    csv_buf = _io.StringIO()
                    writer = _csv.writer(csv_buf)
                    writer.writerow([
                        "# トレンド銘柄（上位N位・判定問わず）",
                        f"保存日時:{_dt.datetime.now().strftime('%Y/%m/%d %H:%M')}",
                        f"市場:{market_now}",
                    ])
                    # 判定内容も分かるよう列を拡張（先頭2列 code, name は既存フォーマットと互換）
                    writer.writerow(["code", "name", "順位", "総合判定", "確信度"])
                    for i, item in enumerate(target_list_all, 1):
                        writer.writerow([
                            item["code"], item["name"], i,
                            item.get("overall", ""), item.get("confidence", ""),
                        ])
                    csv_bytes_all = csv_buf.getvalue().encode("utf-8-sig")
                    csv_filename_all = f"トレンド銘柄_上位{save_count_all}位_{_dt.date.today().strftime('%Y%m%d')}.csv"

                    st.download_button(
                        label=f"📥 上位{save_count_all}位をダウンロード",
                        data=csv_bytes_all,
                        file_name=csv_filename_all,
                        mime="text/csv",
                        use_container_width=True,
                        key="trend_csv_dl_all",
                    )
        else:
            st.button(
                "📊 トレンド銘柄CSV",
                use_container_width=True,
                disabled=True,
                help="「AIトレンド判定」を実行後に有効になります",
            )
    with col_pdf:
        st.write("")
        # PDFは「作成」ボタンを押した時にのみ生成する（画面描画のたびに重い処理を
        # 走らせないため）。作成済みのPDFはセッションにキャッシュしておき、
        # 銘柄構成が変わらない限り再利用する。
        pdf_cache_key = (
            tuple(c["code"] for c in display_companies),
            bool(st.session_state.get("trend_ranking")),
            len(st.session_state.analysis),
        )
        cached_pdf = st.session_state.get("_pdf_cache")
        cached_key = st.session_state.get("_pdf_cache_key")

        if cached_pdf is not None and cached_key == pdf_cache_key:
            import datetime
            suffix = "分析" if has_analysis else "グラフ"
            filename = f"株探{suffix}_{datetime.date.today().strftime('%Y%m%d')}.pdf"
            st.download_button(
                label="📄 PDFをダウンロード",
                data=cached_pdf,
                file_name=filename,
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            if st.button("📄 PDFを作成する", use_container_width=True,
                         help="クリックするとPDFを生成します。生成完了後にダウンロードボタンが表示されます。"):
                with st.spinner("PDFを作成中..."):
                    try:
                        # 価格情報をcompanyデータに添付してPDFへ渡す
                        price_targets = st.session_state.get("price_targets", {})
                        companies_with_pt = []
                        for c in display_companies:
                            c_copy = dict(c)
                            pt = price_targets.get(c["code"])
                            if pt:
                                c_copy["_price_target"] = pt
                            companies_with_pt.append(c_copy)

                        pdf_bytes = generate_analysis_pdf(
                            companies_with_pt,
                            st.session_state.analysis,
                            st.session_state.charts,
                            daily_series=st.session_state.daily_series,
                            trend_ranking=st.session_state.get("trend_ranking") or None,
                        )
                        st.session_state["_pdf_cache"] = pdf_bytes
                        st.session_state["_pdf_cache_key"] = pdf_cache_key
                        st.toast("📄 PDFの準備ができました！下のボタンからダウンロードできます。", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"PDF生成失敗: {e}")

    # ── AIトレンド判定の処理 ──
    if ai_trend_clicked:
        active_key = claude_api_key or grok_api_key or gemini_api_key
        if not active_key:
            st.warning("サイドバーでAI APIキーを入力してください。")
        else:
            # 数値判定済み（フェーズ1+2通過）の銘柄があればそれを優先して使う
            passed_codes  = st.session_state.get("numerical_passed_codes", set())
            cached_scores = st.session_state.get("numerical_passed_codes") and \
                            st.session_state.get("numerical_scores", {})

            if passed_codes and st.session_state.get("numerical_scores"):
                target_companies_for_trend = [
                    info["company"]
                    for code, info in sorted(
                        st.session_state.numerical_scores.items(),
                        key=lambda x: x[1]["score"], reverse=True
                    )
                    if code in passed_codes
                ]
                st.info(
                    f"数値判定済みの{len(passed_codes)}社をVision AIで評価します"
                    f"（全{len(st.session_state.numerical_scores)}社中、スコア閾値通過分のみ）。"
                )
                st.session_state.auto_trend_active = True
                st.session_state.auto_trend_companies = target_companies_for_trend
                st.session_state.auto_trend_total = len(target_companies_for_trend)
                st.session_state.auto_trend_num_scores = {
                    c["code"]: st.session_state.numerical_scores[c["code"]]
                    for c in target_companies_for_trend
                    if c["code"] in st.session_state.numerical_scores
                }
                st.session_state.auto_trend_vision_results = {}

                if use_divergence_filter:
                    # 適正株価乖離率フィルターへ進む（voteはdivergenceから）
                    _codes = [c["code"] for c in target_companies_for_trend]
                    st.session_state.auto_trend_stage = "divergence"
                    st.session_state.auto_trend_divergence_queue = _codes
                    st.session_state.auto_trend_divergence_total = len(_codes)
                    st.session_state.auto_trend_divergence_results = {}
                    st.session_state.auto_trend_vision_queue = []
                    st.session_state.auto_trend_vision_total = 0
                else:
                    # ステートマシンをscoreステージ完了済みの状態で開始（voteはvisionから）
                    st.session_state.auto_trend_stage = "vision"
                    st.session_state.auto_trend_vision_queue = [
                        c["code"] for c in target_companies_for_trend
                    ]
                    st.session_state.auto_trend_vision_total = len(target_companies_for_trend)
            else:
                # 数値判定未実施 → ステートマシンをscoreステージから開始
                # （chartは既に取得済みの前提。取得漏れがあればscoreステージ内で個別に補完される）
                target_companies_for_trend = display_companies
                st.info("数値スコアリングを実施してからVision AI判定へ進みます。")
                st.session_state.auto_trend_active = True
                st.session_state.auto_trend_stage = "score"
                st.session_state.auto_trend_companies = target_companies_for_trend
                st.session_state.auto_trend_total = len(target_companies_for_trend)
                st.session_state.auto_trend_score_queue = [
                    c["code"] for c in target_companies_for_trend
                ]
                st.session_state.auto_trend_num_scores = {}
                st.session_state.auto_trend_vision_queue = []
                st.session_state.auto_trend_vision_results = {}

            st.session_state.auto_trend_price_queue = []
            st.session_state.auto_trend_strong_up = []
            st.session_state.use_divergence_filter_active = use_divergence_filter
            st.session_state.divergence_threshold_active = divergence_threshold
            st.rerun()


    # ── トレンドランキング表の表示 ──
    trend_ranking = st.session_state.get("trend_ranking", [])
    if trend_ranking and st.session_state.get("trend_sort_active"):
        st.subheader("📊 AIトレンド判定ランキング")
        st.caption(
            "数値スコア（MA/価格動向）でまず絞り込み、上位銘柄をVision AIが詳細判定。"
            "グラフの表示順もこのランキング順に変更されています。"
        )

        # ランキング表
        rank_rows = []
        for i, item in enumerate(trend_ranking, 1):
            icon, _ = TREND_LABELS.get(item["overall"], ("⚪", 3))
            d = item["details"]
            rank_rows.append({
                "順位": i,
                "銘柄": f"{item['name']}（{item['code']}）",
                "総合判定": f"{icon} {item['overall']}",
                "日足": f"{_score_to_symbol(d['day'])} {item.get('day_trend','')}",
                "週足": f"{_score_to_symbol(d['week'])} {item.get('week_trend','')}",
                "月足": f"{_score_to_symbol(d['month'])} {item.get('month_trend','')}",
                "確信度": "★" * item["confidence"] + "☆" * (5 - item["confidence"]),
                "AIコメント": item.get("comment", ""),
            })
        st.dataframe(
            rank_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "順位":     st.column_config.NumberColumn("順位", width="small"),
                "銘柄":     st.column_config.TextColumn("銘柄", width="medium"),
                "総合判定": st.column_config.TextColumn("総合判定", width="small"),
                "日足":     st.column_config.TextColumn("日足", width="small"),
                "週足":     st.column_config.TextColumn("週足", width="small"),
                "月足":     st.column_config.TextColumn("月足", width="small"),
                "確信度":   st.column_config.TextColumn("確信度", width="small"),
                "AIコメント": st.column_config.TextColumn(
                    "AIコメント",
                    width="large",
                    help="AIによるトレンド判定コメント（全文表示）",
                ),
            },
        )

        if st.button("🔄 ランキングをリセットして元の順序に戻す",
                     key="reset_trend_btn"):
            st.session_state.trend_ranking  = []
            st.session_state.trend_sort_active = False
            st.rerun()

        st.divider()

        # トレンドランキング順にdisplay_companiesを並び替える
        code_rank = {item["code"]: i for i, item in enumerate(trend_ranking)}
        display_companies = sorted(
            display_companies,
            key=lambda c: code_rank.get(c["code"], 999),
        )

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

        # ── 「強い上昇」銘柄：現在株価・目標株価・乖離率を表示 ──
        pt = st.session_state.price_targets.get(code)
        trend_item_for_price = next(
            (t for t in st.session_state.get("trend_ranking", []) if t["code"] == code),
            None
        )
        if pt and trend_item_for_price and trend_item_for_price.get("overall") == "強い上昇":
            is_jp_code = (market == "jp" and
                          not re.fullmatch(r"[A-Z]{1,6}", code.upper()))
            price_str = format_price_target_str(pt, is_jp=is_jp_code)
            if price_str:
                div = pt.get("divergence")
                color = "#d32f2f" if (div is not None and div < 0) else "#1565c0"
                st.markdown(
                    f'<span style="color:{color}; font-size:1.0em; font-weight:600;">'
                    f'{price_str}</span>',
                    unsafe_allow_html=True,
                )

        # ── 急騰モード時：メトリクス（急騰率・ランキング順位）を表示 ──
        surge_ranking = st.session_state.get("surge_ranking", [])
        top20_codes   = st.session_state.get("surge_top20_codes", set())
        is_surge_mode = bool(top20_codes) and code in top20_codes

        surge_ratio = 0.0
        surge_rank  = None
        if is_surge_mode and surge_ranking:
            for rank_idx, item in enumerate(surge_ranking, 1):
                if item["company"]["code"] == code:
                    surge_ratio = item["ratio"]
                    surge_rank  = rank_idx
                    break

        if is_surge_mode and surge_ratio > 0:
            mc1, mc2, mc3 = st.columns(3)
            ratio_str  = f"▲{surge_ratio:.2f}倍" if surge_ratio >= 1 else f"▼{surge_ratio:.2f}倍"
            delta_sign = f"+{surge_ratio - 1:.2f}倍" if surge_ratio >= 1 else f"{surge_ratio - 1:.2f}倍"
            with mc1:
                st.metric(
                    label="📊 出来高急騰率",
                    value=ratio_str,
                    delta=delta_sign,
                    help="直近7日間の平均出来高 ÷ 過去23日間の平均出来高",
                )
            with mc2:
                st.metric(
                    label="🏆 急騰ランキング",
                    value=f"{surge_rank}位",
                    delta=f"全{len(surge_ranking)}社中",
                    delta_color="off",
                )
            with mc3:
                recent7_vol = st.session_state.daily_series.get(code, [])[-7:]
                prev23_vol  = st.session_state.daily_series.get(code, [])[-30:-7]
                if recent7_vol and prev23_vol:
                    avg_r = sum(d["volume"] for d in recent7_vol) / len(recent7_vol)
                    avg_p = sum(d["volume"] for d in prev23_vol)  / len(prev23_vol)
                    unit  = "株" if market == "jp" else "株"
                    st.metric(
                        label="直近7日平均出来高",
                        value=f"{avg_r:,.0f}{unit}",
                        delta=f"基準比 +{avg_r - avg_p:,.0f}" if avg_r >= avg_p else f"基準比 {avg_r - avg_p:,.0f}",
                    )

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
                close  = d["close"]
                volume = int(d["volume"])

                # 最新行（1行目）のみ終値の右に騰落率を表示
                if is_jp:
                    close_disp = f"{close:,.0f}  {change_str}" if idx == 0 else f"{close:,.0f}"
                    row = {
                        "日付": date_str,
                        "終値（円）": close_disp,
                    }
                else:
                    close_disp = f"{close:.2f}  {change_str}" if idx == 0 else f"{close:.2f}"
                    row = {
                        "日付": date_str,
                        "終値（$）": close_disp,
                    }

                # 急騰モード時：最新行のみ急騰率列を追加、他行は空欄
                if is_surge_mode and surge_ratio > 0:
                    row["急騰率"] = (
                        f"▲{surge_ratio:.2f}倍" if surge_ratio >= 1 else f"▼{surge_ratio:.2f}倍"
                    ) if idx == 0 else ""

                row["出来高（株）"] = f"{volume:,}"
                rows.append(row)

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
