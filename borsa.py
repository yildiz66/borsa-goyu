import os
import telebot
import yfinance as yf
import pandas_ta as ta
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import time
import pandas as pd
import json
import threading
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. AYARLAR ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
DATA_FILE = "borsa_verileri.json"
bot = telebot.TeleBot(TOKEN)

# --- 2. VERİ YÖNETİMİ ---
def listeleri_yonet():
    # JSON dosyasından güncel listeleri çeker
    if not os.path.exists(DATA_FILE):
        return {"katilim": [], "bist30": [], "bist100": []}
    with open(DATA_FILE, "r") as f:
        return json.load(f)["lists"]

# --- 3. ANALİZ MOTORU ---
def analiz_et(ticker, donem="günlük"):
    try:
        ticker = ticker.strip().upper()
        if not ticker.endswith(".IS"): ticker += ".IS"
        
        # Filtre: Sistem kelimelerini Yahoo'ya sorma
        if any(x in ticker for x in ["START", "GÜNLÜK", "HAFTA", "AYLIK"]): return None

        p, i = ("6mo", "1d") if "gün" in donem else ("2y", "1wk") if "hafta" in donem else ("5y", "1mo")
        df = yf.download(ticker, period=p, interval=i, progress=False)
        
        if df.empty or len(df) < 15: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.rsi(df["Close"], length=14)
        df["EMA9"] = ta.ema(df["Close"], length=9)
        df["BB_U"] = ta.bbands(df["Close"], length=20).iloc[:, 2] # Upper Band

        last = df.iloc[-1]
        res = {
            "ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]),
            "ema9": float(last["EMA9"]), "upper_bb": float(last["BB_U"]),
            "df": df, "donem": donem
        }
        # Karar Mekanizması
        res["karar"] = "🔥 GÜÇLÜ" if res["fiyat"] > res["ema9"] and 45 < res["rsi"] < 65 else "⚖️ NÖTR"
        return res
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        mesaj = (f"🎯 *{t['ticker']}* ({t['donem'].upper()})\n"
                 f"💰 Fiyat: `{round(t['fiyat'], 2)}` | RSI: `{round(t['rsi'], 1)}`\n"
                 f"🏁 Karar: `{t['karar']}`\n🎯 Hedef: `{round(t['upper_bb'], 2)}`")
        plt.figure(figsize=(6, 3)); plt.plot(t["df"]["Close"].tail(30).values); plt.title(t["ticker"])
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 4. MESAJ YÖNETİMİ (SORUNU ÇÖZEN KISIM) ---
@bot.message_handler(func=lambda message: True)
def handle_all(message):
    txt = message.text.lower().strip()
    cid = message.chat.id
    aktif_listeler = listeleri_yonet() # JSON'dan listeleri burada çekiyoruz

    # Periyot tespiti
    donem = "günlük"
    if "hafta" in txt: donem = "haftalık"
    elif "ay" in txt: donem = "aylık"

    # Liste eşleştirme (JSON anahtarlarına bakar)
    secilen_grup = None
    for grup_adi in aktif_listeler.keys():
        if grup_adi in txt:
            secilen_grup = grup_adi
            break

    if secilen_grup:
        bot.send_message(cid, f"🔍 {secilen_grup.upper()} listesi {donem} taranıyor...")
        for h in aktif_listeler[secilen_grup]:
            res = analiz_et(h, donem)
            # Sadece güçlü olanları veya spesifik 'fırsat' isteğini gönder
            if res and (res["karar"] != "⚖️ NÖTR" or "fırsat" in txt):
                sonuc_gonder(cid, res)
        bot.send_message(cid, "✅ Tarama bitti.")
    else:
        # Eğer mesaj bir liste değilse tekil hisse olarak dene
        hisse = txt.split()[0].upper()
        if len(hisse) >= 3 and len(hisse) <= 6:
            res = analiz_et(hisse, donem)
            if res: sonuc_gonder(cid, res)
            else: bot.send_message(cid, "❌ Veri bulunamadı.")

# --- 5. BAŞLATICI ---
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True).start()
    print("🚀 Bot başlatıldı...")
    bot.infinity_polling(timeout=20)
