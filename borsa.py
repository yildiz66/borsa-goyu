import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
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

# --- GÜNCEL LİSTELER ---
KATILIM_LISTESI = ["AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", "JANTS", "KCAER", "KONTR", "KONYA", "KORDS", "KOZAL", "MAVI", "MGROS", "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", "YEOTK"]
FON_LISTESI = ["ALTINS1.IS", "GMSTR.IS", "ZGOLD.IS", "GLDGR.IS"]

def set_commands():
    try:
        bot.delete_my_commands()
        time.sleep(1)
        commands = [
            telebot.types.BotCommand("gunluk", "Katılım: Günlük"),
            telebot.types.BotCommand("ikihaftalik", "Katılım: 2 Haftalık"),
            telebot.types.BotCommand("aylik", "Katılım: Aylık"),
            telebot.types.BotCommand("fonlar", "Altın, Gümüş ve Fonlar"),
            telebot.types.BotCommand("start", "Sistemi Başlat")
        ]
        bot.set_my_commands(commands)
    except: pass

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker if ticker.endswith(".IS") else ticker + ".IS"
        p = "1y" if donem == "1d" else "5y"
        
        # Yahoo hatası durumunda programın çökmesini engellemek için timeout ekledik
        df = yf.download(f_t, period=p, interval=donem, progress=False, threads=False, timeout=10)
        
        if df is None or df.empty or len(df) < 10: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        last = df.iloc[-1]
        
        return {"ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]), "hedef": float(bb.iloc[-1, 2]), "df": df}
    except:
        return None

def ai_yorumla(hisse_verileri, vade_adi):
    try:
        # Veri olmasa bile Gemini piyasa yorumu yapacak
        prompt = f"Borsa uzmanı olarak Emir Bey'e {vade_adi} periyodu için teknik analiz özeti ver. Veriler: {hisse_verileri if hisse_verileri else 'Kriterlere uyan hisse yok.'}. Maksimum 3 cümle."
        return ai_model.generate_content(prompt).text
    except: return "⚠️ Analiz şu an hazır değil."

def rapor_gonder(liste, vade_kod, vade_adi):
    bot.send_message(MY_ID, f"🔍 {vade_adi} tarama başlatıldı...")
    havuz = []
    
    for h in liste:
        res = analiz_motoru(h, vade_kod)
        # RSI aralığını (35-75) yaparak veriyi garantiliyoruz
        if res and 35 < res["rsi"] < 75:
            havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: ((x['hedef'] - x['fiyat']) / x['fiyat']), reverse=True)[:5]
    
    ai_data = []
    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        ai_data.append(f"{t['ticker']}(%{pot})")
        
        plt.figure(figsize=(4, 2)); plt.plot(t["df"]["Close"].tail(20).values, color='green'); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 *{t['ticker']}* | Potansiyel: %{pot}")
        plt.close(); time.sleep(0.4)

    bot.send_message(MY_ID, f"🤖 *Gemini Raporu:*")
    bot.send_message(MY_ID, ai_yorumla(ai_data, vade_adi))

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📈 Terminal Aktif. Mavi menü butonunu kullanın.")

@bot.message_handler(commands=['gunluk'])
def cmd_1(m): rapor_gonder(KATILIM_LISTESI, "1d", "GÜNLÜK")

@bot.message_handler(commands=['ikihaftalik'])
def cmd_2(m): rapor_gonder(KATILIM_LISTESI, "1wk", "2 HAFTALIK")

@bot.message_handler(commands=['aylik'])
def cmd_3(m): rapor_gonder(KATILIM_LISTESI, "1mo", "AYLIK")

@bot.message_handler(commands=['fonlar'])
def cmd_4(m): rapor_gonder(FON_LISTESI, "1d", "FON/METAL")

if __name__ == "__main__":
    # Webhook temizliği
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    set_commands()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling()
