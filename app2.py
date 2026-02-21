# app.py
# Streamlit + Plotly 30D Forecast App (DAU / Revenue / Cost / Break-even) with Excel export + KPI cards + model explanation

import numpy as np
import pandas as pd
import streamlit as st
from io import BytesIO

import plotly.graph_objects as go

st.set_page_config(page_title="30D Forecast", layout="wide")

st.title("Mobile Game 30 Günlük Forecast")
st.caption("DAU / Revenue / Cost / Profit / Break-even — Cohort Stacking yaklaşımı ile")

# -----------------------------
# Sidebar Inputs
# -----------------------------
st.sidebar.header("Inputs")

ret_d1 = st.sidebar.number_input("Retention D1 (%)", min_value=0.0, max_value=100.0, value=50.0, step=1.0) / 100.0
ret_d7 = st.sidebar.number_input("Retention D7 (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0) / 100.0
ret_d14 = st.sidebar.number_input("Retention D14 (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0) / 100.0
ret_d30 = st.sidebar.number_input("Retention D30 (%)", min_value=0.0, max_value=100.0, value=5.0, step=1.0) / 100.0

st.sidebar.divider()
inter_impr_per_dau = st.sidebar.number_input("Inter Impressions / DAU", min_value=0.0, value=6.0, step=0.5)
inter_cpm = st.sidebar.number_input("Inter CPM ($)", min_value=0.0, value=12.0, step=0.5)

reward_impr_per_dau = st.sidebar.number_input("Rewarded Impressions / DAU", min_value=0.0, value=1.0, step=0.5)
reward_cpm = st.sidebar.number_input("Rewarded CPM ($)", min_value=0.0, value=25.0, step=0.5)

st.sidebar.divider()
cpi = st.sidebar.number_input("CPI ($)", min_value=0.0, value=0.50, step=0.01)
organic_ratio = st.sidebar.number_input("Organic / Paid (%)", min_value=0.0, max_value=300.0, value=5.0, step=1.0) / 100.0
paid_installs_daily = st.sidebar.number_input("Paid Installs Daily", min_value=0, value=10000, step=500)

st.sidebar.divider()
days = st.sidebar.slider("Forecast Days", min_value=7, max_value=120, value=30, step=1)

method = st.sidebar.selectbox(
    "Retention Model",
    ["Piecewise Linear (D0/D1/D7/D14/D30)", "Exponential (fit to D1)"],
)

show_advanced = st.sidebar.checkbox("Advanced (ek metrikler)", value=True)
run = st.sidebar.button("Forecast Çalıştır", use_container_width=True)

# -----------------------------
# Helpers
# -----------------------------
def build_retention_piecewise(days_count: int, d1: float, d7: float, d14: float, d30: float):
    """
    Piecewise linear interpolation using points at day 0,1,7,14,30.
    For days >30, retention is clamped at day30 value (flat extension).
    """
    points = {0: 1.0, 1: d1, 7: d7, 14: d14, 30: d30}
    x = np.array(sorted(points.keys()), dtype=float)
    y = np.array([points[i] for i in x], dtype=float)

    idx = np.arange(days_count, dtype=float)
    idx_clip = np.minimum(idx, 30.0)
    ret = np.interp(idx_clip, x, y)
    return ret, points


def build_retention_exponential(days_count: int, d1: float):
    """
    retention(d) = exp(-lambda * d), fit lambda using retention(1)=d1.
    """
    d1 = float(np.clip(d1, 1e-9, 0.999999))
    lam = -np.log(d1)
    idx = np.arange(days_count, dtype=float)
    ret = np.exp(-lam * idx)
    return ret, lam


def cohort_dau(days_count: int, installs_daily_total: float, retention: np.ndarray):
    """
    Cohort stacking:
    DAU(t) = sum_{cohort_day=0..t} installs * retention(t-cohort_day)
    """
    dau = np.zeros(days_count, dtype=float)
    for t in range(days_count):
        ages = np.arange(t + 1, dtype=int)[::-1]  # 0..t (reversed) -> ages
        dau[t] = float(np.sum(installs_daily_total * retention[ages]))
    return dau


def to_excel_bytes(inputs_df: pd.DataFrame, forecast_df: pd.DataFrame, notes: str):
    """
    Export Inputs + Forecast to a downloadable Excel file (in-memory).
    """
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        inputs_df.to_excel(writer, sheet_name="Inputs", index=False)
        forecast_df.to_excel(writer, sheet_name="Forecast", index=False)

        # Notes sheet
        wb = writer.book
        ws_notes = wb.add_worksheet("Notes")
        ws_notes.write(0, 0, notes)

        # Formatting
        ws = writer.sheets["Forecast"]
        ws_in = writer.sheets["Inputs"]

        money_fmt = wb.add_format({"num_format": "$#,##0"})
        num_fmt = wb.add_format({"num_format": "#,##0"})
        dec_fmt = wb.add_format({"num_format": "#,##0.00"})
        dec5_fmt = wb.add_format({"num_format": "#,##0.00000"})

        ws.set_column("A:A", 6)
        ws.set_column("B:B", 14, num_fmt)   # DAU
        ws.set_column("C:C", 14, money_fmt) # Revenue
        ws.set_column("D:D", 12, money_fmt) # Cost
        ws.set_column("E:E", 14, money_fmt) # Profit
        ws.set_column("F:F", 16, money_fmt) # CumProfit
        ws.set_column("G:G", 18, dec5_fmt)  # ARPDAU
        ws.set_column("H:H", 18, num_fmt)   # BreakEven DAU

        ws_in.set_column("A:A", 26)
        ws_in.set_column("B:B", 28)

    bio.seek(0)
    return bio


# -----------------------------
# Main
# -----------------------------
if not run:
    st.info("Soldan metrikleri girip **Forecast Çalıştır** butonuna bas.")
    st.stop()

# Derived inputs
installs_daily_total = paid_installs_daily * (1 + organic_ratio)
daily_cost = paid_installs_daily * cpi

arpdau_ads = (inter_impr_per_dau * inter_cpm + reward_impr_per_dau * reward_cpm) / 1000.0
break_even_dau = (daily_cost / arpdau_ads) if arpdau_ads > 0 else np.inf

# Retention curve
if method.startswith("Piecewise"):
    retention, points = build_retention_piecewise(days, ret_d1, ret_d7, ret_d14, ret_d30)
    model_name = "Piecewise Linear"
    model_note = f"Piecewise points: {points}"
else:
    retention, lam = build_retention_exponential(days, ret_d1)
    model_name = "Exponential"
    model_note = f"Exponential lambda: {lam:.6f}"

# Forecast
dau = cohort_dau(days, installs_daily_total, retention)
revenue = dau * arpdau_ads
cost = np.repeat(daily_cost, days)
profit = revenue - cost
cum_profit = np.cumsum(profit)
cum_revenue = np.cumsum(revenue)
cum_cost = np.cumsum(cost)

# Payback day (cumulative)
payback_day = None
for i in range(days):
    if cum_profit[i] >= 0:
        payback_day = i + 1
        break

# Optional: daily BE achieved day(s)
daily_be_achieved_days = np.where(dau >= break_even_dau)[0] + 1 if np.isfinite(break_even_dau) else np.array([])

# Build tables
inputs_df = pd.DataFrame(
    [
        ["Retention D1/D7/D14/D30", f"{ret_d1:.2%}/{ret_d7:.2%}/{ret_d14:.2%}/{ret_d30:.2%}"],
        ["Inter Impr/DAU", inter_impr_per_dau],
        ["Inter CPM ($)", inter_cpm],
        ["Rewarded Impr/DAU", reward_impr_per_dau],
        ["Rewarded CPM ($)", reward_cpm],
        ["CPI ($)", cpi],
        ["Organic/Paid", f"{organic_ratio:.2%}"],
        ["Paid Installs Daily", paid_installs_daily],
        ["Total Installs Daily", installs_daily_total],
        ["ARPDAU_ads ($/DAU/day)", arpdau_ads],
        ["Daily Cost ($)", daily_cost],
        ["Daily Break-even DAU", break_even_dau],
        ["Payback Day (CumProfit>=0)", payback_day if payback_day is not None else "N/A"],
        ["Model", model_name],
        ["Model Note", model_note],
    ],
    columns=["Metric", "Value"],
)

forecast_df = pd.DataFrame(
    {
        "Day": np.arange(1, days + 1),
        "DAU": np.round(dau, 2),
        "Revenue": np.round(revenue, 2),
        "Cost": np.round(cost, 2),
        "Profit": np.round(profit, 2),
        "CumProfit": np.round(cum_profit, 2),
        "ARPDAU_ads": np.round(np.repeat(arpdau_ads, days), 5),
        "Daily_BreakEven_DAU": np.round(np.repeat(break_even_dau, days), 2),
    }
)

# -----------------------------
# KPI Cards
# -----------------------------
st.subheader("KPI Özet")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("ARPDAU (ads)", "-" if arpdau_ads <= 0 else f"${arpdau_ads:.3f}")
k2.metric("Daily Cost", f"${daily_cost:,.0f}")
k3.metric("Break-even DAU", "-" if not np.isfinite(break_even_dau) else f"{break_even_dau:,.0f}")
k4.metric("Payback Day", "-" if payback_day is None else f"Day {payback_day}")
k5.metric("Total Installs/day", f"{installs_daily_total:,.0f}")

if show_advanced:
    st.caption(
        "Not: Break-even DAU, **o günün** UA maliyetinin (paid installs × CPI) **o günün** ads geliriyle (DAU × ARPDAU) karşılanması için gereken DAU eşiğidir."
    )

# -----------------------------
# Layout: Inputs + Forecast table
# -----------------------------
c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("Inputs")
    st.dataframe(inputs_df, use_container_width=True, height=440)

    st.subheader("Kısa Okuma Rehberi")
    if arpdau_ads <= 0:
        st.warning("ARPDAU 0 görünüyor; CPM veya impression inputlarını kontrol et.")
    else:
        if daily_be_achieved_days.size > 0:
            st.write(f"- **Günlük break-even** ilk kez **Day {int(daily_be_achieved_days[0])}** gününde sağlanıyor.")
        else:
            st.write("- 30 gün içinde **günlük break-even** sağlanmıyor (DAU, break-even eşiğinin altında kalıyor).")

        st.write(f"- **Cumulative payback**: **{('Day ' + str(payback_day)) if payback_day else '30 gün içinde yok'}**")
        st.write(f"- **Model**: {model_name}")

with c2:
    st.subheader("Forecast Tablosu")
    st.dataframe(forecast_df, use_container_width=True, height=520)

# -----------------------------
# Plotly Charts
# -----------------------------
st.subheader("Grafikler (Plotly)")

# 1) DAU vs Break-even
fig1 = go.Figure()
fig1.add_trace(
    go.Scatter(
        x=forecast_df["Day"],
        y=forecast_df["DAU"],
        mode="lines+markers",
        name="DAU (Forecast)",
        hovertemplate="Day %{x}<br>DAU %{y:,.0f}<extra></extra>",
    )
)
fig1.add_trace(
    go.Scatter(
        x=forecast_df["Day"],
        y=forecast_df["Daily_BreakEven_DAU"],
        mode="lines",
        name="Daily Break-even DAU",
        line=dict(dash="dash"),
        hovertemplate="Day %{x}<br>Break-even DAU %{y:,.0f}<extra></extra>",
    )
)
fig1.update_layout(
    title=f"DAU vs Daily Break-even DAU ({model_name})",
    xaxis_title="Day",
    yaxis_title="Users",
    hovermode="x unified",
    legend_title_text="Çizgiler",
)
st.plotly_chart(fig1, use_container_width=True)

# 2) Revenue vs Cost
fig2 = go.Figure()
fig2.add_trace(
    go.Scatter(
        x=forecast_df["Day"],
        y=forecast_df["Revenue"],
        mode="lines+markers",
        name="Daily Revenue ($)",
        hovertemplate="Day %{x}<br>Revenue $%{y:,.0f}<extra></extra>",
    )
)
fig2.add_trace(
    go.Scatter(
        x=forecast_df["Day"],
        y=forecast_df["Cost"],
        mode="lines",
        name="Daily Cost ($)",
        line=dict(dash="dash"),
        hovertemplate="Day %{x}<br>Cost $%{y:,.0f}<extra></extra>",
    )
)
fig2.update_layout(
    title=f"Daily Revenue vs Daily Cost ({model_name})",
    xaxis_title="Day",
    yaxis_title="$",
    hovermode="x unified",
    legend_title_text="Çizgiler",
)
st.plotly_chart(fig2, use_container_width=True)

# 3) Cumulative Profit (Payback)
fig3 = go.Figure()
fig3.add_trace(
    go.Scatter(
        x=forecast_df["Day"],
        y=forecast_df["CumProfit"],
        mode="lines+markers",
        name="Cumulative Profit ($)",
        hovertemplate="Day %{x}<br>CumProfit $%{y:,.0f}<extra></extra>",
    )
)
fig3.add_hline(y=0, line_dash="dash", annotation_text="Break-even (0)", annotation_position="top left")
fig3.update_layout(
    title=f"Cumulative Profit (Payback) ({model_name})",
    xaxis_title="Day",
    yaxis_title="$",
    hovermode="x unified",
    legend_title_text="Çizgiler",
)
st.plotly_chart(fig3, use_container_width=True)

# Optional: retention curve chart
if show_advanced:
    fig4 = go.Figure()
    fig4.add_trace(
        go.Scatter(
            x=np.arange(0, days),
            y=retention,
            mode="lines+markers",
            name="Retention Curve",
            hovertemplate="Day %{x}<br>Retention %{y:.2%}<extra></extra>",
        )
    )
    fig4.update_layout(
        title=f"Retention Curve Used in Forecast ({model_name})",
        xaxis_title="Day since install",
        yaxis_title="Retention",
        hovermode="x unified",
    )
    st.plotly_chart(fig4, use_container_width=True)

# -----------------------------
# Excel download
# -----------------------------
notes = (
    "This file was generated by the Streamlit 30D Forecast app.\n"
    "Sheets:\n"
    "- Inputs: model parameters\n"
    "- Forecast: daily outputs (DAU/Revenue/Cost/Profit/CumProfit)\n"
    "Model:\n"
    f"- {model_name}\n"
)

excel_bytes = to_excel_bytes(inputs_df, forecast_df, notes)
st.download_button(
    label="Excel çıktısını indir (Inputs + Forecast + Notes)",
    data=excel_bytes,
    file_name="forecast_30d.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

# -----------------------------
# Bottom: Model explanation
# -----------------------------
st.divider()
with st.expander("Arkada çalışan mantık (Forecast nasıl hesaplanıyor?)", expanded=False):
    st.markdown(
        f"""
### 1) Türetilen temel değerler
- **Total Installs/day** = Paid × (1 + OrganicRatio)  
  → `{paid_installs_daily} × (1 + {organic_ratio:.2%}) = {installs_daily_total:,.0f}`
- **ARPDAU (ads)** = (InterImpr×InterCPM + RewardImpr×RewardCPM) / 1000  
  → `({inter_impr_per_dau}×{inter_cpm} + {reward_impr_per_dau}×{reward_cpm}) / 1000 = ${arpdau_ads:.3f} / DAU / gün`
- **Daily Cost** = Paid Installs/day × CPI  
  → `{paid_installs_daily} × ${cpi:.2f} = ${daily_cost:,.0f}`
- **Daily Break-even DAU** = Daily Cost / ARPDAU  
  → `${daily_cost:,.0f} / ${arpdau_ads:.3f} = {break_even_dau:,.0f}`

### 2) Retention eğrisi (seçilen model: **{model_name}**)
- **Piecewise Linear:** D0/D1/D7/D14/D30 noktaları arasında doğrusal interpolasyon yapılır.  
- **Exponential:** `R(d)=exp(-λd)` alınır ve `R(1)=D1` olacak şekilde **λ** kalibre edilir.

### 3) DAU tahmini (Cohort Stacking)
Her gün yeni bir cohort gelir. Gün **t**’de:

**DAU(t)** = Σ Install(cohort_day) × Retention(age)  
burada **age = t − cohort_day**.

Bu, birikimli olarak eski cohort’ların kalan aktif kullanıcılarını üst üste “stack” etmektir.

### 4) Gelir / Maliyet / Kârlılık
- **Revenue(t)** = DAU(t) × ARPDAU  
- **Profit(t)** = Revenue(t) − Daily Cost  
- **Cumulative Profit** = Σ Profit  
**Payback day**, kümülatif kârın ilk kez 0’ı geçtiği gündür.
"""
    )