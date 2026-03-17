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
import threading
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

app = Flask(__name__)

@app.route('/')
def home(): 
    return "Syborsa Bot Aktif! (v2.5 - Tüm Pazarlar Dahil)", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)
CSV_FILE = "hisse_endeks_katilim_ds.csv"

# --- 1. LİSTE YÖNETİMİ ---
def katilim_listesi_yukle():
    try:
        if os.path.exists(CSV_FILE):
            df_csv = pd.read_csv(CSV_FILE, sep=';', encoding='utf-8')
            ham_liste = df_csv.iloc[:, 0].dropna().astype(str).tolist()
            temiz_liste = []
            for h in ham_liste:
                kod = h.strip().upper().split(".E")[0] # .E takısını temizle
                if not kod.endswith(".IS") and kod != "": kod += ".IS"
                if kod not in temiz_liste: temiz_liste.append(kod)
            return temiz_liste
        return ["THYAO.IS"]
    except: return ["THYAO.IS"]

def gruplari_getir():
    return {
        "katilim": katilim_listesi_yukle(),
        "bist30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"],
        "bist100": ["SASA.IS", "HEKTS.IS", "SISE.IS", "PETKM.IS", "KOZAL.IS"], # Örnek, yfinance endeks takibi için
        "anapazar": ["ALCTL.IS", "DESPC.IS", "INDES.IS"], # Örnek
        "altin": ["ALTINS.IS", "ZGOLD.IS", "GMSTR.IS"]
    }

# --- 2. ANALİZ MOTORU ---
def hisse_skorla(ticker, period="6mo"):
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, threads=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()

        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        skor = (1 if fiyat > float(last["EMA9"]) else 0) + (2 if 40 < rsi < 65 else 0)
        karar = "🔥 GÜÇLÜ" if skor >= 3 else "📈 OLUMLU" if skor >= 1 else "⚖️ NÖTR"

        return {"ticker": ticker, "fiyat": fiyat, "rsi": rsi, "upper_bb": float(last["BB_U"]), 
                "ema21": float(last["EMA21"]), "ema9": float(last["EMA9"]), "karar": karar, "df": df}
    except: return None

# --- 3. GÖRSEL VE MESAJ ---
def sonuc_gonder(chat_id, t, etiket=""):
    try:
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        risk = round(((t["fiyat"] - t["ema21"]) / t["fiyat"]) * 100, 2)
        clean_ticker = t['ticker'].replace(".", "\\.")
        
        mesaj = (f"🏆 *{clean_ticker}* {etiket}\n"
                 f"💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n"
                 f"🏁 *Karar:* `{t['karar']}`\n"
                 f"🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n"
                 f"🛑 *Stop:* `{round(t['ema21'], 2)}` (%{risk})")

        plt.figure(figsize=(7, 4))
        plt.plot(t["df"]["Close"].tail(30).values, color="#1f77b4", linewidth=2)
        buf = io.BytesIO(); plt.savefig(buf, format="png", bbox_inches='tight'); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="MarkdownV2")
        plt.close("all")
    except: pass

# --- 4. YENİ MENÜ TASARIMI ---
def menu_ayarla():
    komutlar = [
        telebot.types.BotCommand("katilim_gunluk", "Katılım: Günlük"),
        telebot.types.BotCommand("katilim_2hafta", "Katılım: 2 Hafta"),
        telebot.types.BotCommand("katilim_aylik", "Katılım: Aylık"),
        telebot.types.BotCommand("bist30", "BIST 30 Tara"),
        telebot.types.BotCommand("bist100", "BIST 100 Tara"),
        telebot.types.BotCommand("anapazar", "Ana Pazar Tara"),
        telebot.types.BotCommand("altin", "Altın/Gümüş"),
        telebot.types.BotCommand("tum_katilim", "Katılım: Tüm Liste")
    ]
    bot.set_my_commands(komutlar)

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    text = message.text.strip().lower().replace("/", "")
    period, etiket = "6mo", ""
    if "gunluk" in text: period, etiket = "1mo", "⏳ GÜNLÜK"
    elif "2hafta" in text: period, etiket = "3mo", "⏳ 2 HAFTA"
    elif "aylik" in text: period, etiket = "1y", "⏳ AY"

    aktif_gruplar = gruplari_getir()
    
    # Hedef grubu bul
    target = ""
    for g in aktif_gruplar.keys():
        if g in text:
            target = g
            break

    if target:
        hisseler = aktif_gruplar[target]
        bot.send_message(message.chat.id, f"🔍 {target.upper()} {etiket} taranıyor...")
        for h in hisseler:
            res = hisse_skorla(h, period=period)
            if "tum_" in text or (res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]):
                sonuc_gonder(message.chat.id, res, etiket)
        bot.send_message(message.chat.id, "✅ Tarama bitti.")
    else:
        res = hisse_skorla(text, period=period)
        if res: sonuc_gonder(message.chat.id, res, etiket)
        else: bot.send_message(message.chat.id, "❌ Hata: Hisse bulunamadı.")

if __name__ == "__main__":
    menu_ayarla()
    threading.Thread(target=run_web_server, daemon=True).start()
    bot.infinity_polling()
