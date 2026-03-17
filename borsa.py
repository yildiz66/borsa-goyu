import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, schedule
import matplotlib
# Hatayı çözmek için 'use' komutunu importun hemen ardından veriyoruz
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import google.generativeai as genai # Uyarıyı şu anlık görmezden gelebiliriz, sistem çalışır
from telebot import types
from flask import Flask

# Uyarıları sessize al
warnings.filterwarnings("ignore")

# --- 1. AYARLAR ---
app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# 147 Hisse Listesi (Kısaltılmış örnek, sizdeki tam listeyi buraya koyun)
KATILIM_LISTESI = ["AKSA", "ASELS", "THYAO", "TUPRS", "FROTO", "EREGL", "SASA", "SISE"] # Listenin devamı aynı kalsın

# --- 2. FONKSİYONLAR ---

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        if not (ticker.endswith(".IS") or "=" in ticker): ticker += ".IS"
        p = "6mo" if donem == "1d" else "2y" if donem == "1wk" else "5y"
        
        df = yf.download(ticker, period=p, interval=donem, progress=False, threads=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.rsi(df["Close"], length=14)
        df["EMA9"] = ta.ema(df["Close"], length=9)
        bb = ta.bbands(df["Close"], length=20)
        
        last = df.iloc[-1]
        res = {
            "ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]),
            "hedef": float(bb.iloc[-1, 2]), "df": df, "vade": donem
        }
        return res
    except: return None

def gemini_strateji_al(hisse_listesi, vade_adi):
    try:
        ozet = "".join([f"{h['ticker']}: Fiyat {h['fiyat']}, RSI {h['rsi']}. " for h in hisse_listesi])
        prompt = (f"Borsa uzmanı olarak bu hisseleri kıyasla: {ozet}. "
                  f"Emir Bey için en potansiyelli 2 tanesini seç ve nedenini açıkla.")
        response = ai_model.generate_content(prompt)
        return response.text
    except: return "AI yorumu şu an ulaşılamaz."

# --- 3. RAPORLAMA ---

def rapor_gonder(vade_kod="1d", vade_adi="GÜNLÜK"):
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        if res and 48 < res["rsi"] < 68: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['rsi'], reverse=True)[:5]
    if not en_iyi_5: return

    for t in en_iyi_5:
        mesaj = f"💎 *{vade_adi} ANALİZ:* {t['ticker']}\n🛒 *Fiyat:* `{t['fiyat']}` | 🎯 *Hedef:* `{round(t['hedef'], 2)}`"
        plt.figure(figsize=(5, 2)); plt.plot(t["df"]["Close"].tail(30).values, color="green"); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")

    ai_yorum = gemini_strateji_al(en_iyi_5, vade_adi)
    bot.send_message(MY_ID, f"⭐ *ÖZEL SEÇİM*\n\n{ai_yorum}", parse_mode="Markdown")

# --- 4. KOMUTLAR VE ZAMANLAYICI ---

@bot.message_handler(func=lambda m: True)
def handle(message):
    if "fırsat" in message.text.lower():
        rapor_gonder("1d", "MANUEL TARAMA")

def scheduler_start():
    schedule.every().monday.to.friday.at("09:55").do(lambda: rapor_gonder("1d", "SABAH AÇILIŞ"))
    schedule.every().monday.to.friday.at("17:50").do(lambda: rapor_gonder("1d", "AKŞAM KAPANIŞ"))
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=scheduler_start, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling()
