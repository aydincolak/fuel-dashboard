"""
app.py
------
Yakıt Fiyat Gösterge Paneli
Streamlit + Plotly tabanlı interaktif dashboard.
Veri kaynağı: FRED (Federal Reserve Bank of St. Louis)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import json
from datetime import datetime, timedelta

# ── Sayfa Ayarları ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Yakıt Fiyat Gösterge Paneli",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Renk Paleti (IATA Standart) ─────────────────────────────────────────────
COLORS = {
    "Brent":    "#F5A623",   # Sarı
    "JetFuel":  "#1A6FBF",   # Mavi
    "Diesel":   "#27AE60",   # Yeşil
    "Gasoline": "#8E44AD",   # Mor
    "Crack":    "#E74C3C",   # Kırmızı
}

LABELS = {
    "Brent":    "Brent Petrol (USD/varil)",
    "JetFuel":  "Jet Yakıtı (USD/galon)",
    "Diesel":   "Dizel (USD/galon)",
    "Gasoline": "Benzin (USD/galon)",
    "Crack":    "Crack Spread (USD/varil)",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ── Stil ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Ana arka plan */
    .stApp { background-color: #0F1117; }

    /* Başlık alanı */
    .header-box {
        background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
        border: 1px solid #2d3561;
        border-radius: 12px;
        padding: 20px 28px;
        margin-bottom: 24px;
    }
    .header-title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #F5A623;
        margin: 0 0 4px 0;
    }
    .header-sub {
        font-size: 0.95rem;
        color: #8899aa;
        margin: 0;
    }
    .meta-badge {
        display: inline-block;
        background: #1e2740;
        border: 1px solid #2d3d5c;
        border-radius: 6px;
        padding: 4px 12px;
        font-size: 0.82rem;
        color: #7fb3d3;
        margin-top: 10px;
    }

    /* Tab başlıkları */
    .stTabs [data-baseweb="tab"] {
        background-color: #1a1f2e;
        border-radius: 8px 8px 0 0;
        color: #8899aa;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2d3561 !important;
        color: #F5A623 !important;
    }

    /* Metrik kutuları */
    .metric-card {
        background: #1a1f2e;
        border: 1px solid #2d3561;
        border-radius: 10px;
        padding: 14px 18px;
        text-align: center;
    }
    .metric-label { font-size: 0.78rem; color: #8899aa; margin-bottom: 4px; }
    .metric-value { font-size: 1.4rem; font-weight: 700; }
    .metric-delta { font-size: 0.82rem; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# ── Veri Yükleme ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)  # 1 saatlik önbellek
def load_data():
    files = {
        "Brent":    ("Brent.csv",    "DCOILBRENTEU"),
        "JetFuel":  ("JetFuel.csv",  "DJFUELUSGULF"),
        "Diesel":   ("Diesel.csv",   "DDFUELUSGULF"),
        "Gasoline": ("Gasoline.csv", "DGASUSGULF"),
    }
    dfs = {}
    for key, (fname, col) in files.items():
        path = os.path.join(DATA_DIR, fname)
        df = pd.read_csv(path)
        df["DATE"] = pd.to_datetime(df["DATE"])
        df = df.rename(columns={col: key}).set_index("DATE").sort_index()
        dfs[key] = df

    merged = pd.concat(dfs.values(), axis=1).sort_index()
    # Hafta sonu boşluklarını doldur
    all_dates = pd.date_range(start=merged.index.min(), end=merged.index.max(), freq="D")
    merged = merged.reindex(all_dates).ffill().bfill()

    # Varil dönüşümü [1 varil = 42 galon]
    merged["JetFuel_bbl"] = merged["JetFuel"] * 42
    merged["Diesel_bbl"]  = merged["Diesel"]  * 42
    merged["Gasoline_bbl"]= merged["Gasoline"]* 42
    merged["Crack"]       = merged["JetFuel_bbl"] - merged["Brent"]

    # 7 günlük hareketli ortalama
    for col in ["Brent", "JetFuel", "Diesel", "Gasoline", "Crack",
                "JetFuel_bbl", "Diesel_bbl", "Gasoline_bbl"]:
        merged[f"{col}_MA7"] = merged[col].rolling(7, center=True).mean()

    return merged


@st.cache_data(ttl=3600)
def load_meta():
    meta_path = os.path.join(DATA_DIR, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            return json.load(f)
    return {"last_updated": "Bilinmiyor"}


# ── Zaman Filtresi ────────────────────────────────────────────────────────────
def filter_by_range(df: pd.DataFrame, period: str) -> pd.DataFrame:
    end = df.index.max()
    delta_map = {
        "Son 1 Ay":  30,
        "Son 3 Ay":  90,
        "Son 6 Ay":  180,
        "Son 1 Yıl": 365,
        "Son 5 Yıl": 1825,
    }
    days = delta_map.get(period, 90)
    start = end - timedelta(days=days)
    return df[df.index >= start]


# ── Grafik Fonksiyonları ──────────────────────────────────────────────────────
def make_dual_chart(df: pd.DataFrame, s1: str, s2: str) -> go.Figure:
    """
    İki seriyi çift Y ekseninde gösterir.
    s1, s2: 'Brent', 'JetFuel', 'Diesel', 'Gasoline' anahtarları
    """
    unit1 = "USD/varil" if s1 == "Brent" else "USD/galon"
    unit2 = "USD/varil" if s2 == "Brent" else "USD/galon"

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Seri 1 - ham veri (şeffaf)
    fig.add_trace(go.Scatter(
        x=df.index, y=df[s1],
        name=s1, mode="lines",
        line=dict(color=COLORS[s1], width=1, dash="dot"),
        opacity=0.3, showlegend=False
    ), secondary_y=False)

    # Seri 1 - MA7
    fig.add_trace(go.Scatter(
        x=df.index, y=df[f"{s1}_MA7"],
        name=f"{s1} (7G MA)", mode="lines",
        line=dict(color=COLORS[s1], width=2.5),
    ), secondary_y=False)

    # Seri 2 - ham veri (şeffaf)
    fig.add_trace(go.Scatter(
        x=df.index, y=df[s2],
        name=s2, mode="lines",
        line=dict(color=COLORS[s2], width=1, dash="dot"),
        opacity=0.3, showlegend=False
    ), secondary_y=True)

    # Seri 2 - MA7
    fig.add_trace(go.Scatter(
        x=df.index, y=df[f"{s2}_MA7"],
        name=f"{s2} (7G MA)", mode="lines",
        line=dict(color=COLORS[s2], width=2.5),
    ), secondary_y=True)

    # Pearson r hesapla
    clean = df[[s1, s2]].dropna()
    if len(clean) > 5:
        r = round(clean[s1].corr(clean[s2]), 3)
        fig.add_annotation(
            text=f"Pearson r = {r}",
            xref="paper", yref="paper", x=0.01, y=0.97,
            showarrow=False,
            font=dict(size=13, color="#ffffff", family="monospace"),
            bgcolor="#2d3561", bordercolor="#F5A623",
            borderwidth=1, borderpad=6
        )

    fig.update_layout(
        plot_bgcolor="#0F1117",
        paper_bgcolor="#0F1117",
        font=dict(color="#cdd9e5", family="Inter, sans-serif"),
        legend=dict(
            bgcolor="#1a1f2e", bordercolor="#2d3561",
            borderwidth=1, orientation="h", yanchor="bottom", y=1.02
        ),
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        xaxis=dict(gridcolor="#1e2740", showgrid=True),
        yaxis=dict(
            title=f"{s1} ({unit1})",
            gridcolor="#1e2740", showgrid=True,
            title_font=dict(color=COLORS[s1])
        ),
        yaxis2=dict(
            title=f"{s2} ({unit2})",
            title_font=dict(color=COLORS[s2]),
            showgrid=False
        ),
    )
    return fig


def make_iata_chart(df: pd.DataFrame) -> go.Figure:
    """Ana grafik: Brent + Jet + Dizel + Crack Spread, tek Y ekseni."""
    fig = go.Figure()

    # Crack Spread - dolgulu alan (en altta, arka planda)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Crack"],
        name="Crack Spread (USD/varil)", mode="lines", fill="tozeroy",
        line=dict(color=COLORS["Crack"], width=1.5),
        fillcolor="rgba(231,76,60,0.18)"
    ))

    # Brent - kalın sarı çizgi
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Brent"],
        name="Brent Petrol (USD/varil)", mode="lines",
        line=dict(color=COLORS["Brent"], width=2.5)
    ))

    # Jet Yakıtı - varil bazında, kalın mavi
    fig.add_trace(go.Scatter(
        x=df.index, y=df["JetFuel_bbl"],
        name="Jet Yakıtı (USD/varil)", mode="lines",
        line=dict(color=COLORS["JetFuel"], width=2.5)
    ))

    # Dizel - kesikli yeşil
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Diesel_bbl"],
        name="Dizel (USD/varil)", mode="lines",
        line=dict(color=COLORS["Diesel"], width=1.8, dash="dash")
    ))

    fig.update_layout(
        plot_bgcolor="#0F1117",
        paper_bgcolor="#0F1117",
        font=dict(color="#cdd9e5", family="Inter, sans-serif"),
        legend=dict(
            bgcolor="#1a1f2e", bordercolor="#2d3561",
            borderwidth=1, orientation="h", yanchor="bottom", y=1.02
        ),
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        xaxis=dict(gridcolor="#1e2740", showgrid=True),
        yaxis=dict(
            title="USD / Varil",
            gridcolor="#1e2740", showgrid=True,
            rangemode="tozero"
        ),
    )
    return fig


# ── Son Fiyat Metrikleri ──────────────────────────────────────────────────────
def render_metrics(df: pd.DataFrame):
    items = [
        ("Brent",       "Brent Petrol", "USD/varil"),
        ("JetFuel_bbl", "Jet Yakıtı",   "USD/varil"),
        ("Diesel_bbl",  "Dizel",        "USD/varil"),
        ("Gasoline_bbl","Benzin",       "USD/varil"),
        ("Crack",       "Crack Spread", "USD/varil"),
    ]
    cols = st.columns(len(items))
    for col, (key, label, unit) in zip(cols, items):
        val  = df[key].dropna().iloc[-1]
        prev = df[key].dropna().iloc[-8] if len(df[key].dropna()) > 8 else val
        delta     = val - prev
        delta_pct = (delta / prev * 100) if prev else 0
        color = "#27AE60" if delta >= 0 else "#E74C3C"
        arrow = "▲" if delta >= 0 else "▼"
        col.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value" style="color:{COLORS.get(key.split('_')[0], '#cdd9e5')}">
                ${val:.2f}
            </div>
            <div class="metric-delta" style="color:{color}">
                {arrow} {abs(delta):.2f} ({abs(delta_pct):.1f}%) 7G
            </div>
            <div class="metric-label" style="margin-top:4px">{unit}</div>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# UYGULAMA
# ══════════════════════════════════════════════════════════════════════════════

df_full = load_data()
meta    = load_meta()

# ── Başlık ───────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="header-box">
    <p class="header-title">⛽ Yakıt Fiyat Gösterge Paneli</p>
    <p class="header-sub">Brika Sürdürülebilirlik | Havacılık Yakıtı Piyasa Analizi</p>
    <span class="meta-badge">
        📡 Kaynak: FRED — Federal Reserve Bank of St. Louis &nbsp;|&nbsp;
        🕐 Son güncelleme: {meta.get('last_updated', 'Bilinmiyor')} &nbsp;|&nbsp;
        📅 Veri: {df_full.index.min().strftime('%d.%m.%Y')} – {df_full.index.max().strftime('%d.%m.%Y')}
    </span>
</div>
""", unsafe_allow_html=True)

# ── Zaman Filtresi ───────────────────────────────────────────────────────────
period_choice = st.radio(
    "Zaman Aralığı",
    ["Son 1 Ay", "Son 3 Ay", "Son 6 Ay", "Son 1 Yıl", "Son 5 Yıl"],
    index=1,
    horizontal=True,
    label_visibility="collapsed"
)

df = filter_by_range(df_full, period_choice)

# ── Metrikler ────────────────────────────────────────────────────────────────
st.markdown("---")
render_metrics(df_full)
st.markdown("---")

# ── Sekmeler ─────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📊 Ana Grafik", "🔀 İkili Karşılaştırmalar"])

with tab1:
    st.markdown(f"##### Brent Petrol · Jet Yakıtı · Dizel · Crack Spread  |  {period_choice}")
    st.plotly_chart(make_iata_chart(df), width="stretch")

with tab2:
    st.markdown(f"##### İkili Yakıt Fiyat Karşılaştırmaları &nbsp;|&nbsp; {period_choice}")
    pairs = [
        ("JetFuel", "Brent"),
        ("JetFuel", "Diesel"),
        ("Diesel",  "Brent"),
        ("JetFuel", "Gasoline"),
        ("Diesel",  "Gasoline"),
        ("Gasoline","Brent"),
    ]
    pair_labels = {
        ("JetFuel", "Brent"):    "Jet Yakıtı vs Brent",
        ("JetFuel", "Diesel"):   "Jet Yakıtı vs Dizel",
        ("Diesel",  "Brent"):    "Dizel vs Brent",
        ("JetFuel", "Gasoline"): "Jet Yakıtı vs Benzin",
        ("Diesel",  "Gasoline"): "Dizel vs Benzin",
        ("Gasoline","Brent"):    "Benzin vs Brent",
    }

    col_left, col_right = st.columns(2)
    for i, (s1, s2) in enumerate(pairs):
        col = col_left if i % 2 == 0 else col_right
        with col:
            st.markdown(f"**{pair_labels[(s1,s2)]}**")
            st.plotly_chart(
                make_dual_chart(df, s1, s2),
                width="stretch",
                key=f"chart_{s1}_{s2}"
            )

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; color:#445566; font-size:0.8rem; margin-top:24px; padding-top:16px; border-top:1px solid #1e2740;">
    Veri Kaynağı: FRED — Federal Reserve Bank of St. Louis &nbsp;|&nbsp;
    Brika Sürdürülebilirlik © 2024
</div>
""", unsafe_allow_html=True)
