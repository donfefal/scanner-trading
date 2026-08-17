import streamlit as st
import requests
import pandas as pd
import ta
import time

st.set_page_config(page_title="Scanner Forex/Crypto + Telegram", page_icon="📊", layout="wide")

st.title("📊 Scanner Reversal Multi-Timeframe")
st.caption("Filtres : Sweep HTF + Structure W/M LTF + Retest Neckline + EMA 200/800 + RSI")

# Secrets
API_KEY = st.secrets.get("TWELVEDATA_API_KEY", "")
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

st.sidebar.header("⚙️ Configuration")
HTF = st.sidebar.selectbox("Timeframe Supérieur (HTF)", ["1day", "4h", "1week", "1month"])

TIMEFRAME_MAP = {
    "1month": "1day",
    "1week": "4h",
    "1day": "1h",
    "4h": "15min"
}

ALL_PAIRS = [
    "XAU/USD", "BTC/USD",
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/CAD", "EUR/AUD", "EUR/NZD",
    "GBP/JPY", "GBP/CHF", "GBP/CAD", "GBP/AUD", "GBP/NZD",
    "AUD/JPY", "AUD/NZD", "AUD/CAD", "AUD/CHF",
    "NZD/JPY", "NZD/CAD", "NZD/CHF",
    "CAD/JPY", "CAD/CHF", "CHF/JPY"
]

SYMBOLS = st.sidebar.multiselect("Paires analysées", ALL_PAIRS, default=ALL_PAIRS)

def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        st.error(f"Erreur d'envoi Telegram : {e}")

def fetch_data(symbol, interval):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=300&apikey={API_KEY}"
    try:
        res = requests.get(url).json()
        if "values" not in res: 
            return pd.DataFrame()
        df = pd.DataFrame(res["values"])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        for c in ['open', 'high', 'low', 'close']: 
            df[c] = df[c].astype(float)
        return df
    except: 
        return pd.DataFrame()

def check_pattern_w_m(df_ltf):
    """
    Détection de structure W (Double Bottom) ou M (Double Top) et du retest de la ligne de cou (Neckline)
    """
    if len(df_ltf) < 20:
        return None, None

    recent = df_ltf.tail(20).reset_index(drop=True)
    current_price = recent['close'].iloc[-1]
    
    # Recherche des creux et sommets locaux
    min1 = recent['low'].iloc[:-10].min()
    min2 = recent['low'].iloc[-10:].min()
    max_between_mins = recent['high'].iloc[recent['low'].idxmin():].max() if not recent['low'].empty else None

    max1 = recent['high'].iloc[:-10].max()
    max2 = recent['high'].iloc[-10:].max()
    min_between_maxs = recent['low'].iloc[recent['high'].idxmax():].min() if not recent['high'].empty else None

    # Condition W (Double Bottom + Retest Ligne de cou)
    w_shape = abs(min1 - min2) / min1 < 0.003  # Creux à un niveau similaire
    if w_shape and max_between_mins:
        neckline = max_between_mins
        # Retest de la ligne de cou : le prix est proche ou rebondit sur la ligne de cou après l'avoir cassée
        retest_w = current_price >= (neckline * 0.998) and current_price <= (neckline * 1.003)
        if retest_w:
            return "W (Double Bottom)", neckline

    # Condition M (Double Top + Retest Ligne de cou)
    m_shape = abs(max1 - max2) / max1 < 0.003  # Sommets à un niveau similaire
    if m_shape and min_between_maxs:
        neckline = min_between_maxs
        retest_m = current_price <= (neckline * 1.002) and current_price >= (neckline * 0.997)
        if retest_m:
            return "M (Double Top)", neckline

    return None, None

def analyze(symbol):
    ltf = TIMEFRAME_MAP.get(HTF, "15min")
    df_htf = fetch_data(symbol, HTF)
    df_ltf = fetch_data(symbol, ltf)

    if df_htf.empty or df_ltf.empty or len(df_htf) < 3:
        return {"Paire": symbol, "Signal": "NEUTRE", "Prix": "-", "Pattern LTF": "-", "Raison": "Données manquantes"}

    # 1. Sweep HTF
    b_prev, b_curr = df_htf.iloc[-2], df_htf.iloc[-1]
    prev_mid = (b_prev['open'] + b_prev['close']) / 2
    
    swept_low = b_curr['low'] < b_prev['low'] and b_curr['close'] > prev_mid and b_curr['close'] > b_curr['open']
    swept_high = b_curr['high'] > b_prev['high'] and b_curr['close'] < prev_mid and b_curr['close'] < b_curr['open']

    # 2. Indicators LTF
    df_ltf['EMA200'] = ta.trend.ema_indicator(df_ltf['close'], window=200)
    df_ltf['EMA800'] = ta.trend.ema_indicator(df_ltf['close'], window=800)
    df_ltf['RSI'] = ta.momentum.rsi(df_ltf['close'], window=14)
    df_ltf['Base'] = ta.trend.sma_indicator(df_ltf['RSI'], window=14)

    price = df_ltf['close'].iloc[-1]
    e200, e800 = df_ltf['EMA200'].iloc[-1], df_ltf['EMA800'].iloc[-1]
    rsi_c, base_c = df_ltf['RSI'].iloc[-1], df_ltf['Base'].iloc[-1]
    rsi_p, base_p = df_ltf['RSI'].iloc[-2], df_ltf['Base'].iloc[-2]

    ema_bull = price > e200 and price > e800
    ema_bear = price < e200 and price < e800

    rsi_buy = (rsi_p <= base_p and rsi_c >= base_c) or ((base_c - rsi_c) <= 2.5 and rsi_c < base_c)
    rsi_sell = (rsi_p >= base_p and rsi_c <= base_c) or ((rsi_c - base_c) <= 2.5 and rsi_c > base_c)

    # 3. Structure W/M & Retest
    pattern, neckline = check_pattern_w_m(df_ltf)

    # Signal ACHAT : Sweep Low HTF + Pattern W LTF + Tendance EMA OK + RSI OK
    if swept_low and pattern == "W (Double Bottom)" and ema_bull and rsi_buy:
        return {
            "Paire": symbol, "Signal": "🚀 ACHAT", "Prix": price, 
            "Pattern LTF": f"W Retest ({neckline:.5f})", "RSI": f"{rsi_c:.1f}/{base_c:.1f}", 
            "Raison": f"Sweep Low {HTF} + Retest W {ltf}"
        }
    
    # Signal VENTE : Sweep High HTF + Pattern M LTF + Tendance EMA OK + RSI OK
    elif swept_high and pattern == "M (Double Top)" and ema_bear and rsi_sell:
        return {
            "Paire": symbol, "Signal": "🔻 VENTE", "Prix": price, 
            "Pattern LTF": f"M Retest ({neckline:.5f})", "RSI": f"{rsi_c:.1f}/{base_c:.1f}", 
            "Raison": f"Sweep High {HTF} + Retest M {ltf}"
        }

    return {"Paire": symbol, "Signal": "NEUTRE", "Prix": price, "Pattern LTF": pattern if pattern else "-", "RSI": f"{rsi_c:.1f}/{base_c:.1f}", "Raison": "Conditions non alignées"}

if API_KEY:
    if st.button("🔄 Lancer le Scan & Envoyer sur Telegram"):
        st.cache_data.clear()
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        alerts = []
        total = len(SYMBOLS)
        
        for idx, symbol in enumerate(SYMBOLS):
            status_text.text(f"Analyse en cours ({HTF}) : {symbol} ({idx+1}/{total})...")
            res = analyze(symbol)
            results.append(res)
            
            if res["Signal"] in ["🚀 ACHAT", "🔻 VENTE"]:
                alerts.append(f"🔔 *SIGNAL {res['Signal']}*\n• Paire: `{symbol}`\n• Prix: `{res['Prix']}`\n• Pattern: `{res['Pattern LTF']}`\n• Raison: {res['Raison']}")
            
            progress_bar.progress((idx + 1) / total)
            time.sleep(0.3)
            
        status_text.text("Analyse terminée !")
        
        # Envoi de la notification globale Telegram
        if alerts:
            msg = f"⚡ *OPPORTUNITÉS SCANNER ({HTF})* ⚡\n\n" + "\n\n".join(alerts)
            send_telegram_alert(msg)
            st.success(f"{len(alerts)} alerte(s) envoyée(s) sur Telegram !")
        else:
            send_telegram_alert(f"ℹ️ Scan {HTF} terminé. Aucune opportunité validée pour le moment.")
            st.info("Scan terminé. Aucune alerte à envoyer.")
            
        st.dataframe(pd.DataFrame(results), use_container_width=True)
else:
    st.warning("Insère ta clé Twelve Data dans les secrets pour commencer.")
