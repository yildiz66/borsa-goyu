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
import schedule
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. YAPILANDIRMA VE FLASK (CANLI TUTMA) ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Borsa Botu Aktif! Port 8080 Dinleniyor.", 200

def run_web_server():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

# API Anahtarları (Environment Variables üzerinden çekilir)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
DATA_FILE = "borsa_verileri.json"
bot = telebot.TeleBot(TOKEN)

# Başlangıç Listeleri
VARSAYILAN_GRUPLAR = {
    "katilim": ["ASTOR.IS", "BIMAS.IS", "CANTE.IS", "EGEEN.IS", "ENJSA.IS", "FROTO.IS", "HEKTS.IS", "KONTR.IS", "THYAO.IS", "YEOTK.IS"],
    "bist30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"],
    "bist100": ["SASA.IS", "HEKTS.IS", "KOZAL.IS", "DOAS.IS", "AKSA.IS", "MIATK.IS"]
}

# --- 2. VERİ VE LİSTE YÖNETİMİ ---
def listeleri_yonet():
    if not os.path.exists(DATA_FILE):
        data = {"last_update": time.time(), "lists": VARSAYILAN_GRUPLAR}
        with open(DATA_FILE, "w") as f: json.dump(data, f)
        return VARSAYILAN_GRUPLAR
    with open(DATA_FILE, "r") as f: return json.load(f)["lists"]

def listeleri_internetten_guncelle():
    print("🌐 Listeler güncelleniyor...")
    try:
        url = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/temel-veriler.aspx"
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        cekilen = [tag.text.strip() + ".IS" for tag in soup.find_all('th') if 2 <= len(tag.text.strip()) <= 6]
        
        if len(cekilen) > 50:
            aktif = listeleri_yonet()
            aktif["bist100"] = cekilen[:100]
            aktif["bist30"] = cekilen[:30]
            with open(DATA_FILE, "w") as f:
                json.dump({"last_update": time.time(), "lists": aktif}, f)
            return True
    except: return False

# --- 3. ANALİZ VE SKORLAMA MOTORU ---
def analiz_et(ticker, donem="günlük"):
    try:
        # Periyoda göre veri ayarı
        interval = "1d"; period = "6mo"
        if "hafta" in donem.lower(): interval = "1wk"; period = "2y"
        if "ay" in donem.lower(): interval = "1mo"; period = "5y"

        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty or len(df) < 20: return None
        
        # MultiIndex sütun düzeltme
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # Teknik İndikatörler
        df["RSI"] = ta.momentum.rsi(df["Close"], window=14)
        df["EMA9"] = ta.trend.ema_indicator(df["Close"], window=9)
        df["EMA21"] = ta.trend.ema_indicator(df["Close"], window=21)
        df["BB_U"] = ta.volatility.bollinger_hband(df["Close"])
        
        last = df.iloc[-1]
        fiyat = float(last["Close"])
        rsi = float(last["RSI"])
        
        # Basit Skorlama
        skor = (1 if fiyat > float(last["EMA9"]) else 0) + (2 if 40 < rsi < 65 else 0)
        karar = "🔥 GÜÇLÜ" if skor >= 3 else "📈 OLUMLU" if skor >= 1 else "⚖️ NÖTR"
        
        return {
            "ticker": ticker, "fiyat": fiyat, "rsi": rsi, "karar": karar,
            "ema9": float(last["EMA9"]), "ema21": float(last["EMA21"]), 
            "upper_bb": float(last["BB_U"]), "df": df, "donem": donem
        }
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        mesaj = (f"🎯 *{t['ticker']}* ({t['donem'].upper()})\n"
                 f"---------------------------\n"
                 f"💰 *Fiyat:* `{round(t['fiyat'], 2)}` | *RSI:* `{round(t['rsi'], 1)}`\n"
                 f"🏁 *Karar:* `{t['karar']}`\n"
                 f"🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` \n"
                 f"🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n"
                 f"🛑 *Stop (EMA21):* `{round(t['ema21'], 2)}` \n"
                 f"---------------------------\n"
                 f"💡 *Strateji:* EMA9 üstünde kalıcılık yükselişi tetikleyebilir.")

        plt.figure(figsize=(8, 4))
        plt.plot(t["df"]["Close"].tail(35).values, label="Fiyat", color="blue")
        plt.title(f"{t['ticker']} Teknik Görünüm")
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 4. OTOMATİK RAPOR VE ZAMANLAYICI ---
def seans_raporu(tip):
    aktif = listeleri_yonet()
    bot.send_message(MY_CHAT_ID, f"📢 **{tip.upper()} SEANS RAPORU BAŞLADI**", parse_mode="Markdown")
    # Sadece Katılım grubundaki güçlüleri raporla
    for h in aktif.get("katilim", []):
        res = analiz_et(h)
        if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]:
            sonuc_gonder(MY_CHAT_ID, res)

def zamanlayici_dongusu():
    # Hafta içi raporları
    is_gunleri = [schedule.every().monday, schedule.every().tuesday, schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]
    
    for gun in is_gunleri:
        gun.at("09:55").do(seans_raporu, "Sabah Açılış")
        gun.at("18:05").do(seans_raporu, "Akşam Kapanış")
    
    # Her Pazar akşamı haftalık hazırlık
    schedule.every().sunday.at("21:00").do(seans_raporu, "Haftalık Hazırlık")

    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 5. MESAJ YÖNETİMİ VE MENÜ ---
@bot.message_handler(commands=['start'])
def welcome(message):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("Katılım Günlük", "Katılım 2 Hafta", "Katılım Aylık")
    markup.add("Bist 30 Fırsat", "Bist 100 Fırsat")
    bot.send_message(message.chat.id, "📊 Emir Bey, Borsa Terminali Aktif!", reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_all(message):
    txt = message.text.lower()
    cid = message.chat.id
    aktif_listeler = listeleri_yonet()

    # Periyot Tespiti
    donem = "günlük"
    if "hafta" in txt: donem = "haftalık"
    elif "ay" in txt: donem = "aylık"

    # Liste Taraması
    anahtar = None
    if "katilim" in txt: anahtar = "katilim"
    elif "bist 30" in txt or "bist30" in txt: anahtar = "bist30"
    elif "bist 100" in txt or "bist100" in txt: anahtar = "bist100"

    if anahtar:
        bot.send_message(cid, f"🔍 {anahtar.upper()} {donem} periyodunda taranıyor...")
        for h in aktif_listeler.get(anahtar, []):
            res = analiz_et(h, donem)
            # Manuel istekte sadece 'fırsat' (güçlü/olumlu) olanları gönder
            if res and ("fırsat" in txt or res["karar"] != "⚖️ NÖTR"):
                sonuc_gonder(cid, res)
        bot.send_message(cid, "✅ Tarama tamamlandı.")
    else:
        # Tekil Hisse Analizi
        hisse = txt.upper().replace("/", "")
        if not hisse.endswith(".IS"): hisse += ".IS"
        res = analiz_et(hisse, donem)
        if res: sonuc_gonder(cid, res)
        else: bot.send_message(cid, "❌ Hisse bulunamadı veya veri çekilemedi.")

# --- 6. ANA ÇALIŞTIRICI ---
if __name__ == "__main__":
    # İnternetten listeleri çek (İlk açılışta)
    listeleri_internetten_guncelle()
    
    # Threading başlatma
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici_dongusu, daemon=True).start()

    print("🚀 Sistem Aktif! Port 8080 üzerinden izleniyor.")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
