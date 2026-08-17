import streamlit as st
import requests
import pandas as pd
import ta
import time

st.set_page_config(page_title="Scanner Multi-Séquences MTF", page_icon="📊", layout="wide")

st.title("📊 Scanner Reversal - Alignement HTF, TDI & Continuation")
st.caption("Cascade : Clôture HTF -> Structure M/W & TDI -> Retest OU Bougie de Continuation")

# Secrets Streamlit Cloud
API_KEY = st.secrets.get("TWELVEDATA_API_KEY", "")
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

st.sidebar.header("⚙️ Configuration HTF")
HTF = st.sidebar.selectbox("Clôture HTF (Contexte)", ["1month", "1week", "1day", "4h"])

# Mapping exact de la chronologie TDI
MTF_MAP = {
    "1month": {"struct_tdi": "1day",  "entry": "1h"},
    "1week":  {"struct_tdi": "4h",    "entry": "15min"},
    "1day":   {"struct_tdi": "1h",    "entry": "15min"},
    "4h":     {"struct_tdi": "15min", "entry": "5min"}
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

def analyze_sequences(symbol):
    tf_struct = MTF_MAP[HTF]["struct_tdi"]
    tf_entry = MTF_MAP[HTF]["entry"]
    
    df_htf = fetch_data(symbol, HTF)
    df_struct = fetch_data(symbol, tf_struct)
    df_entry = fetch_data(symbol, tf_entry)

    if df_htf.empty or df_struct.empty or df_entry.empty:
        return None

    # Indicateurs TDI calculés strictement sur le Timeframe de Structure (D1, H4, H1 ou M15)
    df_struct['RSI'] = ta.momentum.rsi(df_struct['close'], window=14)
    df_struct['Base'] = ta.trend.sma_indicator(df_struct['RSI'], window=14)
    
    # 1. Clôture Bougie HTF / Sweep
    b_prev, b_curr = df_htf.iloc[-2], df_htf.iloc[-1]
    prev_mid = (b_prev['open'] + b_prev['close']) / 2
    swept_low = b_curr['low'] < b_prev['low'] and b_curr['close'] > prev_mid
    swept_high = b_curr['high'] > b_prev['high'] and b_curr['close'] < prev_mid

    step1 = f"✅ Clôture/Sweep Bas ({HTF})" if swept_low else (f"✅ Clôture/Sweep Haut ({HTF})" if swept_high else "❌ Non")
    bias = "ACHAT" if swept_low else ("VENTE" if swept_high else "NEUTRE")

    # 2. Structure M ou W sur le Timeframe de Structure
    recent_s = df_struct.tail(30).reset_index(drop=True)
    price = df_entry['close'].iloc[-1]
    
    max1_idx, max2_idx = recent_s['high'].iloc[:-12].idxmax(), recent_s['high'].iloc[-12:].idxmax()
    max1, max2 = recent_s['high'].iloc[max1_idx], recent_s['high'].iloc[max2_idx]
    min_between = recent_s['low'].iloc[max1_idx:max2_idx+1].min() if max1_idx < max2_idx else None

    min1_idx, min2_idx = recent_s['low'].iloc[:-12].idxmin(), recent_s['low'].iloc[-12:].idxmin()
    min1, min2 = recent_s['low'].iloc[min1_idx], recent_s['low'].iloc[min2_idx]
    max_between = recent_s['high'].iloc[min1_idx:min2_idx+1].max() if min1_idx < min2_idx else None

    is_m = (abs(max1 - max2) / max1 < 0.004) and min_between is not None
    is_w = (abs(min1 - min2) / min1 < 0.004) and max_between is not None

    step2 = f"M sur {tf_struct}" if is_m else (f"W sur {tf_struct}" if is_w else "❌ Non")

    # 3. TDI : Traversée du RSI sur la Baseline (par le bas pour W, par le haut pour M)
    rsi_c, base_c = df_struct['RSI'].iloc[-1], df_struct['Base'].iloc[-1]
    rsi_p, base_p = df_struct['RSI'].iloc[-2], df_struct['Base'].iloc[-2]
    
    rsi_cross_up = (rsi_p <= base_p and rsi_c > base_c)
    rsi_cross_down = (rsi_p >= base_p and rsi_c < base_c)
    step3 = f"✅ RSI traverse Baseline HAUSSE ({tf_struct})" if rsi_cross_up else (f"✅ RSI traverse Baseline BAISSE ({tf_struct})" if rsi_cross_down else f"🔄 Proche ({rsi_c:.1f}/{base_c:.1f})")

    # 4 & 5. Retest OU Bougie de Continuation (Impulsion Sèche)
    neckline = min_between if is_m else (max_between if is_w else None)
    step4 = "❌ Non"
    step5 = "❌ Non"

    if neckline:
        dist = abs(price - neckline) / neckline
        
        # Caractéristiques de la dernière bougie d'entrée LTF
        c_open = df_entry['open'].iloc[-1]
        c_close = df_entry['close'].iloc[-1]
        c_high = df_entry['high'].iloc[-1]
        c_low = df_entry['low'].iloc[-1]
        body_ratio = abs(c_close - c_open) / (c_high - c_low) if (c_high - c_low) > 0 else 0

        # Scénario A : Retest classique de la neckline
        if dist <= 0.002:
            step4 = f"✅ Retest Neckline ({neckline:.5f})"
            step5 = f"✅ Rejet mèche actif sur {tf_entry}"
            
        # Scénario B : Bougie de continuation / Breakout d'impulsion sans retest
        elif is_w and price > neckline and c_close > c_open and body_ratio > 0.6:
            step4 = f"⚡ CONTINUATION HAUSSIÈRE (Cassure sèche {neckline:.5f})"
            step5 = f"🔥 Pas de retest : Bougie d'impulsion acheteuse ({tf_entry})"
            
        elif is_m and price < neckline and c_close < c_open and body_ratio > 0.6:
            step4 = f"⚡ CONTINUATION BAISSIÈRE (Cassure sèche {neckline:.5f})"
            step5 = f"🔥 Pas de retest : Bougie d'impulsion vendeuse ({tf_entry})"
            
        elif price < neckline and is_m:
            step4 = f"⏳ Neckline Cassée (Attente Retest {tf_entry})"
        elif price > neckline and is_w:
            step4 = f"⏳ Neckline Cassée (Attente Retest {tf_entry})"

    # 6. TDI Divergence / Filtre 2ème Sommet-Creux dans Baseline
    step6 = "❌ Standard"
    if is_m and max2_idx < len(recent_s):
        if rsi_c <= base_c + 2:
            step6 = f"🔥 2ème Top filtré sous/dans Baseline TDI ({tf_struct})"

    elif is_w and min2_idx < len(recent_s):
        if rsi_c >= base_c - 2:
            step6 = f"🔥 2ème Bottom filtré sur/dans Baseline TDI ({tf_struct})"

    score = sum([step1 != "❌ Non", is_m or is_w, "✅" in step3, "✅" in step4 or "⚡" in step4, "🔥" in step6])

    return {
        "Paire": symbol,
        "Score": score,
        "Biais": bias,
        "S1_Sweep": f"{step1}",
        "S2_Pattern": f"{step2}",
        "S3_RSI_TDI": f"{step3}",
        "S4_Retest": f"{step4}",
        "S5_NecklineTest": f"{step5}",
        "S6_TDI": step6,
        "Prix": price
    }

if API_KEY:
    if st.button("🔄 Lancer le Scan Chronologique TDI"):
        st.cache_data.clear()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        telegram_alerts = []
        total = len(SYMBOLS)
        
        tf_struct = MTF_MAP[HTF]["struct_tdi"]
        tf_entry = MTF_MAP[HTF]["entry"]

        for idx, symbol in enumerate(SYMBOLS):
            status_text.text(f"Analyse [{HTF} Clôturé -> TDI & Structure sur {tf_struct}] : {symbol} ({idx+1}/{total})...")
            res = analyze_sequences(symbol)
            if res:
                results.append(res)
                # Alerte Telegram envoyée si au moins la structure W/M est active
                if res["S2_Pattern"] != "❌ Non":
                    msg = (
                        f"📊 *ANALYSE CHRONOLOGIQUE TDI : {symbol}*\n"
                        f"🎯 Biais : *{res['Biais']}* | Prix : `{res['Prix']}`\n\n"
                        f"1️⃣ Bougie HTF : {res['S1_Sweep']}\n"
                        f"2️⃣ Structure : {res['S2_Pattern']}\n"
                        f"3️⃣ Signal TDI : {res['S3_RSI_TDI']}\n"
                        f"4️⃣ Zone Retest / Impulsion : {res['S4_Retest']}\n"
                        f"5️⃣ Action du Prix : {res['S5_NecklineTest']}\n"
                        f"6️⃣ Filtre TDI : {res['S6_TDI']}\n"
                    )
                    telegram_alerts.append(msg)
            
            progress_bar.progress((idx + 1) / total)
            time.sleep(0.3)
            
        status_text.text("Scan terminé !")
        
        if telegram_alerts:
            for alert in telegram_alerts:
                send_telegram_alert(alert)
                time.sleep(0.5)
            st.success(f"{len(telegram_alerts)} alerte(s) envoyée(s) sur Telegram !")
        else:
            send_telegram_alert(f"ℹ️ Scan [{HTF} -> {tf_struct}] terminé. Aucune structure M/W active.")
            st.info("Aucune structure M/W active trouvée pour ce timeframe.")
            
        if results:
            st.dataframe(pd.DataFrame(results), use_container_width=True)
else:
    st.warning("Clé API Twelve Data manquante dans les Secrets.")
