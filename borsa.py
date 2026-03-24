import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from groq import Groq
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import re

warnings.filterwarnings("ignore")
app       = Flask(__name__)
TZ_TR     = pytz.timezone("Europe/Istanbul")
scheduler = BackgroundScheduler(timezone=TZ_TR)

# ----------------------------------------------------------------
# ORTAM DEGISKENLERI
# ----------------------------------------------------------------
TOKEN        = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROG_API_KEY")
MY_ID        = os.environ.get("MY_CHAT_ID")
NEWSAPI_KEY  = os.environ.get("NEWSAPI_KEY", "")   # newsapi.org - ucretsiz

bot    = telebot.TeleBot(TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# ----------------------------------------------------------------
# TAHMIN GECMISI (bellekte)
# ----------------------------------------------------------------
TAHMIN_GECMISI = {}

def tahmin_kaydet(ticker, al_fiyat, hedef, sl, tahmin_yuzde, tip="SCALP"):
    tarih   = datetime.now(TZ_TR).strftime("%Y-%m-%d %H:%M")
    anahtar = f"{ticker}_{tarih}_{tip}"
    TAHMIN_GECMISI[anahtar] = {
        "ticker": ticker, "tarih": tarih, "tip": tip,
        "al_fiyat": al_fiyat, "hedef": hedef, "sl": sl,
        "tahmin_yuzde": tahmin_yuzde,
        "gerceklesen": None, "gercek_degisim": None,
        "sonuc": "BEKLIYOR"
    }
    return anahtar

def tahminleri_guncelle():
    """Kapanista tahmin sonuclarini kontrol eder ve bildirir."""
    guncellenenler = []
    for anahtar, t in TAHMIN_GECMISI.items():
        if t["sonuc"] in ("KAZANDI", "KAYBETTI"):
            continue
        try:
            df = yf.download(f"{t['ticker']}.IS", period="2d", interval="1d",
                             progress=False, timeout=8)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            gercek = float(df.iloc[-1]["Close"])
            TAHMIN_GECMISI[anahtar]["gerceklesen"] = gercek
            if t["al_fiyat"] and t["al_fiyat"] > 0:
                gercek_degisim = ((gercek - t["al_fiyat"]) / t["al_fiyat"]) * 100
                TAHMIN_GECMISI[anahtar]["gercek_degisim"] = round(gercek_degisim, 2)
                if gercek >= t["hedef"]:
                    TAHMIN_GECMISI[anahtar]["sonuc"] = "KAZANDI"
                elif t["sl"] and gercek <= t["sl"]:
                    TAHMIN_GECMISI[anahtar]["sonuc"] = "KAYBETTI"
                else:
                    TAHMIN_GECMISI[anahtar]["sonuc"] = "BEKLIYOR"
                guncellenenler.append(TAHMIN_GECMISI[anahtar])
        except:
            continue
    return guncellenenler

def tahmin_raporu_olustur():
    """Tum tahminlerin ozet raporunu olusturur."""
    if not TAHMIN_GECMISI:
        return "Henuz kayitli tahmin yok."
    satirlar = ["<b>TAHMIN RAPORU</b>", ""]
    kazandi = kaybetti = bekliyor = 0
    for anahtar, t in sorted(TAHMIN_GECMISI.items(), key=lambda x: x[1]["tarih"], reverse=True)[:20]:
        if t["sonuc"] == "KAZANDI":
            ikon = "KAZANDI"; kazandi += 1
        elif t["sonuc"] == "KAYBETTI":
            ikon = "KAYBETTI"; kaybetti += 1
        else:
            ikon = "BEKLIYOR"; bekliyor += 1

        gercek_str = ""
        if t["gercek_degisim"] is not None:
            gercek_str = f" | Gercek: %{t['gercek_degisim']:+.1f}"

        satirlar.append(
            f"{ikon} <b>{t['ticker']}</b> ({t['tip']}) {t['tarih']}\n"
            f"   Tahmin: %{t['tahmin_yuzde']:+.1f} | Al: {t['al_fiyat']} | Hedef: {t['hedef']}{gercek_str}"
        )

    toplam = kazandi + kaybetti
    basari = round((kazandi / toplam) * 100, 1) if toplam > 0 else 0
    satirlar.insert(2, f"Kazandi: {kazandi}  |  Kaybetti: {kaybetti}  |  Bekliyor: {bekliyor}")
    satirlar.insert(3, f"Basari Orani: %{basari}  (toplam {toplam} kapali tahmin)")
    satirlar.insert(4, "")
    return "\n".join(satirlar)

# ----------------------------------------------------------------
# HABER & PIYASA BAGLAMLARI
# ----------------------------------------------------------------
def haber_cek(sorgu, dil="tr", adet=5):
    try:
        if not NEWSAPI_KEY:
            return []
        url = (f"https://newsapi.org/v2/everything?q={requests.utils.quote(sorgu)}"
               f"&language={dil}&sortBy=publishedAt&pageSize={adet}"
               f"&apiKey={NEWSAPI_KEY}")
        r    = requests.get(url, timeout=8)
        data = r.json()
        if data.get("status") != "ok":
            return []
        return [a["title"] for a in data.get("articles", [])]
    except:
        return []

def doviz_makro_cek():
    try:
        semboller = {
            "USDTRY=X": "USD/TRY",
            "EURTRY=X": "EUR/TRY",
            "GC=F":     "Altin(USD)",
            "BZ=F":     "Brent Petrol",
            "^XU100":   "BIST100",
        }
        sonuc = {}
        for sembol, isim in semboller.items():
            df = yf.download(sembol, period="2d", interval="1d",
                             progress=False, timeout=6)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            son     = float(df.iloc[-1]["Close"])
            onceki  = float(df.iloc[-2]["Close"]) if len(df) > 1 else son
            degisim = round(((son - onceki) / onceki) * 100, 2)
            sonuc[isim] = {"fiyat": round(son, 2), "degisim": degisim}
        return sonuc
    except:
        return {}

def piyasa_baglamı_olustur(hisse_ticker=""):
    """AI'a verilecek piyasa/haber metnini olusturur."""
    satirlar = []

    makro = doviz_makro_cek()
    if makro:
        satirlar.append("=== MAKRO VERILER ===")
        for isim, v in makro.items():
            satirlar.append(f"{isim}: {v['fiyat']}  ({'+' if v['degisim']>=0 else ''}{v['degisim']}%)")

    tr_haberler = haber_cek("Turkiye ekonomi borsa piyasa", dil="tr", adet=5)
    if tr_haberler:
        satirlar.append("\n=== TURKIYE HABERLERI ===")
        satirlar.extend([f"- {h}" for h in tr_haberler])

    global_haberler = haber_cek("stock market economy Fed interest rate inflation", dil="en", adet=4)
    if global_haberler:
        satirlar.append("\n=== GLOBAL HABERLER ===")
        satirlar.extend([f"- {h}" for h in global_haberler])

    bist_haberler = haber_cek("BIST Borsa Istanbul hisse", dil="tr", adet=4)
    if bist_haberler:
        satirlar.append("\n=== BIST HABERLERI ===")
        satirlar.extend([f"- {h}" for h in bist_haberler])

    sosyal = haber_cek(f"borsa hisse {hisse_ticker} Twitter trend", dil="tr", adet=3)
    if sosyal:
        satirlar.append("\n=== SOSYAL MEDYA TREND ===")
        satirlar.extend([f"- {h}" for h in sosyal])

    return "\n".join(satirlar) if satirlar else ""

# ----------------------------------------------------------------
# KATILIM HISSELERI LISTESI
# ----------------------------------------------------------------
KATILIM_TUMU = [
    "ACSEL","AHSGY","AKFYE","AKHAN","AKSA","AKYHO","ALBRK","ALCTL","ALKA","ALKIM",
    "ALKLC","ALTNY","ALVES","ANGEN","ARASE","ARDYZ","ARFYE","ASELS","ATAKP","ATATP",
    "AVPGY","AYEN","BAHKM","BAKAB","BANVT","BASGZ","BEGYO","BERA","BESTE","BIENY",
    "BIMAS","BINBN","BINHO","BMSTL","BNTAS","BORSK","BOSSA","BRISA","BRKSN","BRLSM",
    "BSOKE","BURCE","BURVA","CANTE","CATES","CELHA","CEMTS","CEMZY","CIMSA","CMBTN",
    "COSMO","CVKMD","CWENE","DAPGM","DARDL","DCTTR","DENGE","DESPC","DGATE","DGNMO",
    "DMSAS","DOFER","DOFRB","DOGUB","DYOBY","EBEBK","EDATA","EDIP","EFOR","EGEPO",
    "EGGUB","EGPRO","EKGYO","EKSUN","ELITE","EMPAE","ENJSA","EREGL","ESCOM","EUPWR",
    "EYGYO","FADE","FONET","FORMT","FORTE","FRMPL","FZLGY","GEDZA","GENIL","GENKM",
    "GENTS","GEREL","GESAN","GLRMK","GOKNR","GOLTS","GOODY","GRSEL","GRTHO","GUBRF",
    "GUNDG","HATSN","HKTM","HOROZ","HRKET","IDGYO","IHEVA","IHLAS","IHLGM","IHYAY",
    "IMASM","INTEM","ISDMR","ISSEN","IZFAS","IZINV","JANTS","KARSN","KATMR","KBORU",
    "KCAER","KIMMR","KLSYN","KNFRT","KOCMT","KONKA","KONTR","KONYA","KOPOL","KOTON",
    "KRDMA","KRDMB","KRDMD","KRGYO","KRONT","KRPLS","KRSTL","KRVGD","KTLEV","KUTPO",
    "KUYAS","KZBGY","LKMNH","LMKDC","LOGO","LXGYO","MAGEN","MAKIM","MARBL","MAVI",
    "MCARD","MEDTR","MEKAG","MERCN","MEYSU","MNDRS","MNDTR","MOBTL","MPARK","NETAS",
    "NTGAZ","OBAMS","OBASE","OFSYM","ONCSM","ORGE","OSTIM","OZRDN","OZYSR","PAGYO",
    "PARSN","PASEU","PENGD","PENTA","PETKM","PETUN","PKART","PLTUR","PNLSN","POLHO",
    "QUAGR","RGYAS","RNPOL","RODRG","RUBNS","SAFKR","SAMAT","SANEL","SANKO","SARKY",
    "SAYAS","SEKUR","SELEC","SELVA","SILVR","SMART","SMRTG","SNGYO","SNICA","SOKE",
    "SRVGY","SUNTK","SURGY","SUWEN","TARKM","TDGYO","TEZOL","TKNSA","TMSN","TOASO",
    "TRILC","TSPOR","TUCLK","TUKAS","TUPRS","TURGG","TUREX","ULAS","ULKER","ULUFA",
    "ULUSE","UNLU","USAK","VAKFN","VANGD","VBTYZ","VERTU","VESBE","VESTL","YEOTK",
    "YGGYO","YGYO","YUNSA","YYLGD","ZEDUR"
]

# ----------------------------------------------------------------
# ALTIN & GUMUS ENSTRUMANLAR
# ----------------------------------------------------------------
ALTIN_LISTESI = {
    "GLDTR":   "Istanbul Altin ETF (Finans AM)",
    "ZGOLD":   "Ziraat Portfoy Altin ETF",
    "ALTINS1": "Is Portfoy Altin Fonu (BYF)",
    "GOLD":    "QNB Finans Altin ETF",
}
GUMUS_LISTESI = {
    "GMSTR": "Finans AM Gumus ETF",
    "SLVR":  "Ziraat Portfoy Gumus ETF",
}
GLOBAL_MADENLER = {
    "GC=F": "Altin Vadeli (XAU/USD)",
    "SI=F": "Gumus Vadeli (XAG/USD)",
    "GLD":  "SPDR Gold Shares (USD ETF)",
}

# ----------------------------------------------------------------
# YARDIMCI: ATR tabanli SL/TP
# ----------------------------------------------------------------
def hesapla_sl_tp(df, fiyat, atr_carpan=1.5):
    try:
        atr     = ta.atr(df["High"], df["Low"], df["Close"], length=14)
        if atr is None or atr.empty:
            return None, None, None
        atr_val = float(atr.iloc[-1])
        sl      = round(fiyat - atr_carpan * atr_val, 2)
        tp      = round(fiyat + atr_carpan * atr_val, 2)
        rr      = round((tp - fiyat) / (fiyat - sl), 2) if (fiyat - sl) != 0 else 0
        return sl, tp, rr
    except:
        return None, None, None

# ----------------------------------------------------------------
# ANALIZ MOTORU (hisse)
# ----------------------------------------------------------------
def analiz_motoru(hisse, vade="1d"):
    try:
        ticker = f"{hisse.upper().strip()}.IS"
        df = yf.download(ticker, period="2y", interval=vade,
                         progress=False, timeout=10)
        if df is None or df.empty or len(df) < 201:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df["EMA9"]    = ta.ema(df["Close"], length=9)
        df["EMA21"]   = ta.ema(df["Close"], length=21)
        df["EMA50"]   = ta.ema(df["Close"], length=50)
        df["SMA200"]  = ta.sma(df["Close"], length=200)
        df["RSI"]     = ta.rsi(df["Close"], length=14)
        df["VOL_AVG"] = ta.sma(df["Volume"], length=20)
        macd_df       = ta.macd(df["Close"])
        df["MACD"]    = macd_df["MACD_12_26_9"]
        df["MACD_S"]  = macd_df["MACDs_12_26_9"]
        bb            = ta.bbands(df["Close"], length=20)

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        c_p   = float(last["Close"])
        u_b   = float(bb.iloc[-1, 2])
        l_b   = float(bb.iloc[-1, 0])
        mid_b = float(bb.iloc[-1, 1])

        hacim_oran  = float(last["Volume"]) / float(last["VOL_AVG"]) if float(last["VOL_AVG"]) > 0 else 1
        hacim_durum = "GUCLU" if hacim_oran > 1.5 else ("POZITIF" if hacim_oran > 1.0 else "ZAYIF")

        ema9  = float(last["EMA9"])
        ema21 = float(last["EMA21"])
        ema50 = float(last["EMA50"])
        s200  = float(last["SMA200"])
        trend = "YUKARI" if (c_p > s200 and ema9 > ema21) else ("YATAY" if abs(c_p - s200)/s200 < 0.03 else "ASAGI")

        macd_sinyal = "AL" if (float(last["MACD"]) > float(last["MACD_S"]) and
                                float(prev["MACD"]) <= float(prev["MACD_S"])) else \
                      "SAT" if (float(last["MACD"]) < float(last["MACD_S"]) and
                                float(prev["MACD"]) >= float(prev["MACD_S"])) else "BEKLE"

        pot     = ((u_b - c_p) / c_p) * 100
        success = round((df[df["Close"] > df["SMA200"]].pct_change()["Close"] > 0).mean() * 100, 1)
        sl, tp, rr = hesapla_sl_tp(df, c_p)

        return {
            "ticker": hisse, "fiyat": c_p, "rsi": float(last["RSI"]),
            "pot": pot, "u_b": u_b, "l_b": l_b, "mid_b": mid_b,
            "s200": s200, "ema9": ema9, "ema21": ema21, "ema50": ema50,
            "hacim": hacim_durum, "hacim_oran": round(hacim_oran, 2),
            "trend": trend, "macd": macd_sinyal,
            "success": success, "sl": sl, "tp": tp, "rr": rr, "df": df
        }
    except:
        return None

# ----------------------------------------------------------------
# ANALIZ MOTORU (maden ETF)
# ----------------------------------------------------------------
def maden_analiz_motoru(ticker_ham, aciklama, bist=True, vade="1d"):
    try:
        ticker = f"{ticker_ham}.IS" if bist else ticker_ham
        df = yf.download(ticker, period="2y", interval=vade,
                         progress=False, timeout=10)
        if df is None or df.empty or len(df) < 50:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        uzun_ma       = 200 if len(df) >= 201 else 50
        df["EMA9"]    = ta.ema(df["Close"], length=9)
        df["EMA21"]   = ta.ema(df["Close"], length=21)
        df["SMA_UZ"]  = ta.sma(df["Close"], length=uzun_ma)
        df["RSI"]     = ta.rsi(df["Close"], length=14)
        df["VOL_AVG"] = ta.sma(df["Volume"], length=20)
        macd_df       = ta.macd(df["Close"])
        df["MACD"]    = macd_df["MACD_12_26_9"]
        df["MACD_S"]  = macd_df["MACDs_12_26_9"]
        bb            = ta.bbands(df["Close"], length=20)

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        c_p   = float(last["Close"])
        u_b   = float(bb.iloc[-1, 2])
        l_b   = float(bb.iloc[-1, 0])
        mid_b = float(bb.iloc[-1, 1])

        hacim_oran  = float(last["Volume"]) / float(last["VOL_AVG"]) if float(last["VOL_AVG"]) > 0 else 1
        hacim_durum = "GUCLU" if hacim_oran > 1.5 else ("POZITIF" if hacim_oran > 1.0 else "ZAYIF")

        ema9  = float(last["EMA9"])
        ema21 = float(last["EMA21"])
        s_uz  = float(last["SMA_UZ"])
        trend = "YUKARI" if (c_p > s_uz and ema9 > ema21) else ("YATAY" if abs(c_p - s_uz)/s_uz < 0.03 else "ASAGI")

        macd_sinyal = "AL" if (float(last["MACD"]) > float(last["MACD_S"]) and
                                float(prev["MACD"]) <= float(prev["MACD_S"])) else \
                      "SAT" if (float(last["MACD"]) < float(last["MACD_S"]) and
                                float(prev["MACD"]) >= float(prev["MACD_S"])) else "BEKLE"

        pot     = ((u_b - c_p) / c_p) * 100
        degisim = round(((c_p - float(prev["Close"])) / float(prev["Close"])) * 100, 2)
        sl, tp, rr = hesapla_sl_tp(df, c_p)

        return {
            "ticker": ticker_ham, "aciklama": aciklama, "bist": bist,
            "fiyat": c_p, "degisim": degisim,
            "rsi": float(last["RSI"]), "pot": pot,
            "u_b": u_b, "l_b": l_b, "mid_b": mid_b,
            "s_uz": s_uz, "ema9": ema9, "ema21": ema21,
            "hacim": hacim_durum, "hacim_oran": round(hacim_oran, 2),
            "trend": trend, "macd": macd_sinyal,
            "sl": sl, "tp": tp, "rr": rr, "df": df
        }
    except:
        return None

# ----------------------------------------------------------------
# AI SINYAL -- HABER + TEKNIK BIRLIKTE
# ----------------------------------------------------------------
def ai_sinyal_uret(res, mod="GUNLUK", piyasa_metni=""):
    try:
        para_birimi = "TL"
        if mod == "GUNLUK_SCALP":
            tip_aciklamasi = "Ayni gun al-sat (scalping). BIST acilis saati 10:00, kapanis 18:00."
        elif mod == "GUNLUK_SWING":
            tip_aciklamasi = "Bugun al, yarin sat (swing). Ertesi gun acilista veya gun ici satis."
        elif mod == "HAFTALIK":
            tip_aciklamasi = "Haftalik pozisyon. 5-7 is gunu elde tutulacak."
        elif mod == "IKI HAFTALIK":
            tip_aciklamasi = "Iki haftalik pozisyon."
        else:
            tip_aciklamasi = "Aylik uzun vade pozisyon."

        talimat = f"""Sen profesyonel bir BIST analisti ve yapay zeka destekli yatirim danismanisin.
Asagidaki TEKNIK VERI ve PIYASA BAGLAMINI birlikte degerlendirerek net emir ver.

=== TEKNIK VERI ===
Hisse: {res['ticker']}, Fiyat: {round(res['fiyat'],2)} TL
RSI: {round(res['rsi'],1)}, Trend: {res['trend']}, MACD: {res['macd']}
EMA9: {round(res['ema9'],2)}, EMA21: {round(res['ema21'],2)}, SMA200: {round(res['s200'],2)}
Bollinger Alt: {round(res['l_b'],2)}, Orta: {round(res['mid_b'],2)}, Ust: {round(res['u_b'],2)} TL
Hacim: {res['hacim']} ({res['hacim_oran']}x ortalama)
Stop-Loss: {res['sl']} TL, Take-Profit: {res['tp']} TL

{piyasa_metni}

=== ISLEM TIPI ===
{tip_aciklamasi}

SADECE su formatta cevap ver, baska hicbir sey yazma:
ALINACAK FIYAT: X.XX TL
SATILACAK FIYAT: X.XX TL
STOP-LOSS: X.XX TL
BEKLENEN KAR: %X.X
TAHMIN GUVEN: %XX (0-100 arasi)
GEREKCЕ: (max 2 cumle, Turkce, hem teknik hem haber bazli)"""

        comp = client.chat.completions.create(
            messages=[{"role": "user", "content": talimat}],
            model="llama-3.3-70b-versatile",
            temperature=0.3
        )
        return comp.choices[0].message.content.replace("*","").replace("_","").replace("#","").strip()
    except:
        return "AI analizi yuklenemedi."

def ai_maden_sinyal(res, vade_label="GUNLUK", piyasa_metni=""):
    try:
        para_birimi = "TL" if res["bist"] else "USD"
        talimat = f"""Sen kiymetli maden yatirim uzmanisisin.
Asagidaki teknik veri ve piyasa kosullarini degerlendirerek net emir ver.

Enstruman: {res['ticker']} - {res['aciklama']}
Fiyat: {round(res['fiyat'],2)} {para_birimi}  (Gunluk: {res['degisim']:+.2f}%)
RSI: {round(res['rsi'],1)}, Trend: {res['trend']}, MACD: {res['macd']}
Hacim: {res['hacim']} ({res['hacim_oran']}x)
Bollinger: Alt {round(res['l_b'],2)} / Orta {round(res['mid_b'],2)} / Ust {round(res['u_b'],2)} {para_birimi}
SL: {res['sl']} {para_birimi}, TP: {res['tp']} {para_birimi}

{piyasa_metni}

SADECE su formatta cevap ver:
ALINACAK FIYAT: X.XX {para_birimi}
SATILACAK FIYAT: X.XX {para_birimi}
STOP-LOSS: X.XX {para_birimi}
BEKLENEN KAR: %X.X
TAHMIN GUVEN: %XX
GEREKCЕ: (max 2 cumle, Turkce)"""

        comp = client.chat.completions.create(
            messages=[{"role": "user", "content": talimat}],
            model="llama-3.3-70b-versatile",
            temperature=0.3
        )
        return comp.choices[0].message.content.replace("*","").replace("_","").replace("#","").strip()
    except:
        return "AI analizi yuklenemedi."

# ----------------------------------------------------------------
# AI CEVABINDAN SAYISAL DEGER CIKAR
# ----------------------------------------------------------------
def ai_yanit_parse(ai_yanit, fiyat):
    """AI cevabindan al/sat/sl/tp degerlerini cikarir, tahmin kaydeder."""
    try:
        al  = re.search(r"ALINACAK\s+FIYAT[:\s]+([0-9]+[.,][0-9]+)", ai_yanit)
        sat = re.search(r"SATILACAK\s+FIYAT[:\s]+([0-9]+[.,][0-9]+)", ai_yanit)
        sl  = re.search(r"STOP.LOSS[:\s]+([0-9]+[.,][0-9]+)", ai_yanit)
        kar = re.search(r"BEKLENEN\s+KAR[:\s]+%?([0-9]+[.,][0-9]+)", ai_yanit)

        al_f  = float(al.group(1).replace(",","."))  if al  else fiyat
        sat_f = float(sat.group(1).replace(",",".")) if sat else None
        sl_f  = float(sl.group(1).replace(",","."))  if sl  else None
        kar_f = float(kar.group(1).replace(",",".")) if kar else 0
        return al_f, sat_f, sl_f, kar_f
    except:
        return fiyat, None, None, 0

# ----------------------------------------------------------------
# GRAFIK OLUSTUR
# ----------------------------------------------------------------
def grafik_olustur(t, baslik_ek="", maden=False):
    fig = plt.figure(figsize=(12, 8), facecolor="#0d1117")
    gs  = gridspec.GridSpec(3, 1, height_ratios=[2.5, 1, 1], hspace=0.08)

    renk = "#FFD700" if maden and ("GOLD" in str(t.get("aciklama","")).upper() or
                                    "ALTIN" in str(t.get("aciklama","")).upper() or
                                    "GC" in str(t.get("ticker","")) or
                                    "GLD" in str(t.get("ticker",""))) else \
           "#C0C0C0" if maden else "#2ecc71"

    fiyat_label = round(t.get("fiyat",0), 2)
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor("#0d1117")
    df_p = t["df"].tail(60)
    x    = range(len(df_p))

    ax1.plot(x, df_p["Close"].values,  color=renk,     linewidth=2,   label=f"Fiyat ({fiyat_label})")
    ax1.plot(x, df_p["EMA9"].values,   color="#f1c40f", linewidth=1,   linestyle="--", label="EMA9")
    ax1.plot(x, df_p["EMA21"].values,  color="#3498db", linewidth=1,   linestyle="--", label="EMA21")

    sma_col = "SMA_UZ" if maden else "SMA200"
    if sma_col in df_p.columns:
        ax1.plot(x, df_p[sma_col].values, color="#e67e22", linewidth=1.5, label="SMA Uzun")

    bb_ust = "BBU_20_2.0" if "BBU_20_2.0" in df_p.columns else None
    bb_alt = "BBL_20_2.0" if "BBL_20_2.0" in df_p.columns else None
    if bb_ust and bb_alt:
        ax1.fill_between(x, df_p[bb_alt].values, df_p[bb_ust].values, alpha=0.07, color="#9b59b6")

    if t.get("sl"):
        ax1.axhline(y=t["sl"], color="#e74c3c", linewidth=1, linestyle=":", label=f"SL: {t['sl']}")
    if t.get("tp"):
        ax1.axhline(y=t["tp"], color="#1abc9c", linewidth=1, linestyle=":", label=f"TP: {t['tp']}")

    ticker_label = t.get("ticker","")
    aciklama_label = t.get("aciklama","")
    trend_label  = t.get("trend","")
    hacim_label  = t.get("hacim","")
    baslik_str   = f"#{ticker_label}"
    if aciklama_label: baslik_str += f" - {aciklama_label}"
    baslik_str  += f"  |  {baslik_ek}  |  Trend: {trend_label}  |  Hacim: {hacim_label}"

    ax1.set_title(baslik_str, color="white", fontsize=10, pad=8)
    ax1.legend(loc="upper left", fontsize=7, facecolor="#1a1a2e", labelcolor="white", framealpha=0.7)
    ax1.tick_params(colors="gray", labelsize=7)
    ax1.grid(True, alpha=0.1, color="gray")
    for spine in ax1.spines.values(): spine.set_edgecolor("#333")

    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.set_facecolor("#0d1117")
    ax2.plot(x, df_p["RSI"].values, color="#9b59b6", linewidth=1.5)
    ax2.axhline(70, color="#e74c3c", linewidth=0.8, linestyle="--", alpha=0.7)
    ax2.axhline(30, color="#2ecc71", linewidth=0.8, linestyle="--", alpha=0.7)
    ax2.axhline(50, color="gray",    linewidth=0.5, linestyle=":",  alpha=0.5)
    ax2.fill_between(x, df_p["RSI"].values, 70, where=(df_p["RSI"].values>=70), color="#e74c3c", alpha=0.2)
    ax2.fill_between(x, df_p["RSI"].values, 30, where=(df_p["RSI"].values<=30), color="#2ecc71", alpha=0.2)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI", color="gray", fontsize=8)
    ax2.tick_params(colors="gray", labelsize=7)
    ax2.grid(True, alpha=0.1, color="gray")
    for spine in ax2.spines.values(): spine.set_edgecolor("#333")

    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax3.set_facecolor("#0d1117")
    macd_v  = df_p["MACD"].values   if "MACD"   in df_p.columns else [0]*len(df_p)
    macds_v = df_p["MACD_S"].values  if "MACD_S" in df_p.columns else [0]*len(df_p)
    hist    = [m-s for m,s in zip(macd_v, macds_v)]
    ax3.plot(x, macd_v,  color="#3498db", linewidth=1.2)
    ax3.plot(x, macds_v, color="#e67e22", linewidth=1.0, linestyle="--")
    ax3.bar(x, hist, color=["#2ecc71" if h>=0 else "#e74c3c" for h in hist], alpha=0.5, width=0.8)
    ax3.axhline(0, color="gray", linewidth=0.5)
    ax3.set_ylabel("MACD", color="gray", fontsize=8)
    ax3.tick_params(colors="gray", labelsize=7)
    ax3.grid(True, alpha=0.1, color="gray")
    for spine in ax3.spines.values(): spine.set_edgecolor("#333")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0d1117")
    buf.seek(0)
    plt.close()
    return buf

# ----------------------------------------------------------------
# MESAJ FORMATLARI
# ----------------------------------------------------------------
def caption_olustur(t, mod, ai_yanit):
    etiketler = {
        "GUNLUK_SCALP":   ("Ayni Gun Al-Sat (Scalp)",    "SCALP"),
        "GUNLUK_SWING":   ("Ertesi Gun Pozisyon (Swing)", "SWING"),
        "HAFTALIK":       ("Haftalik",                    "HAFTA"),
        "IKI HAFTALIK":   ("Iki Haftalik",                "2HAFTA"),
        "AYLIK":          ("Aylik",                       "AYLIK"),
    }
    label, tip_kisa = etiketler.get(mod, (mod, mod))
    ikon = {"GUNLUK_SCALP":"", "GUNLUK_SWING":"", "HAFTALIK":"",
            "IKI HAFTALIK":"", "AYLIK":""}

    return (
        f"<b>#{t['ticker']} | {label}</b>\n"
        f"Fiyat: {round(t['fiyat'],2)} TL  |  Trend: {t['trend']}\n"
        f"RSI: {round(t['rsi'],1)}  |  MACD: {t['macd']}\n"
        f"Hacim: {t['hacim']} ({t['hacim_oran']}x)\n"
        f"Hedef (BB): {round(t['u_b'],2)} TL (%{round(t['pot'],1)})\n"
        f"Stop-Loss: {t['sl']} TL  |  TP: {t['tp']} TL  |  R/R: 1:{t['rr']}\n"
        f"Basari Orani: %{t['success']}\n"
        f"\n<b>AI Emir:</b>\n<code>{ai_yanit}</code>"
    )

def maden_caption_olustur(res, vade_label, ai_yanit):
    pb  = "TL" if res["bist"] else "USD"
    deg = f"{res['degisim']:+.2f}%"
    return (
        f"<b>{res['ticker']} | {res['aciklama']} | {vade_label}</b>\n"
        f"Fiyat: {round(res['fiyat'],2)} {pb}  ({deg})\n"
        f"Trend: {res['trend']}  |  RSI: {round(res['rsi'],1)}  |  MACD: {res['macd']}\n"
        f"Hacim: {res['hacim']} ({res['hacim_oran']}x)\n"
        f"Hedef: {round(res['u_b'],2)} {pb} (%{round(res['pot'],1)})\n"
        f"SL: {res['sl']} {pb}  |  TP: {res['tp']} {pb}  |  R/R: 1:{res['rr']}\n"
        f"\n<b>AI Emir:</b>\n<code>{ai_yanit}</code>"
    )

# ----------------------------------------------------------------
# FILTRELEME & SIRALAMA
# ----------------------------------------------------------------
def filtrele_sirala(havuz, mod):
    sonuc = []
    for res in havuz:
        if mod == "GUNLUK_SCALP":
            if (40 < res["rsi"] < 60 and res["hacim_oran"] >= 1.0 and res["ema9"] > res["ema21"]):
                sonuc.append(res)
        elif mod == "GUNLUK_SWING":
            if (res["fiyat"] > res["s200"] and 35 < res["rsi"] < 65 and res["ema9"] > res["ema21"]):
                sonuc.append(res)
        elif mod == "HAFTALIK":
            if res["fiyat"] > res["s200"] and 35 < res["rsi"] < 68:
                sonuc.append(res)
        elif mod == "IKI HAFTALIK":
            if res["fiyat"] > res["s200"] and 30 < res["rsi"] < 70:
                sonuc.append(res)
        elif mod == "AYLIK":
            if res["fiyat"] > res["s200"] and res["rsi"] < 72 and (res["rr"] or 0) >= 1.5:
                sonuc.append(res)
    return sorted(sonuc, key=lambda x: x["pot"], reverse=True)[:3]

# ----------------------------------------------------------------
# RAPOR GONDER (ana fonksiyon)
# ----------------------------------------------------------------
def rapor_gonder(liste, vade, mod, baslik, otomatik=False):
    try:
        bot.send_message(MY_ID,
            f"<b>{baslik} ANALIZ BASLADI</b>\n{len(liste)} hisse taranıyor...",
            parse_mode="HTML")
    except:
        pass

    # Piyasa baglamini bir kez cek
    piyasa = piyasa_baglamı_olustur()

    havuz = []
    for h in liste:
        res = analiz_motoru(h, vade)
        if res:
            havuz.append(res)
        time.sleep(0.05)

    en_iyi = filtrele_sirala(havuz, mod)

    if not en_iyi:
        try:
            bot.send_message(MY_ID,
                f"<b>{baslik}</b> icin uygun hisse bulunamadi.", parse_mode="HTML")
        except:
            pass
        return

    for t in en_iyi:
        ai_yanit = ai_sinyal_uret(t, mod, piyasa)

        # Tahmini kaydet
        al_f, sat_f, sl_f, kar_f = ai_yanit_parse(ai_yanit, t["fiyat"])
        if sat_f:
            tahmin_kaydet(t["ticker"], al_f, sat_f, sl_f or t["sl"], kar_f, tip=mod)

        buf     = grafik_olustur(t, baslik)
        caption = caption_olustur(t, mod, ai_yanit)
        try:
            bot.send_photo(MY_ID, buf, caption=caption, parse_mode="HTML")
        except:
            pass
        time.sleep(1.5)

# ----------------------------------------------------------------
# GUNLUK TAM RAPOR (scalp + swing)
# ----------------------------------------------------------------
def gunluk_tam_rapor(liste, otomatik=False):
    prefix = "OTOMATIK " if otomatik else ""
    try:
        bot.send_message(MY_ID,
            f"<b>{prefix}GUNLUK TAM ANALIZ</b>\n"
            f"SCALP: Ayni gun al-sat\n"
            f"SWING: Ertesi gun pozisyon",
            parse_mode="HTML")
    except:
        pass

    rapor_gonder(liste, "1d", "GUNLUK_SCALP", f"{prefix}GUNLUK SCALP", otomatik)
    time.sleep(2)
    rapor_gonder(liste, "1d", "GUNLUK_SWING", f"{prefix}GUNLUK SWING", otomatik)

# ----------------------------------------------------------------
# MADEN RAPOR
# ----------------------------------------------------------------
def maden_rapor_gonder(vade="1d", vade_label="GUNLUK", sadece="hepsi"):
    piyasa = piyasa_baglamı_olustur("altin gumus")

    if sadece in ("hepsi", "altin"):
        try:
            bot.send_message(MY_ID, "<b>BIST ALTIN ETF & FONLARI</b>", parse_mode="HTML")
        except:
            pass
        for ticker, aciklama in ALTIN_LISTESI.items():
            res = maden_analiz_motoru(ticker, aciklama, bist=True, vade=vade)
            if res:
                ai_yanit = ai_maden_sinyal(res, vade_label, piyasa)
                al_f, sat_f, sl_f, kar_f = ai_yanit_parse(ai_yanit, res["fiyat"])
                if sat_f:
                    tahmin_kaydet(ticker, al_f, sat_f, sl_f or res["sl"], kar_f, tip=f"MADEN_{vade_label}")
                buf     = grafik_olustur(res, vade_label, maden=True)
                caption = maden_caption_olustur(res, vade_label, ai_yanit)
                try:
                    bot.send_photo(MY_ID, buf, caption=caption, parse_mode="HTML")
                except:
                    pass
                time.sleep(1.5)
            time.sleep(0.5)

    if sadece in ("hepsi", "gumus"):
        try:
            bot.send_message(MY_ID, "<b>BIST GUMUS ETF & FONLARI</b>", parse_mode="HTML")
        except:
            pass
        for ticker, aciklama in GUMUS_LISTESI.items():
            res = maden_analiz_motoru(ticker, aciklama, bist=True, vade=vade)
            if res:
                ai_yanit = ai_maden_sinyal(res, vade_label, piyasa)
                al_f, sat_f, sl_f, kar_f = ai_yanit_parse(ai_yanit, res["fiyat"])
                if sat_f:
                    tahmin_kaydet(ticker, al_f, sat_f, sl_f or res["sl"], kar_f, tip=f"MADEN_{vade_label}")
                buf     = grafik_olustur(res, vade_label, maden=True)
                caption = maden_caption_olustur(res, vade_label, ai_yanit)
                try:
                    bot.send_photo(MY_ID, buf, caption=caption, parse_mode="HTML")
                except:
                    pass
                time.sleep(1.5)
            time.sleep(0.5)

    if sadece == "hepsi":
        try:
            bot.send_message(MY_ID, "<b>GLOBAL ALTIN & GUMUS (USD)</b>", parse_mode="HTML")
        except:
            pass
        for ticker, aciklama in GLOBAL_MADENLER.items():
            res = maden_analiz_motoru(ticker, aciklama, bist=False, vade=vade)
            if res:
                ai_yanit = ai_maden_sinyal(res, vade_label, piyasa)
                buf     = grafik_olustur(res, vade_label, maden=True)
                caption = maden_caption_olustur(res, vade_label, ai_yanit)
                try:
                    bot.send_photo(MY_ID, buf, caption=caption, parse_mode="HTML")
                except:
                    pass
                time.sleep(1.5)
            time.sleep(0.5)

    try:
        bot.send_message(MY_ID, "<b>Kiymetli maden analizi tamamlandi.</b>", parse_mode="HTML")
    except:
        pass

# ----------------------------------------------------------------
# OTOMATIK ZAMANLAMA
# 09:50 -- Sabah scalp raporu
# 17:55 -- Aksam swing raporu + kapanis tahmini guncelle
# ----------------------------------------------------------------
def otomatik_sabah():
    """09:50 -- Ayni gun scalp sinyalleri."""
    threading.Thread(target=lambda: rapor_gonder(
        KATILIM_TUMU, "1d", "GUNLUK_SCALP", "OTOMATIK SABAH SCALP", otomatik=True
    ), daemon=True).start()

def otomatik_aksam():
    """17:55 -- Ertesi gun swing sinyalleri + tahmin guncelleme."""
    # Once kapanıs tahminlerini guncelle
    def aksam_is():
        # Tahmin sonuclari
        guncellenenler = tahminleri_guncelle()
        if guncellenenler:
            satirlar = ["<b>TAHMIN SONUCLARI (Kapanis)</b>", ""]
            for t in guncellenenler:
                if t["sonuc"] == "KAZANDI":
                    satirlar.append(
                        f"KAZANDI {t['ticker']} ({t['tip']})\n"
                        f"Tahmin: %{t['tahmin_yuzde']:+.1f} | "
                        f"Gercek: %{t.get('gercek_degisim',0):+.1f}"
                    )
                elif t["sonuc"] == "KAYBETTI":
                    satirlar.append(
                        f"KAYBETTI {t['ticker']} ({t['tip']})\n"
                        f"Tahmin: %{t['tahmin_yuzde']:+.1f} | "
                        f"Gercek: %{t.get('gercek_degisim',0):+.1f}"
                    )
            try:
                bot.send_message(MY_ID, "\n".join(satirlar), parse_mode="HTML")
            except:
                pass
            time.sleep(2)

        # Ertesi gun swing sinyalleri
        rapor_gonder(KATILIM_TUMU, "1d", "GUNLUK_SWING", "OTOMATIK AKSAM SWING", otomatik=True)

    threading.Thread(target=aksam_is, daemon=True).start()

scheduler.add_job(otomatik_sabah, "cron", hour=9,  minute=50)
scheduler.add_job(otomatik_aksam, "cron", hour=17, minute=55)

# ----------------------------------------------------------------
# TELEGRAM KOMUTLARI
# ----------------------------------------------------------------
@bot.message_handler(commands=["gunluk"])
def cmd_gunluk(m):
    threading.Thread(target=gunluk_tam_rapor, args=(KATILIM_TUMU,), daemon=True).start()

@bot.message_handler(commands=["haftalik"])
def cmd_haftalik(m):
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1wk", "HAFTALIK", "HAFTALIK"), daemon=True).start()

@bot.message_handler(commands=["ikihaftalik"])
def cmd_ikihaftalik(m):
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1wk", "IKI HAFTALIK", "IKI HAFTALIK"), daemon=True).start()

@bot.message_handler(commands=["aylik"])
def cmd_aylik(m):
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1mo", "AYLIK", "AYLIK"), daemon=True).start()

@bot.message_handler(commands=["altin"])
def cmd_altin(m):
    parca = m.text.strip().split()
    vade, vade_label = "1d", "GUNLUK"
    if len(parca) > 1:
        p = parca[1].lower()
        if p in ("haftalik","hafta"): vade, vade_label = "1wk", "HAFTALIK"
        elif p in ("aylik","ay"):     vade, vade_label = "1mo", "AYLIK"
    threading.Thread(target=maden_rapor_gonder,
        args=(vade, vade_label, "altin"), daemon=True).start()

@bot.message_handler(commands=["gumus"])
def cmd_gumus(m):
    parca = m.text.strip().split()
    vade, vade_label = "1d", "GUNLUK"
    if len(parca) > 1:
        p = parca[1].lower()
        if p in ("haftalik","hafta"): vade, vade_label = "1wk", "HAFTALIK"
        elif p in ("aylik","ay"):     vade, vade_label = "1mo", "AYLIK"
    threading.Thread(target=maden_rapor_gonder,
        args=(vade, vade_label, "gumus"), daemon=True).start()

@bot.message_handler(commands=["madenler"])
def cmd_madenler(m):
    parca = m.text.strip().split()
    vade, vade_label = "1d", "GUNLUK"
    if len(parca) > 1:
        p = parca[1].lower()
        if p in ("haftalik","hafta"): vade, vade_label = "1wk", "HAFTALIK"
        elif p in ("aylik","ay"):     vade, vade_label = "1mo", "AYLIK"
    threading.Thread(target=maden_rapor_gonder,
        args=(vade, vade_label, "hepsi"), daemon=True).start()

@bot.message_handler(commands=["tahminler"])
def cmd_tahminler(m):
    rapor = tahmin_raporu_olustur()
    try:
        bot.send_message(m.chat.id, rapor, parse_mode="HTML")
    except:
        bot.send_message(m.chat.id, "Tahmin raporu olusturulamadi.")

@bot.message_handler(commands=["piyasa"])
def cmd_piyasa(m):
    def gonder_piyasa():
        makro = doviz_makro_cek()
        if not makro:
            bot.send_message(m.chat.id, "Piyasa verisi alinamadi.")
            return
        satirlar = ["<b>GUNCEL PIYASA VERILERI</b>", ""]
        for isim, v in makro.items():
            yon = "+" if v["degisim"] >= 0 else ""
            satirlar.append(f"<b>{isim}:</b> {v['fiyat']}  ({yon}{v['degisim']}%)")
        haberler = haber_cek("Turkiye ekonomi borsa", dil="tr", adet=5)
        if haberler:
            satirlar.append("\n<b>SON HABERLER</b>")
            satirlar.extend([f"- {h}" for h in haberler])
        bot.send_message(m.chat.id, "\n".join(satirlar), parse_mode="HTML")
    threading.Thread(target=gonder_piyasa, daemon=True).start()

@bot.message_handler(commands=["start", "yardim"])
def cmd_start(m):
    bot.send_message(m.chat.id,
        "<b>Borsa Gozu | Profesyonel Sinyal Botu</b>\n"
        "\n"
        "<b>HISSE SINYALLERI</b>\n"
        "/gunluk - Scalp (ayni gun) + Swing (ertesi gun)\n"
        "/haftalik - Haftalik pozisyonlar\n"
        "/ikihaftalik - Iki haftalik pozisyonlar\n"
        "/aylik - Aylik uzun vade\n"
        "\n"
        "<b>KIYMETLI MADENLER</b>\n"
        "/altin - Altin ETF + global analizi\n"
        "/altin haftalik - Haftalik altin\n"
        "/gumus - Gumus ETF analizi\n"
        "/madenler - Altin + gumus hepsi\n"
        "\n"
        "<b>TAHMIN & PIYASA</b>\n"
        "/tahminler - Tahmin basari raporu\n"
        "/piyasa - Canli kur + haberler\n"
        "\n"
        "<b>OTOMATIK RAPORLAR</b>\n"
        "Sabah 09:50 - Gunluk scalp sinyalleri\n"
        "Aksam 17:55 - Swing sinyalleri + tahmin sonuclari\n"
        "\n"
        "<b>Her sinyal icin:</b>\n"
        "Grafik (Fiyat + RSI + MACD)\n"
        "AI net al/sat fiyat emirleri\n"
        "Stop-Loss, Take-Profit, Risk/Odul\n"
        "Haber + piyasa bazli AI tahmini\n"
        "Tahmin basari takibi",
        parse_mode="HTML"
    )

# ----------------------------------------------------------------
# FLASK HEALTH CHECK
# ----------------------------------------------------------------
@app.route("/")
def home():
    return "Sistem Aktif", 200

# ----------------------------------------------------------------
# BASLAT
# ----------------------------------------------------------------
if __name__ == "__main__":
    scheduler.start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))),
        daemon=True
    ).start()
    print("Borsa Gozu Bot basladi.")
    print("Otomatik: 09:50 scalp | 17:55 swing + tahmin guncelle")
    bot.infinity_polling()
