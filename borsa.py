import os
import telebot
import yfinance as yf
import ta
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import time
import pandas as pd
import json
import schedule
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Bot Calisiyor! (Ana Dizin)", 200

@app.route('/api')
def health_check(): 
    return "Sistem Aktif (API)", 200

def run_web_server():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)
DATA_FILE = "borsa_verileri.json"

# --- 2. LİSTE VE JSON ---
GRUPLAR = {
    "katilim": [],
    "bist30": [],
    "bist50": [],
    "bist100": [],
    "altin": []
}

def listeleri_yonet():
    if not os.path.exists(DATA_FILE):
        data = {"last_update": time.time(), "lists": GRUPLAR}
        with open(DATA_FILE, "w") as f: json.dump(data, f)
        return GRUPLAR
    with open(DATA_FILE, "r") as f: return json.load(f)["lists"]

# --- 3. KATILIM GÜNCELLEME ---
def katilim_tum_guncelle():
    print("📥 Katılım Tüm Excel indiriliyor...")
    try:
        url = "https://www.borsaistanbul.com/files/endeksler/XKTUM_Endeks_Bilesenleri.xlsx"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        dosya = "katilim.xlsx"
        with open(dosya, "wb") as f: f.write(r.content)
        df = pd.read_excel(dosya)
        kod_kolon = [c for c in df.columns if "KOD" in str(c).upper()]
        if not kod_kolon:
            print("⚠️ Excel’de 'KOD' kolonu bulunamadı! Liste boş bırakılıyor.")
            hisseler = []
        else:
            hisseler = df[kod_kolon[0]].dropna().tolist()
            hisseler = [str(h).strip() + ".IS" for h in hisseler if len(str(h)) <= 6]
        print("Excel'den gelen Katılım hisseleri:", hisseler)
        if len(hisseler) < 10: return False
        aktif = listeleri_yonet()
        aktif["katilim"] = hisseler
        with open(DATA_FILE, "w") as f: json.dump({"last_update": time.time(), "lists": aktif}, f)
        if os.path.exists(dosya): os.remove(dosya)
        print(f"✅ {len(hisseler)} Katılım hissesi güncellendi")
        return True
    except Exception as e:
        print("❌ Katılım güncelleme hatası:", e)
        return False

# --- 4. DİĞER ENDEKSLER (BIST30/50/100, ALTIN) ---
def endeks_tum_guncelle(endeks_adi, url, kolon_keyword="KOD"):
    print(f"📥 {endeks_adi.upper()} Excel indiriliyor...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        dosya = f"{endeks_adi}.xlsx"
        with open(dosya, "wb") as f: f.write(r.content)
        df = pd.read_excel(dosya)
        kod_kolon = [c for c in df.columns if kolon_keyword in str(c).upper()]
        if not kod_kolon:
            print(f"⚠️ Excel’de '{kolon_keyword}' kolonu bulunamadı! Liste boş bırakılıyor.")
            hisseler = []
        else:
            hisseler = df[kod_kolon[0]].dropna().tolist()
            hisseler = [str(h).strip() + ".IS" for h in hisseler if len(str(h)) <= 6]
        print(f"{endeks_adi.upper()} Excel'den gelen hisseler:", hisseler)
        if len(hisseler) < 5: return False
        aktif = listeleri_yonet()
        aktif[endeks_adi] = hisseler
        with open(DATA_FILE, "w") as f: json.dump({"last_update": time.time(), "lists": aktif}, f)
        if os.path.exists(dosya): os.remove(dosya)
        print(f"✅ {endeks_adi.upper()} listesi güncellendi ({len(hisseler)} hisse)")
        return True
    except Exception as e:
        print(f"❌ {endeks_adi.upper()} güncelleme hatası:", e)
        return False

# --- 5. ANALİZ ---
def gemini_yorumu_ekle(ticker, rsi, fiyat, ema9, upper_bb, donem):
    alim = round(ema9, 2)
    strateji = f"\n💡 *Strateji:* {alim} desteği takip edilebilir." if donem != "sabah" else f"\n🚀 *Strateji:* {fiyat} üstü kalıcılık pozitif."
    if rsi < 32: return f"\n💎 **Gemini:** Hisse dipte, toplama bölgesi.{strateji}"
    elif rsi > 72 or fiyat >= upper_bb: return f"\n⚠️ **Gemini:** Doyumda, kâr alımı uygun olabilir.{strateji}"
    elif fiyat > ema9: return f"\n📈 **Gemini:** Trend yukarı canlı duruyor.{strateji}"
    else: return f"\n⚖️ **Gemini:** Güç topluyor, destek beklenmeli.{strateji}"

def hisse_skorla(ticker, donem="manuel"):
    try:
        ticker = str(ticker).strip().upper().replace("/", "")
        # Spot emtia kontrolü
        if not any(x in ticker for x in [".IS", "=", "-"]):
            if ticker not in ["GLDTR", "ALTIN1GOLD"]: ticker += ".IS"
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Close'])
        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()
        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        skor = (1 if fiyat > float(last["EMA9"]) else 0) + (2 if 40 < rsi < 65 else 0)
        karar = "🔥 GÜÇLÜ" if skor >= 3 else "📈 OLUMLU" if skor >= 1 else "⚖️ NÖTR"
        return {
            "ticker": ticker, "fiyat": fiyat, "rsi": rsi, "upper_bb": float(last["BB_U"]),
            "ema21": float(last["EMA21"]), "ema9": float(last["EMA9"]),
            "karar": karar, "df": df, "yorum": gemini_yorumu_ekle(ticker, rsi, fiyat, float(last["EMA9"]), float(last["BB_U"]), donem)
        }
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        risk = round(((t["fiyat"] - t["ema21"]) / t["fiyat"]) * 100, 2)
        mesaj = (f"🏆 *{t['ticker']}*\n💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n🏁 *Karar:* `{t['karar']}`\n"
                 f"---------------------------\n🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` \n🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n"
                 f"🛑 *Stop (EMA21):* `{round(t['ema21'], 2)}` (%{risk})\n---------------------------\n{t['yorum']}")
        plt.figure(figsize=(7, 4)); plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 6. ZAMANLAYICI ---
def seans_raporu(donem):
    aktif = listeleri_yonet()
    bot.send_message(MY_CHAT_ID, f"📢 **RAPOR: {donem.upper()}**", parse_mode="Markdown")
    for h in aktif.get("katilim", []):
        res = hisse_skorla(h, donem)
        if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]: sonuc_gonder(MY_CHAT_ID, res)

def zamanlayici():
    # Günlük katılım endeksi
    schedule.every().day.at("08:30").do(katilim_tum_guncelle)

    # Çeyrek başı endeks güncellemesi
    def uc_aylik_guncelleme():
        simdi = datetime.now()
        if simdi.day == 1 and simdi.month in [1,4,7,10]:
            endeks_tum_guncelle("bist30", "https://www.borsaistanbul.com/files/endeksler/XBIST30_Endeks_Bilesenleri.xlsx")
            endeks_tum_guncelle("bist50", "https://www.borsaistanbul.com/files/endeksler/XBIST50_Endeks_Bilesenleri.xlsx")
            endeks_tum_guncelle("bist100", "https://www.borsaistanbul.com/files/endeksler/XBIST100_Endeks_Bilesenleri.xlsx")
            endeks_tum_guncelle("altin", "https://www.borsaistanbul.com/files/endeksler/XALTIN_Endeks_Bilesenleri.xlsx")

    schedule.every().day.at("08:00").do(uc_aylik_guncelleme)

    # Seans raporları
    is_gunleri = [schedule.every().monday, schedule.every().tuesday, 
                  schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]
    for gun in is_gunleri:
        gun.at("09:55").do(seans_raporu, "sabah")
        gun.at("18:05").do(seans_raporu, "aksam")
    schedule.every().sunday.at("21:00").do(seans_raporu, "pazar")

    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 7. TELEGRAM MESAJ YÖNETİMİ ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.strip().replace("/", "").lower()
    temiz_metin = metin.replace("tum_", "")
    aktif_listeler = listeleri_yonet()
    if temiz_metin in aktif_listeler:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} listesi taranıyor...")
        for h in aktif_listeler[temiz_metin]:
            res = hisse_skorla(h)
            if res: sonuc_gonder(message.chat.id, res)
        bot.send_message(message.chat.id, "✅ Tarama bitti.")
    else:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} analiz ediliyor...")
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)
        else: bot.send_message(message.chat.id, "❌ Veri alınamadı.")

# --- 8. PROGRAM BAŞLANGICI ---
if __name__ == "__main__":
    # JSON dosyasını temizle
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)

    # Katılım listesi güncel
    katilim_tum_guncelle()

    # Diğer listeleri JSON’da eksikse doldur
    aktif = listeleri_yonet()
    if not aktif.get("bist30"):
        endeks_tum_guncelle("bist30", "https://www.borsaistanbul.com/files/endeksler/XBIST30_Endeks_Bilesenleri.xlsx")
    if not aktif.get("bist50"):
        endeks_tum_guncelle("bist50", "https://www.borsaistanbul.com/files/endeksler/XBIST50_Endeks_Bilesenleri.xlsx")
    if not aktif.get("bist100"):
        endeks_tum_guncelle("bist100", "https://www.borsaistanbul.com/files/endeksler/XBIST100_Endeks_Bilesenleri.xlsx")
    if not aktif.get("altin"):
        endeks_tum_guncelle("altin", "https://www.borsaistanbul.com/files/endeksler/XALTIN_Endeks_Bilesenleri.xlsx")

    # Flask ve zamanlayıcı
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()

    print("🚀 Sistem Hazır! Port 8080 aktif.")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
