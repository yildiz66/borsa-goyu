import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
from groq import Groq # Gemini yerine Groq geldi
from flask import Flask

warnings.filterwarnings("ignore")
app = Flask(__name__)
@app.route('/')
def home(): return "BorsaBot Groq Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROG_API_KEY = os.environ.get("GROG_API_KEY") # Railway'e bu isimle ekleyin
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
client = Groq(api_key=GROG_API_KEY)

# 215 Hisselik Liste
KATILIM_TUMU = ["ACSEL", "AHSGY", "AKFYE", "AKHAN", "AKSA", "AKYHO", "ALBRK", "ALCTL", "ALKA", "ALKIM", "ALKLC", "ALTNY", "ALVES", "ANGEN", "ARASE", "ARDYZ", "ARFYE", "ASELS", "ATAKP", "ATATP", "AVPGY", "AYEN", "BAHKM", "BAKAB", "BANVT", "BASGZ", "BEGYO", "BERA", "BESTE", "BIENY", "BIMAS", "BINBN", "BINHO", "BMSTL", "BNTAS", "BORSK", "BOSSA", "BRISA", "BRKSN", "BRLSM", "BSOKE", "BURCE", "BURVA", "CANTE", "CATES", "CELHA", "CEMTS", "CEMZY", "CIMSA", "CMBTN", "COSMO", "CVKMD", "CWENE", "DAPGM", "DARDL", "DCTTR", "DENGE", "DESPC", "DGATE", "DGNMO", "DMSAS", "DOFER", "DOFRB", "DOGUB", "DYOBY", "EBEBK", "EDATA", "EDIP", "EFOR", "EGEPO", "EGGUB", "EGPRO", "EKGYO", "EKSUN", "ELITE", "EMPAE", "ENJSA", "EREGL", "ESCOM", "EUPWR", "EYGYO", "FADE", "FONET", "FORMT", "FORTE", "FRMPL", "FZLGY", "GEDZA", "GENIL", "GENKM", "GENTS", "GEREL", "GESAN", "GLRMK", "GOKNR", "GOLTS", "GOODY", "GRSEL", "GRTHO", "GUBRF", "GUNDG", "HATSN", "HKTM", "HOROZ", "HRKET", "IDGYO", "IHEVA", "IHLAS", "IHLGM", "IHYAY", "IMASM", "INTEM", "ISDMR", "ISSEN", "IZFAS", "IZINV", "JANTS", "KARSN", "KATMR", "KBORU", "KCAER", "KIMMR", "KLSYN", "KNFRT", "KOCMT", "KONKA", "KONTR", "KONYA", "KOPOL", "KOTON", "KRDMA", "KRDMB", "KRDMD", "KRGYO", "KRONT", "KRPLS", "KRSTL", "KRVGD", "KTLEV", "KUTPO", "KUYAS", "KZBGY", "LKMNH", "LMKDC", "LOGO", "LXGYO", "MAGEN", "MAKIM", "MARBL", "MAVI", "MCARD", "MEDTR", "MEKAG", "MERCN", "MEYSU", "MNDRS", "MNDTR", "MOBTL", "MPARK", "NETAS", "NTGAZ", "OBAMS", "OBASE", "OFSYM", "ONCSM", "ORGE", "OSTIM", "OZRDN", "OZYSR", "PAGYO", "PARSN", "PASEU", "PENGD", "PENTA", "PETKM", "PETUN", "PKART", "PLTUR", "PNLSN", "POLHO", "QUAGR", "RGYAS", "RNPOL", "RODRG", "RUBNS", "SAFKR", "SAMAT", "SANEL", "SANKO", "SARKY", "SAYAS", "SEKUR", "SELEC", "SELVA", "SILVR", "SMART", "SMRTG", "SNGYO", "SNICA", "SOKE", "SRVGY", "SUNTK", "SURGY", "SUWEN", "TARKM", "TDGYO", "TEZOL", "TKNSA", "TMSN", "TOASO", "TRILC", "TSPOR", "TUCLK", "TUKAS", "TUPRS", "TURGG", "TUREX", "ULAS", "ULKER", "ULUFA", "ULUSE", "UNLU", "USAK", "VAKFN", "VANGD", "VBTYZ", "VERTU", "VESBE", "VESTL", "YEOTK", "YGGYO", "YGYO", "YUNSA", "YYLGD", "ZEDUR"]

def analiz_motoru(hisse, vade="1d"):
    try:
        f_t = f"{hisse.upper().strip()}.IS"
        df = yf.download(f_t, period="2y", interval=vade, progress=False, timeout=10)
        if df is None or df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        c_p, c_r = float(df.iloc[-1]["Close"]), float(df.iloc[-1]["RSI"])
        u_b = float(bb.iloc[-1, 2])
        pot = ((u_b - c_p) / c_p) * 100
        return {"ticker": hisse, "fiyat": c_p, "rsi": c_r, "pot": pot, "df": df}
    except: return None

def rapor_gonder(liste, vade, baslik):
    bot.send_message(MY_ID, f"🚀 {baslik} Analiz Başladı Emir Bey...\n(Groq Hız Motoru Aktif)")
    havuz = []
    for h in liste:
        res = analiz_motoru(h, vade)
        if res and 30 < res["rsi"] < 70: havuz.append(res)
        time.sleep(0.05)

    en_iyi = sorted(havuz, key=lambda x: x['pot'], reverse=True)[:5]
    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Uygun hisse bulunamadı.")
        return

    ai_data = []
    for t in en_iyi:
        plt.figure(figsize=(5, 3))
        plt.plot(t["df"]["Close"].tail(30).values, color='green', linewidth=2)
        plt.title(f"{t['ticker']} Trend")
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 *{t['ticker']}*\nFiyat: {round(t['fiyat'],2)} | RSI: {round(t['rsi'],1)}")
        plt.close()
        ai_data.append(f"{t['ticker']}(Fiyat:{round(t['fiyat'],1)}, RSI:{round(t['rsi'],0)})")

    # --- GROQ ANALİZ (SÜPER HIZLI) ---
    try:
        prompt = (f"Sen uzman bir borsa stratejistisin. {baslik} vade için seçilen 3 hisse: {', '.join(ai_data)}. "
                  "Her biri için net 'AL' veya 'BEKLE' kararı ver ve nedenini 1 cümleyle açıkla.")
        
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", # En güçlü ve dengeli model
        )
        
        bot.send_message(MY_ID, f"⚡ *Groq Analiz Kararı:*\n\n{chat_completion.choices[0].message.content}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(MY_ID, f"⚠️ Analiz Hatası: {str(e)[:50]}")

@bot.message_handler(commands=['gunluk'])
def cmd_1(m): rapor_gonder(KATILIM_TUMU, "1d", "GÜNLÜK")

@bot.message_handler(commands=['ikihaftalik'])
def cmd_2(m): rapor_gonder(KATILIM_TUMU, "1wk", "İKİ HAFTALIK")

@bot.message_handler(commands=['aylik'])
def cmd_3(m): rapor_gonder(KATILIM_TUMU, "1mo", "AYLIK")

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📈 Groq Destekli Terminal Aktif!\n/gunluk\n/ikihaftalik\n/aylik")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling()
