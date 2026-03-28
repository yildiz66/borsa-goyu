import os, sqlite3, logging, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from groq import Groq
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import re
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, BotCommand

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("borsa.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger        = logging.getLogger("BorsaGozu")
BOT_BASLANGIC = datetime.now()

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
GNEWS_KEY    = os.environ.get("GNEWS_API_KEY", "")  # gnews.io - ucretsiz (100 req/gun)

bot    = telebot.TeleBot(TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# ----------------------------------------------------------------
# VERITABANI
# Sadece yerel SQLite
# ----------------------------------------------------------------
DB_YOLU = os.environ.get("DB_YOLU", "tahminler.db")

# -----------------------------------------------------------------
def db_baslat():
    """Tabloyu olusturur (Turso veya SQLite)."""
    sql_create = """
        CREATE TABLE IF NOT EXISTS tahminler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anahtar TEXT UNIQUE,
            ticker TEXT,
            tarih TEXT,
            tip TEXT,
            al_fiyat REAL,
            hedef REAL,
            sl REAL,
            tahmin_yuzde REAL,
            gerceklesen REAL,
            gercek_degisim REAL,
            sonuc TEXT DEFAULT 'BEKLIYOR'
        )
    """
    conn = sqlite3.connect(DB_YOLU)
    conn.execute(sql_create)
    conn.commit()
    conn.close()
    logger.info("Veritabani hazir: SQLite (%s)", DB_YOLU)

def tahmin_kaydet(ticker, al_fiyat, hedef, sl, tahmin_yuzde, tip="SCALP"):
    tarih   = datetime.now(TZ_TR).strftime("%Y-%m-%d %H:%M")
    anahtar = f"{ticker}_{tarih}_{tip}"
    sql = """
        INSERT OR IGNORE INTO tahminler
        (anahtar, ticker, tarih, tip, al_fiyat, hedef, sl, tahmin_yuzde, sonuc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR')
    """
    params = (anahtar, ticker, tarih, tip, al_fiyat, hedef, sl, tahmin_yuzde)
    try:
        conn = sqlite3.connect(DB_YOLU)
        conn.execute(sql, params)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Tahmin kaydedilemedi: %s", e)
    return anahtar

def tahminleri_guncelle():
    """Kapanista tahmin sonuclarini kontrol eder ve bildirir."""
    guncellenenler = []
    try:
        sel_sql = "SELECT anahtar, ticker, al_fiyat, hedef, sl, tip, tahmin_yuzde FROM tahminler WHERE sonuc='BEKLIYOR'"
        conn = sqlite3.connect(DB_YOLU)
        bekleyenler = conn.execute(sel_sql).fetchall()
        conn.close()
    except Exception as e:
        logger.error("Tahmin guncelleme DB hatasi: %s", e)
        return guncellenenler

    upd_sql = "UPDATE tahminler SET gerceklesen=?, gercek_degisim=?, sonuc=? WHERE anahtar=?"
    for row in bekleyenler:
        anahtar, ticker, al_fiyat, hedef, sl, tip, tahmin_yuzde = row
        try:
            df = yf.download(f"{ticker}.IS", period="2d", interval="1d",
                             progress=False, timeout=8)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            gercek         = float(df.iloc[-1]["Close"])
            gercek_degisim = None
            if al_fiyat and float(al_fiyat) > 0:
                gercek_degisim = round(((gercek - float(al_fiyat)) / float(al_fiyat)) * 100, 2)
            hedef_f = float(hedef) if hedef else None
            sl_f    = float(sl)    if sl    else None
            if hedef_f and gercek >= hedef_f:
                sonuc = "KAZANDI"
            elif sl_f and gercek <= sl_f:
                sonuc = "KAYBETTI"
            else:
                sonuc = "BEKLIYOR"
            upd_params = (gercek, gercek_degisim, sonuc, anahtar)
            conn2 = sqlite3.connect(DB_YOLU)
            conn2.execute(upd_sql, upd_params)
            conn2.commit()
            conn2.close()
            guncellenenler.append({
                "ticker": ticker, "tip": tip, "sonuc": sonuc,
                "tahmin_yuzde": tahmin_yuzde or 0,
                "gercek_degisim": gercek_degisim or 0
            })
        except Exception as e:
            logger.error("Tahmin guncellenemedi (%s): %s", ticker, e)
            continue
    return guncellenenler

def tahmin_raporu_olustur():
    """Tum tahminlerin ozet raporunu olusturur."""
    try:
        sel_sql = "SELECT ticker, tip, tarih, tahmin_yuzde, al_fiyat, hedef, sonuc, gercek_degisim FROM tahminler ORDER BY tarih DESC LIMIT 20"
        kaz_sql = "SELECT COUNT(*) FROM tahminler WHERE sonuc='KAZANDI'"
        kay_sql = "SELECT COUNT(*) FROM tahminler WHERE sonuc='KAYBETTI'"
        bkl_sql = "SELECT COUNT(*) FROM tahminler WHERE sonuc='BEKLIYOR'"
        conn = sqlite3.connect(DB_YOLU)
        rows       = conn.execute(sel_sql).fetchall()
        kazandi_s  = conn.execute(kaz_sql).fetchone()[0]
        kaybetti_s = conn.execute(kay_sql).fetchone()[0]
        bekliyor_s = conn.execute(bkl_sql).fetchone()[0]
        conn.close()
    except Exception as e:
        logger.error("Tahmin raporu hatasi: %s", e)
        return "Rapor olusturulamadi."
    if not rows:
        return "Henuz kayitli tahmin yok."
    toplam = kazandi_s + kaybetti_s
    basari = round((kazandi_s / toplam) * 100, 1) if toplam > 0 else 0
    satirlar = [
        "<b>TAHMIN RAPORU</b>", "",
        f"Kazandi: {kazandi_s}  |  Kaybetti: {kaybetti_s}  |  Bekliyor: {bekliyor_s}",
        f"Basari Orani: %{basari}  (toplam {toplam} kapali tahmin)", ""
    ]
    for row in rows:
        ticker, tip, tarih, tahmin_yuzde, al_fiyat, hedef, sonuc, gercek_degisim = row
        ikon       = "✅" if sonuc == "KAZANDI" else ("❌" if sonuc == "KAYBETTI" else "⏳")
        gercek_str = f" | Gercek: %{float(gercek_degisim):+.1f}" if gercek_degisim is not None else ""
        satirlar.append(
            f"{ikon} <b>{ticker}</b> ({tip}) {tarih}\n"
            f"   Tahmin: %{(tahmin_yuzde or 0):+.1f} | Al: {al_fiyat} | Hedef: {hedef}{gercek_str}"
        )
    return "\n".join(satirlar)

def hisse_kazanma_orani(ticker):
    """Bir hissenin gecmis tahmin basari oranini dondurur (None = yeterli veri yok)."""
    try:
        sql = "SELECT sonuc FROM tahminler WHERE ticker=? AND sonuc IN ('KAZANDI','KAYBETTI')"
        conn = sqlite3.connect(DB_YOLU)
        rows = conn.execute(sql, (ticker,)).fetchall()
        conn.close()
        if not rows or len(rows) < 3:
            return None
        kazandi = sum(1 for r in rows if r[0] == "KAZANDI")
        return kazandi / len(rows)
    except Exception as e:
        logger.error("Kazanma orani hatasi (%s): %s", ticker, e)
        return None

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
            "XU100.IS":   "BIST100",
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
# KATILIM HISSELERI LISTESI (Dinamik Yukleme)
# ----------------------------------------------------------------
def katilim_listesi_yukle():
    """Localdeki hisse_endeks_katilim_ds.csv dosyasindan hisseleri dinamik olarak okur (Tekrarsiz)."""
    hisseler = set()
    dosya_yolu = "hisse_endeks_katilim_ds.csv"
    try:
        if os.path.exists(dosya_yolu):
            import csv
            with open(dosya_yolu, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f, delimiter=';')
                for row in reader:
                    # Ilk sutunda ".E" ile biten bilesen kodlari (Orn: AKSA.E) bulunur.
                    if len(row) > 0 and row[0].endswith(".E"):
                        ticker = row[0].replace(".E", "").strip()
                        hisseler.add(ticker) # set oldugu icin tekrarlayanlar otomatik elenir
        else:
            logger.error("Katilim CSV dosyasi (%s) bulunamadi!", dosya_yolu)
    except Exception as e:
        logger.error("Katilim listesi CSV'den yuklenirken hata: %s", e)

    # Eger dosyalar yuklenemediyse veya bossa, varsayilan kucuk bir liste dondur (Hata almamak icin)
    if not hisseler:
        logger.warning("Katilim CSV okunamadi, varsayilan statik liste kullaniliyor.")
        hisseler = {"BIMAS", "THYAO", "ASELS", "TUPRS", "FROTO", "TTKOM", "KCHOL"}

    logger.info(f"Katilim endeksinden {len(hisseler)} adet benzersiz hisse yuku basariyla alindi.")
    return sorted(list(hisseler))

KATILIM_TUMU = katilim_listesi_yukle()


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

def bist100_trend_kontrol():
    """BIST100 piyasa yonunu kontrol eder (True = Guvenli, False = Riskli)."""
    try:
        df = yf.download("XU100.IS", period="2d", interval="1d", progress=False, timeout=8)
        if df is None or df.empty: return True # Veri yoksa guvenli varsay
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        c_p    = float(df.iloc[-1]["Close"])
        prev_p = float(df.iloc[-2]["Close"])
        degisim = ((c_p - prev_p) / prev_p) * 100
        
        # BIST100 gunluk %2'den fazla dusuyorsa riskli
        if degisim < -2.0: return False
        return True
    except:
        return True

# ----------------------------------------------------------------
# ANALIZ MOTORU (hisse)
# ----------------------------------------------------------------
def analiz_motoru(hisse, vade="1d"):
    try:
        hisse_clean = hisse.upper().strip()
        # Eger zaten .IS, =X, =F veya ^ ile basliyorsa dokunma, yoksa .IS ekle
        if not hisse_clean.endswith(".IS") and not any(x in hisse_clean for x in ["=", "^", "XU100"]):
            ticker = f"{hisse_clean}.IS"
        else:
            ticker = hisse_clean
            
        # Daha saglikli MA verisi icin 2 yil yerine 2.5 yil cekelim (SMA200 daha stabil olur)
        df = yf.download(ticker, period="3y", interval="1d",
                         progress=False, timeout=10)
        if df is None or df.empty or len(df) < 201:
            logger.warning(f"Veri yetersiz: {ticker}")
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # VWAP Hesapla
        # vwap = (Price * Volume) cum sum / Volume cum sum
        # pandas_ta vwap genellikle intraday için. Manuel hesapliyoruz (gunluk bazda yaklasik)
        df["VWAP"] = (df["Close"] * df["Volume"]).cumsum() / df["Volume"].cumsum()

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
        vwap  = float(last["VWAP"])

        hacim_oran  = float(last["Volume"]) / float(last["VOL_AVG"]) if float(last["VOL_AVG"]) > 0 else 1
        hacim_durum = "GUCLU" if hacim_oran > 1.5 else ("POZITIF" if hacim_oran > 1.0 else "ZAYIF")

        ema9  = float(last["EMA9"])
        ema21 = float(last["EMA21"])
        ema50 = float(last["EMA50"])
        s200  = float(last["SMA200"])
        
        # Trend Gucu: Fiyat SMA200 ustunde ve EMA9 > EMA21 ise GUCLU
        trend = "GUCLU YUXARI" if (c_p > s200 and ema9 > ema21 and c_p > vwap) else \
                "YUKARI" if (c_p > s200 or ema9 > ema21) else \
                "YATAY" if abs(c_p - s200)/s200 < 0.03 else "ASAGI"

        macd_sinyal = "AL" if (float(last["MACD"]) > float(last["MACD_S"]) and
                                float(prev["MACD"]) <= float(prev["MACD_S"])) else \
                      "SAT" if (float(last["MACD"]) < float(last["MACD_S"]) and
                                float(prev["MACD"]) >= float(prev["MACD_S"])) else "BEKLE"

        pot     = ((u_b - c_p) / c_p) * 100
        success = round((df[df["Close"] > df["SMA200"]].pct_change()["Close"] > 0).mean() * 100, 1)
        sl, tp, rr = hesapla_sl_tp(df, c_p)

        return {
            "ticker": hisse, "fiyat": c_p, "rsi": float(last["RSI"]),
            "pot": pot, "u_b": u_b, "l_b": l_b, "mid_b": mid_b, "vwap": vwap,
            "s200": s200, "ema9": ema9, "ema21": ema21, "ema50": ema50,
            "hacim": hacim_durum, "hacim_oran": round(hacim_oran, 2),
            "trend": trend, "macd": macd_sinyal,
            "success": success, "sl": sl, "tp": tp, "rr": rr, "df": df
        }
    except Exception as e:
        logger.error("Analiz motoru hatasi (%s): %s", hisse, e)
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
    from datetime import timedelta
    bugun  = datetime.now(TZ_TR)
    yarin  = bugun + timedelta(days=1)
    etiketler = {
        "GUNLUK_SCALP":   ("Bugün Al-Sat",            "BUGUN",   f"📅 Hedef: Bugün {bugun.strftime('%d %B %Y')}"),
        "GUNLUK_SWING":   ("Yarın Sat",               "YARIN",   f"📅 Hedef: Yarın {yarin.strftime('%d %B %Y')}"),
        "HAFTALIK":       ("Bu Hafta İçinde Sat",     "HAFTALIK",f"📅 Hedef: Bu hafta içinde"),
        "IKI HAFTALIK":   ("2 Hafta İçinde Sat",      "2HAFTA",  f"📅 Hedef: 2 hafta içinde"),
        "AYLIK":          ("Bu Ay İçinde Sat",         "AYLIK",   f"📅 Hedef: Bu ay içinde"),
    }
    label, tip_kisa, tarih_str = etiketler.get(mod, (mod, mod, ""))
    
    # En iyi hisse ise yildiz ekle
    yildiz = "⭐ <b>GÜNÜN EN İYİ ADAYI</b> ⭐\n" if t.get("en_iyi") else ""

    return (
        f"{yildiz}"
        f"<b>#{t['ticker']} | {label}</b>\n"
        f"{tarih_str}\n"
        f"Fiyat: {round(t['fiyat'],2)} TL  |  Yön: {t['trend']}\n"
        f"RSI: {round(t['rsi'],1)}  |  MACD: {t['macd']}\n"
        f"Hacim: {t['hacim']} ({t['hacim_oran']}x)\n"
        f"Hedef Fiyat (BB): {round(t['u_b'],2)} TL (%{round(t['pot'],1)})\n"
        f"Zarar Kes: {t['sl']} TL  |  Kâr Al: {t['tp']} TL  |  Risk/Kazanç: 1:{t['rr']}\n"
        f"Geçmiş Başarı: %{t['success']}\n"
        f"\n<b>Yapay Zeka Emri:</b>\n<code>{ai_yanit}</code>"
    )

def maden_caption_olustur(res, vade_label, ai_yanit):
    pb  = "TL" if res["bist"] else "USD"
    deg = f"{res['degisim']:+.2f}%"
    return (
        f"<b>{res['ticker']} | {res['aciklama']} | {vade_label}</b>\n"
        f"Fiyat: {round(res['fiyat'],2)} {pb}  ({deg})\n"
        f"Yön: {res['trend']}  |  RSI: {round(res['rsi'],1)}  |  MACD: {res['macd']}\n"
        f"Hacim: {res['hacim']} ({res['hacim_oran']}x)\n"
        f"Hedef Fiyat: {round(res['u_b'],2)} {pb} (%{round(res['pot'],1)})\n"
        f"Zarar Kes: {res['sl']} {pb}  |  Kâr Al: {res['tp']} {pb}  |  Risk/Kazanç: 1:{res['rr']}\n"
        f"\n<b>Yapay Zeka Emri:</b>\n<code>{ai_yanit}</code>"
    )

def su_anki_vade_ve_mod_belirle():
    """Saat ve gune gore vade/mod belirler.
    Hafta sonu veya gece ise HAFTALIK modu dondurur (VWAP olmadan da calismasi icin).
    """
    simdi = datetime.now(TZ_TR)
    saat  = simdi.hour
    gun   = simdi.weekday()  # 0=Pazartesi ... 6=Pazar

    # Hafta sonu (Cumartesi=5, Pazar=6) -> HAFTALIK swing mod
    if gun >= 5:
        return "1wk", "HAFTALIK", "HAFTALIK (HAFTA SONU)"

    # Is gunu: 17:00 ve sonrasi -> yarinki swing
    if saat >= 17:
        return "1d", "GUNLUK_SWING", "YARIN SAT (OTOMATIK)"
    # Is gunu: 10:00-17:00 -> bugunku scalp
    elif saat >= 10:
        return "1d", "GUNLUK_SCALP", "BUGUN AL-SAT (OTOMATIK)"
    # Is gunu sabah oncesi -> acilis scalp
    else:
        return "1d", "GUNLUK_SCALP", "BUGUN ACILIS AL-SAT"

# ----------------------------------------------------------------
# FILTRELEME & SIRALAMA
# ----------------------------------------------------------------
def filtrele_sirala(havuz, mod):
    # Piyasa kotuyse filtrele (Opsiyonel: Kullanici kesin para kazanmak istiyor)
    if not bist100_trend_kontrol():
        logger.warning("Piyasa (BIST100) riskli gorunuyor, filtreler sikilastirildi.")
        devam_et = False # Cok guclu sinyal yoksa dondurme
    else:
        devam_et = True

    sonuc = []
    for res in havuz:
        # Kazanma orani filtresi (%40 alti ise alma)
        k_orani = hisse_kazanma_orani(res["ticker"])
        if k_orani is not None and k_orani < 0.40:
            continue

        if mod == "GUNLUK_SCALP":
            # Scalp: RSI orta seviyelerde, hacim pozitif, EMA9 > EMA21 ve Fiyat > VWAP
            if (35 < res["rsi"] < 65 and res["hacim_oran"] >= 0.9 and 
                res["ema9"] > res["ema21"] and res["fiyat"] > res["vwap"]):
                sonuc.append(res)
        elif mod == "GUNLUK_SWING":
            # Swing: Ana trend (SMA200) yukari, RSI asiri alimda degil
            if (res["fiyat"] > res["s200"] and 30 < res["rsi"] < 68 and 
                res["ema9"] > res["ema21"]):
                sonuc.append(res)
        elif mod == "HAFTALIK":
            if res["fiyat"] > res["s200"] and 35 < res["rsi"] < 70:
                sonuc.append(res)
        else:
            # Diger vadeler (Aylik vb.)
            if res["fiyat"] > res["s200"] and res["rsi"] < 72:
                sonuc.append(res)

    # Potansiyele (Bollinger Ust Bandina uzaklik) gore sirala
    sirali = sorted(sonuc, key=lambda x: x["pot"], reverse=True)[:3]
    
    # En iyi 1 tanesini isaretle
    if sirali:
        for i, s in enumerate(sirali):
            sirali[i]["en_iyi"] = (i == 0) # Ilk siradaki en iyisi
            
    return sirali

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

# Hafta ici (Pazartesi-Cuma) otomatik raporlar
scheduler.add_job(otomatik_sabah, "cron", day_of_week="mon-fri", hour=9,  minute=50)
scheduler.add_job(otomatik_aksam, "cron", day_of_week="mon-fri", hour=17, minute=55)

# Pazar aksami haftalik sinyal raporu (20:00)
def otomatik_pazar_aksam():
    """Pazar 20:00 -- Haftaya ait haftalik swing sinyallerini gonder."""
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1wk", "HAFTALIK", "PAZAR AKSAM HAFTALIK SINYAL"),
        kwargs={"otomatik": True},
        daemon=True
    ).start()

scheduler.add_job(otomatik_pazar_aksam, "cron", day_of_week="sun", hour=20, minute=0)

# ----------------------------------------------------------------
# KLAVYE MENUSU
# ----------------------------------------------------------------
def ana_menu_olustur():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📅 Günlük"),
        KeyboardButton("📅 Haftalık"),
        KeyboardButton("📅 İki Haftalık"),
        KeyboardButton("📅 Aylık"),
        KeyboardButton("🥇 Altın"),
        KeyboardButton("🥈 Gümüş"),
        KeyboardButton("💎 Tüm Madenler"),
        KeyboardButton("📈 Tahminler"),
        KeyboardButton("🌍 Piyasa")
    )
    return markup

# ----------------------------------------------------------------
# TELEGRAM KOMUTLARI
# ----------------------------------------------------------------
def _tek_hisse_islem(chat_id, ticker_input):
    """Tek hisse analizi - thread icinde calisir."""
    import traceback
    try:
        logger.info("Tek hisse analiz basladi: %s (chat_id=%s)", ticker_input, chat_id)
        vade, mod, baslik = su_anki_vade_ve_mod_belirle()
        logger.info("Mod: %s, Vade: %s", mod, vade)

        res = analiz_motoru(ticker_input, "1d")  # Her zaman gunluk veri kullan
        if not res:
            bot.send_message(chat_id,
                f"<b>{ticker_input}</b> için yeterli veri bulunamadı veya hisse kodu hatalı.\n"
                "(BIST hisselerini sadece kod olarak girin, örn: THYAO)",
                parse_mode="HTML")
            return

        piyasa   = piyasa_baglamı_olustur()
        ai_yanit = ai_sinyal_uret(res, mod, piyasa)

        al_f, sat_f, sl_f, kar_f = ai_yanit_parse(ai_yanit, res["fiyat"])
        if sat_f:
            tahmin_kaydet(res["ticker"], al_f, sat_f, sl_f or res["sl"], kar_f, tip=f"TEK_{mod}")

        buf     = grafik_olustur(res, "TEK HİSSE SORGUSU")
        caption = caption_olustur(res, mod, ai_yanit)
        bot.send_photo(chat_id, buf, caption=caption, parse_mode="HTML", reply_markup=ana_menu_olustur())
        logger.info("Tek hisse analiz tamamlandi: %s", ticker_input)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Hisse islem hatasi (%s): %s\n%s", ticker_input, e, tb)
        try:
            bot.send_message(chat_id,
                f"❌ <b>{ticker_input}</b> analizi sırasında hata:\n<code>{str(e)[:200]}</code>",
                parse_mode="HTML")
        except:
            pass

@bot.message_handler(commands=["hisse"])
def cmd_hisse_slash(m):
    logger.info(f">>> [DEBUG] /hisse komutu alindi: {m.text}")
    """Slash komutu: /hisse THYAO"""
    parca = m.text.strip().split()
    if len(parca) < 2:
        bot.send_message(m.chat.id,
            "Lütfen bir hisse kodu girin.\nÖrn: <code>/hisse THYAO</code>",
            parse_mode="HTML", reply_markup=ana_menu_olustur())
        return
    ticker_input = parca[1].upper()
    bot.send_message(m.chat.id, f"<b>{ticker_input}</b> için analiz hazırlanıyor...", parse_mode="HTML")
    threading.Thread(target=_tek_hisse_islem, args=(m.chat.id, ticker_input), daemon=True).start()

@bot.message_handler(func=lambda m: m.text and m.text.strip().lower().startswith("hisse "))
def cmd_hisse_metin(m):
    logger.info(f">>> [DEBUG] hisse metni alindi: {m.text}")
    """Metin komutu: hisse THYAO"""
    parca = m.text.strip().split()
    if len(parca) < 2:
        bot.send_message(m.chat.id,
            "Lütfen bir hisse kodu girin.\nÖrn: <code>hisse THYAO</code>",
            parse_mode="HTML", reply_markup=ana_menu_olustur())
        return
    ticker_input = parca[1].upper()
    bot.send_message(m.chat.id, f"<b>{ticker_input}</b> için analiz hazırlanıyor...", parse_mode="HTML")
    threading.Thread(target=_tek_hisse_islem, args=(m.chat.id, ticker_input), daemon=True).start()

def _ai_sohbet_islem(chat_id, ticker, soru):
    import traceback
    try:
        res = analiz_motoru(ticker, "1d")
        if not res:
            bot.send_message(chat_id, f"❌ <b>{ticker}</b> kodlu hisse bulunamadı veya verisi çekilemedi.", parse_mode="HTML")
            return
        
        piyasa = piyasa_baglamı_olustur()
        
        talimat = f"""Sen Borsa İstanbul uzmanı, yapay zeka tabanlı bir yatırım asistanısın. 
Kullanıcı sana {ticker} hissesi hakkında özel bir soru soruyor: "{soru}"

Aşağıda hissenin güncel teknik verileri ve genel piyasa durumu var. Bu verilerden faydalanarak kullanıcının sorusuna doğrudan, açık, anlaşılır ve Türkçe olarak yanıt ver. 

=== {ticker} TEKNİK VERİLER ===
Fiyat: {round(res['fiyat'], 2)} TL
RSI: {round(res['rsi'], 1)} (Aşırı alım/satım göstergesi)
Trend: {res['trend']}
MACD: {res['macd']}
Hacim Durumu: {res['hacim']}

=== PİYASA DURUMU ===
{piyasa}

Lütfen yukarıdaki soruyu bu teknik verilere dayanarak (fakat kati yatırım tavsiyesi olmadığını belirterek) mantıklı bir şekilde cevapla. Gerekirse genel temel analiz (haber, beklenti vb.) bilgilerinden de yararlanabilirsin."""

        comp = client.chat.completions.create(
            messages=[{"role": "user", "content": talimat}],
            model="llama-3.3-70b-versatile",
            temperature=0.5
        )
        import html
        cevap = html.escape(comp.choices[0].message.content.strip())
        bot.send_message(chat_id, f"🤖 <b>{ticker} AI Yanıtı:</b>\n\n{cevap}", parse_mode="HTML")
    except Exception as e:
        logger.error("AI sohbet hatasi: %s", e)
        try:
            bot.send_message(chat_id, "Yapay zekaya danışırken bir hata oluştu.")
        except:
            pass

@bot.message_handler(commands=["sor", "sohbet"])
def cmd_sor(m):
    logger.info(f">>> [DEBUG] /sor komutu alindi: {m.text}")
    parca = m.text.strip().split(" ", 2)
    if len(parca) < 3:
        bot.send_message(m.chat.id,
            "Lütfen bir hisse kodu ve sorunuzu girin.\nÖrn: <code>/sor THYAO bu hissede bedelsiz potansiyeli var mı?</code>",
            parse_mode="HTML")
        return
    ticker_input = parca[1].upper()
    soru = parca[2]
    bot.send_message(m.chat.id, f"🤖 <b>{ticker_input}</b> için yapay zekaya danışılıyor... Lütfen bekleyin.", parse_mode="HTML")
    threading.Thread(target=_ai_sohbet_islem, args=(m.chat.id, ticker_input, soru), daemon=True).start()

@bot.message_handler(func=lambda m: m.text and m.text.strip().lower().startswith("sor "))
def cmd_sor_metin(m):
    logger.info(f">>> [DEBUG] sor metni alindi: {m.text}")
    parca = m.text.strip().split(" ", 2)
    if len(parca) < 3:
        bot.send_message(m.chat.id,
            "Lütfen bir hisse kodu ve sorunuzu girin.\nÖrn: <code>sor THYAO nasil durumlar?</code>",
            parse_mode="HTML")
        return
    ticker_input = parca[1].upper()
    soru = parca[2]
    bot.send_message(m.chat.id, f"🤖 <b>{ticker_input}</b> için yapay zekaya danışılıyor... Lütfen bekleyin.", parse_mode="HTML")
    threading.Thread(target=_ai_sohbet_islem, args=(m.chat.id, ticker_input, soru), daemon=True).start()

@bot.message_handler(commands=["gunluk"])
@bot.message_handler(func=lambda m: m.text == "📅 Günlük")
def cmd_gunluk(m):
    logger.info(f">>> [DEBUG] /gunluk komutu alindi: {m.text}")
    vade, mod, baslik = su_anki_vade_ve_mod_belirle()
    threading.Thread(target=rapor_gonder, args=(KATILIM_TUMU, vade, mod, baslik), daemon=True).start()

@bot.message_handler(commands=["haftalik"])
@bot.message_handler(func=lambda m: m.text == "📅 Haftalık")
def cmd_haftalik(m):
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1wk", "HAFTALIK", "HAFTALIK"), daemon=True).start()

@bot.message_handler(commands=["ikihaftalik"])
@bot.message_handler(func=lambda m: m.text == "📅 İki Haftalık")
def cmd_ikihaftalik(m):
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1wk", "IKI HAFTALIK", "IKI HAFTALIK"), daemon=True).start()

@bot.message_handler(commands=["aylik"])
@bot.message_handler(func=lambda m: m.text == "📅 Aylık")
def cmd_aylik(m):
    threading.Thread(target=rapor_gonder,
        args=(KATILIM_TUMU, "1mo", "AYLIK", "AYLIK"), daemon=True).start()

@bot.message_handler(commands=["altin"])
@bot.message_handler(func=lambda m: m.text == "🥇 Altın")
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
@bot.message_handler(func=lambda m: m.text == "🥈 Gümüş")
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
@bot.message_handler(func=lambda m: m.text == "💎 Tüm Madenler")
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
@bot.message_handler(func=lambda m: m.text == "📈 Tahminler")
def cmd_tahminler(m):
    rapor = tahmin_raporu_olustur()
    try:
        bot.send_message(m.chat.id, rapor, parse_mode="HTML")
    except:
        bot.send_message(m.chat.id, "Tahmin raporu olusturulamadi.")

@bot.message_handler(commands=["piyasa"])
@bot.message_handler(func=lambda m: m.text == "🌍 Piyasa")
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
        "<b>Borsa Gözü | Kişisel Hisse Sinyal Botu</b>\n"
        "\n"
        "<b>HİSSE SİNYALLERİ & SOHBET</b>\n"
        "/hisse [KOD] - Tek bir hisse için anlık detaylı analiz (Örn: /hisse THYAO)\n"
        "/sor [KOD] [SORU] - Seçtiğiniz hisse hakkında yapay zekaya sorular sorun (Örn: /sor ASELS sence yükselir mi?)\n"
        "/gunluk - Bugün al-sat + Yarın sat sinyalleri\n"
        "/haftalik - Bu hafta içinde sat\n"
        "/ikihaftalik - 2 hafta içinde sat\n"
        "/aylik - Uzun vade (bu ay içinde sat)\n"
        "\n"
        "<b>KIYMETLİ MADENLER</b>\n"
        "/altin - Altın ETF + global altın analizi\n"
        "/altin haftalik - Haftalık altın\n"
        "/gumus - Gümüş ETF analizi\n"
        "/madenler - Altın + gümüş hepsi\n"
        "\n"
        "<b>TAHMİN & PİYASA</b>\n"
        "/tahminler - Geçmiş tahmin başarı raporu\n"
        "/piyasa - Canlı döviz + son haberler\n"
        "\n"
        "<b>OTOMATİK RAPORLAR</b>\n"
        "Sabah 09:50 → Bugün al-sat sinyalleri\n"
        "Akşam 17:55 → Yarın sat sinyalleri + tahmin sonuçları\n"
        "\n"
        "<b>Her sinyal için:</b>\n"
        "📊 Grafik (Fiyat + RSI + MACD)\n"
        "🤖 Yapay zeka al/sat fiyat emri\n"
        "🛡 Zarar Kes ve Kâr Al seviyeleri\n"
        "📅 Hangi güne ait olduğu\n"
        "✅ Geçmiş tahmin başarı takibi",
        parse_mode="HTML",
        reply_markup=ana_menu_olustur()
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
    db_baslat()
    
    # Mavi Menu Komutlarini Ayarla
    try:
        bot.set_my_commands([
            BotCommand("start", "Ana menü ve yardım"),
            BotCommand("hisse", "Tek hisse analizi (Örn: /hisse THYAO)"),
            BotCommand("sor", "Hisseyle ilgili yapay zekayla sohbet (Örn: /sor KOD SORU)"),
            BotCommand("gunluk", "Bugün al-sat + Yarın sat"),
            BotCommand("haftalik", "Bu hafta içinde sat"),
            BotCommand("ikihaftalik", "2 hafta içinde sat"),
            BotCommand("aylik", "Uzun vade (aylık)"),
            BotCommand("altin", "Altın fon & ETF analizi"),
            BotCommand("gumus", "Gümüş fon & ETF analizi"),
            BotCommand("madenler", "Tüm oymetli madenler"),
            BotCommand("tahminler", "Geçmiş başarı ve AI raporu"),
            BotCommand("piyasa", "Döviz ve güncel haberler")
        ])
    except Exception as e:
        logger.error("Mavi menu komutlari ayarlanamadi: %s", e)


    scheduler.start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))),
        daemon=True
    ).start()
    print("Borsa Gozu Bot basladi.")
    print("Otomatik: 09:50 bugün al-sat | 17:55 yarın sat + tahmin guncelle")
    # 409 Conflict hatasindan kacinmak icin webhook temizle ve bekle
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        logger.warning("Webhook temizlenemedi: %s", e)
    bot.infinity_polling(none_stop=True, timeout=20, long_polling_timeout=5)

