import os
os.chdir("/Users/finsight")
from dotenv import load_dotenv; load_dotenv("backend/.env.python")
import logging; logging.disable(logging.WARNING)
import backend.graph.router as R
from backend.graph.rdf_graph import run_sparql
R.rebuild_graph_from_ravendb(); g = R._get_graph()

# Cover every A2 shape (#1–#5) + edge cases. Each is diffed registry-vs-SPARQL.
QS = [
  ("#1 year",              "What was Microsoft's net income in fiscal year 2024?"),
  ("#1 year nvda",         "What was NVIDIA's operating cash flow in fiscal 2026?"),
  ("#1 year cost_rev",     "In NVIDIA's fiscal 2026, what were cost of revenue and cash flow from operating activities?"),
  ("#2 no-year",           "What is Apple's net income?"),
  ("#2 multiyear",         "What was Apple's net income from 2022 to 2024?"),
  ("#2 revenue no-year",   "What is Microsoft's total revenue?"),
  ("#3 two-co metric",     "Compare Apple and Microsoft net income in fiscal 2024."),
  ("#3 three-co metric",   "Compare net income for Apple, Microsoft and NVIDIA."),
  ("#4 single multimetric","Give me an overview of Apple's financials."),
  ("#5 multi multimetric", "Compare Apple and Microsoft overall."),
  ("#6 all-company(SPARQL)","Which company had the highest net income?"),
  ("op_income year",       "What was Apple's operating income in fiscal 2024?"),
  ("gross_margin_pct",     "What was Apple's gross margin percent in 2024?"),
  ("debt_to_equity",       "What is Apple's debt to equity in 2024?"),
]
known = R._graph_tickers()
checked = mism = staysparql = 0
for label, q in QS:
    avail = [t for t in R._extract_tickers(q, known_tickers=known) if t in known]
    sparql = R._build_sparql(q, avail)
    srows = run_sparql(g, sparql)
    rrows = R._registry_lookup(q, avail)
    if rrows is None:
        staysparql += 1
        print(f"[SPARQL-only] {label:24} tickers={avail} sparql_rows={len(srows)} (registry declined -> engine)")
        continue
    checked += 1
    ok = rrows == srows
    if not ok:
        mism += 1
        print(f"[MISMATCH] {label:24} tickers={avail} sparql={len(srows)} reg={len(rrows)}")
        print("   sparql[:3]=", srows[:3]); print("   reg[:3]   =", rrows[:3])
    else:
        print(f"[OK]       {label:24} tickers={avail} rows={len(srows)} identical")
print(f"\nSHADOW_RESULT checked={checked} mismatch={mism} sparql_only={staysparql} => "
      f"{'CLEAN' if mism==0 else 'DRIFT'}")
