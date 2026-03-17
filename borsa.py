import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, schedule
import pandas as pd
import matplotlib
# Hatayı önlemek için matplotlib ayarını en başta yapıyoruz
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
from flask import Flask

# Gereksiz uyarıları kapat
warnings.filterwarnings("ignore")

app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

# API Bilgileri
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# Buraya tam listenizi yapıştırın
KATILIM_LISTESI = ["AKSA", "ALTNY", "ASELS", "BIMAS", "THYAO", "TUPRS", "SASA", "EREGL"]

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
    except Exception as e:
        print(f"Hata ({hisse}): {e}")
        return None

def gemini_strateji_al(hisse_listesi, vade_adi):
    try:
        ozet = "".join([f"{h['ticker']}: Fiyat {h['fiyat']}, RSI {round(h['rsi'],1)}. " for h in hisse_listesi])
        prompt = (f"Bir borsa stratejisti olarak şu hisseleri {vade_adi} periyotta kıyasla: {ozet}. "
                  f"Hacim artışını ve haberleri düşünerek Emir Bey için en iyi 1 veya 2 tanesini seç. "
                  f"Nedenini kısa açıkla ve net bir hedef ver.")
        response = ai_model.generate_content(prompt)
        return response.text
    except: return "AI seçimi şu an yapılamadı."

def rapor_hazirla_ve_gonder(vade_kod="1d", vade_adi="GÜNLÜK"):
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        # RSI 48-68 arası teknik olarak "yolun başında" demektir
        if res and 48 < res["rsi"] < 68: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['rsi'], reverse=True)[:5]
    if not en_iyi_5:
        bot.send_message(MY_ID, f"😕 {vade_adi} için kriterlere uygun hisse bulunamadı.")
        return

    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        mesaj = (f"💎 *{vade_adi} ANALİZ:* {t['ticker']}\n"
                 f"🛒 *Fiyat:* `{t['fiyat']}` | 🎯 *Hedef:* `{round(t['hedef'], 2)}` (%{pot})")
        
        plt.figure(figsize=(5, 2.5)); plt.plot(t["df"]["Close"].tail(30).values, color="green"); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")
        time.sleep(1)

    ai_secim = gemini_strateji_al(en_iyi_5, vade_adi)
    bot.send_message(MY_ID, f"⭐ *EMİR BEY İÇİN ÖZEL SEÇİM*\n\n{ai_secim}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def manual_handler(message):
    txt = message.text.upper().strip()
    if "FIRSAT" in txt:
        bot.send_message(message.chat.id, "🔍 Tarama başlatıldı...")
        rapor_hazirla_ve_gonder("1d", "MANUEL TARAMA")
    elif 2 <= len(txt) <= 6:
        res = analiz_motoru(txt)
        if res:
            ai_notu = gemini_strateji_al([res], "ÖZEL")
            bot.send_message(message.chat.id, f"📍 *{res['ticker']}*\nFiyat: {res['fiyat']}\n🤖 AI: {ai_notu}", parse_mode="Markdown")

def scheduler_loop():
    # 'monday.to.friday' hatasını günleri tek tek ekleyerek çözüyoruz
    gunler = [schedule.every().monday, schedule.every().tuesday, 
              schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]
    
    for gun in gunler:
        gun.at("09:55").do(lambda: rapor_hazirla_ve_gonder("1d", "SABAH AÇILIŞ"))
        gun.at("17:50").do(lambda: rapor_hazirla_ve_gonder("1d", "AKŞAM KAPANIŞ"))
    
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    # Zamanlayıcıyı başlat
    threading.Thread(target=scheduler_loop, daemon=True).start()
    # Flask sunucusunu Railway portuna bağla
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    # Botu çalıştır
    print("🚀 Sistem Railway üzerinde başarıyla başlatıldı.")
    bot.infinity_polling(timeout=20)
