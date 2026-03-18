import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
from groq import Groq
from flask import Flask

warnings.filterwarnings("ignore")
app = Flask(__name__)

# --- AYARLAR ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROG_API_KEY = os.environ.get("GROG_API_KEY") 
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
client = Groq(api_key=GROG_API_KEY)

# --- LİSTE ---
KATILIM_TUMU = ["ACSEL", "AHSGY", "AKFYE", "AKHAN", "AKSA", "AKYHO", "ALBRK", "ALCTL", "ALKA", "ALKIM", "ALKLC", "ALTNY", "ALVES", "ANGEN", "ARASE", "ARDYZ", "ARFYE", "ASELS", "ATAKP", "ATATP", "AVPGY", "AYEN", "BAHKM", "BAKAB", "BANVT", "BASGZ", "BEGYO", "BERA", "BESTE", "BIENY", "BIMAS", "BINBN", "BINHO", "BMSTL", "BNTAS", "BORSK", "BOSSA", "BRISA", "BRKSN", "BRLSM", "BSOKE", "BURCE", "BURVA", "CANTE", "CATES", "CELHA", "CEMTS", "CEMZY", "CIMSA", "CMBTN", "COSMO", "CVKMD", "CWENE", "DAPGM", "DARDL", "DCTTR", "DENGE", "DESPC", "DGATE", "DGNMO", "DMSAS", "DOFER", "DOFRB", "DOGUB", "DYOBY", "EBEBK", "EDATA", "EDIP", "EFOR", "EGEPO", "EGGUB", "EGPRO", "EKGYO", "EKSUN", "ELITE", "EMPAE", "ENJSA", "EREGL", "ESCOM", "EUPWR", "EYGYO", "FADE", "FONET", "FORMT", "FORTE", "FRMPL", "FZLGY", "GEDZA", "GENIL", "GENKM", "GENTS", "GEREL", "GESAN", "GLRMK", "GOKNR", "GOLTS", "GOODY", "GRSEL", "GRTHO", "GUBRF", "GUNDG", "HATSN", "HKTM", "HOROZ", "HRKET", "IDGYO", "IHEVA", "IHLAS", "IHLGM", "IHYAY", "IMASM", "INTEM", "ISDMR", "ISSEN", "IZFAS", "IZINV", "JANTS", "KARSN", "KATMR", "KBORU", "KCAER", "KIMMR", "KLSYN", "KNFRT", "KOCMT", "KONKA", "KONTR", "KONYA", "KOPOL", "KOTON", "KRDMA", "KRDMB", "KRDMD", "KRGYO", "KRONT", "KRPLS", "KRSTL", "KRVGD", "KTLEV", "KUTPO", "KUYAS", "KZBGY", "LKMNH", "LMKDC", "LOGO", "LXGYO", "MAGEN", "MAKIM", "MARBL", "MAVI", "MCARD", "MEDTR", "MEKAG", "MERCN", "MEYSU", "MNDRS", "MNDTR", "MOBTL", "MPARK", "NETAS", "NTGAZ", "OBAMS", "OBASE", "OFSYM", "ONCSM", "ORGE", "OSTIM", "OZRDN", "OZYSR", "PAGYO", "PARSN", "PASEU", "PENGD", "PENTA", "PETKM", "PETUN", "PKART", "PLTUR", "PNLSN", "POLHO", "QUAGR", "RGYAS", "RNPOL", "RODRG", "RUBNS", "SAFKR", "SAMAT", "SANEL", "SANKO", "SARKY", "SAYAS", "SEKUR", "SELEC", "SELVA", "SILVR", "SMART", "SMRTG", "SNGYO", "SNICA", "SOKE", "SRVGY", "SUNTK", "SURGY", "SUWEN", "TARKM", "TDGYO", "TEZOL", "TKNSA", "TMSN", "TOASO", "TRILC", "TSPOR", "TUCLK", "TUKAS", "TUPRS", "TURGG", "TUREX", "ULAS", "ULKER", "ULUFA", "ULUSE", "UNLU", "USAK", "VAKFN", "VANGD", "VBTYZ", "VERTU", "VESBE", "VESTL", "YEOTK", "YGGYO", "YGYO", "YUNSA", "YYLGD", "ZEDUR"]

@app.route('/')
def home(): return "Sistem Aktif", 200

# --- ANALİZ MOTORU ---
def analiz_motoru(hisse, vade="1d"):
    try:
        f_t = f"{hisse.upper().strip()}.IS"
        df = yf.download(f_t, period="2y", interval=vade, progress=False, timeout=10)
        if df is None or df.empty or len(df) < 201: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["EMA9"] = ta.ema(df["Close"], length=9)
        df["EMA21"] = ta.ema(df["Close"], length=21)
        df["SMA200"] = ta.sma(df["Close"], length=200)
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        last = df.iloc[-1]
        c_p = float(last["Close"])
        u_b = float(bb.iloc[-1, 2])
        success_rate = (df[df["Close"] > df["SMA200"]].pct_change()["Close"] > 0).mean() * 100

        return {
            "ticker": hisse, "fiyat": c_p, "rsi": float(last["RSI"]), 
            "pot": ((u_b - c_p) / c_p) * 100, "u_b": u_b, "s200": float(last["SMA200"]),
            "ema9": float(last["EMA9"]), "ema21": float(last["EMA21"]),
            "success": round(success_rate, 1), "df": df
        }
    except: return None

# --- AI STRATEJİ ---
def ai_sinyal_uret(res, vade):
    try:
        if vade == "1d":
            p = (f"{res['ticker']} {res['fiyat']} TL. Hedef {round(res['u_b'],2)} TL (%{round(res['pot'],1)}). "
                 f"Stop {round(res['ema21'],2)} TL. Sadece 'Şuradan al, şuradan sat, kâr oranı şu' şeklinde net emir ver.")
        else:
            p = f"{res['ticker']} hissesi için {round(res['fiyat'],2)} fiyatıyla teknik analiz özeti yaz."
        
        comp = client.chat.completions.create(messages=[{"role":"user","content":p}], model="llama-3.3-70b-versatile")
        return comp.choices[0].message.content.replace("*", "").replace("_", "").replace("#", "")
    except: return "Analiz yüklenemedi."

# --- RAPOR GÖNDERME ---
def rapor_gonder(liste, vade, baslik):
    bot.send_message(MY_ID, f"🚀 {baslik} ANALİZ BAŞLADI...")
    havuz = []
    for h in liste:
        res = analiz_motoru(h, vade)
        if res and res["fiyat"] > res["s200"] and 35 < res["rsi"] < 65:
            havuz.append(res)
        time.sleep(0.04)

    en_iyi = sorted(havuz, key=lambda x: x['pot'], reverse=True)[:3]
    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Uygun hisse bulunamadı."); return

    for t in en_iyi:
        # Grafik Çizimi
        fig, ax = plt.subplots(figsize=(10, 5))
        df_p = t["df"].tail(50)
        ax.plot(df_p['Close'].values, color='#2ecc71', label="Fiyat")
        ax.plot(df_p['EMA9'].values, color='#f1c40f', linestyle='--', label="EMA9")
        ax.plot(df_p['SMA200'].values, color='#e67e22', label="SMA200")
        ax.legend(); ax.grid(True, alpha=0.1)
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0); plt.close()
        
        # AI Stratejisi
        strateji = ai_sinyal_uret(t, vade)
        
        # Senin istediğin o meşhur format (Caption içine)
        caption = (f"💎 #{t['ticker']} ({baslik})\n"
                   f"💰 Fiyat: {round(t['fiyat'],2)} TL\n"
                   f"🎯 Hedef: {round(t['u_b'],2)} TL (%{round(t['pot'],1)})\n"
                   f"📈 Başarı: %{t['success']}\n"
                   f"📊 RSI: {round(t['rsi'],1)}\n\n"
                   f"🧠 AI: {strateji}")
        
        bot.send_photo(MY_ID, buf, caption=caption)
        time.sleep(1)

# --- KOMUTLAR ---
@bot.message_handler(commands=['gunluk'])
def cmd_1(m): rapor_gonder(KATILIM_TUMU, "1d", "GÜNLÜK")

@bot.message_handler(commands=['ikihaftalik'])
def cmd_2(m): rapor_gonder(KATILIM_TUMU, "1wk", "İKİ HAFTALIK")

@bot.message_handler(commands=['aylik'])
def cmd_3(m): rapor_gonder(KATILIM_TUMU, "1mo", "AYLIK")

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📈 Terminal Aktif!\n/gunluk\n/ikihaftalik\n/aylik")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling()
