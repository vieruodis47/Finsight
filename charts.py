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
import re


# =====================================================================
# CORE VISUALIZATION FUNCTIONS
# =====================================================================

def generate_industry_boxplot_chart(global_lookup_map, all_ratios, target_sector, target_ticker, compare_ticker=None, target_name="Company X", compare_name="Company Y"):
    """
    Generates dynamic horizontal box plots where the industry spectrum statistics 
    are calculated EXCLUSIVELY out of the background population.
    Labels ONLY the raw numerical values for Q1, Median, and Q3 above the box plot.
    """
    import plotly.graph_objects as go
    import numpy as np

    # 1. Gather all actual companies sharing the target sector classification
    sector_tickers = []
    for ticker, info in global_lookup_map.items():
        p_sic = info.get("sic", "")
        if not p_sic: continue
        try:
            sic_val = int(float(str(p_sic).strip()))
            if 100 <= sic_val <= 999: current_sec = "Agriculture, Forestry, & Fishing"
            elif 1000 <= sic_val <= 1499: current_sec = "Mining, Energy, & Drilling"
            elif 1500 <= sic_val <= 1799: current_sec = "Construction & Contractors"
            elif 2000 <= sic_val <= 3999: current_sec = "Manufacturing & Heavy Industrial"
            elif 4000 <= sic_val <= 4999: current_sec = "Technology, Infrastructure, & Utilities"
            elif 5000 <= sic_val <= 5199: current_sec = "Wholesale Trade"
            elif 5200 <= sic_val <= 5999: current_sec = "Retail Trade & Apparel"
            elif 6000 <= sic_val <= 6799: current_sec = "Finance, Banking, & Real Estate"
            elif 7000 <= sic_val <= 8999: current_sec = "Services, Software, & Healthcare"
            else: current_sec = "Other Operational Entities"
                
            if current_sec == target_sector:
                sector_tickers.append(ticker.upper().strip())
        except Exception:
            continue

    benchmarks = ["gross_margin_pct", "inventory_turnover", "debt_to_equity"]
    fig_list = []

    fallback_profiles = {
        "Manufacturing & Heavy Industrial": {
            "gross_margin_pct": {"mean": 27.0, "std": 10.0},
            "inventory_turnover": {"mean": 6.5, "std": 3.0},
            "debt_to_equity": {"mean": 0.9, "std": 4.0}
        }
    }
    default_profile = {
        "gross_margin_pct": {"mean": 40.0, "std": 15.0},
        "inventory_turnover": {"mean": 8.0, "std": 5.0},
        "debt_to_equity": {"mean": 1.2, "std": 4.0}
    }

    for metric in benchmarks:
        try:
            industry_values = []
            target_val = None
            compare_val = None

            # Extract raw values from actual industry records
            for ticker in sector_tickers:
                if ticker in [str(target_ticker).upper(), str(compare_ticker).upper() if compare_ticker else ""]: 
                    continue
                ticker_ratios = all_ratios.get(ticker, {}) if all_ratios else {}
                if not ticker_ratios: continue
                years_sorted = sorted(list(ticker_ratios.keys()))
                if not years_sorted: continue
                latest_yr = years_sorted[-1]
                val = ticker_ratios[latest_yr].get(metric, None)
                if val is not None and not np.isnan(float(val)):
                    industry_values.append(float(val))

            # Resolve target metrics values
            ratios_map = {str(k).strip().upper(): v for k, v in all_ratios.items()} if all_ratios else {}
            
            t_key = str(target_ticker).strip().upper()
            if t_key in ratios_map and ratios_map[t_key]:
                yrs = sorted(list(ratios_map[t_key].keys()))
                if yrs and metric in ratios_map[t_key][yrs[-1]]:
                    target_val = float(ratios_map[t_key][yrs[-1]][metric])

            if compare_ticker:
                c_key = str(compare_ticker).strip().upper()
                if c_key in ratios_map and ratios_map[c_key]:
                    yrs_c = sorted(list(ratios_map[c_key].keys()))
                    if yrs_c and metric in ratios_map[c_key][yrs_c[-1]]:
                        compare_val = float(ratios_map[c_key][yrs_c[-1]][metric])

            # Populate pure background market distributions without clamping limits
            is_simulated = False
            if len(industry_values) < 5:
                is_simulated = True
                sec_config = fallback_profiles.get(target_sector, default_profile).get(metric)
                np.random.seed(42)
                sim_data = np.random.normal(loc=sec_config["mean"], scale=sec_config["std"], size=150)
                industry_values = list(sim_data)

            if not industry_values: continue

            # Calculate true background metrics statistics
            min_boxplot = float(np.min(industry_values))
            max_boxplot = float(np.max(industry_values))
            q1 = float(np.percentile(industry_values, 25))
            median = float(np.percentile(industry_values, 50))
            q3 = float(np.percentile(industry_values, 75))

            fig = go.Figure()

            # Trace A: Pure Industry Spectrum Layout Box
            fig.add_trace(go.Box(
                x=industry_values,
                name="Industry Spectrum",
                boxpoints=False, 
                marker_color='#0D9488', 
                fillcolor='rgba(20, 184, 166, 0.20)', 
                line=dict(color='#0F766E', width=2.5), 
                orientation='h',
                hoverinfo="none"
            ))

            suffix = "%" if metric == "gross_margin_pct" else ""

            # =====================================================================
            # 🎨 NUMBERS-ONLY STATISTICAL ANNOTATIONS
            # =====================================================================

            # 1. Q1 Numerical Value Only
            fig.add_annotation(
                x=q1, y="Industry Spectrum",
                text=f"<b style='color:#0f172a; font-size:11px;'>{q1:.2f}{suffix}</b>",
                showarrow=True, arrowhead=2, arrowsize=0.8, arrowcolor="#0F766E",
                ax=0, ay=-35,
                align="center",
                bgcolor="rgba(255, 255, 255, 0.95)",
                bordercolor="rgba(15, 118, 110, 0.4)",
                borderpad=4
            )

            # 2. Median Numerical Value Only (Shifted higher to avoid collisions)
            fig.add_annotation(
                x=median, y="Industry Spectrum",
                text=f"<b style='color:#0f766e; font-size:11px;'>{median:.2f}{suffix}</b>",
                showarrow=True, arrowhead=2, arrowsize=0.8, arrowcolor="#0F766E",
                ax=0, ay=-70,
                align="center",
                bgcolor="rgba(255, 255, 255, 0.95)",
                bordercolor="#0F766E",
                borderpad=4
            )

            # 3. Q3 Numerical Value Only
            fig.add_annotation(
                x=q3, y="Industry Spectrum",
                text=f"<b style='color:#0f172a; font-size:11px;'>{q3:.2f}{suffix}</b>",
                showarrow=True, arrowhead=2, arrowsize=0.8, arrowcolor="#0F766E",
                ax=0, ay=-35,
                align="center",
                bgcolor="rgba(255, 255, 255, 0.95)",
                bordercolor="rgba(15, 118, 110, 0.4)",
                borderpad=4
            )

            # 4. Industry Whiskers (Lower & Upper Fences)
            bottom_labels = [(min_boxplot, "Lower Fence"), (max_boxplot, "Upper Fence")]
            for val, label in bottom_labels:
                fig.add_annotation(
                    x=val, y="Industry Spectrum", 
                    text=f"<span style='color:#94a3b8; font-size:9px; font-weight:600;'>{label.upper()}</span><br><b style='color:#475569;'>{val:.2f}{suffix}</b>",
                    showarrow=False, yshift=-45, font=dict(size=10), align="center"
                )

            # Trace B: Target Company Scatter Point Overlay
            if target_val is not None:
                fig.add_trace(go.Scatter(
                    x=[target_val], y=["Industry Spectrum"], mode="markers+text", name=str(target_name),
                    marker=dict(color="#1D4ED8", size=14, symbol="diamond", line=dict(color="white", width=2)),
                    text=[f" <b>{target_ticker}</b> <span style='color:#1e3a8a;'>({target_val:.2f}{suffix})</span>"],
                    textposition="top right",
                    textfont=dict(size=11, color="#1e293b")
                ))

            # Trace C: Comparison Company Scatter Point Overlay
            if compare_val is not None:
                fig.add_trace(go.Scatter(
                    x=[compare_val], y=["Industry Spectrum"], mode="markers+text", name=str(compare_name),
                    marker=dict(color="#D97706", size=13, symbol="square", line=dict(color="white", width=2)),
                    text=[f" <b>{compare_ticker}</b> <span style='color:#78350f;'>({compare_val:.2f}{suffix})</span>"],
                    textposition="bottom right",
                    textfont=dict(size=11, color="#1e293b")
                ))

            metric_title = metric.replace("_", " ").title()
            
            # Auto-scale layout range framing
            all_points = industry_values + [v for v in [target_val, compare_val] if v is not None]
            x_range_min = min(all_points) - (abs(min(all_points)) * 0.15 if min(all_points) != 0 else 1)
            x_range_max = max(all_points) + (abs(max(all_points)) * 0.15 if max(all_points) != 0 else 1)

            fig.update_layout(
                title=dict(
                    text=f"Industry Distribution Benchmarking: {metric_title}{' (Market Proxy Mode)' if is_simulated else ''}<br><sup>Sector Segment: {target_sector} (n={len(industry_values)} Reference Assets)</sup>",
                    font=dict(size=14, color="#1E293B")
                ),
                xaxis=dict(
                    title=f"Metric Value Scale: {metric_title}", 
                    gridcolor="rgba(226, 232, 240, 0.6)", 
                    zerolinecolor="rgba(203, 213, 225, 1)",
                    range=[x_range_min, x_range_max]
                ),
                yaxis=dict(showgrid=False), paper_bgcolor="white", plot_bgcolor="white", showlegend=True, height=420, margin=dict(l=50, r=50, t=100, b=60)
            )
            fig_list.append(fig)
            
        except Exception as metric_err:
            print(f"      ❌ Debug internal loop error on [{metric}]: {metric_err}")
            continue
        
    return fig_list
  

def yoy_line_chart(ratios_data, metric_name, company_name, raw_metrics_pool=None, ticker=None):
    """
    Plots a single company's financial metric over time.
    Uses a standalone Navy Slate color theme to distinguish it from multi-peer comparison views.
    """
    import plotly.graph_objects as go

    metric_data = {}
    if raw_metrics_pool and ticker in raw_metrics_pool:
        company_raw = raw_metrics_pool[ticker]
        if metric_name in company_raw and "values" in company_raw[metric_name]:
            metric_data = company_raw[metric_name]["values"]

    if not metric_data:
        metric_data = {yr: dt.get(metric_name) for yr, dt in ratios_data.items() if dt.get(metric_name) is not None}

    sorted_dates = sorted(list(metric_data.keys()))
    values = [metric_data[date] for date in sorted_dates]
    clean_years = [str(date)[:4] for date in sorted_dates]
    clean_metric_title = metric_name.replace('_', ' ').title()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=clean_years,
        y=values,
        mode='lines+markers',
        name=company_name,
        # 🎨 Standalone Slate/Navy Blue for single asset context
        line=dict(width=3, color='#2B5C8F'),
        marker=dict(size=8, color='#2B5C8F')
    ))

    fig.update_layout(
        title=f"{company_name} — {clean_metric_title} Over Time",
        xaxis=dict(
            title="Fiscal Year", 
            type="category", 
            automargin=True, 
            tickangle=45
        ),
        yaxis=dict(title=clean_metric_title, automargin=True),
        template="plotly_white",
        hovermode="x unified"
    )
    return fig


def yoy_comparison_chart(filtered_ratios, metric_name, company_names, target_company=None):
    """
    Compares Company X (Target) and Company Y over time.
    Forces a clean categorical axis to completely strip out empty pre-2017 space.
    """
    import plotly.graph_objects as go

    fig = go.Figure()
    clean_metric_title = metric_name.replace('_', ' ').title()

    # Track all years that actually contain real data points
    active_years = set()

    for ticker, years_data in filtered_ratios.items():
        sorted_years = sorted(list(years_data.keys()))
        
        # Build clean values, filtering out any missing periods
        values = [years_data[yr].get(metric_name) for yr in sorted_years if years_data[yr].get(metric_name) is not None]
        clean_years = [str(yr)[:4] for yr in sorted_years if years_data[yr].get(metric_name) is not None]

        # Add to our active list to calculate strict axis ranges
        active_years.update(clean_years)

        trace_color = '#E15759' if ticker == target_company else '#4E79A7'

        fig.add_trace(go.Scatter(
            x=clean_years,
            y=values,
            mode='lines+markers',
            name=company_names.get(ticker, ticker),
            line=dict(width=3, color=trace_color),
            marker=dict(size=8, color=trace_color)
        ))

    # Determine the clean, tight category boundaries
    sorted_active_timeline = sorted(list(active_years))

    fig.update_layout(
        title=f"{clean_metric_title} — Company Comparison Over Time",
        xaxis=dict(
            title="Fiscal Year", 
            type="category", 
            categoryorder="array",
            categoryarray=sorted_active_timeline,
            automargin=True,
            tickangle=45  # Rotate labels by 45 degrees so they never collide!
        ),
        yaxis=dict(title=clean_metric_title, automargin=True),
        template="plotly_white",
        hovermode="x unified"
    )
    
    return fig


def quarterly_bar_chart(quarter_data, metric_name, year, company_name):
    """
    Bar chart for single company quarterly indicators.
    """
    import plotly.graph_objects as go
    
    quarters = list(quarter_data.keys())
    values = list(quarter_data.values())
    clean_metric_title = metric_name.replace('_', ' ').title()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=quarters,
        y=values,
        name=company_name,
        # 🎨 Matched Slate/Navy Blue for single asset charts
        marker_color='#2B5C8F',
        text=[f"${v:,.0f}" for v in values],
        textposition='auto'
    ))

    fig.update_layout(
        title=f"{company_name} — {clean_metric_title} by Quarter (FY ending {year})",
        xaxis=dict(title="Quarter", automargin=True),
        yaxis=dict(title=clean_metric_title, automargin=True),
        template="plotly_white"
    )
    return fig


def peer_comparison_bar_chart(all_ratios, metric_name, target_year, company_names, target_company=None):
    """
    Bar chart comparing a single metric across all companies for a specific year.
    Ensures zero values display a small visual placeholder and explicit N/A label.
    """
    tickers = list(all_ratios.keys())
    values = []
    display_text = []
    labels = []
    colors = []

    target_year_str = str(target_year)[:4]

    for ticker in tickers:
        company_data = all_ratios.get(ticker, {})
        matched_value = None
        
        for reporting_date, metrics in company_data.items():
            if target_year_str in str(reporting_date):
                matched_value = metrics.get(metric_name)
                break

        if matched_value is None and company_data:
            latest_date = max(list(company_data.keys()))
            matched_value = company_data[latest_date].get(metric_name)

        # Visual adjustment for missing or flat indicators
        if matched_value is None or matched_value == 0.0:
            values.append(0.1) 
            display_text.append("N/A (No Asset Data)")
        else:
            values.append(matched_value)
            display_text.append(f"{matched_value:.2f}")

        labels.append(company_names.get(ticker, ticker))
        colors.append('#E15759' if ticker == target_company else '#4E79A7')

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels,
        y=values,
        marker_color=colors,
        text=display_text,       
        textposition='outside'   # Push labels outside so baseline metrics render smoothly
    ))

    fig.update_layout(
        title=f"Peer Comparison: {metric_name.replace('_', ' ').title()} ({target_year_str})",
        xaxis=dict(title="Company", automargin=True),
        yaxis=dict(title=metric_name.replace('_', ' ').title(), automargin=True),
        template="plotly_white"
    )

    return fig


def margin_breakdown_stacked_chart(raw_metrics, company_name):
    """
    Plots a stacked area/bar breakdown of revenue components over time.
    Dynamically falls back to operational expense breakdowns if retail COGS tags 
    are completely missing (e.g., for oil/gas service sectors like Helmerich & Payne).
    """
    import plotly.graph_objects as go

    revenue_data = raw_metrics.get("revenue", {}).get("values", {})
    if not revenue_data:
        return None

    sorted_dates = sorted(list(revenue_data.keys()))
    clean_years = [str(d)[:4] for d in sorted_dates]
    
    cogs_data = raw_metrics.get("cogs", {}).get("values", {})
    operating_income_data = raw_metrics.get("operating_income", {}).get("values", {})
    net_income_data = raw_metrics.get("net_income", {}).get("values", {})

    fig = go.Figure()

    # STRATEGY A: Standard Retail / Hardware Manufacturing Breakdown
    if cogs_data and any(cogs_data.get(d) for d in sorted_dates):
        cogs_vals = [cogs_data.get(d, 0) for d in sorted_dates]
        net_inc_vals = [net_income_data.get(d, 0) for d in sorted_dates]
        
        overhead_vals = []
        for d in sorted_dates:
            rev = revenue_data.get(d, 0)
            cg = cogs_data.get(d, 0)
            ni = net_income_data.get(d, 0)
            overhead_vals.append(max(0, rev - cg - ni))

        fig.add_trace(go.Bar(x=clean_years, y=cogs_vals, name="Cost of Goods Sold (COGS)", marker_color='#4E79A7'))
        fig.add_trace(go.Bar(x=clean_years, y=overhead_vals, name="Operating Overhead / SG&A", marker_color='#F28E2B'))
        fig.add_trace(go.Bar(x=clean_years, y=net_inc_vals, name="Net Income", marker_color='#59A14F'))

    # STRATEGY B: Service / Industrial Drilling Sector Fallback Engine
    else:
        op_inc_vals = [operating_income_data.get(d, 0) for d in sorted_dates]
        
        opex_vals = []
        for d in sorted_dates:
            rev = revenue_data.get(d, 0)
            oi = operating_income_data.get(d, 0)
            opex_vals.append(max(0, rev - oi))

        fig.add_trace(go.Bar(x=clean_years, y=opex_vals, name="Operating & Drilling Expenses", marker_color='#76B7B2'))
        fig.add_trace(go.Bar(x=clean_years, y=op_inc_vals, name="Operating Income", marker_color='#59A14F'))

    fig.update_layout(
        title=f"{company_name} — Revenue & Margin Breakdown Over Time",
        xaxis=dict(title="Fiscal Year", type="category", automargin=True, tickangle=45),
        yaxis=dict(title="Consolidated Amount ($ USD)", automargin=True),
        barmode='stack', 
        template="plotly_white"
    )

    return fig


def revenue_vs_profit_chart(company_metrics, company_name="Company"):
    """
    Dual-axis line chart tracking Revenue vs Net Income over time.
    """
    rev_dict = company_metrics.get('revenue', {}).get('values', {})
    ni_dict = company_metrics.get('net_income', {}).get('values', {})

    years = sorted(list(set(rev_dict.keys()) | set(ni_dict.keys())))
    clean_years = [str(year)[:4] for year in years]

    revenue = [rev_dict.get(year) for year in years]
    net_income = [ni_dict.get(year) for year in years]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=clean_years,
        y=revenue,
        mode='lines+markers',
        name='Total Revenue',
        line=dict(width=3, color='#4E79A7')
    ))

    fig.add_trace(go.Scatter(
        x=clean_years,
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


def price_history_chart(stock_data, company_names, target_company=None):
    """
    Line chart showing daily closing price history.
    """
    fig = go.Figure()

    for name, data in stock_data.items():
        history = data["history"]
        if history.empty:
            continue
            
        trace_color = '#E15759' if name == target_company else '#4E79A7'
        
        fig.add_trace(go.Scatter(
            x=history.index,
            y=history["Close"],
            mode='lines',
            name=company_names.get(name, name),
            line=dict(width=2, color=trace_color)
        ))

    fig.update_layout(
        title="Stock Price History — Context Timeline",
        xaxis=dict(title="Date", automargin=True, tickangle=45),
        yaxis=dict(title="Closing Price (USD)", automargin=True),
        template="plotly_white",
        hovermode="x unified",
        legend_title="Company"
    )

    return fig


def returns_comparison_chart(stock_data, company_names, target_company=None):
    """
    Grouped bar chart comparing 1M, 3M, 6M, 1Y returns.
    """
    return_periods = ["1_month_return_pct", "3_month_return_pct",
                      "6_month_return_pct", "1_year_return_pct"]
    period_labels = ["1 Month", "3 Months", "6 Months", "1 Year"]

    fig = go.Figure()

    for name, data in stock_data.items():
        returns = data["returns"]
        values = [returns.get(p) for p in return_periods]
        
        trace_color = '#E15759' if name == target_company else '#4E79A7'
        
        fig.add_trace(go.Bar(
            x=period_labels,
            y=values,
            name=company_names.get(name, name),
            marker_color=trace_color
        ))

    fig.update_layout(
        title="Stock Returns Comparison — Active Metrics Context",
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
        std = 0.001

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

    fig.add_trace(go.Scatter(
        x=x, y=y, mode='lines',
        line=dict(color='#4E79A7', width=2),
        showlegend=False
    ))

    fig.add_vline(x=mean, line_dash="dash", line_color="gray", annotation_text=f"μ={mean:.2f}")

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
    Renders regression trendline forecasts with anomaly indicators.
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
        all_labels = [y[:4] for y in years] + ["FY2027\n(proj)"]
        
    fig = go.Figure()

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

    fig.add_trace(go.Scatter(
        x=[x_hist[-1], x_pred, x_pred, x_hist[-1]],
        y=[values[-1], ci_upper, ci_lower, values[-1]],
        fill='toself',
        fillcolor=r2_fill,
        line=dict(color=r2_color, dash='dot'),
        name=f'95% CI ({reliability.upper()})',
    ))

    fig.add_trace(go.Scatter(
        x=[x_pred], y=[pred_val],
        mode='markers+text',
        marker=dict(size=12, color=r2_color, symbol='diamond', line=dict(width=2, color='white')),
        text=[f"${pred_val:.2f}" if len(years) > 50 else f"{pred_val:.2f}"],
        textposition='top center',
        name=f'Target Target (R²={prediction["r_squared"]})'
    ))

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
# DASHBOARD GRID LAYOUT CONVERGER
# =====================================================================

def generate_dashboard_page(figures, filename="financial_dashboard.html", page_title="Executive Analytics Dashboard"):
    """
    Compiles a collection of Plotly figures into a clean grid system
    saved inside a single HTML file with a dynamic corporate title.
    """
    import os
    import webbrowser

    figures = [fig for fig in figures if fig is not None]
    divs = [fig.to_html(full_html=False, include_plotlyjs='cdn') for fig in figures]

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{page_title}</title>
        <style>
            body {{ font-family: 'Helvetica Neue', Arial, sans-serif; margin: 30px; background-color: #f4f6f9; color: #333; }}
            .dashboard-header {{ text-align: center; margin-bottom: 40px; padding: 20px; background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            h1 {{ margin: 0; color: #1e293b; font-size: 2.5em; font-weight: 700; }}
            p {{ margin: 5px 0 0 0; color: #64748b; font-size: 1.1em; }}
            .grid-container {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(600px, 1fr)); gap: 30px; }}
            
            /* 💡 THE CRITICAL CSS SIZING FIX */
            .chart-card {{ 
                background: white; 
                padding: 20px; 
                border-radius: 12px; 
                box-shadow: 0 4px 6px rgba(0,0,0,0.05); 
                min-height: 380px; /* Forces hidden/collapsed plot frames to render with real height */
                display: flex;
                flex-direction: column;
            }}
            
            /* Forces internal Plotly container targets to fill out the flex container card */
            .chart-card .plotly-graph-div {{
                flex-grow: 1;
                width: 100%;
                height: 100%;
            }}
        </style>
    </head>
    <body>

        <div class="dashboard-header">
            <h1>{page_title}</h1>
            <p>FinSight Executive Portfolio Framework — Consolidated Financial Statements & Interactive Trends</p>
        </div>

        <div class="grid-container">
            {"".join([f'<div class="chart-card">{d}</div>' for d in divs])}
        </div>

    </body>
    </html>
    """

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"🖥️ Web framework update complete: Dashboard exported successfully to '{filename}'")

    absolute_path = os.path.abspath(filename)
    webbrowser.open(f"file://{absolute_path}")


def answer_metric_query(user_query, all_raw_metrics, all_ratios, all_figures):
    """
    NLP routing matrix that prioritizes multi-company peer comparisons
    before defaulting to single-company macro trend lookups.
    """
    query = user_query.strip().upper()
    active_ticker = list(all_raw_metrics.keys())[0] if all_raw_metrics else "GAP"
    
    quarter_match = re.search(r'\bQ([1-4])\b', query)
    year_match = re.search(r'\b(20\d{2})\b', query)
    
    requested_quarter = f"Q{quarter_match.group(1)}" if quarter_match else None
    requested_year = year_match.group(1) if year_match else None

    peer_ticker_match = None
    for ticker_key in COMPANIES:
        if ticker_key in query and ticker_key != active_ticker:
            peer_ticker_match = ticker_key
            break

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

    # PRIORITY 1: MULTI-COMPANY COMPARISONS
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
                f"📊 **Cross-Sectional Peer Analysis:** For the latest reporting cycle, "
                f"{active_ticker} reported a {metric_label} of **{fmt_t1}** vs. "
                f"{peer_ticker_match} at **{fmt_t2}**. "
                f"This gives **{leader}** a net structural edge variance of **{gap:.2f}{suffix}**."
            )
            
            related_chart = None
            for fig in all_figures:
                if fig and fig.layout.title.text:
                    title_txt = fig.layout.title.text.lower()
                    if "comparison" in title_txt and metric_label.lower() in title_txt:
                        related_chart = fig
                        break
            return insight, related_chart

    # PRIORITY 2: TIME-SLICE QUARTERLY MATRIX
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

    # PRIORITY 3: SINGLE-COMPANY MACRO TREND LINES
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


def find_ticker_by_name(user_input, companies_registry, master_sec_data=None):
    """
    Cleans and matches user input against the SEC registry.
    Prioritizes exact matches to prevent accidental overrides (like AERG hijacking Apple).
    """
    clean_input = user_input.strip().upper()
    
    if clean_input in companies_registry:
        return clean_input

    def clean_name(n):
        return re.sub(r'\b(INC|CORP|CO|CORPORATION|LTD|GROUP|PLC|CLASS [A-Z])\b', '', str(n).upper()).strip()

    search_term = clean_name(clean_input)
    if not search_term:
        return None

    local_names = {
        "APPLE": "AAPL", "AAPL": "AAPL",
        "NVIDIA": "NVDA", "NVDA": "NVDA",
        "MICROSOFT": "MSFT", "MSFT": "MSFT",
        "TESLA": "TSLA", "TSLA": "TSLA",
        "GAP": "GAP"
    }
    if search_term in local_names:
        return local_names[search_term]

    if master_sec_data and "companies" in master_sec_data:
        for item in master_sec_data.get("companies", []):
            comp_name = item.get("name", "")
            comp_ticker = item.get("ticker", "")
            if comp_name and comp_ticker:
                if search_term == clean_name(comp_name):
                    return str(comp_ticker).strip().upper()

    if master_sec_data and "companies" in master_sec_data:
        for item in master_sec_data.get("companies", []):
            comp_name = item.get("name", "")
            comp_ticker = item.get("ticker", "")
            if comp_name and comp_ticker:
                if search_term in clean_name(comp_name):
                    return str(comp_ticker).strip().upper()

    return None


# =====================================================================
# SYSTEM MAIN ENGINE EXECUTION LOOP
# =====================================================================

if __name__ == "__main__":
    from metrics import COMPANIES, get_company_metrics, calculate_ratios, get_quarterly_metrics, get_available_years, get_industry_sector, master_sec_data
    from stock_data import get_all_stock_data
    from stats import analyze_metric, run_monte_carlo_forecast, monte_carlo_forecast_chart

    COMPANY_NAMES = {
        "GAP": "Gap Inc.",
        "PVH": "PVH Corp",
        "AEO": "American Eagle"
    }

    print("\n" + "="*60)
    print(f" FINSIGHT DYNAMIC SECTOR ENGINE — {len(COMPANIES)} ASSETS LOADED")
    print("="*60)
    
    # 1. GET TARGET METRIC COMPANY
    raw_x = input("Enter Target Company Name or Ticker (e.g., Apple, GAP, Microsoft): ").strip()
    resolved_x = find_ticker_by_name(raw_x, COMPANIES, master_sec_data=master_sec_data if 'master_sec_data' in locals() or 'master_sec_data' in globals() else None)
    
    if not resolved_x:
        print(f"⚠️ Could not resolve '{raw_x}' to an SEC ticker. Defaulting to AAPL.")
        TARGET_COMPANY = "AAPL"
    else:
        TARGET_COMPANY = resolved_x
        print(f"✅ Resolved '{raw_x}' ➔ Ticker: {TARGET_COMPANY}")

    # =====================================================================
    # 2. FULLY UNFILTERED DYNAMIC REGISTRY SCANNER (NO HARDCODED CIKs)
    # =====================================================================
    
    # 💡 GLOBAL SCOPE DEFAULTS: Guarantee these exist before any processing loops run
    GLOBAL_LOOKUP_MAP = {}
    raw_companies_list = []
    target_common_name = f"{TARGET_COMPANY} Inc."
    target_sic_clean = "7000"
    target_sector = "Services, Software, & Healthcare" # Safe dynamic global fallback
    
    # Pull the raw loaded array directly out of the application memory namespaces
    global_data = globals().get('master_sec_data', locals().get('master_sec_data', None))
    
    if global_data:
        if isinstance(global_data, dict):
            has_list_key = False
            for k in ["companies", "list", "data", "results", "registry"]:
                if k in global_data and isinstance(global_data[k], list):
                    raw_companies_list = global_data[k]
                    has_list_key = True
                    break
            
            if not has_list_key:
                for key_ticker, info in global_data.items():
                    if isinstance(info, dict):
                        item_copy = info.copy()
                        item_copy["ticker"] = key_ticker
                        raw_companies_list.append(item_copy)
                    else:
                        raw_companies_list.append({"ticker": key_ticker, "name": key_ticker})
                        
        elif isinstance(global_data, list):
            raw_companies_list = global_data

    # Emergency Local Disk Scanner if the memory namespace boundary is disconnected
    if not raw_companies_list:
        import json
        for path in ["master_sec_data.json", "data/master_sec_data.json", "../master_sec_data.json"]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        file_data = json.load(f)
                        if isinstance(file_data, dict):
                            has_list_key = False
                            for k in ["companies", "list", "data", "results", "registry"]:
                                if k in file_data and isinstance(file_data[k], list):
                                    raw_companies_list = file_data[k]
                                    has_list_key = True
                                    break
                            if not has_list_key:
                                for key_ticker, info in file_data.items():
                                    if isinstance(info, dict):
                                        item_copy = info.copy()
                                        item_copy["ticker"] = key_ticker
                                        raw_companies_list.append(item_copy)
                        elif isinstance(file_data, list):
                            raw_companies_list = file_data
                        if raw_companies_list: break
                except Exception:
                    pass

    # 2. CASE-INSENSITIVE DYNAMIC KEY DISCOVERY
    ticker_field = "ticker"
    name_field = "name"
    sic_field = "sic"

    if raw_companies_list and isinstance(raw_companies_list[0], dict):
        sample = raw_companies_list[0]
        for k in sample.keys():
            if k.lower() in ["ticker", "symbol", "symbol_key", "stock_ticker", "cik"]: ticker_field = k; break
        for k in sample.keys():
            if k.lower() in ["name", "title", "company", "company_name", "description"]: name_field = k; break
        for k in sample.keys():
            if k.lower() in ["sic", "sic_code", "siccode", "industry_code", "sic_num"]: sic_field = k; break

    # 3. Populate the global lookup index mapping cleanly
    for item in raw_companies_list:
        if not isinstance(item, dict): continue
        
        raw_t = item.get(ticker_field, "")
        raw_n = item.get(name_field, raw_t)
        raw_s = item.get(sic_field, "")
        
        t_clean = str(raw_t).strip().upper()
        
        s_clean = ""
        if raw_s is not None and str(raw_s).strip() != "" and str(raw_s).upper() != "NONE":
            try:
                s_clean = str(int(float(str(raw_s).strip())))
            except (ValueError, TypeError):
                s_clean = ""

        if t_clean:
            GLOBAL_LOOKUP_MAP[t_clean] = {
                "name": str(raw_n).strip().title() if raw_n else f"{t_clean} Inc.",
                "sic": s_clean
            }

    # =====================================================================
    # 2b. DYNAMIC TARGET SECTOR IDENTIFICATION LAYER
    # =====================================================================
    target_profile = GLOBAL_LOOKUP_MAP.get(TARGET_COMPANY)
    if target_profile:
        target_common_name = target_profile["name"]
        if target_profile["sic"]:
            target_sic_clean = target_profile["sic"]

    # Calculate the operational sector using the baseline metrics function rules
    try:
        target_sector = get_industry_sector(target_sic_clean)
    except Exception:
        # Local routing fallback if module function boundary fails
        try:
            sic_int = int(float(target_sic_clean))
            if 100 <= sic_int <= 999:
                target_sector = "Agriculture, Forestry, & Fishing"
            elif 1000 <= sic_int <= 1499:
                target_sector = "Mining & Mineral Extraction"
            elif 1500 <= sic_int <= 1799:
                target_sector = "Construction & Infrastructure"
            elif 2000 <= sic_int <= 3999:
                target_sector = "Manufacturing & Heavy Industrial"
            elif 4000 <= sic_int <= 4999:
                target_sector = "Transportation, Communications, & Utilities"
            elif 5000 <= sic_int <= 5199:
                target_sector = "Wholesale Trade"
            elif 5200 <= sic_int <= 5999:
                target_sector = "Retail Trade"
            elif 6000 <= sic_int <= 6799:
                target_sector = "Finance, Insurance, & Real Estate"
            elif 7000 <= sic_int <= 8999:
                target_sector = "Services, Software, & Healthcare"
            else:
                target_sector = "Public Administration & Government Operations"
        except ValueError:
            target_sector = "Services, Software, & Healthcare"

    print(f"📂 Dynamic Sector Match: {target_common_name} ({TARGET_COMPANY}) mapped to [{target_sector}].")

    # =====================================================================
    # 3. UNRESTRICTED DYNAMIC INTERACTIVE COMPARISON ENGINE
    # =====================================================================
    
    # 💡 SAFE INITIALIZATION: Guarantee these variables exist globally before any input loops
    COMPARE_COMPANY = None
    PEERS = [TARGET_COMPANY]
    
    raw_y = input(f"\nEnter Comparison Company Name or Ticker (or press ENTER to skip): ").strip()
    
    if not raw_y:
        resolved_y = None
    else:
        test_y = raw_y.upper()
        if test_y in GLOBAL_LOOKUP_MAP:
            resolved_y = test_y
        else:
            resolved_y = None
            for ticker, info in GLOBAL_LOOKUP_MAP.items():
                if test_y in info["name"].upper():
                    resolved_y = ticker
                    break

    if not resolved_y:
        if raw_y:
            print(f"❌ Could not resolve comparison target '{raw_y}' inside the global public registry. Single Company Mode activated!")
        else:
            print(f"🎯 Single Company Mode activated for {TARGET_COMPANY}!")
        # Fallbacks are already handled above by our safe defaults
        
    elif resolved_y == TARGET_COMPANY:
        print("⚠️ Cannot compare a company to itself. Switching to Single Company Mode.")
        
    else:
        # Pull Company B data parameters directly out of the dynamic lookup database map
        peer_profile = GLOBAL_LOOKUP_MAP[resolved_y]
        peer_common_name = peer_profile["name"]
        
        try:
            peer_sic_clean = str(int(float(peer_profile["sic"])))
        except (ValueError, TypeError):
            peer_sic_clean = "7000"
            
        peer_sector = get_industry_sector(peer_sic_clean)

        # Trigger explicit cross-sector override message gate if they mismatch
        if peer_sector != target_sector:
            print("\n" + "!" * 80)
            print(" ⚠️  CROSS-SECTOR ANOMALY DETECTED  ⚠️")
            print("!" * 80)
            print(f" • Target Asset: {target_common_name} [{TARGET_COMPANY}] -> Sector: {target_sector}")
            print(f" • Peer Target:  {peer_common_name} [{resolved_y}] -> Sector: {peer_sector}")
            print("-" * 80)
            print(" WARNING: Comparing entities across completely distinct structural industries")
            print(" can distort benchmark financial metrics due to drastically different operating metrics.")
            print("-" * 80)
            
            override_input = input(" Do you still want to force this cross-sector comparison? (Y/N): ").strip().upper()
            
            if override_input in ["Y", "YES"]:
                print(f"\n🔓 Cross-Sector Override Accepted! Actively bridging {TARGET_COMPANY} vs {resolved_y}...")
                COMPARE_COMPANY = resolved_y
                PEERS = [TARGET_COMPANY.upper().strip(), COMPARE_COMPANY.upper().strip()]
            else:
                print(f"\n❌ Override Denied. Dropping comparison. Switching to Single Company Mode for {TARGET_COMPANY}!")
                COMPARE_COMPANY = None
                PEERS = [TARGET_COMPANY.upper().strip()]
        else:
            COMPARE_COMPANY = resolved_y
            target_sic = None
            # Get the target company's SIC code
            if TARGET_COMPANY in GLOBAL_LOOKUP_MAP:
                try:
                    target_sic = int(float(GLOBAL_LOOKUP_MAP[TARGET_COMPANY]["sic"]))
                except:
                    target_sic = None

            PEERS = []

            if target_sic is not None:
                # Same broad sector classification as your charts.py
                def classify_sector(sic):
                    if 100 <= sic <= 999: return "Agriculture, Forestry, & Fishing"
                    elif 1000 <= sic <= 1499: return "Mining, Energy, & Drilling"
                    elif 1500 <= sic <= 1799: return "Construction & Contractors"
                    elif 2000 <= sic <= 3999: return "Manufacturing & Heavy Industrial"
                    elif 4000 <= sic <= 4999: return "Technology, Infrastructure, & Utilities"
                    elif 5000 <= sic <= 5199: return "Wholesale Trade"
                    elif 5200 <= sic <= 5999: return "Retail Trade & Apparel"
                    elif 6000 <= sic <= 6799: return "Finance, Banking, & Real Estate"
                    elif 7000 <= sic <= 8999: return "Services, Software, & Healthcare"
                    else: return "Other Operational Entities"

                target_sector = classify_sector(target_sic)
                for ticker, info in GLOBAL_LOOKUP_MAP.items():
                    try:
                        sic = int(float(info["sic"]))
                        if classify_sector(sic) == target_sector:
                            PEERS.append(ticker.upper().strip())
                    except:
                        continue
            
            # 💡 THE CRITICAL FIX: Explicitly guarantee the primary selections are in the data collection pool!
            t_upper = str(TARGET_COMPANY).upper().strip()
            c_upper = str(COMPARE_COMPANY).upper().strip()
            
            if t_upper not in PEERS:
                PEERS.append(t_upper)
            if c_upper not in PEERS:
                PEERS.append(c_upper)
                    
            print(f"Found {len(PEERS)} companies in {target_sector}.")                   
            print(f"🚀 Dual Sector Analysis activated: Comparing {target_common_name} vs {peer_common_name}!")

    # Synchronize Downstream Plotly chart loop scopes to prevent runtime crashing errors
    RUN_LIST = [TARGET_COMPANY]
    KEY_METRICS = ["gross_margin_pct", "inventory_turnover", "debt_to_equity"]
    
    PEER_DISPLAY_NAMES = {}
    for ticker in PEERS:
        profile = GLOBAL_LOOKUP_MAP.get(ticker)
        if profile and isinstance(profile, dict) and "name" in profile:
            PEER_DISPLAY_NAMES[ticker] = profile["name"]
        else:
            PEER_DISPLAY_NAMES[ticker] = f"{ticker} Inc."
            
    # 💡 THE FIX: Initialize the empty tracking list container right here!
    all_figures = []

    # 4. DATA EXTRACTION HARVESTER
    all_ratios = {}
    all_raw_metrics = {}
    
    print(f"\nProcessing SEC financial frameworks...")
    for ticker in PEERS:
        try:
            metrics = get_company_metrics(ticker)
            all_raw_metrics[ticker] = metrics
            all_ratios[ticker] = calculate_ratios(metrics)
        except Exception as e:
            print(f"❌ Critical error loading SEC filings for {ticker}: {e}")
            if ticker == TARGET_COMPANY:
                sys.exit(1)
    
    # =====================================================================
    # --- CHART GENERATION GENERATORS (ALL COMPILING STABLE) ---
    # =====================================================================

    # =====================================================================
    # 1. Dynamic Peer-Overlaid YoY Historical Metrics Lines
    # =====================================================================
    # 💡 THE FIX: If a comparison company exists, we route to yoy_comparison_chart 
    # to overlay BOTH lines on the same plot instead of printing single company paths.
    
    if COMPARE_COMPANY:
        # Build an uppercase dictionary slice of only the selected active targets
        active_comparison_ratios = {
            TARGET_COMPANY.upper().strip(): all_ratios.get(TARGET_COMPANY.upper().strip(), {}),
            COMPARE_COMPANY.upper().strip(): all_ratios.get(COMPARE_COMPANY.upper().strip(), {})
        }
        
        for metric in KEY_METRICS:
            fig = yoy_comparison_chart(
                filtered_ratios=active_comparison_ratios,
                metric_name=metric,
                company_names=PEER_DISPLAY_NAMES,
                target_company=TARGET_COMPANY.upper().strip()
            )
            all_figures.append(fig)
            
    else:
        # Fallback to single standalone asset timeline lines if no peer company is selected
        for ticker in RUN_LIST:
            display_name = PEER_DISPLAY_NAMES.get(ticker, f"{ticker} Inc.")
            for metric in KEY_METRICS:
                fig = yoy_line_chart(
                    all_ratios[ticker], 
                    metric, 
                    display_name, 
                    raw_metrics_pool=all_raw_metrics, 
                    ticker=ticker
                )
                all_figures.append(fig)

    # 3. Quarterly Breakdown Bar Histograms (Company X Only)
    QUARTERLY_METRICS_TO_CHART = ["revenue", "cogs", "gross_profit", "operating_income", "net_income"]
    for ticker in RUN_LIST:
        try:
            years = sorted(list(all_ratios[ticker].keys()))
            latest_year = years[-1]
            quarterly = get_quarterly_metrics(ticker, year=latest_year)
            for metric in QUARTERLY_METRICS_TO_CHART:
                if metric in quarterly and quarterly[metric]:
                    # Target the specific localized key variant
                    active_year_key = list(quarterly[metric].keys())[0]
                    fig = quarterly_bar_chart(quarterly[metric][active_year_key], metric, latest_year, COMPANY_NAMES[ticker])
                    all_figures.append(fig)
        except Exception as e:
            print(f"⚠️ Quarterly distribution metrics skipped for {ticker}: {e}")

    # =====================================================================
    # # 4. Dynamic Peer Comparison Bar Charts (ONLY RUNS IN DUAL MODE)
    # =====================================================================
    if COMPARE_COMPANY:
        try:
            sample_ticker = TARGET_COMPANY.upper()
            
            # 1. Normalize all_ratios keys to uppercase to prevent case mismatches
            clean_all_ratios = {str(k).strip().upper(): v for k, v in all_ratios.items()} if all_ratios else {}
            
            # 2. Defensive check: Ensure our target company exists in the calculation pool
            if sample_ticker not in clean_all_ratios or not clean_all_ratios[sample_ticker]:
                print(f"⚠️ Warning: Target [{sample_ticker}] is missing ratios. Injecting mock timeline structure.")
                clean_all_ratios[sample_ticker] = {
                    "2024": {"gross_margin_pct": 0.0, "inventory_turnover": 0.0, "debt_to_equity": 0.0},
                    "2025": {"gross_margin_pct": 0.0, "inventory_turnover": 0.0, "debt_to_equity": 0.0}
                }
            
            # 3. Safely extract years from the nested timeline structure
            available_years_pool = sorted(list(clean_all_ratios[sample_ticker].keys()))
            latest_shared_year = available_years_pool[-1] if available_years_pool else "2025"
            
            # 4. Safely construct the peer ratios pool using the normalized lookup dictionary
            peer_ratios_pool = {}
            for k in PEERS:
                peer_ticker = str(k).strip().upper()
                if peer_ticker in clean_all_ratios:
                    peer_ratios_pool[peer_ticker] = clean_all_ratios[peer_ticker]
                else:
                    # Inject matching nested structures for missing comparison companies
                    print(f"⚠️ Warning: Peer [{peer_ticker}] missing calculations. Injecting timeline fallback.")
                    peer_ratios_pool[peer_ticker] = {
                        latest_shared_year: {"gross_margin_pct": 0.0, "inventory_turnover": 0.0, "debt_to_equity": 0.0}
                    }
            
            # 5. Loop through and append metrics charts cleanly
            for metric in KEY_METRICS:
                fig = peer_comparison_bar_chart(
                    peer_ratios_pool, 
                    metric, 
                    latest_shared_year, 
                    PEER_DISPLAY_NAMES, 
                    target_company=TARGET_COMPANY
                )
                all_figures.append(fig)
                
        except Exception as e:
            print(f"⚠️ Single-year peer bar chart skipped: {e}")

    # =====================================================================
    # NEW SECTION: Self-Debugging Cross-Sectional Industry Benchmarking Boxplots
    # =====================================================================
    is_same_industry = True
    
    def discover_sic_dynamically(ticker_str, lookup_map):
        tk_clean = str(ticker_str).upper().strip()
        
        # Check direct key match
        if tk_clean in lookup_map and lookup_map[tk_clean].get("sic"):
            return lookup_map[tk_clean]["sic"]
            
        # Check by internal attributes or name strings
        for key, info in lookup_map.items():
            if not isinstance(info, dict): continue
            info_name = str(info.get("name", "")).upper()
            info_ticker = str(info.get("ticker", "")).upper()
            
            if tk_clean == info_ticker or f"({tk_clean})" in info_name or info_name.startswith(tk_clean):
                if info.get("sic"):
                    return info["sic"]
        return None

    # Get target and comparison ticker targets
    t_tk = str(TARGET_COMPANY).upper().strip()
    c_tk = str(COMPARE_COMPANY).upper().strip() if COMPARE_COMPANY else None

    target_sic = discover_sic_dynamically(TARGET_COMPANY, GLOBAL_LOOKUP_MAP)
    compare_sic = discover_sic_dynamically(COMPARE_COMPANY, GLOBAL_LOOKUP_MAP) if COMPARE_COMPANY else None

    # 💡 DEBUG LOG ENGINE: Tells us exactly what your database file is providing
    print(f"🔧 [DATABASE DEBUG LOG] Resolved {t_tk} SIC -> {target_sic}")
    if c_tk:
        print(f"🔧 [DATABASE DEBUG LOG] Resolved {c_tk} SIC -> {compare_sic}")

    # Map directly to human sectors (Fails gracefully to manufacturing if tech targets lack files)
    t_sector = get_industry_sector(target_sic) if target_sic else "Manufacturing & Heavy Industrial"
    
    if COMPARE_COMPANY:
        print(f"🔍 Auditing sector parity boundaries for {t_tk} vs {c_tk}...")
        c_sector = get_industry_sector(compare_sic) if compare_sic else "Manufacturing & Heavy Industrial"
                
        if t_sector != c_sector:
            is_same_industry = False
            print(f"🚫 Cross-Sector Alignment Mismatch: '{t_sector}' vs '{c_sector}'. Skipping boxplots.")
        else:
            print(f"✅ Sector Parity Audited: Both assets belong to [{t_sector}].")

    # Only execute boxplot calculations if they belong to the exact same industry pool
    if is_same_industry:
        print(f"📊 Sector alignment verified. Calculating cross-sectional market footprints across [{t_sector}]...")
        try:
            target_display_title = PEER_DISPLAY_NAMES.get(TARGET_COMPANY, TARGET_COMPANY)
            compare_display_title = PEER_DISPLAY_NAMES.get(COMPARE_COMPANY, COMPARE_COMPANY) if COMPARE_COMPANY else None
            
            normalized_ratios = {str(k).strip().upper(): v for k, v in all_ratios.items()}
            
            industry_boxplots = generate_industry_boxplot_chart(
                global_lookup_map=GLOBAL_LOOKUP_MAP,
                all_ratios=normalized_ratios,
                target_sector=t_sector, 
                target_ticker=TARGET_COMPANY.upper(),
                compare_ticker=COMPARE_COMPANY.upper() if COMPARE_COMPANY else None,
                target_name=target_display_title,
                compare_name=compare_display_title
            )
            
            for box_fig in industry_boxplots:
                all_figures.append(box_fig)
                
        except Exception as e:
            print(f"⚠️ Industry benchmarking analysis module skipped: {e}")
    else:
        print("💡 Operational Strategy: Boxplot benchmarks suppressed to prevent scale distortion across separate industries.")

            
    # =====================================================================
    # 5. Margin Breakdown Stacked Charts
    # =====================================================================
    for ticker in RUN_LIST:
        # 💡 SAFE EXTRACTION: Pull the resolved name from our unified registry index
        display_name = PEER_DISPLAY_NAMES.get(ticker, f"{ticker} Inc.")
        
        fig = margin_breakdown_stacked_chart(
            all_raw_metrics[ticker], 
            display_name # 💡 FIX: Passed the safe resolved variable name here
        )
        all_figures.append(fig)

    # =====================================================================
    # 6. Dual-Axis Consolidated Revenue vs Net Income Line Trends (Company X Only)
    # =====================================================================
    for ticker in RUN_LIST:
        # 💡 SAFE EXTRACTION: Pull from our dynamic peer display name index mapping
        display_name = PEER_DISPLAY_NAMES.get(ticker, f"{ticker} Inc.")
        
        fig = revenue_vs_profit_chart(
            all_raw_metrics[ticker], 
            display_name # 💡 FIX: Replaced COMPANY_NAMES[ticker] with our safe variable
        )
        if fig:
            all_figures.append(fig)


    # =====================================================================
    # 7. Yahoo Finance Real-time Market Timelines & Stock Price Predictions
    # =====================================================================
    print(f"\nRequesting market histories for peer mapping...")
    stock_data = get_all_stock_data(tickers=PEERS, period="2y")
    
    if stock_data:
        if COMPARE_COMPANY:
            fig = price_history_chart(stock_data, PEER_DISPLAY_NAMES, target_company=TARGET_COMPANY)
            all_figures.append(fig)

            fig = returns_comparison_chart(stock_data, PEER_DISPLAY_NAMES, target_company=TARGET_COMPANY)
            all_figures.append(fig)

        # 💡 DUAL PRICE FORECAST: Run stock price trend predictions for BOTH companies
        targets_for_analysis = [TARGET_COMPANY, COMPARE_COMPANY] if COMPARE_COMPANY else [TARGET_COMPANY]
        for tk in targets_for_analysis:
            if tk in stock_data:
                target_market_profile = stock_data[tk]
                history_df = target_market_profile["history"]
                
                if not history_df.empty:
                    price_series = {
                        str(date.date()): float(price) 
                        for date, price in zip(history_df.index, history_df["Close"])
                    }
                    
                    resolved_name = PEER_DISPLAY_NAMES.get(tk, f"{tk} Inc.")
                    price_analysis = analyze_metric(price_series, metric_name="stock_closing_price")
                    
                    price_pred_fig = prediction_chart(price_analysis, company_name=resolved_name)
                    if price_pred_fig:
                        price_pred_fig.update_layout(
                            title=f"{resolved_name} — Daily Stock Price Time-Series Prediction",
                            xaxis=dict(title="Trading Date Timeline"),
                            yaxis=dict(title="Closing Price (USD)")
                        )
                        all_figures.append(price_pred_fig)

    # =====================================================================
    # 8. Deterministic Distribution Profiles & Core Projections (BOTH COMPANIES)
    # =====================================================================
    # 💡 DUAL DISTRIBUTIONS: Generates Bell Curves & Predictions for Gross Margin, Revenue, & Operating Margin
    ANALYSIS_COMPANIES = [TARGET_COMPANY, COMPARE_COMPANY] if COMPARE_COMPANY else [TARGET_COMPANY]
    
    for ticker in ANALYSIS_COMPANIES:
        if not ticker: continue
        display_name = PEER_DISPLAY_NAMES.get(ticker, f"{ticker} Inc.")
        
        metrics = all_raw_metrics.get(ticker, {})
        ratios = all_ratios.get(ticker, {})
        
        pivoted_series = {}
        for year, ratio_dict in ratios.items():
            for metric, val in ratio_dict.items():
                if metric not in pivoted_series:
                    pivoted_series[metric] = {}
                pivoted_series[metric][year] = val
                
        if "revenue" in metrics and "values" in metrics["revenue"]:
            pivoted_series["revenue"] = metrics["revenue"]["values"]
        
        # Gross Margin Pct, Revenue, and Operating Margin Pct
        metrics_to_forecast = ["gross_margin_pct", "revenue", "operating_margin_pct"]
        for metric in metrics_to_forecast:
            if metric in pivoted_series and pivoted_series[metric]:
                analysis_result = analyze_metric(pivoted_series[metric], metric_name=metric)
                
                # Distribution Bell Curve
                dist_fig = normal_distribution_chart(analysis_result, display_name)
                if dist_fig:
                    all_figures.append(dist_fig)
                
                # Regression Forecast
                pred_fig = prediction_chart(analysis_result, display_name)
                if pred_fig:
                    all_figures.append(pred_fig)

    # =====================================================================
    # 🚀 9. MONTE CARLO PROBABILISTIC SHADED RISK CLOUDS (BOTH COMPANIES)
    # =====================================================================
    print("Simulating probabilistic Monte Carlo vector spaces...")
    for ticker in ANALYSIS_COMPANIES:
        if not ticker: continue
        display_name = PEER_DISPLAY_NAMES.get(ticker, f"{ticker} Inc.")
        
        metrics = all_raw_metrics.get(ticker, {})
        ratios = all_ratios.get(ticker, {})
        
        pivoted_series = {}
        for year, ratio_dict in ratios.items():
            for metric, val in ratio_dict.items():
                if metric not in pivoted_series:
                    pivoted_series[metric] = {}
                pivoted_series[metric][year] = val
                
        if "revenue" in metrics and "values" in metrics["revenue"]:
            pivoted_series["revenue"] = metrics["revenue"]["values"]
        
        # 💡 MONTE CARLO FORECAST: Gross Margin Pct + Revenue Log-Normal Risk Clouds
        metrics_to_simulate = ["gross_margin_pct", "revenue"]
        for metric in metrics_to_simulate:
            if metric in pivoted_series and pivoted_series[metric]:
                mc_data = run_monte_carlo_forecast(pivoted_series[metric], steps=3, simulations=5000)
                
                mc_fig = monte_carlo_forecast_chart(mc_data, metric, display_name)
                if mc_fig:
                    all_figures.append(mc_fig)
                    
    # =====================================================================
    # 10. DYNAMIC OUTPUT TITLE COMPILER & SAVE
    # =====================================================================
    if COMPARE_COMPANY:
        # 💡 FIX 2: Swap out COMPANY_NAMES for our database-backed PEER_DISPLAY_NAMES
        target_name = PEER_DISPLAY_NAMES.get(TARGET_COMPANY, f"{TARGET_COMPANY} Corp")
        peer_name = PEER_DISPLAY_NAMES.get(COMPARE_COMPANY, f"{COMPARE_COMPANY} Corp")
        dynamic_title = f"FinSight Analytics Dashboard: {target_name} vs. {peer_name}"
        print(f"\n🎉 Compiling final interactive layout for {target_name} vs {peer_name}...")
    else:
        target_name = PEER_DISPLAY_NAMES.get(TARGET_COMPANY, f"{TARGET_COMPANY} Corp")
        dynamic_title = f"FinSight Deep Dive Analysis: {target_name}"
        print(f"\n🎉 Compiling final single-asset deep dive layout for {target_name}...")
        
    generate_dashboard_page(all_figures, page_title=dynamic_title)


    # =====================================================================
    # RECURSIVE CONVERSATIONAL QUERY TERMINAL INTERFACE
    # =====================================================================
    print("\n" + "-"*50)
    print(" FINSIGHT COGNITIVE QUERY INTERACTION LAYER")
    print(" (Type 'EXIT' or 'QUIT' at any time to close the session)")
    print("-"*50)

    while True:
        user_question = input("\nAsk a question about this asset: ").strip()
        
        if user_question.upper() in ["EXIT", "QUIT", "Q"]:
            print("\n👋 Closing conversational query session. Have a great day!")
            break
            
        if not user_question:
            continue

        insight_text, matched_chart = answer_metric_query(user_question, all_raw_metrics, all_ratios, all_figures)
        
        print("\n" + "="*60)
        print(insight_text)
        print("=" * 60)

        if matched_chart:
            print(f"📊 Chart Link Established: Linked to '{matched_chart.layout.title.text}'")
        else:
            print("💡 Tip: Try rephrasing your question using keywords like 'Revenue' or 'Gross Margin'.")
