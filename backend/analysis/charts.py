"""
analysis/charts.py

Generates Plotly charts from financial ratio data and raw financial metrics.
Saves and compiles all visual assets into a single cohesive HTML page layout.
"""

import os
import sys
import webbrowser
import plotly.graph_objects as go
import numpy as np


# Color palette assigned per-company by index (no hardcoded ticker -> color map).
PALETTE = ["#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#76B7B2",
           "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]


# =====================================================================
# CORE VISUALIZATION FUNCTIONS
# =====================================================================

def yoy_line_chart(ratios, metric_name, company_name="Company"):
    """
    Line chart showing one metric over time for a single company.
    """
    years = sorted(ratios.keys())
    values = [ratios[year].get(metric_name) for year in years]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years,
        y=values,
        mode='lines+markers',
        name=company_name,
        line=dict(width=3, color='#4E79A7'),
        marker=dict(size=8)
    ))

    fig.update_layout(
        title=f"{company_name} — {metric_name.replace('_', ' ').title()} Over Time",
        xaxis=dict(
            title="Fiscal Year End",
            type="category",
            automargin=True,
            tickangle=45
        ),
        yaxis=dict(
            title=metric_name.replace('_', ' ').title(),
            automargin=True
        ),
        template="plotly_white",
        hovermode="x unified",
        showlegend=False
    )

    return fig


def yoy_comparison_chart(all_ratios, metric_name, company_names):
    """
    Line chart comparing one metric across multiple companies over time.
    """
    fig = go.Figure()

    for ticker, ratios in all_ratios.items():
        years = sorted(ratios.keys())
        values = [ratios[year].get(metric_name) for year in years]

        fig.add_trace(go.Scatter(
            x=years,
            y=values,
            mode='lines+markers',
            name=company_names.get(ticker, ticker),
            line=dict(width=3),
            marker=dict(size=8)
        ))

    fig.update_layout(
        title=f"{metric_name.replace('_', ' ').title()} — Company Comparison Over Time",
        xaxis=dict(title="Fiscal Year End", type="category", automargin=True, tickangle=45),
        yaxis=dict(title=metric_name.replace('_', ' ').title(), automargin=True),
        margin=dict(b=100),
        template="plotly_white",
        hovermode="x unified"
    )

    return fig


def quarterly_bar_chart(quarterly_data, metric_name, year, company_name="Company"):
    """
    Bar chart showing Q1-Q4 values for one metric, for one company, in one fiscal year.
    """
    quarters_dict = quarterly_data.get(year, {})
    quarter_labels = ["Q1", "Q2", "Q3", "Q4"]
    values = [quarters_dict.get(q) for q in quarter_labels]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=quarter_labels,
        y=values,
        marker_color='#4C78A8',
        text=[f"${v:,.0f}" if v is not None else "N/A" for v in values],
        textposition='outside'
    ))

    fig.update_layout(
        title=f"{company_name} — {metric_name.replace('_', ' ').title()} by Quarter (FY ending {year})",
        xaxis=dict(title="Quarter", automargin=True),
        yaxis=dict(title=metric_name.replace('_', ' ').title(), automargin=True),
        template="plotly_white",
        showlegend=False
    )

    return fig


def peer_comparison_bar_chart(all_ratios, metric_name, target_year, company_names):
    """
    Bar chart comparing a single metric across all companies for a specific year.
    Bulletproof parsing version to handle sector reporting date alignment errors.
    """
    tickers = list(all_ratios.keys())
    values = []
    labels = []

    # Clean target year down to a plain 4-digit number string (e.g., "2025")
    target_year_str = str(target_year)[:4]

    for ticker in tickers:
        company_data = all_ratios.get(ticker, {})
        matched_value = None

        # Match if the target year shows up anywhere in the reporting-date key
        for reporting_date, metrics in company_data.items():
            reporting_date_str = str(reporting_date)
            if target_year_str in reporting_date_str:
                matched_value = metrics.get(metric_name)
                break

        # Fallback: if no date matched, grab the most recent year available
        if matched_value is None:
            if company_data:
                latest_available_date = max(list(company_data.keys()))
                matched_value = company_data[latest_available_date].get(metric_name)

        # Safety rail: still None -> 0.0 so the frame renders
        if matched_value is None:
            matched_value = 0.0

        values.append(matched_value)
        labels.append(company_names.get(ticker, ticker))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels,
        y=values,
        marker_color='#4C78A8',
        text=[f"{v:.2f}" if v != 0.0 else "N/A" for v in values],
        textposition='auto'
    ))

    fig.update_layout(
        title=f"Peer Comparison: {metric_name.replace('_', ' ').title()} ({target_year_str})",
        xaxis=dict(title="Company", automargin=True),
        yaxis=dict(title=metric_name.replace('_', ' ').title(), automargin=True),
        template="plotly_white"
    )

    return fig


def margin_breakdown_stacked_chart(company_metrics, company_name="Company"):
    """
    Stacked bar chart showing COGS vs Gross Profit over multiple years.
    """
    cogs_dict = company_metrics.get('cogs', {}).get('values', {})
    gp_dict = company_metrics.get('gross_profit', {}).get('values', {})

    years = sorted(list(set(cogs_dict.keys()) | set(gp_dict.keys())))

    cogs_values = [cogs_dict.get(year, 0) for year in years]
    gross_profit_values = [gp_dict.get(year, 0) for year in years]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=years,
        y=cogs_values,
        name='Cost of Goods Sold (COGS)',
        marker_color='#E15759'
    ))

    fig.add_trace(go.Bar(
        x=years,
        y=gross_profit_values,
        name='Gross Profit',
        marker_color='#4E79A7'
    ))

    fig.update_layout(
        barmode='stack',
        title=f"{company_name} — Margin Breakdown Over Time",
        xaxis=dict(title="Fiscal Year End", type="category", automargin=True, tickangle=45),
        yaxis=dict(title="Amount ($)", automargin=True),
        template="plotly_white",
        hovermode="x unified"
    )

    return fig


def revenue_vs_profit_chart(company_metrics, company_name="Company"):
    """
    Dual-axis line chart tracking Revenue vs Net Income over time.
    """
    rev_dict = company_metrics.get('revenue', {}).get('values', {})
    ni_dict = company_metrics.get('net_income', {}).get('values', {})

    years = sorted(list(set(rev_dict.keys()) | set(ni_dict.keys())))

    revenue = [rev_dict.get(year) for year in years]
    net_income = [ni_dict.get(year) for year in years]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=years,
        y=revenue,
        mode='lines+markers',
        name='Total Revenue',
        line=dict(width=3, color='#4E79A7')
    ))

    fig.add_trace(go.Scatter(
        x=years,
        y=net_income,
        mode='lines+markers',
        name='Net Income',
        line=dict(width=3, color='#F28E2B'),
        yaxis='y2'
    ))

    fig.update_layout(
        title=f"{company_name} — Revenue vs Net Income Trend",
        xaxis=dict(title="Fiscal Year End", type="category", automargin=True, tickangle=45),
        yaxis=dict(
            title=dict(text="Revenue ($)", font=dict(color="#4E79A7")),
            tickfont=dict(color="#4E79A7"),
            automargin=True
        ),
        yaxis2=dict(
            title=dict(text="Net Income ($)", font=dict(color="#F28E2B")),
            tickfont=dict(color="#F28E2B"),
            overlaying='y',
            side='right',
            automargin=True
        ),
        template="plotly_white",
        hovermode="x unified"
    )

    return fig


def price_history_chart(stock_data, company_names):
    """
    Line chart showing daily closing price history for the active portfolio context.
    """
    fig = go.Figure()

    for i, (name, data) in enumerate(stock_data.items()):
        history = data["history"]
        if history.empty:
            continue
        fig.add_trace(go.Scatter(
            x=history.index,
            y=history["Close"],
            mode='lines',
            name=company_names.get(name, name),
            line=dict(width=2, color=PALETTE[i % len(PALETTE)])
        ))

    fig.update_layout(
        title="Stock Price History",
        xaxis=dict(title="Date", automargin=True, tickangle=45),
        yaxis=dict(title="Closing Price (USD)", automargin=True),
        template="plotly_white",
        hovermode="x unified",
        legend_title="Company"
    )

    return fig


def returns_comparison_chart(stock_data, company_names):
    """
    Grouped bar chart comparing 1M, 3M, 6M, 1Y returns across active tracking targets.
    """
    return_periods = ["1_month_return_pct", "3_month_return_pct",
                      "6_month_return_pct", "1_year_return_pct"]
    period_labels = ["1 Month", "3 Months", "6 Months", "1 Year"]

    fig = go.Figure()

    for i, (name, data) in enumerate(stock_data.items()):
        returns = data["returns"]
        values = [returns.get(p) for p in return_periods]
        fig.add_trace(go.Bar(
            x=period_labels,
            y=values,
            name=company_names.get(name, name),
            marker_color=PALETTE[i % len(PALETTE)]
        ))

    fig.update_layout(
        title="Stock Returns Comparison",
        xaxis=dict(title="Period", automargin=True),
        yaxis=dict(title="Return (%)", automargin=True),
        barmode="group",
        template="plotly_white",
        legend_title="Company"
    )

    return fig


def normal_distribution_chart(analysis_result, company_name="Company"):
    """
    Plots the statistical probability density bell curve for corporate metrics.
    """
    standardized = analysis_result["standardized"]
    metric_name = analysis_result["metric_name"]

    if not standardized:
        return None

    sample = list(standardized.values())[0]
    mean = sample["mean"]
    std = sample["std"]

    if std == 0:
        std = 0.001  # Prevent division by zero constraints

    x = np.linspace(mean - 4*std, mean + 4*std, 300)
    y = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean) / std) ** 2)

    fig = go.Figure()

    # ±2σ band
    x_2sig = np.linspace(mean - 2*std, mean + 2*std, 100)
    y_2sig = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_2sig - mean) / std) ** 2)
    fig.add_trace(go.Scatter(
        x=np.concatenate([x_2sig, x_2sig[::-1]]),
        y=np.concatenate([y_2sig, np.zeros(len(y_2sig))]),
        fill='toself', fillcolor='rgba(255, 165, 0, 0.15)',
        line=dict(color='rgba(255,255,255,0)'),
        name='±2σ range'
    ))

    # ±1σ band
    x_1sig = np.linspace(mean - std, mean + std, 100)
    y_1sig = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_1sig - mean) / std) ** 2)
    fig.add_trace(go.Scatter(
        x=np.concatenate([x_1sig, x_1sig[::-1]]),
        y=np.concatenate([y_1sig, np.zeros(len(y_1sig))]),
        fill='toself', fillcolor='rgba(78, 121, 167, 0.2)',
        line=dict(color='rgba(255,255,255,0)'),
        name='±1σ range'
    ))

    # Main curve
    fig.add_trace(go.Scatter(
        x=x, y=y, mode='lines',
        line=dict(color='#4E79A7', width=2),
        showlegend=False
    ))

    # Mean line
    fig.add_vline(x=mean, line_dash="dash", line_color="gray",
                 annotation_text=f"μ={mean:.2f}")

    # Plot each year as a dot
    for year, data in standardized.items():
        val = data["value"]
        y_val = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((val - mean) / std) ** 2)
        is_anomaly = data["is_anomaly"]
        color = '#E15759' if is_anomaly else '#4E79A7'
        label = f"{year[:4]} ⚠️" if is_anomaly else year[:4]
        fig.add_trace(go.Scatter(
            x=[val], y=[y_val],
            mode='markers',
            marker=dict(size=10, color=color, line=dict(width=2, color='white')),
            name=label,
            hovertemplate=f"{label}: {val:.2f}<extra></extra>",
            showlegend=is_anomaly
        ))

    fig.update_layout(
        title=f"{company_name} — {metric_name.replace('_', ' ').title()} Distribution",
        xaxis=dict(title=metric_name.replace('_', ' ').title(), automargin=True),
        yaxis=dict(title="Probability Density", automargin=True),
        template="plotly_white"
    )

    return fig


def prediction_chart(analysis_result, company_name="Company"):
    """
    Renders time-series forecasts with dynamic scale configurations to fix visual overlaps.
    """
    standardized = analysis_result["standardized"]
    prediction = analysis_result["prediction"]
    metric_name = analysis_result["metric_name"]

    if not standardized or not prediction:
        return None

    years = sorted(standardized.keys())
    values = [standardized[y]["value"] for y in years]
    anomaly_years = {y for y in years if standardized[y]["is_anomaly"]}

    pred_val = prediction["predicted_value"]
    ci_lower, ci_upper = prediction["confidence_interval"]

    x_hist = list(range(len(years)))
    x_pred = len(years)
    all_x = x_hist + [x_pred]

    if len(years) > 50:
        all_labels = None
    else:
        all_labels = [y[:4] for y in years] + ["Next\n(proj)"]

    fig = go.Figure()

    # Historical baseline channel
    fig.add_trace(go.Scatter(
        x=x_hist, y=values,
        mode='lines',
        name='Historical Baseline',
        line=dict(color='#4E79A7', width=2),
        hovertemplate='Interval: %{text}<br>Value: %{y:.2f}<extra></extra>',
        text=years
    ))

    reliability = prediction.get("reliability", "low")
    r2_color = {"high": "#59A14F", "moderate": "#F28E2B", "low": "#E15759"}.get(reliability, "#E15759")
    r2_fill = {"high": "rgba(89, 161, 79, 0.15)", "moderate": "rgba(242, 142, 43, 0.15)", "low": "rgba(225, 87, 89, 0.15)"}.get(reliability, "rgba(225, 87, 89, 0.15)")

    # Shaded boundary thresholds
    fig.add_trace(go.Scatter(
        x=[x_hist[-1], x_pred, x_pred, x_hist[-1]],
        y=[values[-1], ci_upper, ci_lower, values[-1]],
        fill='toself',
        fillcolor=r2_fill,
        line=dict(color=r2_color, dash='dot'),
        name=f'95% CI ({reliability.upper()})',
    ))

    # Prediction target node
    fig.add_trace(go.Scatter(
        x=[x_pred], y=[pred_val],
        mode='markers+text',
        marker=dict(size=12, color=r2_color, symbol='diamond', line=dict(width=2, color='white')),
        text=[f"${pred_val:.2f}" if len(years) > 50 else f"{pred_val:.2f}"],
        textposition='top center',
        name=f'Target (R²={prediction["r_squared"]})'
    ))

    # Limit legends for large daily time-series loops
    show_anomaly_legend = True if len(years) < 50 else False

    for i, year in enumerate(years):
        if year in anomaly_years:
            fig.add_trace(go.Scatter(
                x=[i], y=[values[i]],
                mode='markers',
                marker=dict(size=8 if len(years) > 50 else 14,
                            color='#E15759', symbol='circle-open',
                            line=dict(width=1.5 if len(years) > 50 else 3, color='#E15759')),
                name=f"Volatility Event" if len(years) > 50 else f"Anomaly {year[:4]}",
                hovertemplate=f"Volatility Outlier {year}: {values[i]:.2f}<extra></extra>",
                showlegend=show_anomaly_legend
            ))

    trend_color = {"improving": "green", "declining": "red", "stable": "gray"}
    fig.add_annotation(
        x=0.02, y=0.98, xref="paper", yref="paper",
        text=f"Trend: {prediction['trend'].upper()} | R²: {prediction['r_squared']} | Confidence: {reliability.upper()}",
        showarrow=False,
        font=dict(size=11, color=trend_color.get(prediction['trend'], 'gray')),
        align="left", bgcolor="rgba(255,255,255,0.8)"
    )

    fig.update_layout(
        title=f"{company_name} — {metric_name.replace('_', ' ').title()} Prediction",
        xaxis=dict(
            title="Timeline Interval",
            tickmode='array' if len(years) < 50 else 'auto',
            tickvals=all_x if len(years) < 50 else None,
            ticktext=all_labels if len(years) < 50 else None,
            nticks=5 if len(years) > 50 else None,
            automargin=True,
            tickangle=0 if len(years) > 50 else 45
        ),
        yaxis=dict(title=metric_name.replace('_', ' ').title(), automargin=True),
        template="plotly_white",
        hovermode="x unified"
    )

    return fig


# =====================================================================
# SINGLE PAGE HTML GENERATOR
# =====================================================================

def generate_dashboard_page(figures, filename="financial_dashboard.html"):
    """
    Compiles a collection of Plotly figures into a clean grid system
    saved inside a single HTML file.
    """
    # Filter out any None figures that didn't render.
    figures = [fig for fig in figures if fig is not None]

    divs = [fig.to_html(full_html=False, include_plotlyjs='cdn') for fig in figures]

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FinSight Financial Performance Dashboard</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: #f4f6f9;
                margin: 0;
                padding: 20px;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background-color: #ffffff;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            }}
            .header h1 {{ margin: 0; color: #2C3E50; font-size: 28px; }}
            .header p {{ margin: 5px 0 0 0; color: #7F8C8D; }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(600px, 1fr));
                gap: 25px;
            }}
            .chart-card {{
                background-color: #ffffff;
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.05);
                min-height: 450px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>FinSight Executive Analytics Dashboard</h1>
            <p>Consolidated view of trends, metrics, margins, and comparative analytics.</p>
        </div>
        <div class="grid">
    """

    for div in divs:
        html_content += f'\n<div class="chart-card">{div}</div>'

    html_content += """
        </div>
    </body>
    </html>
    """

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n[Success] Dashboard compiled into: {os.path.abspath(filename)}")
    webbrowser.open(f"file://{os.path.abspath(filename)}")


import re

def answer_metric_query(user_query, all_raw_metrics, all_ratios, all_figures):
    """
    NLP routing that prioritizes multi-company peer comparisons before defaulting
    to single-company macro trend lookups. Operates only over the companies that
    were actually loaded this session (the keys of all_raw_metrics).
    """
    query = user_query.strip().upper()
    loaded_tickers = list(all_raw_metrics.keys())
    active_ticker = loaded_tickers[0] if loaded_tickers else None

    if active_ticker is None:
        return "No company data is loaded for this session.", None

    # 1. TIME-SLICE REGEX EXTRACTION (e.g., "Q4 2025")
    quarter_match = re.search(r'\bQ([1-4])\b', query)
    year_match = re.search(r'\b(20\d{2})\b', query)

    requested_quarter = f"Q{quarter_match.group(1)}" if quarter_match else None
    requested_year = year_match.group(1) if year_match else None

    # 2. TICKER PARSING FOR PEER COMPARISONS — only among loaded companies.
    peer_ticker_match = None
    for ticker_key in loaded_tickers:
        if ticker_key != active_ticker and re.search(rf'\b{re.escape(ticker_key)}\b', query):
            peer_ticker_match = ticker_key
            break

    # 3. FINANCIAL METRIC KEY MAPPING
    metric_key = None
    metric_label = ""

    if "GROSS MARGIN" in query or "GROSS PROFIT" in query or "GROSSMARGIN" in query:
        metric_key = "gross_profit" if requested_quarter else "gross_margin_pct"
        metric_label = "Gross Profit" if requested_quarter else "Gross Margin Percentage"
    elif "OPERATING INCOME" in query or "OPERATING MARGIN" in query:
        metric_key = "operating_income"
        metric_label = "Operating Income"
    elif "NET INCOME" in query or "PROFIT" in query:
        metric_key = "net_income"
        metric_label = "Net Income"
    elif "COGS" in query or "COST OF GOODS" in query:
        metric_key = "cogs"
        metric_label = "Cost of Goods Sold (COGS)"
    elif "REVENUE" in query or "SALES" in query:
        metric_key = "revenue"
        metric_label = "Total Revenue"
    elif "INVENTORY TURNOVER" in query:
        metric_key = "inventory_turnover"
        metric_label = "Inventory Turnover"
    elif "DEBT TO EQUITY" in query or "LEVERAGE" in query:
        metric_key = "debt_to_equity"
        metric_label = "Debt to Equity"

    if not metric_key and not any(k in query for k in ["STOCK", "PRICE", "RETURNS", "FORECAST", "PREDICT"]):
        return "🔍 I couldn't identify the financial metric. Try asking about Revenue, Gross Profit, Operating Income, Net Income, Inventory Turnover, or Debt to Equity.", None

    # =====================================================================
    # PRIORITY 1: CROSS-SECTIONAL MULTI-COMPANY PEER COMPARISON
    # =====================================================================
    if peer_ticker_match and metric_key:
        t1_data = {}
        t2_data = {}

        if metric_key in all_raw_metrics.get(active_ticker, {}):
            t1_data = all_raw_metrics[active_ticker][metric_key].get("values", {})
        else:
            t1_data = {yr: r[metric_key] for yr, r in all_ratios.get(active_ticker, {}).items() if metric_key in r}

        if metric_key in all_raw_metrics.get(peer_ticker_match, {}):
            t2_data = all_raw_metrics[peer_ticker_match][metric_key].get("values", {})
        else:
            t2_data = {yr: r[metric_key] for yr, r in all_ratios.get(peer_ticker_match, {}).items() if metric_key in r}

        if t1_data and t2_data:
            t1_latest_year = max(t1_data.keys())
            t2_latest_year = max(t2_data.keys())

            val_1 = t1_data[t1_latest_year]
            val_2 = t2_data[t2_latest_year]

            fmt_t1 = f"${val_1:,.2f}" if "pct" not in metric_key else f"{val_1:.2f}%"
            fmt_t2 = f"${val_2:,.2f}" if "pct" not in metric_key else f"{val_2:.2f}%"

            leader = active_ticker if val_1 > val_2 else peer_ticker_match
            gap = abs(val_1 - val_2)
            suffix = "%" if "pct" in metric_key else ""

            insight = (
                f"📊 **Peer Analysis:** For the latest reporting cycle, "
                f"{active_ticker} reported a {metric_label} of **{fmt_t1}** vs. "
                f"{peer_ticker_match} at **{fmt_t2}**. "
                f"This gives **{leader}** an edge of **{gap:.2f}{suffix}**."
            )

            related_chart = None
            for fig in all_figures:
                if fig and fig.layout.title.text:
                    title_txt = fig.layout.title.text.lower()
                    if "comparison" in title_txt and metric_label.lower() in title_txt:
                        related_chart = fig
                        break
            return insight, related_chart

    # =====================================================================
    # PRIORITY 2: GRANULAR QUARTERLY TIME-SLICE LOOKUPS
    # =====================================================================
    if requested_quarter and requested_year and metric_key:
        quarterly_maps = all_raw_metrics.get(active_ticker, {}).get(metric_key, {}).get("quarterly", {})
        related_chart = None
        for fig in all_figures:
            if fig and fig.layout.title.text:
                title_text = fig.layout.title.text.upper()
                if metric_label.upper() in title_text and "BY QUARTER" in title_text and requested_year in title_text:
                    related_chart = fig
                    break

        target_data_point = None
        for data_date, quarters in quarterly_maps.items():
            if requested_year in data_date:
                target_data_point = quarters.get(requested_quarter)
                break

        if target_data_point is not None:
            return f"📊 **Time-Slice Extraction Complete:** {active_ticker}'s {metric_label} for **{requested_quarter} {requested_year}** was **${target_data_point:,.2f}**.", related_chart
        else:
            return f"⚠️ Could not locate matching quarterly data for {active_ticker} in {requested_quarter} {requested_year}.", related_chart

    # =====================================================================
    # PRIORITY 3: SINGLE-COMPANY MACRO TRENDS / PREDICTIONS
    # =====================================================================
    related_chart = None
    search_token = ""

    if "PREDICT" in query or "FORECAST" in query:
        search_token = "prediction"
        insight_prefix = "🔮 **Time-Series Predictive Insights:**"
    elif "DISTRIBUTION" in query or "ANOMALY" in query:
        search_token = "distribution"
        insight_prefix = "📈 **Statistical Distribution Analysis:**"
    elif "STOCK PRICE" in query or "RETURNS" in query:
        search_token = "stock price history" if "PRICE" in query else "returns comparison"
        insight_prefix = "📉 **Market Momentum Summary:**"
    else:
        search_token = "over time" if not requested_year else "comparison"
        insight_prefix = "📈 **Macro Trend Directional Summary:**"

    for fig in all_figures:
        if fig and fig.layout.title.text:
            title_text = fig.layout.title.text.lower()
            if search_token in title_text and (metric_label.lower() in title_text or search_token in ["stock price history", "returns comparison"]):
                related_chart = fig
                break

    metric_data = {}
    if metric_key in all_raw_metrics.get(active_ticker, {}):
        metric_data = all_raw_metrics[active_ticker][metric_key].get("values", {})
    elif metric_key:
        for yr, ratios in all_ratios.get(active_ticker, {}).items():
            if metric_key in ratios:
                metric_data[yr] = ratios[metric_key]

    if not metric_data:
        if "STOCK" in query:
            return f"{insight_prefix} Extracted live market timelines for {active_ticker}. Refer to the linked chart asset below.", related_chart
        return f"I recognized the request for {metric_label}, but no history exists for {active_ticker}.", None

    sorted_years = sorted(metric_data.keys())
    start_val, end_val = metric_data[sorted_years[0]], metric_data[sorted_years[-1]]
    pct_change = ((end_val - start_val) / start_val) * 100 if start_val != 0 else 0

    direction = "improving" if end_val > start_val else "declining"
    fmt_start = f"${start_val:,.2f}" if "pct" not in metric_key else f"{start_val:.2f}%"
    fmt_end = f"${end_val:,.2f}" if "pct" not in metric_key else f"{end_val:.2f}%"

    insight_text = (
        f"{insight_prefix} {active_ticker}'s {metric_label} has been **{direction}** long-term. "
        f"It moved from {fmt_start} ({sorted_years[0][:4]}) to {fmt_end} ({sorted_years[-1][:4]}), "
        f"marking a net shift of {pct_change:+.2f}% over the tracked period."
    )
    return insight_text, related_chart


# =====================================================================
# DYNAMIC SINGLE OR DUAL COMPANY EXECUTION ENGINE
# =====================================================================

if __name__ == "__main__":
    from metrics import (
        COMPANIES, COMPANY_NAMES,
        get_company_metrics, calculate_ratios,
        get_quarterly_metrics, get_available_years,
    )

    print("\n" + "="*60)
    print(f" FINSIGHT INTELLIGENCE ENGINE — {len(COMPANIES)} COMPANIES IN REGISTRY")
    print("="*60)

    if not COMPANIES:
        print("⚠️ No companies loaded. Generate company_name/sec_companies.json first.")
        sys.exit(1)

    # 1. TARGET COMPANY X
    user_x = input("Enter Target Company X ticker (e.g., AAPL, NVDA, NKE): ").strip().upper()
    if user_x not in COMPANIES:
        print(f"⚠️ '{user_x}' not found in the SEC registry ({len(COMPANIES)} companies). Exiting.")
        sys.exit(1)
    TARGET_COMPANY = user_x

    # 2. OPTIONAL COMPARISON COMPANY Y
    user_y = input("Enter Comparison Company Y ticker (press ENTER to skip): ").strip().upper()
    if not user_y:
        print(f"🎯 Single-company mode for {TARGET_COMPANY}.")
        COMPARE_COMPANY = None
        PEERS = [TARGET_COMPANY]
    elif user_y not in COMPANIES:
        print(f"⚠️ '{user_y}' not found — continuing in single-company mode.")
        COMPARE_COMPANY = None
        PEERS = [TARGET_COMPANY]
    elif user_y == TARGET_COMPANY:
        print("⚠️ Can't compare a company to itself — single-company mode.")
        COMPARE_COMPANY = None
        PEERS = [TARGET_COMPANY]
    else:
        COMPARE_COMPANY = user_y
        PEERS = [TARGET_COMPANY, COMPARE_COMPANY]

    # Display names pulled from the registry, ticker as fallback.
    NAMES = {t: COMPANY_NAMES.get(t, t) for t in PEERS}

    RUN_LIST = [TARGET_COMPANY]
    KEY_METRICS = ["gross_margin_pct", "inventory_turnover", "debt_to_equity"]
    all_figures = []

    # 3. SEC PIPELINE EXTRACTION
    all_ratios = {}
    all_raw_metrics = {}

    print(f"\nProcessing SEC financial frameworks...")
    for ticker in PEERS:
        try:
            metrics = get_company_metrics(ticker)
            all_raw_metrics[ticker] = metrics
            all_ratios[ticker] = calculate_ratios(metrics)
        except Exception as e:
            print(f"❌ Error loading SEC filings for {ticker}: {e}")
            if ticker == TARGET_COMPANY:
                sys.exit(1)

    # 1. YoY metric trends (Company X only)
    for ticker in RUN_LIST:
        for metric in KEY_METRICS:
            fig = yoy_line_chart(all_ratios[ticker], metric, NAMES[ticker])
            all_figures.append(fig)

    # 2. Peer comparison over time (dual mode only)
    if COMPARE_COMPANY:
        for metric in KEY_METRICS:
            filtered_ratios = {k: all_ratios[k] for k in PEERS if k in all_ratios}
            if len(filtered_ratios) > 1:
                fig = yoy_comparison_chart(filtered_ratios, metric, NAMES)
                all_figures.append(fig)

    # 3. Quarterly breakdown, latest year (Company X only)
    QUARTERLY_METRICS_TO_CHART = ["revenue", "cogs", "gross_profit", "operating_income", "net_income"]
    for ticker in RUN_LIST:
        try:
            years = get_available_years(ticker)
            latest_year = years[-1]
            quarterly = get_quarterly_metrics(ticker, year=latest_year)
            for metric in QUARTERLY_METRICS_TO_CHART:
                fig = quarterly_bar_chart(quarterly[metric], metric, latest_year, NAMES[ticker])
                all_figures.append(fig)
        except Exception:
            pass

    # 4. Peer comparison bar, latest shared year (dual mode only)
    if COMPARE_COMPANY:
        try:
            latest_shared_year = get_available_years(TARGET_COMPANY)[-1]
            peer_ratios_pool = {k: all_ratios[k] for k in PEERS if k in all_ratios}
            for metric in KEY_METRICS:
                fig = peer_comparison_bar_chart(peer_ratios_pool, metric, latest_shared_year, NAMES)
                all_figures.append(fig)
        except Exception as e:
            print(f"⚠️ Single-year peer bar chart skipped: {e}")

    # 5. Margin breakdown stacked (Company X only)
    for ticker in RUN_LIST:
        fig = margin_breakdown_stacked_chart(all_raw_metrics[ticker], NAMES[ticker])
        all_figures.append(fig)

    # 6. Dual-axis revenue vs profit (Company X only)
    for ticker in RUN_LIST:
        fig = revenue_vs_profit_chart(all_raw_metrics[ticker], NAMES[ticker])
        all_figures.append(fig)

    # 7. Market data pipeline (yfinance)
    print(f"\nRequesting market histories...")
    try:
        from stock_data import get_all_stock_data
        stock_data = get_all_stock_data(tickers=PEERS, period="2y")
    except Exception as e:
        print(f"⚠️ Market data unavailable: {e}")
        stock_data = {}

    if stock_data:
        if COMPARE_COMPANY:
            all_figures.append(price_history_chart(stock_data, NAMES))
            all_figures.append(returns_comparison_chart(stock_data, NAMES))

        # Stock-price prediction (Company X only)
        if TARGET_COMPANY in stock_data:
            try:
                from stats import analyze_metric
                history_df = stock_data[TARGET_COMPANY]["history"]
                if not history_df.empty:
                    price_series = {
                        str(d.date()): float(price)
                        for d, price in zip(history_df.index, history_df["Close"])
                    }
                    price_analysis = analyze_metric(price_series, metric_name="stock_closing_price")
                    price_pred_fig = prediction_chart(price_analysis, company_name=NAMES[TARGET_COMPANY])
                    if price_pred_fig:
                        price_pred_fig.update_layout(
                            title=f"{NAMES[TARGET_COMPANY]} — Daily Stock Price Prediction",
                            xaxis=dict(title="Trading Date"),
                            yaxis=dict(title="Closing Price (USD)")
                        )
                        all_figures.append(price_pred_fig)
            except Exception as e:
                print(f"⚠️ Price prediction skipped: {e}")

    # 8. Statistical analysis — distribution + prediction (Company X only)
    from stats import analyze_metric
    for ticker in RUN_LIST:
        metrics = all_raw_metrics[ticker]
        ratios = all_ratios[ticker]

        pivoted_series = {}
        for year, ratio_dict in ratios.items():
            for metric, val in ratio_dict.items():
                pivoted_series.setdefault(metric, {})[year] = val

        pivoted_series["revenue"] = metrics["revenue"]["values"]

        metrics_to_forecast = ["revenue", "gross_margin_pct", "operating_margin_pct"]
        for metric in metrics_to_forecast:
            if metric in pivoted_series:
                analysis_result = analyze_metric(pivoted_series[metric], metric_name=metric)

                dist_fig = normal_distribution_chart(analysis_result, NAMES[ticker])
                if dist_fig:
                    all_figures.append(dist_fig)

                pred_fig = prediction_chart(analysis_result, NAMES[ticker])
                if pred_fig:
                    all_figures.append(pred_fig)

    # 9. OUTPUT
    if COMPARE_COMPANY:
        print(f"\n🎉 Compiling layout for {TARGET_COMPANY} vs {COMPARE_COMPANY}...")
    else:
        print(f"\n🎉 Compiling single-company layout for {TARGET_COMPANY}...")

    generate_dashboard_page(all_figures)

    # =====================================================================
    # CONVERSATIONAL QUERY INTERFACE
    # =====================================================================
    print("\n" + "-"*50)
    print(" FINSIGHT COGNITIVE QUERY INTERACTION LAYER")
    print(" (Type 'EXIT' or 'QUIT' at any time to close the session)")
    print("-"*50)

    while True:
        user_question = input("\nAsk a question about this asset (e.g., 'Is revenue declining?'): ").strip()

        if user_question.upper() in ["EXIT", "QUIT", "Q"]:
            print("\n👋 Closing conversational query session.")
            break

        if not user_question:
            print("⚠️ Please ask a financial question or type 'EXIT' to leave.")
            continue

        insight_text, matched_chart = answer_metric_query(user_question, all_raw_metrics, all_ratios, all_figures)

        print("\n" + "="*60)
        print(insight_text)
        print("="*60)

        if matched_chart:
            print(f"📊 Chart Link Established: '{matched_chart.layout.title.text}'")
        else:
            print("💡 Tip: Try keywords like 'Revenue', 'Operating Income', 'Net Income', or 'Gross Margin'.")