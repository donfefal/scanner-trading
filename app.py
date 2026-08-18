import streamlit as st
import requests
import pandas as pd
import ta
import time

st.set_page_config(page_title="Scanner Multi-Séquences MTF", page_icon="📊", layout="wide")

st.title("📊 Scanner Reversal - Alignement HTF, TDI & Double Retest")
st.caption("Cascade Chronologique : Sweep/Rejet HTF -> Structure M/W (Flexible) -> Retest Neckline/EMA200")

# Secrets Streamlit Cloud
API_KEY = st.secrets.get("TWELVEDATA_API_KEY", "")
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

st.sidebar.header("⚙️ Configuration HTF")
HTF = st.sidebar.selectbox("Clôture HTF (Contexte)", ["1month", "1week", "1day", "4h"])

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

    # TDI et EMA200 sur Timeframe de Structure
    df_struct['RSI'] = ta.momentum.rsi(df_struct['close'], window=14)
    df_struct['Base'] = ta.trend.sma_indicator(df_struct['RSI'], window=14)
    df_struct['Signal'] = ta.trend.sma_indicator(df_struct['RSI'], window=2)
    df_struct['EMA200'] = ta.trend.ema_indicator(df_struct['close'], window=200)

    # 1. Clôture Bougie HTF / Sweep / Rejet Puissant
    b_prev, b_curr = df_htf.iloc[-2], df_htf.iloc[-1]
    prev_mid = (b_prev['open'] + b_prev['close']) / 2
    
    swept_low = b_curr['low'] < b_prev['low'] and b_curr['close'] > prev_mid
    swept_high = b_curr['high'] > b_prev['high'] and b_curr['close'] < prev_mid
    
    body_curr = abs(b_curr['close'] - b_curr['open'])
    range_curr = b_curr['high'] - b_curr['low'] if (b_curr['high'] - b_curr['low']) > 0 else 1
    is_bull_reversal = (b_curr['close'] > b_curr['open']) and (body_curr / range_curr > 0.4)
    is_bear_reversal = (b_curr['close'] < b_curr['open']) and (body_curr / range_curr > 0.4)

    if swept_low or is_bull_reversal:
        step1 = f"✅ Rejet/Retournement Haussier ({HTF})"
        bias = "ACHAT"
    elif swept_high or is_bear_reversal:
        step1 = f"✅ Rejet/Retournement Baissier ({HTF})"
        bias = "VENTE"
    else:
        step1 = "❌ Non"
        bias = "NEUTRE"

    # 2. Structure M ou W (Tolérance Élargie aux W/M Asymétriques)
    recent_s = df_struct.tail(35).reset_index(drop=True)
    price = df_entry['close'].iloc[-1]
    
    max1_idx, max2_idx = recent_s['high'].iloc[:-10].idxmax(), recent_s['high'].iloc[-10:].idxmax()
    max1, max2 = recent_s['high'].iloc[max1_idx], recent_s['high'].iloc[max2_idx]
    min_between = recent_s['low'].iloc[max1_idx:max2_idx+1].min() if max1_idx < max2_idx else None

    min1_idx, min2_idx = recent_s['low'].iloc[:-10].idxmin(), recent_s['low'].iloc[-10:].idxmin()
    min1, min2 = recent_s['low'].iloc[min1_idx], recent_s['low'].iloc[min2_idx]
    max_between = recent_s['high'].iloc[min1_idx:min2_idx+1].max() if min1_idx < min2_idx else None

    # Tolérance élargie à 1.2% pour capter les creux/sommets asymétriques (Sweep)
    is_m = (abs(max1 - max2) / max1 < 0.012) and min_between is not None
    is_w = (abs(min1 - min2) / min1 < 0.012) and max_between is not None

    step2 = f"M sur {tf_struct}" if is_m else (f"W sur {tf_struct}" if is_w else "❌ Non")

    # 3. TDI : Croisement RSI/Signal vs Baseline
    rsi_c, base_c, sig_c = df_struct['RSI'].iloc[-1], df_struct['Base'].iloc[-1], df_struct['Signal'].iloc[-1]
    rsi_p, base_p = df_struct['RSI'].iloc[-2], df_struct['Base'].iloc[-2]
    
    rsi_cross_up = (rsi_p <= base_p and rsi_c > base_c)
    rsi_cross_down = (rsi_p >= base_p and rsi_c < base_c)
    step3 = f"✅ TDI Cross-Up" if rsi_cross_up else (f"✅ TDI Cross-Down" if rsi_cross_down else f"🔄 TDI actif ({rsi_c:.1f}/{base_c:.1f})")

    # 4 & 5. Retest (Neckline OU EMA 200) + Rejet TDI
    neckline = min_between if is_m else (max_between if is_w else None)
    ema200_val = df_struct['EMA200'].iloc[-1]
    
    step4 = "❌ Non"
    step5 = "❌ Non"

    if neckline or ema200_val:
        ref_level = neckline if neckline else ema200_val
        dist_neck = abs(price - neckline) / neckline if neckline else 1.0
        dist_ema = abs(price - ema200_val) / ema200_val if ema200_val else 1.0

        c_open = df_entry['open'].iloc[-1]
        c_close = df_entry['close'].iloc[-1]
        c_high = df_entry['high'].iloc[-1]
        c_low = df_entry['low'].iloc[-1]
        body_ratio = abs(c_close - c_open) / (c_high - c_low) if (c_high - c_low) > 0 else 0

        tdi_retest = (abs(rsi_c - base_c) <= 7) or (abs(sig_c - base_c) <= 7)
        at_retest_zone = (dist_neck <= 0.0035) or (dist_ema <= 0.0035)

        if at_retest_zone and tdi_retest:
            is_reversal_candle = (is_w and c_close > c_open) or (is_m and c_close < c_open)
            retest_target = "EMA 200" if dist_ema <= 0.0035 else f"Neckline ({neckline:.5f})"
            if is_reversal_candle:
                step4 = f"🎯 SETUP VALIDE : Retest sur {retest_target}"
                step5 = f"🔥 Bougie de retournement {tf_entry} + TDI sur Baseline"
            else:
                step4 = f"⏳ Retest en cours sur {retest_target}"
                step5 = f"🔄 Attente clôture bougie de retournement ({tf_entry})"
        elif is_w and price > ref_level and c_close > c_open and body_ratio > 0.6:
            step4 = f"⚡ CONTINUATION HAUSSIÈRE (Breakout {ref_level:.5f})"
            step5 = f"🔥 Impulsion forte sans retest sur {tf_entry}"
        elif is_m and price < ref_level and c_close < c_open and body_ratio > 0.6:
            step4 = f"⚡ CONTINUATION BAISSIÈRE (Breakout {ref_level:.5f})"
            step5 = f"🔥 Impulsion forte sans retest sur {tf_entry}"

    # 6. Filtre TDI 2ème Creux/Sommet
    step6 = "❌ Standard"
    if is_m and max2_idx < len(recent_s):
        if rsi_c <= base_c + 3:
            step6 = f"🔥 2ème Top filtré sous Baseline TDI ({tf_struct})"
    elif is_w and min2_idx < len(recent_s):
        if rsi_c >= base_c - 3:
            step6 = f"🔥 2ème Bottom filtré sur Baseline TDI ({tf_struct})"

    score = sum([step1 != "❌ Non", is_m or is_w, "✅" in step3 or "🔄" in step3, "🎯" in step4 or "⚡" in step4, "🔥" in step5, "🔥" in step6])

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
            status_text.text(f"Analyse [{HTF} -> TDI {tf_struct} -> Entrée {tf_entry}] : {symbol} ({idx+1}/{total})...")
            res = analyze_sequences(symbol)
            if res:
                results.append(res)
                if res["S2_Pattern"] != "❌ Non":
                    msg = (
                        f"📊 *ANALYSE CHRONOLOGIQUE TDI : {symbol}*\n"
                        f"🎯 Biais : *{res['Biais']}* | Prix : `{res['Prix']}`\n\n"
                        f"1️⃣ Bougie HTF : {res['S1_Sweep']}\n"
                        f"2️⃣ Structure : {res['S2_Pattern']}\n"
                        f"3️⃣ Signal TDI : {res['S3_RSI_TDI']}\n"
                        f"4️⃣ Zone Retest / EMA : {res['S4_Retest']}\n"
                        f"5️⃣ Entrée / Signal : {res['S5_NecklineTest']}\n"
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
    
