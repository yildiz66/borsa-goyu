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

# --- 1. AYARLAR VE FLASK (RAILWAY UYUMLU) ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Bot Calisiyor! (Railway)", 200

def run_web_server():
    # Railway'in atadığı PORT'u alıyoruz
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)
DATA_FILE = "borsa_verileri.json"

# İlk Kurulum Listeleri
GRUPLAR = {
    "katilim": ["ASTOR.IS", "BIMAS.IS", "THYAO.IS"], # İlk kurulum için, sonra güncellenecek
    "bist30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"]
}

# --- 2. LİSTE VE VERİ YÖNETİMİ ---
def listeleri_yonet():
    if not os.path.exists(DATA_FILE):
        data = {"last_update": time.time(), "lists": GRUPLAR}
        with open(DATA_FILE, "w") as f: json.dump(data, f)
        return GRUPLAR
    with open(DATA_FILE, "r") as f: return json.load(f)["lists"]

def katilim_listesini_guncelle():
    print("🌐 Tüm Katılım Endeksi (XKTUM) listesi güncelleniyor...")
    try:
        url = "https://www.getmidas.com/canli-borsa/katilim-endeksi-hisseleri/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        cekilen = []
        for td in soup.find_all('td'):
            kod = td.text.strip()
            if 3 <= len(kod) <= 6 and kod.isupper() and kod.isalpha():
                cekilen.append(kod + ".IS")
        
        if len(cekilen) > 50:
            aktif = listeleri_yonet()
            aktif["katilim"] = sorted(list(set(cekilen)))
            with open(DATA_FILE, "w") as f:
                json.dump({"last_update": time.time(), "lists": aktif}, f)
            print(f"✅ {len(aktif['katilim'])} katılım hissesi başarıyla güncellendi.")
            return True
    except Exception as e:
        print(f"❌ Katılım listesi çekilemedi: {e}")
        return False

# --- 3. ANALİZ VE SKORLAMA ---
def gemini_yorumu_ekle(ticker, rsi, fiyat, ema9, upper_bb, donem):
    alim = round(ema9, 2)
    strateji = f"\n💡 *Strateji:* {alim} desteği takip edilebilir." if donem != "sabah" else f"\n🚀 *Strateji:* {fiyat} üstü kalıcılık pozitif."
    if rsi < 32: return f"\n💎 **Analiz:** Hisse dipte, toplama bölgesi.{strateji}"
    elif rsi > 72 or fiyat >= upper_bb: return f"\n⚠️ **Analiz:** Doyumda, kâr alımı uygun olabilir.{strateji}"
    elif fiyat > ema9: return f"\n📈 **Analiz:** Trend yukarı canlı duruyor.{strateji}"
    else: return f"\n⚖️ **Analiz:** Güç topluyor, destek beklenmeli.{strateji}"

def hisse_skorla(ticker, donem="manuel"):
    try:
        ticker = str(ticker).strip().upper().replace("/", "")
        if not any(x in ticker for x in [".IS", "=", "-"]): ticker += ".IS"

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

        plt.figure(figsize=(7, 4))
        plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        plt.title(f"{t['ticker']} Son 30 Gün")
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 4. ZAMANLAYICI ---
def seans_raporu(donem):
    aktif = listeleri_yonet()
    hisseler = aktif.get("katilim", [])
    bot.send_message(MY_CHAT_ID, f"📢 **TARAMA BAŞLADI: {len(hisseler)} Hisse ({donem.upper()})**")
    
    bulunan = 0
    for h in hisseler:
        res = hisse_skorla(h, donem)
        if res and res["karar"] in ["🔥 GÜÇLÜ"]: # Çok hisse olduğu için sadece en güçlüleri gönderir
            sonuc_gonder(MY_CHAT_ID, res)
            bulunan += 1
            time.sleep(1.5) # Railway ve Yahoo ban koruması
    
    bot.send_message(MY_CHAT_ID, f"✅ Tarama bitti. {bulunan} adet güçlü sinyal bulundu.")

def zamanlayici():
    # Başlangıçta listeyi bir kez güncelle
    katilim_listesini_guncelle()

    schedule.every().day.at("08:00").do(katilim_listesini_guncelle)

    is_gunleri = [schedule.every().monday, schedule.every().tuesday, 
                  schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]

    for gun in is_gunleri:
        gun.at("09:55").do(seans_raporu, "sabah")
        gun.at("18:05").do(seans_raporu, "aksam")

    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 5. MESAJ YÖNETİMİ ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.strip().replace("/", "").lower()
    aktif_listeler = listeleri_yonet()

    if metin in aktif_listeler:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} listesi taranıyor (Sadece Güçlüler)...")
        for h in aktif_listeler[metin]:
            res = hisse_skorla(h)
            if res and res["karar"] == "🔥 GÜÇLÜ":
                sonuc_gonder(message.chat.id, res)
                time.sleep(1)
        bot.send_message(message.chat.id, "✅ İşlem tamamlandı.")
    else:
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)
        else: bot.send_message(message.chat.id, "❌ Hisse bulunamadı veya veri hatası.")

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()
    print("🚀 Railway Sistemi Hazır!")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
