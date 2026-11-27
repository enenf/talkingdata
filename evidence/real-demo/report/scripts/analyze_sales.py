#!/usr/bin/env python3
"""Analyse uploads/sales.csv: revenue, cost, gross profit, gross margin by month and channel.

Definitions (kept explicit so every number in the report is traceable):
  gross_profit  = revenue - cost
  gross_margin  = gross_profit / revenue      (NOT net profit, NOT net margin)
  aov           = revenue / orders
"""

import csv
import os
from collections import OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "uploads", "sales.csv")
OUT_CSV = os.path.join(BASE, "artifacts", "summary.csv")


def r2(x):
    return round(x + 1e-12, 2)


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["revenue"] = float(row["revenue"])
        row["cost"] = float(row["cost"])
        row["orders"] = int(row["orders"])
    return rows


def agg(rows):
    revenue = sum(r["revenue"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    orders = sum(r["orders"] for r in rows)
    gp = revenue - cost
    return {
        "revenue": revenue,
        "cost": cost,
        "gross_profit": gp,
        "gross_margin_pct": r2(gp / revenue * 100) if revenue else 0.0,
        "orders": orders,
        "aov": r2(revenue / orders) if orders else 0.0,
        "cost_per_order": r2(cost / orders) if orders else 0.0,
    }


def main():
    rows = load_rows(SRC)
    months = sorted({r["month"] for r in rows})
    channels = sorted({r["channel"] for r in rows})

    by_month = OrderedDict()
    for m in months:
        by_month[m] = agg([r for r in rows if r["month"] == m])

    by_channel = OrderedDict()
    for c in channels:
        by_channel[c] = agg([r for r in rows if r["channel"] == c])

    grand = agg(rows)

    # month-over-month revenue growth
    mom = OrderedDict()
    for i, m in enumerate(months):
        mom[m] = None if i == 0 else r2(
            (by_month[m]["revenue"] / by_month[months[i - 1]]["revenue"] - 1) * 100
        )

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    header = [
        "scope", "key", "month", "channel", "revenue", "cost", "gross_profit",
        "gross_margin_pct", "orders", "aov", "cost_per_order", "revenue_mom_pct",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        def row(scope, key, month, channel, a, mom_pct=""):
            w.writerow([scope, key, month, channel, f"{a['revenue']:.2f}", f"{a['cost']:.2f}",
                        f"{a['gross_profit']:.2f}", f"{a['gross_margin_pct']:.2f}",
                        a["orders"], f"{a['aov']:.2f}", f"{a['cost_per_order']:.2f}", mom_pct])

        for m in months:
            row("month", m, m, "ALL", by_month[m],
                "" if mom[m] is None else f"{mom[m]:.2f}")
        for c in channels:
            row("channel", c, "ALL", c, by_channel[c])
        for m in months:
            for c in channels:
                sub = [r for r in rows if r["month"] == m and r["channel"] == c]
                row("month_channel", f"{m}|{c}", m, c, agg(sub))
        row("total", "ALL", "ALL", "ALL", grand)

    # ---- console report (used to write report.md) ----
    print("=== MONTH ===")
    for m in months:
        a = by_month[m]
        g = "" if mom[m] is None else f"  rev_mom={mom[m]:+.2f}%"
        print(f"{m}  rev={a['revenue']:>9.2f} cost={a['cost']:>9.2f} "
              f"gp={a['gross_profit']:>9.2f} margin={a['gross_margin_pct']:>6.2f}% "
              f"orders={a['orders']:>4} aov={a['aov']:>7.2f}{g}")
    print("=== CHANNEL ===")
    for c in channels:
        a = by_channel[c]
        print(f"{c:>12}  rev={a['revenue']:>9.2f} cost={a['cost']:>9.2f} "
              f"gp={a['gross_profit']:>9.2f} margin={a['gross_margin_pct']:>6.2f}% "
              f"orders={a['orders']:>4} aov={a['aov']:>7.2f} "
              f"rev_share={r2(a['revenue']/grand['revenue']*100):>5.2f}% "
              f"gp_share={r2(a['gross_profit']/grand['gross_profit']*100):>5.2f}%")
    a = grand
    print("=== TOTAL ===")
    print(f"TOTAL       rev={a['revenue']:.2f} cost={a['cost']:.2f} gp={a['gross_profit']:.2f} "
          f"margin={a['gross_margin_pct']:.2f}% orders={a['orders']} aov={a['aov']:.2f}")
    print("=== DETAIL ===")
    for r in rows:
        cpo = r2(r["cost"] / r["orders"])
        print(f"{r['month']} {r['channel']:>12} rev={r['revenue']:>8.2f} cost={r['cost']:>8.2f} "
              f"gp={r['revenue']-r['cost']:>8.2f} margin={r2((r['revenue']-r['cost'])/r['revenue']*100):>6.2f}% "
              f"orders={r['orders']:>4} cost_per_order={cpo:>6.2f} aov={r2(r['revenue']/r['orders']):>7.2f}")
    print("=== GROWTH Sep->Nov ===")
    first, last = months[0], months[-1]
    print(f"total revenue  {by_month[first]['revenue']:.2f} -> {by_month[last]['revenue']:.2f} "
          f"= {r2((by_month[last]['revenue']/by_month[first]['revenue']-1)*100):+.2f}%")
    print(f"total cost     {by_month[first]['cost']:.2f} -> {by_month[last]['cost']:.2f} "
          f"= {r2((by_month[last]['cost']/by_month[first]['cost']-1)*100):+.2f}%")
    print(f"total gp       {by_month[first]['gross_profit']:.2f} -> {by_month[last]['gross_profit']:.2f} "
          f"= {r2((by_month[last]['gross_profit']/by_month[first]['gross_profit']-1)*100):+.2f}%")
    for c in channels:
        sub = [r for r in rows if r["channel"] == c]
        f = agg(sub[:1]); l = agg(sub[-1:])
        print(f"{c:>12} rev {f['revenue']:.2f} -> {l['revenue']:.2f} "
              f"= {r2((l['revenue']/f['revenue']-1)*100):+.2f}% | "
              f"margin {f['gross_margin_pct']:.2f}% -> {l['gross_margin_pct']:.2f}% | "
              f"cost/order {r2(sub[0]['cost']/sub[0]['orders']):.2f} -> {r2(sub[-1]['cost']/sub[-1]['orders']):.2f}")
    mp_share = [r2(agg([r for r in rows if r['month'] == m and r['channel'] == 'marketplace'])['revenue']
                   / by_month[m]['revenue'] * 100) for m in months]
    print(f"marketplace revenue share by month: {mp_share}")
    mp_gp_share = [r2(agg([r for r in rows if r['month'] == m and r['channel'] == 'marketplace'])['gross_profit']
                      / by_month[m]['gross_profit'] * 100) for m in months]
    print(f"marketplace gross-profit share by month: {mp_gp_share}")


if __name__ == "__main__":
    main()
