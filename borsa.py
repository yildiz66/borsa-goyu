import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
import google.generativeai as genai
from flask import Flask

warnings.filterwarnings("ignore")
app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# 1. ÖZEL LİSTE (Sizin takip ettikleriniz)
OZEL_LISTE = ["AKSA", "ASELS", "BIMAS", "EREGL", "FROTO", "KOZAL", "SASA", "THYAO", "TUPRS"]

# 2. TÜM KATILIM (Genişletilmiş Liste)
KATILIM_TUMU = [
    "AKSA", "ALTNY", "ASELS", "BIMAS", "BRISA", "BSOKE", "CANTE", "CIMSA", "CWENE", 
    "DOAS", "EGEEN", "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", 
    "JANTS", "KCAER", "KONTR", "KONYA", "KORDS", "KOZAL", "MAVI", "MGROS", "MIATK", 
    "OYAKC", "PGSUS", "REEDR", "SASA", "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", 
    "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", "YEOTK", "ZEDUR"
]

FON_LISTESI = ["ALTINS1.IS", "GC=F", "GMSTR.IS", "SI=F", "USDTRY=X"]

def set_commands():
    try:
        bot.delete_my_commands()
        time.sleep(1)
        commands = [
            telebot.types.BotCommand("gunluk", "Özel Liste: Günlük"),
            telebot.types.BotCommand("katilim_tumu", "Tüm Katılım Hisseleri"),
            telebot.types.BotCommand("fonlar", "Altın/Gümüş/Döviz"),
            telebot.types.BotCommand("start", "Sistemi Başlat")
        ]
        bot.set_my_commands(commands)
    except: pass

def analiz_motoru(hisse):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker if ("=" in ticker or ".IS" in ticker) else ticker + ".IS"
        df = yf.download(f_t, period="1y", interval="1d", progress=False, timeout=10)
        
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        return {
            "ticker": ticker, 
            "fiyat": float(df.iloc[-1]["Close"]), 
            "rsi": float(df.iloc[-1]["RSI"]), 
            "ust_bant": float(bb.iloc[-1, 2]),
            "df": df
        }
    except: return None

def rapor_gonder(liste, baslik):
    bot.send_message(MY_ID, f"🔍 {baslik} taranıyor... (Hisse sayısı: {len(liste)})")
    havuz = []
    
    for h in liste:
        res = analiz_motoru(h)
        # RSI 30-70 arası, potansiyeli olanları seç
        if res and 30 < res["rsi"] < 70:
            havuz.append(res)
        time.sleep(0.1) # Yahoo ban koruması

    # En yüksek potansiyelli 5 taneyi seç
    en_iyi = sorted(havuz, key=lambda x: ((x['ust_bant'] - x['fiyat']) / x['fiyat']), reverse=True)[:5]

    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Kriterlere uygun hisse bulunamadı.")
        return

    ai_ozet = []
    for t in en_iyi:
        pot = round(((t["ust_bant"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        ai_ozet.append(f"{t['ticker']}(%{pot})")
        
        plt.figure(figsize=(4, 2)); plt.plot(t["df"]["Close"].tail(20).values, color='green'); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 *{t['ticker']}*\nFiyat: {round(t['fiyat'], 2)} | Pot: %{pot}")
        plt.close()

    # Gemini Yorumu
    try:
        prompt = f"Borsa uzmanı olarak bu hisseleri yorumla: {ai_ozet}. Emir Bey'e kısa tavsiye ver."
        bot.send_message(MY_ID, f"🤖 *Gemini:* {ai_model.generate_content(prompt).text}")
    except: pass

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📊 Emir Bey terminal aktif. Menüden 'Tüm Katılım' seçeneğini deneyebilirsiniz.")

@bot.message_handler(commands=['gunluk'])
def cmd_g(m): rapor_gonder(OZEL_LISTE, "Özel Liste")

@bot.message_handler(commands=['katilim_tumu'])
def cmd_k(m): rapor_gonder(KATILIM_TUMU, "Tüm Katılım")

@bot.message_handler(commands=['fonlar'])
def cmd_f(m): rapor_gonder(FON_LISTESI, "Fon/Metal")

if __name__ == "__main__":
    # Çakışma (Conflict) çözüm katmanı
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    time.sleep(2)
    set_commands()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling(timeout=25)
