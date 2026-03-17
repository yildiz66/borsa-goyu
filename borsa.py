import os, telebot, yfinance as yf, ta, pandas as pd
from google import genai
from telebot import types
import warnings

warnings.filterwarnings("ignore")

# --- 1. EN GÜNCEL AI YAPILANDIRMASI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

# --- 2. VERİ TEMİZLEME VE LİSTELER ---
def get_clean_list():
    try:
        df = pd.read_csv("hisse_endeks_katilim_ds.csv", sep=';')
        raw_list = df.iloc[:,0].dropna().tolist()
        clean_list = []
        # Başlıkları ve hatalı kodları ayıkla
        for k in raw_list:
            k_str = str(k).strip().upper()
            if k_str in ["CODE", "SYMBOL", "CONSTITUENT", "BILESEN KODU"]: continue
            if len(k_str) > 2:
                clean_list.append(k_str.split('.')[0] + ".IS")
        return list(set(clean_list))
    except:
        return ["THYAO.IS", "BIMAS.IS", "ASELS.IS"]

LİSTELER = {
    "BIST30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "BRSAN.IS", "EKGYO.IS", "ENJSA.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "GUBRF.IS", "HEKTS.IS", "KCHOL.IS", "KONTR.IS", "KOZAL.IS", "KRDMD.IS", "MGROS.IS", "ODAS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS", "SISE.IS", "TAVHL.IS", "THYAO.IS", "TOASO.IS", "TCELL.IS", "TUPRS.IS", "YKBNK.IS"],
    "KATILIM": get_clean_list()
}

# --- 3. NOKTA ATIŞI ANALİZ MOTORU ---
def nokta_atisi_engine(ticker, periyot="1d", skor_esigi=3):
    try:
        df = yf.download(ticker, period="1y", interval=periyot, progress=False)
        if df.empty or len(df) < 30: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        # Teknik Metrikler
        c = df["Close"]
        rsi = ta.momentum.RSIIndicator(c).rsi().iloc[-1]
        ema9 = ta.trend.EMAIndicator(c, window=9).ema_indicator().iloc[-1]
        hacim_ort = df["Volume"].rolling(window=10).mean().iloc[-1]
        son_hacim = df["Volume"].iloc[-1]
        fiyat = float(c.iloc[-1])

        # Skorlama
        skor = 0
        if fiyat > ema9: skor += 1
        if 48 < rsi < 68: skor += 1
        if son_hacim > (hacim_ort * 1.15): skor += 1

        if skor >= skor_esigi:
            prompt = f"{ticker} için {periyot} periyodunda profesyonel analiz yap. Fiyat:{fiyat}, RSI:{rsi}. Hedef ve stop belirt."
            response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return {"ticker": ticker, "fiyat": fiyat, "skor": skor, "ai": response.text, "rsi": rsi}
    except: return None

# --- 4. BAĞIMSIZ MENÜ VE KOMUTLAR ---
@bot.message_handler(commands=['start'])
def start(message):
    m = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    m.add("📈 BIST 100", "🏆 BIST 30", "🏢 BIST ANA PAZAR")
    m.add("🔥 BIST 100 FIRSAT", "⭐ BIST 30 FIRSAT", "💎 BIST ANA FIRSAT")
    m.add("🕌 KATILIM TÜM", "🎯 KATILIM FIRSAT GÜNLÜK")
    m.add("⏳ KATILIM FIRSAT 2 HAFTALIK", "🗓️ KATILIM FIRSAT AYLIK")
    bot.send_message(message.chat.id, "🚀 **Yapay Zeka Destekli Analiz Sistemi Aktif!**\nLütfen bir seçenek belirle:", reply_markup=m)

@bot.message_handler(func=lambda msg: True)
def handle_requests(message):
    secim = message.text
    bot.send_message(message.chat.id, f"🔍 `{secim}` için derin analiz başlatıldı...")
    
    target_list = []
    periyot = "1d"
    esik = 3

    # Bağımsız Mantık Kurgusu
    if "BIST 30 FIRSAT" in secim:
        target_list = LİSTELER["BIST30"]
    elif "KATILIM FIRSAT GÜNLÜK" in secim:
        target_list = LİSTELER["KATILIM"]
    elif "2 HAFTALIK" in secim:
        target_list = LİSTELER["KATILIM"]; periyot = "1wk"; esik = 2
    elif "AYLIK" in secim:
        target_list = LİSTELER["KATILIM"]; periyot = "1mo"; esik = 2
    
    found = 0
    for t in target_list:
        res = nokta_atisi_engine(t, periyot, esik)
        if res:
            found += 1
            msg = f"✅ **{res['ticker']}** (%{res['skor']*25} Güç)\n💰 Fiyat: {round(res['fiyat'],2)}\n📊 RSI: {round(res['rsi'],1)}\n\n{res['ai']}"
            bot.send_message(message.chat.id, msg)
    
    if found == 0:
        bot.send_message(message.chat.id, "⚖️ Kriterlere uyan nokta atışı bir fırsat şu an bulunamadı.")

bot.polling()
