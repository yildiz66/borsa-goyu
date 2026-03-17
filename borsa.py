import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, schedule
import pandas as pd
import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
from flask import Flask

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

# Katılım Endeksine Uygun Hisse Listesi
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

# --- 2. ANALİZ VE AI MOTORU ---

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        if not (ticker.endswith(".IS") or "=" in ticker): ticker += ".IS"
        p = "6mo" if donem == "1d" else "2y" if donem == "1wk" else "5y"
        
        df = yf.download(ticker, period=p, interval=donem, progress=False, threads=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        last = df.iloc[-1]
        return {
            "ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]),
            "hedef": float(bb.iloc[-1, 2]), "df": df
        }
    except: return None

def gemini_strateji_al(hisse_listesi, vade_adi):
    try:
        ozet = "".join([f"{h['ticker']}: Fiyat {h['fiyat']}, RSI {round(h['rsi'],1)}. " for h in hisse_listesi])
        prompt = (f"Borsa uzmanı olarak bu hisseleri {vade_adi} periyotta kıyasla: {ozet}. "
                  f"Hacim ve haberleri düşünerek Emir Bey için en iyi 1 veya 2 tanesini seç. "
                  f"Nedenini kısa açıkla ve net hedef ver.")
        return ai_model.generate_content(prompt).text
    except: return "AI yorumu şu an alınamıyor."

# --- 3. RAPORLAMA VE KLAVYE ---

def ana_menu():
    m = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    m.add("Günlük Katılım Fırsat", "İki Haftalık Katılım Fırsat")
    m.add("Aylık Katılım Fırsat", "Tüm Katılım")
    return m

def rapor_hazirla_ve_gonder(vade_kod="1d", vade_adi="GÜNLÜK"):
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        if res and 48 < res["rsi"] < 68: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['rsi'], reverse=True)[:5]
    if not en_iyi_5: return

    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        mesaj = f"💎 *{vade_adi}:* {t['ticker']}\n🛒 Fiyat: `{t['fiyat']}` | 🎯 Hedef: `{round(t['hedef'], 2)}` (%{pot})"
        plt.figure(figsize=(5, 2.5)); plt.plot(t["df"]["Close"].tail(30).values, color="green"); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")
        time.sleep(1)

    ai_secim = gemini_strateji_al(en_iyi_5, vade_adi)
    bot.send_message(MY_ID, f"⭐ *EMİR BEY İÇİN ÖZEL SEÇİM*\n\n{ai_secim}", parse_mode="Markdown")

# --- 4. KOMUT YÖNETİMİ ---

@bot.message_handler(func=lambda m: True)
def handle_requests(message):
    txt = message.text.upper().strip()
    cid = message.chat.id
    
    if txt.startswith("/"):
        if "START" in txt:
            bot.send_message(cid, "📈 Borsabot Terminali Aktif.", reply_markup=ana_menu())
        return

    if "GÜNLÜK" in txt: rapor_hazirla_ve_gonder("1d", "GÜNLÜK")
    elif "İKİ HAFTALIK" in txt: rapor_hazirla_ve_gonder("1wk", "İKİ HAFTALIK")
    elif "AYLIK" in txt: rapor_hazirla_ve_gonder("1mo", "AYLIK")
    elif "TÜM KATILIM" in txt: rapor_hazirla_ve_gonder("1d", "TAM LİSTE")
    elif 2 <= len(txt) <= 6 and txt.isalpha():
        res = analiz_motoru(txt)
        if res:
            ai_n = gemini_strateji_al([res], "ÖZEL")
            bot.send_message(cid, f"📍 *{res['ticker']}*\nFiyat: {res['fiyat']}\n🤖 AI: {ai_n}", parse_mode="Markdown")

# --- 5. ZAMANLAYICI VE ÇALIŞTIRICI ---

def scheduler_loop():
    gunler = [schedule.every().monday, schedule.every().tuesday, schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]
    for gun in gunler:
        gun.at("09:55").do(lambda: rapor_hazirla_ve_gonder("1d", "SABAH AÇILIŞ"))
        gun.at("17:50").do(lambda: rapor_hazirla_ve_gonder("1d", "AKŞAM KAPANIŞ"))
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    bot.infinity_polling(skip_pending=True)
