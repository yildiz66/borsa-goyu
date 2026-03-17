import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
from flask import Flask

# Tüm uyarıları (FutureWarning vb.) sustur
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

# 147 Hisselik Listeniz (Sadece bir kısmı burada, tamamını koruduğunuzdan emin olun)
KATILIM_LISTESI = sorted(list(set([
    "AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", 
    "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", "JANTS", "KCAER", "KONTR", 
    "KONYA", "KORDS", "KOZAL", "MAVI", "MGROS", "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", 
    "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", 
    "YEOTK", "AGHOL", "AKCNS", "ALARK", "ALFAS", "ASUZU", "BERA", "BIENP", "BRYAT", "BRSAN", 
    "EUPWR", "GENIL", "GSDHO", "GWIND", "INDES", "INVES", "KARYE", "KAYSE", "KCHOL", "KOZAA", 
    "KRDMD", "LOGO", "ODAS", "OTKAR", "QUAGR", "SAHOL", "SKBNK", "SOKM", "TAVHL", "TCELL", 
    "TSKB", "TTKOM", "TURSG", "VAKBN", "VESTL", "YKBNK", "ZOREN"
])))

def ana_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("Günlük Katılım Fırsat", "İki Haftalık Katılım Fırsat", "Aylık Katılım Fırsat", "Tüm Katılım")
    return markup

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        if not (ticker.endswith(".IS") or "=" in ticker): ticker += ".IS"
        p = "6mo" if donem == "1d" else "2y" if donem == "1wk" else "5y"
        
        # Log kirliliğini önlemek için sessiz indirme
        df = yf.download(ticker, period=p, interval=donem, progress=False, threads=False, auto_adjust=True)
        
        if df is None or df.empty or len(df) < 15: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        if df["RSI"].isnull().all(): return None
        last = df.iloc[-1]
        return {"ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]), "hedef": float(bb.iloc[-1, 2]), "df": df}
    except:
        return None # Hata durumunda log basmadan geç

def rapor_gonder(vade_kod, vade_adi):
    bot.send_message(MY_ID, f"🔍 {vade_adi} tarama başlatıldı...")
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        if res and 48 < res["rsi"] < 68: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['rsi'], reverse=True)[:5]
    if not en_iyi_5:
        bot.send_message(MY_ID, "😕 Kriterlere uygun hisse bulunamadı.")
        return

    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        mesaj = f"💎 *{vade_adi}:* {t['ticker']}\n🛒 Fiyat: `{round(t['fiyat'], 2)}` | 🎯 Hedef: `{round(t['hedef'], 2)}` (%{pot})"
        plt.figure(figsize=(5, 2.5)); plt.plot(t["df"]["Close"].tail(30).values, color="green"); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")
        time.sleep(0.5)

@bot.message_handler(func=lambda m: True)
def handle_msg(message):
    txt = message.text.upper().strip()
    if "/START" in txt:
        bot.send_message(message.chat.id, "📈 Terminal Hazır, Emir Bey.", reply_markup=ana_menu())
    elif "GÜNLÜK" in txt: rapor_gonder("1d", "GÜNLÜK")
    elif "İKİ HAFTALIK" in txt: rapor_gonder("1wk", "İKİ HAFTALIK")
    elif "AYLIK" in txt: rapor_gonder("1mo", "AYLIK")
    elif "TÜM" in txt: rapor_gonder("1d", "TAM LİSTE")

if __name__ == "__main__":
    # CONFLICT (409) KÖKTEN ÇÖZÜM: Eski tüm bağlantıları zorla düşür
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
        time.sleep(2)
    except: pass

    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    
    print("🚀 Sistem Emir Bey'in listesiyle tertemiz aktif!")
    
    while True:
        try:
            bot.polling(none_stop=True, skip_pending=True, timeout=60)
        except:
            time.sleep(5)
