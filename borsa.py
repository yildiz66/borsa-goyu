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
import re

warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE FLASK ---
app = Flask(__name__)
@app.route('/')
def home(): return "Sistem Aktif!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)

# --- 2. KATILIM LİSTESİ (OTOMATİK GÜNCELLEME ALANI) ---
KATILIM_LISTESI = ["AKSA.IS", "ALTNY.IS", "ASELS.IS", "BIMAS.IS", "BSOKE.IS", "CANTE.IS", "CWENE.IS", "EGEEN.IS", "ENJSA.IS", "ENTRA.IS", "FROTO.IS", "HEKTS.IS", "KCHOL.IS", "KONTR.IS", "KOTON.IS", "LMKDC.IS", "MGROS.IS", "OBAMS.IS", "SASA.IS", "TKFEN.IS", "TUPRS.IS", "VESBE.IS", "YEOTK.IS", "JANTS.IS", "KCAER.IS", "LKMNH.IS", "LOGO.IS", "MAVI.IS"]

# --- 3. LİSTE VE KOD GÜNCELLEME ---
def kodu_guncelle(yeni_hisseler):
    try:
        dosya_yolu = __file__
        with open(dosya_yolu, "r", encoding="utf-8") as f:
            icerik = f.read()
        yeni_liste_str = f"KATILIM_LISTESI = {json.dumps(yeni_hisseler)}"
        guncel_icerik = re.sub(r"KATILIM_LISTESI = \[.*?\]", yeni_liste_str, icerik)
        with open(dosya_yolu, "w", encoding="utf-8") as f:
            f.write(guncel_icerik)
        return True
    except: return False

def get_market_lists():
    try:
        url = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/temel-veriler.aspx"
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        cekilen = [tag.text.strip() + ".IS" for tag in soup.find_all('th') if 2 <= len(tag.text.strip()) <= 6]
        return {"bist30": cekilen[:30], "bist100": cekilen[:100], "anapazar": cekilen[100:250]}
    except: return {"bist30": [], "bist100": [], "anapazar": []}

# --- 4. ANALİZ VE RAPORLAMA ---
def gemini_yorumu(rsi, fiyat, ema9):
    if rsi < 35: return "💎 Dip seviyelerde, toplama bölgesi olabilir."
    if rsi > 70: return "⚠️ Aşırı alım bölgesinde, kâr satışı gelebilir."
    if fiyat > ema9: return "📈 Trend yukarı yönlü güçlü görünüyor."
    return "⚖️ Kararsız bölge, destek beklemek mantıklı."

def hisse_skorla(ticker, donem="manuel", vade="günlük"):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 25: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()

        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        
        # FIRSAT KRİTERİ (Nokta Atışı)
        firsat = (40 < rsi < 68) and (fiyat > float(last["EMA9"]))
        
        return {
            "ticker": ticker, "fiyat": fiyat, "rsi": rsi, "ema9": float(last["EMA9"]),
            "ema21": float(last["EMA21"]), "upper_bb": float(last["BB_U"]), "df": df,
            "firsat": firsat, "yorum": gemini_yorumu(rsi, fiyat, float(last["EMA9"]))
        }
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        mesaj = (f"🏆 *{t['ticker']}*\n💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n"
                 f"---------------------------\n🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` \n🛑 *Stop (EMA21):* `{round(t['ema21'], 2)}` \n"
                 f"---------------------------\n{t['yorum']}")
        plt.figure(figsize=(7, 4)); plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 5. MESAJ VE ZAMANLAYICI ---
def seans_raporu():
    for h in KATILIM_LISTESI[:15]:
        res = hisse_skorla(h)
        if res and res["firsat"]: sonuc_gonder(MY_CHAT_ID, res)

def zamanlayici():
    schedule.every().day.at("09:55").do(seans_raporu)
    schedule.every().day.at("18:05").do(seans_raporu)
    while True:
        schedule.run_pending()
        time.sleep(30)

@bot.message_handler(content_types=['document'])
def handle_csv(message):
    if message.document.file_name.endswith('.csv'):
        raw = bot.download_file(bot.get_file(message.document.file_id).file_path)
        with open("update.csv", "wb") as f: f.write(raw)
        df = pd.read_csv("update.csv", sep=';', skiprows=2, header=None)
        yeni = [str(h).split('.')[0].strip().upper() + ".IS" for h in df[0].dropna()]
        if yeni and kodu_guncelle(yeni):
            bot.reply_to(message, "✅ Katılım listesi koda işlendi! Botu yeniden başlatın.")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.lower()
    lists = get_market_lists()
    
    # Menü Karşılaştırma
    hedef_liste = []
    if "bist 30" in metin or "bist30" in metin: hedef_liste = lists["bist30"]
    elif "bist 100" in metin or "bist100" in metin: hedef_liste = lists["bist100"]
    elif "anapazar" in metin: hedef_liste = lists["anapazar"]
    elif "katilim" in metin or "günlük" in metin: hedef_liste = KATILIM_LISTESI
    
    if hedef_liste:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} taranıyor...")
        sayac = 0
        for h in hedef_liste:
            res = hisse_skorla(h)
            if res:
                if "fırsat" in metin and not res["firsat"]: continue
                sonuc_gonder(message.chat.id, res)
                sayac += 1
                if sayac >= 10: break
    else:
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)

if __name__ == "__main__":
    bot.set_my_commands([
        telebot.types.BotCommand("start", "🏠 Ana Menü"),
        telebot.types.BotCommand("bist30_firsat", "🔥 BIST 30 Fırsatları"),
        telebot.types.BotCommand("bist100_firsat", "🚀 BIST 100 Fırsatları"),
        telebot.types.BotCommand("anapazar_firsat", "💎 Anapazar Fırsatları"),
        telebot.types.BotCommand("katilim_gunluk", "⚡ Katılım Günlük Fırsat")
    ])
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()
    bot.infinity_polling()
