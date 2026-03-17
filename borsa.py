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

# Gereksiz uyarıları gizle
warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE FLASK (Railway için) ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Syborsa Bot Aktif! (Railway v2.3)", 200

def run_web_server():
    # Railway genellikle 8080 portunu kullanır
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)

# GitHub'a yüklediğin dosya adı
CSV_FILE = "hisse_endeks_katilim_ds.csv"

# --- 2. CSV VE LİSTE YÖNETİMİ ---
def katilim_listesi_yukle():
    """GitHub'daki CSV dosyasını okur ve hisse listesini hazırlar."""
    try:
        if os.path.exists(CSV_FILE):
            # Dosyayı ; ayırıcı ile oku
            df_csv = pd.read_csv(CSV_FILE, sep=';', encoding='utf-8')
            # İlk sütunu al, boşlukları temizle ve .IS ekle
            ham_liste = df_csv.iloc[:, 0].dropna().astype(str).tolist()
            temiz_liste = []
            for h in ham_liste:
                kod = h.strip().upper()
                if not kod.endswith(".IS") and not any(x in kod for x in ["=", "-"]):
                    kod += ".IS"
                temiz_liste.append(kod)
            return temiz_liste
        else:
            print(f"⚠️ {CSV_FILE} bulunamadı, varsayılan liste kullanılıyor.")
            return ["THYAO.IS", "ASTOR.IS", "BIMAS.IS"]
    except Exception as e:
        print(f"❌ CSV Okuma Hatası: {e}")
        return ["THYAO.IS"]

def gruplari_getir():
    return {
        "katilim": katilim_listesi_yukle(),
        "bist30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"],
        "altin": ["ALTINS.IS", "ZGOLD.IS", "GMSTR.IS", "GLDGR.IS"]
    }

# --- 3. TEKNİK ANALİZ ---
def hisse_skorla(ticker, period="6mo"):
    try:
        # Veri çekme
        df = yf.download(ticker, period=period, interval="1d", progress=False, threads=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        # Göstergeler
        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()

        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        
        # Skorlama Mantığı
        skor = (1 if fiyat > float(last["EMA9"]) else 0) + (2 if 40 < rsi < 65 else 0)
        karar = "🔥 GÜÇLÜ" if skor >= 3 else "📈 OLUMLU" if skor >= 1 else "⚖️ NÖTR"

        return {
            "ticker": ticker, "fiyat": fiyat, "rsi": rsi, "upper_bb": float(last["BB_U"]),
            "ema21": float(last["EMA21"]), "ema9": float(last["EMA9"]),
            "karar": karar, "df": df
        }
    except: return None

# --- 4. GÖRSEL VE MESAJ ---
def sonuc_gonder(chat_id, t, baslik_eki=""):
    try:
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        risk = round(((t["fiyat"] - t["ema21"]) / t["fiyat"]) * 100, 2)
        
        mesaj = (f"🏆 *{t['ticker']}* {baslik_eki}\n"
                 f"💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n"
                 f"🏁 *Karar:* `{t['karar']}`\n"
                 f"---------------------------\n"
                 f"🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` \n"
                 f"🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n"
                 f"🛑 *Stop (EMA21):* `{round(t['ema21'], 2)}` (%{risk})\n"
                 f"---------------------------")

        plt.figure(figsize=(7, 4))
        plt.plot(t["df"]["Close"].tail(30).values, color="#1f77b4", linewidth=2)
        plt.grid(True, alpha=0.2)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches='tight')
        buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 5. MENÜ VE KOMUTLAR ---
def menu_ayarla():
    komutlar = [
        telebot.types.BotCommand("katilim_gunluk", "Katılım Fırsat: Günlük"),
        telebot.types.BotCommand("katilim_2hafta", "Katılım Fırsat: İki Haftalık"),
        telebot.types.BotCommand("katilim_aylik", "Katılım Fırsat: Aylık"),
        telebot.types.BotCommand("bist30", "BIST 30: Fırsatları Tara"),
        telebot.types.BotCommand("altin", "Altın ve Fonlar"),
        telebot.types.BotCommand("tum_katilim", "Katılım: Tüm Listeyi Tara")
    ]
    bot.set_my_commands(komutlar)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    raw_text = message.text.strip().lower().replace("/", "")
    
    # Periyot Seçimi
    period = "6mo"
    etiket = ""
    if "gunluk" in raw_text: period, etiket = "1mo", "⏳ (GÜNLÜK)"
    elif "2hafta" in raw_text: period, etiket = "3mo", "⏳ (2 HAFTALIK)"
    elif "aylik" in raw_text: period, etiket = "1y", "⏳ (AYLIK)"

    aktif_gruplar = gruplari_getir()
    
    # Liste Tarama Mantığı
    is_list = False
    target_list = ""
    
    if "katilim" in raw_text: target_list = "katilim"
    elif "bist30" in raw_text: target_list = "bist30"
    elif "altin" in raw_text: target_list = "altin"

    if target_list in aktif_gruplar:
        is_list = True
        hisseler = aktif_gruplar[target_list]
        bot.send_message(message.chat.id, f"🔍 {target_list.upper()} {etiket} taranıyor... ({len(hisseler)} Hisse)")
        
        for h in hisseler:
            res = hisse_skorla(h, period=period)
            if "tum_" in raw_text: # Tümünü gönder
                if res: sonuc_gonder(message.chat.id, res, etiket)
            else: # Sadece fırsatları gönder
                if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]:
                    sonuc_gonder(message.chat.id, res, etiket)
        bot.send_message(message.chat.id, "✅ Tarama tamamlandı.")
    
    if not is_list:
        # Tekil hisse
        res = hisse_skorla(raw_text, period=period)
        if res: sonuc_gonder(message.chat.id, res, etiket)
        else: bot.send_message(message.chat.id, "❌ Hisse bulunamadı veya veri hatası.")

# --- 6. ÇALIŞTIR ---
if __name__ == "__main__":
    menu_ayarla()
    threading.Thread(target=run_web_server, daemon=True).start()
    print("🚀 Bot Railway üzerinde başlatıldı!")
    bot.infinity_polling(timeout=15)
