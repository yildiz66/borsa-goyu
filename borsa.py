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

# --- 1. AYARLAR ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Calisiyor!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)

# --- 2. KATILIM LİSTESİ (BU KISIM OTOMATİK GÜNCELLENECEK) ---
KATILIM_LISTESI = ["AKSA.IS", "ALTNY.IS", "ASELS.IS", "BIMAS.IS", "BSOKE.IS", "CANTE.IS", "CWENE.IS", "EGEEN.IS", "ENJSA.IS", "ENTRA.IS", "FROTO.IS", "HEKTS.IS", "KCHOL.IS", "KONTR.IS", "KOTON.IS", "LMKDC.IS", "MGROS.IS", "OBAMS.IS", "SASA.IS", "TKFEN.IS", "TUPRS.IS", "VESBE.IS", "YEOTK.IS", "JANTS.IS", "KCAER.IS", "LKMNH.IS", "LOGO.IS", "MAVI.IS"]

# --- 3. KODU KENDİ KENDİNE GÜNCELLEME SİSTEMİ ---
def kodu_guncelle(yeni_hisseler):
    try:
        dosya_yolu = __file__
        with open(dosya_yolu, "r", encoding="utf-8") as f:
            icerik = f.read()

        # Regex ile KATILIM_LISTESI satırını bul ve yeni listeyle değiştir
        yeni_liste_str = f"KATILIM_LISTESI = {json.dumps(yeni_hisseler)}"
        guncel_icerik = re.sub(r"KATILIM_LISTESI = \[.*?\]", yeni_liste_str, icerik)

        with open(dosya_yolu, "w", encoding="utf-8") as f:
            f.write(guncel_icerik)
        return True
    except Exception as e:
        print(f"Kod güncelleme hatası: {e}")
        return False

# --- 4. ANALİZ MOTORU ---
def hisse_skorla(ticker, vade="günlük"):
    try:
        ticker = str(ticker).strip().upper()
        if not ticker.endswith(".IS"): ticker += ".IS"
        
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 30: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        
        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        
        uygun = False
        if vade == "günlük" and 30 < rsi < 65: uygun = True
        elif vade == "2 hafta" and fiyat > float(last["EMA9"]): uygun = True
        elif vade == "1 ay" and fiyat > float(last["EMA21"]): uygun = True
        
        return {"ticker": ticker, "fiyat": fiyat, "rsi": rsi, "ema9": float(last["EMA9"]), "ema21": float(last["EMA21"]), "df": df, "vade": vade, "uygun": uygun}
    except: return None

def sonuc_gonder(chat_id, t):
    mesaj = (f"🎯 *{t['ticker']}* ({t['vade'].upper()})\n💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n"
             f"🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` | 🛑 *Stop:* `{round(t['ema21'], 2)}`")
    plt.figure(figsize=(7, 4)); plt.plot(t["df"]["Close"].tail(30).values, color="blue"); buf = io.BytesIO()
    plt.savefig(buf, format="png"); buf.seek(0); bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown"); plt.close()

# --- 5. DOSYA VE MESAJ YÖNETİMİ ---
@bot.message_handler(content_types=['document'])
def handle_csv(message):
    if message.document.file_name.endswith('.csv'):
        raw_file = bot.download_file(bot.get_file(message.document.file_id).file_path)
        with open("update.csv", "wb") as f: f.write(raw_file)
        try:
            df = pd.read_csv("update.csv", sep=';', skiprows=2, header=None)
            yeni = [str(h).split('.')[0].strip().upper() + ".IS" for h in df[0].dropna()]
            if yeni and kodu_guncelle(yeni):
                bot.reply_to(message, f"✅ Başarılı! {len(yeni)} hisse kodun içine işlendi. Botu Railway'den bir kez 'Restart' yapman yeterli.")
        except Exception as e: bot.reply_to(message, f"❌ Hata: {e}")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.lower()
    vade = "günlük" if "günlük" in metin else "2 hafta" if "2 haftalık" in metin else "1 ay" if "1 aylık" in metin else None
    
    if vade:
        bot.send_message(message.chat.id, f"🔍 {vade.upper()} vade taranıyor...")
        for h in KATILIM_LISTESI:
            res = hisse_skorla(h, vade)
            if res and res["uygun"]: sonuc_gonder(message.chat.id, res)
    else:
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)

if __name__ == "__main__":
    bot.set_my_commands([
        telebot.types.BotCommand("start", "Ana Menü"),
        telebot.types.BotCommand("gunluk", "Günlük Fırsatlar"),
        telebot.types.BotCommand("iki_haftalik", "2 Haftalık Fırsatlar"),
        telebot.types.BotCommand("bir_aylik", "1 Aylık Fırsatlar")
    ])
    threading.Thread(target=run_web_server, daemon=True).start()
    bot.infinity_polling()
