# Includes: two retention methods (Piecewise vs Exponential), side-by-side comparison, narrative insights,
# metric definitions, model mechanics, and Excel export.

import numpy as np
import pandas as pd
import streamlit as st
from io import BytesIO
import plotly.graph_objects as go

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="30D Forecast Dashboard", layout="wide")
st.title("Mobile Game 30-Day Forecast Dashboard")
st.caption("Forecast DAU, ad revenue, UA cost, daily break-even, and payback using cohort stacking.")

# -----------------------------
# Sidebar inputs
# -----------------------------
st.sidebar.header("Inputs")

st.sidebar.subheader("Retention points (cohort return rates)")
ret_d1 = st.sidebar.number_input("D1 Retention (%)", 0.0, 100.0, 50.0, 1.0) / 100.0
ret_d7 = st.sidebar.number_input("D7 Retention (%)", 0.0, 100.0, 20.0, 1.0) / 100.0
ret_d14 = st.sidebar.number_input("D14 Retention (%)", 0.0, 100.0, 10.0, 1.0) / 100.0
ret_d30 = st.sidebar.number_input("D30 Retention (%)", 0.0, 100.0, 5.0, 1.0) / 100.0

st.sidebar.divider()
st.sidebar.subheader("Ad load & pricing")
inter_impr_per_dau = st.sidebar.number_input("Interstitial impressions per DAU", 0.0, 100.0, 6.0, 0.5)
inter_cpm = st.sidebar.number_input("Interstitial CPM ($)", 0.0, 500.0, 12.0, 0.5)

reward_impr_per_dau = st.sidebar.number_input("Rewarded impressions per DAU", 0.0, 100.0, 1.0, 0.5)
reward_cpm = st.sidebar.number_input("Rewarded CPM ($)", 0.0, 500.0, 25.0, 0.5)

st.sidebar.divider()
st.sidebar.subheader("Acquisition")
cpi = st.sidebar.number_input("CPI ($)", 0.0, 50.0, 0.50, 0.01)
organic_ratio = st.sidebar.number_input("Organic installs as % of paid (%)", 0.0, 300.0, 5.0, 1.0) / 100.0
paid_installs_daily = st.sidebar.number_input("Paid installs per day", 0, 10_000_000, 10000, 500)

st.sidebar.divider()
days = st.sidebar.slider("Forecast horizon (days)", 7, 180, 30, 1)

show_definitions = st.sidebar.checkbox("Show metric definitions ", value=True)
show_mechanics = st.sidebar.checkbox("Show model mechanics summary", value=True)

run = st.sidebar.button("Run forecast", use_container_width=True)

if not run:
    st.info("Enter your inputs on the left, then click **Run forecast**.")
    st.stop()

# -----------------------------
# Helpers
# -----------------------------
def build_retention_piecewise(days_count: int, d1: float, d7: float, d14: float, d30: float):
    """
    Piecewise linear interpolation across points (0,1,7,14,30).
    For days > 30, we hold retention flat at the D30 value.
    """
    points = {0: 1.0, 1: float(d1), 7: float(d7), 14: float(d14), 30: float(d30)}
    x = np.array(sorted(points.keys()), dtype=float)
    y = np.array([points[i] for i in x], dtype=float)
    idx = np.arange(days_count, dtype=float)
    idx_clip = np.minimum(idx, 30.0)
    ret = np.interp(idx_clip, x, y)
    return ret, points

def build_retention_exponential(days_count: int, d1: float):
    """
    Exponential decay: R(d) = exp(-lambda * d), calibrated so R(1) = D1.
    """
    d1 = float(np.clip(d1, 1e-9, 0.999999))
    lam = -np.log(d1)
    idx = np.arange(days_count, dtype=float)
    ret = np.exp(-lam * idx)
    return ret, lam

def cohort_stacking_dau(days_count: int, installs_daily_total: float, retention: np.ndarray):
    """
    DAU(t) = sum_{cohort_day=0..t} installs * retention(age)
    where age = t - cohort_day
    """
    dau = np.zeros(days_count, dtype=float)
    for t in range(days_count):
        ages = np.arange(t + 1, dtype=int)[::-1]
        dau[t] = float(np.sum(installs_daily_total * retention[ages]))
    return dau

def compute_forecast(days_count: int, installs_daily_total: float, daily_cost: float, arpdau: float, retention: np.ndarray):
    dau = cohort_stacking_dau(days_count, installs_daily_total, retention)
    revenue = dau * arpdau
    cost = np.repeat(daily_cost, days_count)
    profit = revenue - cost
    cum_profit = np.cumsum(profit)
    cum_revenue = np.cumsum(revenue)
    cum_cost = np.cumsum(cost)

    payback_day = None
    for i in range(days_count):
        if cum_profit[i] >= 0:
            payback_day = i + 1
            break

    return {
        "dau": dau,
        "revenue": revenue,
        "cost": cost,
        "profit": profit,
        "cum_profit": cum_profit,
        "cum_revenue": cum_revenue,
        "cum_cost": cum_cost,
        "payback_day": payback_day,
    }

def make_excel_bytes(inputs_df: pd.DataFrame, out_piece: pd.DataFrame, out_exp: pd.DataFrame, comp_df: pd.DataFrame, notes: str):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        inputs_df.to_excel(writer, sheet_name="Inputs", index=False)
        out_piece.to_excel(writer, sheet_name="Forecast_Piecewise", index=False)
        out_exp.to_excel(writer, sheet_name="Forecast_Exponential", index=False)
        comp_df.to_excel(writer, sheet_name="Comparison", index=False)

        wb = writer.book
        ws_notes = wb.add_worksheet("Notes")
        ws_notes.write(0, 0, notes)

        money_fmt = wb.add_format({"num_format": "$#,##0"})
        num_fmt = wb.add_format({"num_format": "#,##0"})
        dec5_fmt = wb.add_format({"num_format": "#,##0.00000"})

        for sh in ["Forecast_Piecewise", "Forecast_Exponential"]:
            ws = writer.sheets[sh]
            ws.set_column("A:A", 6)
            ws.set_column("B:B", 14, num_fmt)    # DAU
            ws.set_column("C:C", 14, money_fmt)  # Revenue
            ws.set_column("D:D", 12, money_fmt)  # Cost
            ws.set_column("E:E", 14, money_fmt)  # Profit
            ws.set_column("F:F", 16, money_fmt)  # CumProfit
            ws.set_column("G:G", 18, dec5_fmt)   # ARPDAU
            ws.set_column("H:H", 18, num_fmt)    # BreakEven DAU

        ws = writer.sheets["Comparison"]
        ws.set_column("A:A", 6)
        ws.set_column("B:E", 18)

    bio.seek(0)
    return bio

def pct(x: float) -> str:
    return f"{x:.2%}"

def fmt_money(x: float) -> str:
    return f"${x:,.0f}"

def fmt_num(x: float) -> str:
    return f"{x:,.0f}"

# -----------------------------
# Derived metrics
# -----------------------------
installs_daily_total = paid_installs_daily * (1 + organic_ratio)
daily_cost = paid_installs_daily * cpi

arpdau_ads = (inter_impr_per_dau * inter_cpm + reward_impr_per_dau * reward_cpm) / 1000.0
daily_break_even_dau = (daily_cost / arpdau_ads) if arpdau_ads > 0 else np.inf

# Build both retention curves (we will compare them side-by-side)
ret_piece, piece_points = build_retention_piecewise(days, ret_d1, ret_d7, ret_d14, ret_d30)
ret_exp, lam = build_retention_exponential(days, ret_d1)

# Compute forecasts
res_piece = compute_forecast(days, installs_daily_total, daily_cost, arpdau_ads, ret_piece)
res_exp = compute_forecast(days, installs_daily_total, daily_cost, arpdau_ads, ret_exp)

# Build output tables
base_cols = {
    "Day": np.arange(1, days + 1),
    "ARPDAU_ads": np.repeat(np.round(arpdau_ads, 5), days),
    "Daily_BreakEven_DAU": np.repeat(np.round(daily_break_even_dau, 2), days),
}

df_piece = pd.DataFrame({
    **base_cols,
    "DAU": np.round(res_piece["dau"], 2),
    "Revenue": np.round(res_piece["revenue"], 2),
    "Cost": np.round(res_piece["cost"], 2),
    "Profit": np.round(res_piece["profit"], 2),
    "CumProfit": np.round(res_piece["cum_profit"], 2),
})

df_exp = pd.DataFrame({
    **base_cols,
    "DAU": np.round(res_exp["dau"], 2),
    "Revenue": np.round(res_exp["revenue"], 2),
    "Cost": np.round(res_exp["cost"], 2),
    "Profit": np.round(res_exp["profit"], 2),
    "CumProfit": np.round(res_exp["cum_profit"], 2),
})

# Comparison summary
avg_dau_piece = float(np.mean(res_piece["dau"]))
avg_dau_exp = float(np.mean(res_exp["dau"]))
total_rev_piece = float(res_piece["cum_revenue"][-1])
total_rev_exp = float(res_exp["cum_revenue"][-1])
total_cost = float(res_piece["cum_cost"][-1])  # same for both
total_profit_piece = float(res_piece["cum_profit"][-1])
total_profit_exp = float(res_exp["cum_profit"][-1])

payback_piece = res_piece["payback_day"]
payback_exp = res_exp["payback_day"]

# Daily BE achieved?
daily_be_days_piece = np.where(res_piece["dau"] >= daily_break_even_dau)[0] + 1 if np.isfinite(daily_break_even_dau) else np.array([])
daily_be_days_exp = np.where(res_exp["dau"] >= daily_break_even_dau)[0] + 1 if np.isfinite(daily_break_even_dau) else np.array([])

comp_df = pd.DataFrame([
    ["Average DAU", avg_dau_piece, avg_dau_exp, avg_dau_piece - avg_dau_exp],
    ["Total Revenue (cum)", total_rev_piece, total_rev_exp, total_rev_piece - total_rev_exp],
    ["Total Cost (cum)", total_cost, total_cost, 0.0],
    ["Total Profit (cum)", total_profit_piece, total_profit_exp, total_profit_piece - total_profit_exp],
    ["Payback Day (cum profit >= 0)", payback_piece if payback_piece else np.nan, payback_exp if payback_exp else np.nan, np.nan],
], columns=["Metric", "Piecewise", "Exponential", "Piecewise - Exponential"])

# -----------------------------
# Inputs table
# -----------------------------
inputs_df = pd.DataFrame(
    [
        ["Retention D1/D7/D14/D30", f"{pct(ret_d1)} / {pct(ret_d7)} / {pct(ret_d14)} / {pct(ret_d30)}"],
        ["Interstitial Impr/DAU", inter_impr_per_dau],
        ["Interstitial CPM ($)", inter_cpm],
        ["Rewarded Impr/DAU", reward_impr_per_dau],
        ["Rewarded CPM ($)", reward_cpm],
        ["ARPDAU_ads ($/DAU/day)", arpdau_ads],
        ["CPI ($)", cpi],
        ["Paid installs/day", paid_installs_daily],
        ["Organic as % of paid", pct(organic_ratio)],
        ["Total installs/day", installs_daily_total],
        ["Daily UA cost ($)", daily_cost],
        ["Daily break-even DAU", daily_break_even_dau],
        ["Piecewise retention points", str(piece_points)],
        ["Exponential lambda (fit to D1)", lam],
    ],
    columns=["Input", "Value"],
)

# -----------------------------
# KPI cards
# -----------------------------
st.subheader("Key KPIs")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("ARPDAU (ads)", "-" if arpdau_ads <= 0 else f"${arpdau_ads:.3f}")
k2.metric("Daily UA Cost", fmt_money(daily_cost))
k3.metric("Daily Break-even DAU", "-" if not np.isfinite(daily_break_even_dau) else fmt_num(daily_break_even_dau))
k4.metric("Total Installs/day", fmt_num(installs_daily_total))
k5.metric("Horizon", f"{days} days")

# -----------------------------
# Narrative insights (automatic commentary)
# -----------------------------
st.subheader("What the results suggest (auto commentary)")

def commentary_for_method(name: str, payback_day, daily_be_days, total_profit: float, total_rev: float):
    lines = []
    if arpdau_ads <= 0:
        return ["ARPDAU is 0 (or negative), which means ad revenue cannot be computed. Check CPM and impression inputs."]

    # Daily break-even
    if daily_be_days.size > 0:
        lines.append(f"- **Daily break-even** is first reached on **Day {int(daily_be_days[0])}** (DAU crosses the daily break-even threshold).")
    else:
        lines.append(f"- **Daily break-even is not reached** within {days} days (DAU stays below the daily break-even threshold).")

    # Payback
    if payback_day is not None:
        lines.append(f"- **Payback day (cumulative profit turns positive)** happens on **Day {payback_day}**.")
    else:
        lines.append(f"- **No payback within {days} days** (cumulative profit remains negative).")

    # End-state
    sign = "positive" if total_profit >= 0 else "negative"
    lines.append(f"- End of horizon: cumulative profit is **{sign}** (**{fmt_money(total_profit)}**) on total revenue **{fmt_money(total_rev)}**.")
    return [f"**{name}**"] + lines

colA, colB = st.columns(2)
with colA:
    for s in commentary_for_method("Piecewise model", payback_piece, daily_be_days_piece, total_profit_piece, total_rev_piece):
        st.write(s)

with colB:
    for s in commentary_for_method("Exponential model", payback_exp, daily_be_days_exp, total_profit_exp, total_rev_exp):
        st.write(s)

# Comparison callout
st.markdown("**Model comparison (how to interpret the difference):**")
if abs(total_profit_piece - total_profit_exp) < 1e-6:
    st.write("- Both models land on effectively the same profit. That usually happens when retention shapes are similar in the first weeks.")
else:
    better = "Piecewise" if total_profit_piece > total_profit_exp else "Exponential"
    delta = total_profit_piece - total_profit_exp
    st.write(f"- **{better}** is more optimistic here by **{fmt_money(abs(delta))}** cumulative profit over {days} days.")
    st.write("- In practice, Piecewise is usually preferred when you trust the D7/D14/D30 points; exponential is a smoother benchmark.")

st.write("- If you want a conservative planning view, consider using the lower of the two profit curves as your base case.")

# Actionable growth levers (simple heuristic guidance)
st.markdown("**Where I’d look first (practical levers):**")
if arpdau_ads > 0 and daily_break_even_dau != np.inf:
    st.write("- If you’re missing break-even, you typically need either **higher ARPDAU** (CPM/ad load) or **higher retention** (more DAU compounding).")
st.write("- Rewarded ads are often a safer ARPDAU lever than interstitial frequency (less retention damage when designed well).")
st.write("- CPI is the hard constraint: if CPI rises, payback moves out unless retention/monetization improves.")

# -----------------------------
# Layout: tables
# -----------------------------
t1, t2, t3 = st.columns([1, 1, 1])
with t1:
    st.subheader("Inputs")
    st.dataframe(inputs_df, use_container_width=True, height=420)

with t2:
    st.subheader("Forecast (Piecewise)")
    st.dataframe(df_piece, use_container_width=True, height=420)

with t3:
    st.subheader("Forecast (Exponential)")
    st.dataframe(df_exp, use_container_width=True, height=420)

st.subheader("Comparison summary")
st.dataframe(comp_df, use_container_width=True)

# -----------------------------
# Plotly charts
# -----------------------------
st.subheader("Charts (interactive)")

# Chart 1: DAU comparison + break-even line
fig1 = go.Figure()
fig1.add_trace(go.Scatter(
    x=df_piece["Day"], y=df_piece["DAU"],
    mode="lines+markers", name="DAU (Piecewise)",
    hovertemplate="Day %{x}<br>DAU %{y:,.0f}<extra></extra>"
))
fig1.add_trace(go.Scatter(
    x=df_exp["Day"], y=df_exp["DAU"],
    mode="lines+markers", name="DAU (Exponential)",
    hovertemplate="Day %{x}<br>DAU %{y:,.0f}<extra></extra>"
))
fig1.add_trace(go.Scatter(
    x=df_piece["Day"], y=df_piece["Daily_BreakEven_DAU"],
    mode="lines", name="Daily Break-even DAU",
    line=dict(dash="dash"),
    hovertemplate="Day %{x}<br>Break-even %{y:,.0f}<extra></extra>"
))
fig1.update_layout(
    title="DAU: Piecewise vs Exponential (with Daily Break-even Threshold)",
    xaxis_title="Day", yaxis_title="Users",
    hovermode="x unified",
    legend_title_text="Series"
)
st.plotly_chart(fig1, use_container_width=True)

# Chart 2: Daily revenue vs cost (piecewise) + (optional) exponential
fig2 = go.Figure()
fig2.add_trace(go.Scatter(
    x=df_piece["Day"], y=df_piece["Revenue"],
    mode="lines+markers", name="Revenue (Piecewise)",
    hovertemplate="Day %{x}<br>Revenue $%{y:,.0f}<extra></extra>"
))
fig2.add_trace(go.Scatter(
    x=df_exp["Day"], y=df_exp["Revenue"],
    mode="lines+markers", name="Revenue (Exponential)",
    hovertemplate="Day %{x}<br>Revenue $%{y:,.0f}<extra></extra>"
))
fig2.add_trace(go.Scatter(
    x=df_piece["Day"], y=df_piece["Cost"],
    mode="lines", name="Daily UA Cost",
    line=dict(dash="dash"),
    hovertemplate="Day %{x}<br>Cost $%{y:,.0f}<extra></extra>"
))
fig2.update_layout(
    title="Daily Revenue vs Daily UA Cost",
    xaxis_title="Day", yaxis_title="$",
    hovermode="x unified",
    legend_title_text="Series"
)
st.plotly_chart(fig2, use_container_width=True)

# Chart 3: Cumulative profit comparison
fig3 = go.Figure()
fig3.add_trace(go.Scatter(
    x=df_piece["Day"], y=df_piece["CumProfit"],
    mode="lines+markers", name="Cumulative Profit (Piecewise)",
    hovertemplate="Day %{x}<br>CumProfit $%{y:,.0f}<extra></extra>"
))
fig3.add_trace(go.Scatter(
    x=df_exp["Day"], y=df_exp["CumProfit"],
    mode="lines+markers", name="Cumulative Profit (Exponential)",
    hovertemplate="Day %{x}<br>CumProfit $%{y:,.0f}<extra></extra>"
))
fig3.add_hline(y=0, line_dash="dash", annotation_text="Payback line (0)", annotation_position="top left")
fig3.update_layout(
    title="Cumulative Profit (Payback View)",
    xaxis_title="Day", yaxis_title="$",
    hovermode="x unified",
    legend_title_text="Series"
)
st.plotly_chart(fig3, use_container_width=True)

# Chart 4: Retention curves used
fig4 = go.Figure()
fig4.add_trace(go.Scatter(
    x=np.arange(days), y=ret_piece,
    mode="lines+markers", name="Retention (Piecewise)",
    hovertemplate="Day %{x}<br>Retention %{y:.2%}<extra></extra>"
))
fig4.add_trace(go.Scatter(
    x=np.arange(days), y=ret_exp,
    mode="lines+markers", name="Retention (Exponential)",
    hovertemplate="Day %{x}<br>Retention %{y:.2%}<extra></extra>"
))
fig4.update_layout(
    title="Retention Curves Used by Each Model",
    xaxis_title="Days since install",
    yaxis_title="Retention",
    hovermode="x unified",
    legend_title_text="Series"
)
st.plotly_chart(fig4, use_container_width=True)

# -----------------------------
# Excel export
# -----------------------------
notes = (
    "Generated by the 30-Day Forecast Dashboard.\n\n"
    "How to read:\n"
    "- Forecast_* sheets: Daily DAU, Revenue, Cost, Profit, CumProfit.\n"
    "- Comparison: Side-by-side totals and averages.\n\n"
    "Important:\n"
    "- This is an ads-only revenue model (no IAP).\n"
    "- Cohort stacking assumes constant daily installs.\n"
    "- Piecewise is anchored to D1/D7/D14/D30 points.\n"
    "- Exponential is a smooth benchmark fit to D1.\n"
)

excel_bytes = make_excel_bytes(inputs_df, df_piece, df_exp, comp_df, notes)
st.download_button(
    "Download Excel (Inputs + Both Forecasts + Comparison)",
    data=excel_bytes,
    file_name="forecast_30d_dashboard.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

# -----------------------------
# Explanations 
# -----------------------------
if show_mechanics:
    st.divider()
    with st.expander("Model mechanics (what’s happening under the hood)", expanded=False):
        st.markdown(f"""
### 1) Derived values
- **Total installs/day** = Paid × (1 + Organic%)  
  → `{paid_installs_daily} × (1 + {organic_ratio:.2%}) = {installs_daily_total:,.0f}`
- **ARPDAU (ads)** = (Inter impressions × Inter CPM + Rewarded impressions × Rewarded CPM) / 1000  
  → `({inter_impr_per_dau}×{inter_cpm} + {reward_impr_per_dau}×{reward_cpm}) / 1000 = ${arpdau_ads:.3f} per DAU per day`
- **Daily UA cost** = Paid installs/day × CPI  
  → `{paid_installs_daily} × ${cpi:.2f} = ${daily_cost:,.0f}`
- **Daily break-even DAU** = Daily UA cost / ARPDAU  
  → `${daily_cost:,.0f} / ${arpdau_ads:.3f} = {daily_break_even_dau:,.0f} DAU`

### 2) Retention curve construction
- **Piecewise Linear:** We connect D0, D1, D7, D14, D30 with straight lines (simple interpolation).
- **Exponential:** We use **R(d)=exp(-λd)** and set **R(1)=D1** (a smooth benchmark).

### 3) DAU forecast via cohort stacking
Every day adds a new cohort of installs. On day *t*, we sum active users from all cohorts:

**DAU(t) = Σ installs(cohort_day) × retention(age)**, where **age = t − cohort_day**.

This mirrors how DAU compounds in real mobile growth when daily acquisition is steady.

### 4) Revenue, cost, profit
- **Revenue(t) = DAU(t) × ARPDAU**
- **Profit(t) = Revenue(t) − Daily UA cost**
- **Payback day** is the first day where cumulative profit crosses zero.
""")

if show_definitions:
    st.divider()
    with st.expander("Metric definitions", expanded=False):
        st.markdown("""
### Retention (D1 / D7 / D14 / D30)
Retention is the percent of users who return on a specific day after install.
- **D1** is your first impression: onboarding + early fun.
- **D7** is early habit formation: “is this game part of my routine?”
- **D30** is long-term stickiness.

Higher retention compounds DAU over time and is one of the strongest drivers of LTV.

### DAU (Daily Active Users)
DAU is the number of unique users who play the game on a given day.
For ad-monetized games, DAU is the main volume driver: revenue scales with it.

### Impressions per DAU
How many ads each active user sees per day.
- More impressions usually increase revenue.
- But pushing interstitials too hard can hurt retention (so you want a balance).

### CPM (Cost per Mille)
Revenue per 1,000 impressions.
Higher CPM means each impression is more valuable (often driven by geo, demand, and traffic quality).

### ARPDAU (Average Revenue per DAU)
Average ad revenue generated by one active user in one day.
In this dashboard:  
**ARPDAU = (Inter Impr × Inter CPM + Rewarded Impr × Rewarded CPM) / 1000**

### CPI (Cost per Install)
How much you pay for one paid install.
To scale profitably, you typically want **LTV > CPI** (or at least a clear path to get there).

### Organic ratio
Organic installs relative to paid installs.
Higher organic uplift reduces blended acquisition cost and improves growth efficiency.

### Daily break-even DAU
The DAU level where *today’s* ad revenue covers *today’s* UA cost:
**Break-even DAU = Daily UA cost / ARPDAU**

### Payback day
The first day when cumulative profit becomes positive.
Shorter payback cycles usually enable safer scaling.
""")

