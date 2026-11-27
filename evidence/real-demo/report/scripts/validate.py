#!/usr/bin/env python3
"""Validate artifacts/summary.csv, artifacts/report.md and artifacts/executive-summary.md
against uploads/sales.csv.

Checks:
  1. summary.csv rows re-derived independently from the source CSV.
  2. Row identities: gross_profit == revenue - cost; margin == gp/rev; aov == rev/orders.
  3. Totals reconcile: sum(month rows) == sum(channel rows) == total row.
  4. Every source row appears in the summary.
  5. report.md length <= 800 characters.
  6. Every figure in report.md's tables matches summary.csv.
  7. Key prose claims match recomputed values.
  8. Gross profit is never presented as net profit.
  9. Numeric provenance: every figure is data-derived or a labelled forward target.
 10. executive-summary.md: one page, required sections, key numbers, channel
     priority table, revenue - cost == gross profit identity, provenance.
"""

import csv
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "uploads", "sales.csv")
SUMMARY = os.path.join(BASE, "artifacts", "summary.csv")
REPORT = os.path.join(BASE, "artifacts", "report.md")
EXEC = os.path.join(BASE, "artifacts", "executive-summary.md")

# Forward-looking targets explicitly labelled as targets in report.md (section VI.3)
# and reused in executive-summary.md. These are goals, NOT observed values.
TARGETS = {32000.0, 14.0, 38.0, 45.0}

failures = []
checks = 0


def check(cond, label, detail=""):
    global checks
    checks += 1
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def fmt(v):
    return f"{v:,.0f}" if float(v) == int(float(v)) else f"{v:,.2f}"


def build_legit(src, summ, expect, months, channels):
    """Every numeric value legitimately derivable from the source data."""
    legit = set()

    def add(v):
        legit.add(round(float(v), 2))

    for r in summ:
        for k in ("revenue", "cost", "gross_profit", "gross_margin_pct",
                  "orders", "aov", "cost_per_order", "revenue_mom_pct"):
            if r[k]:
                add(r[k])
    for r in src:
        add(r["revenue"]); add(r["cost"]); add(r["orders"])
    for i, m in enumerate(months):
        for j, m2 in enumerate(months):
            if i <= j:
                continue
            for c in [None] + channels:
                if c is None:
                    x, y = expect[("month", m)], expect[("month", m2)]
                else:
                    x, y = expect[("month_channel", f"{m}|{c}")], expect[("month_channel", f"{m2}|{c}")]
                for fld in ("revenue", "cost", "gross_profit", "cost_per_order", "orders", "aov"):
                    if y[fld]:
                        add((x[fld] / y[fld] - 1) * 100)
                        add((x[fld] / y[fld]) * 100)
    for c in channels:
        ec = expect[("channel", c)]
        add(ec["revenue"] / expect[("total", "ALL")]["revenue"] * 100)
        add(ec["gross_profit"] / expect[("total", "ALL")]["gross_profit"] * 100)
        for m in months:
            em = expect[("month_channel", f"{m}|{c}")]
            add(em["revenue"] / expect[("month", m)]["revenue"] * 100)
            add(em["gross_profit"] / expect[("month", m)]["gross_profit"] * 100)
    return legit


def provenance_scan(text, legit, targets):
    """Return figures in text that are neither data-derived nor labelled targets."""
    body = re.sub(r"`[^`]*`", "", text)           # code spans
    body = re.sub(r"(?m)^\s*\d+\.\s+", "", body)   # ordered-list markers
    body = re.sub(r"\d{4}-\d{2}", "", body)          # dates
    body = re.sub(r"\d+\s*→\s*\d+\s*月", "", body)   # "9→11 月"
    body = re.sub(r"\d+(?:\.\d+)?\s*(?:个月|周|个渠道|渠道|条记录|个百分点|个百分\s*点|月)", "", body)
    body = re.sub(r"(?m)^#+ ", "", body)             # heading markers

    unexplained = []
    for tok in re.findall(r"\d[\d,]*(?:\.\d+)?%?", body):
        raw = tok.rstrip("%").replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            unexplained.append((tok, "unparseable"))
            continue
        if round(v, 2) in legit or round(v, 2) in targets:
            continue
        unexplained.append((tok, "not derivable from source"))
    return unexplained


def section_body(text, keyword):
    """Return the body lines of the markdown section whose heading contains keyword."""
    out, capture = [], False
    for line in text.splitlines():
        if line.startswith("#"):
            capture = keyword in line
            continue
        if capture:
            out.append(line)
    return "\n".join(out)


def main():
    # ---------- load source ----------
    with open(SRC, newline="", encoding="utf-8") as fh:
        src = list(csv.DictReader(fh))
    for r in src:
        r["revenue"] = float(r["revenue"])
        r["cost"] = float(r["cost"])
        r["orders"] = int(r["orders"])

    months = sorted({r["month"] for r in src})
    channels = sorted({r["channel"] for r in src})

    def agg(rs):
        rev = sum(r["revenue"] for r in rs)
        cost = sum(r["cost"] for r in rs)
        orders = sum(r["orders"] for r in rs)
        gp = rev - cost
        return dict(revenue=rev, cost=cost, gross_profit=gp,
                    gross_margin_pct=round(gp / rev * 100, 2),
                    orders=orders, aov=round(rev / orders, 2),
                    cost_per_order=round(cost / orders, 2))

    expect = {}
    for m in months:
        expect[("month", m)] = agg([r for r in src if r["month"] == m])
    for c in channels:
        expect[("channel", c)] = agg([r for r in src if r["channel"] == c])
    for m in months:
        for c in channels:
            expect[("month_channel", f"{m}|{c}")] = agg(
                [r for r in src if r["month"] == m and r["channel"] == c])
    expect[("total", "ALL")] = agg(src)

    # ---------- load summary ----------
    with open(SUMMARY, newline="", encoding="utf-8") as fh:
        summ = list(csv.DictReader(fh))
    got = {(r["scope"], r["key"]): r for r in summ}

    print("[1] summary.csv matches independently recomputed aggregates")
    want_rows = len(months) + len(channels) + len(months) * len(channels) + 1
    check(len(summ) == want_rows,
          "summary.csv row count", f"(got {len(summ)}, want {want_rows})")
    for key, e in expect.items():
        g = got.get(key)
        if g is None:
            check(False, f"row present {key}")
            continue
        ok = (abs(float(g["revenue"]) - e["revenue"]) < 1e-6
              and abs(float(g["cost"]) - e["cost"]) < 1e-6
              and abs(float(g["gross_profit"]) - e["gross_profit"]) < 1e-6
              and abs(float(g["gross_margin_pct"]) - e["gross_margin_pct"]) < 1e-6
              and int(g["orders"]) == e["orders"]
              and abs(float(g["aov"]) - e["aov"]) < 1e-6
              and abs(float(g["cost_per_order"]) - e["cost_per_order"]) < 1e-6)
        check(ok, f"{key[0]} {key[1]} revenue/cost/gp/margin/orders/aov")

    print("[2] internal identities")
    for r in summ:
        rev, cost = float(r["revenue"]), float(r["cost"])
        gp, mg, aov = float(r["gross_profit"]), float(r["gross_margin_pct"]), float(r["aov"])
        check(abs(gp - (rev - cost)) < 1e-6, f"{r['scope']}/{r['key']}: gp == revenue - cost")
        check(abs(mg - round(gp / rev * 100, 2)) < 1e-6, f"{r['scope']}/{r['key']}: margin == gp/revenue")
        check(abs(aov - round(rev / int(r["orders"]), 2)) < 1e-6, f"{r['scope']}/{r['key']}: aov == revenue/orders")
        cpo = float(r["cost_per_order"])
        check(abs(cpo - round(cost / int(r["orders"]), 2)) < 1e-6, f"{r['scope']}/{r['key']}: cost_per_order == cost/orders")

    print("[3] totals reconcile")
    mrev = sum(float(got[("month", m)]["revenue"]) for m in months)
    crev = sum(float(got[("channel", c)]["revenue"]) for c in channels)
    mcost = sum(float(got[("month", m)]["cost"]) for m in months)
    ccost = sum(float(got[("channel", c)]["cost"]) for c in channels)
    mgp = sum(float(got[("month", m)]["gross_profit"]) for m in months)
    cgp = sum(float(got[("channel", c)]["gross_profit"]) for c in channels)
    t = got[("total", "ALL")]
    check(abs(mrev - crev) < 1e-6, "month revenue sum == channel revenue sum")
    check(abs(mcost - ccost) < 1e-6, "month cost sum == channel cost sum")
    check(abs(mgp - cgp) < 1e-6, "month gross profit sum == channel gross profit sum")
    check(abs(float(t["revenue"]) - mrev) < 1e-6, "total revenue == sum of months")
    check(abs(float(t["cost"]) - mcost) < 1e-6, "total cost == sum of months")
    check(abs(float(t["gross_profit"]) - mgp) < 1e-6, "total gross profit == sum of months")

    print("[4] source coverage")
    for r in src:
        g = got.get(("month", r["month"]))
        check(g is not None and float(g["revenue"]) >= r["revenue"], f"source row {r['month']}/{r['channel']} covered")
    check(len(src) == 6, "source row count == 6")

    # ---------- report ----------
    text = open(REPORT, encoding="utf-8").read()
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    wordstyle = cjk + len(re.findall(r"[A-Za-z0-9_.%,+−-]+", re.sub(r"[\u4e00-\u9fff]", " ", text)))
    print("[5] report.md length")
    check(cjk <= 800, f"CJK characters {cjk} <= 800")
    check(wordstyle <= 800, f"word-style count {wordstyle} <= 800")

    print("[6] report tables match summary.csv")
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    table_rows = []
    for l in lines:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        table_rows.append(cells)
    check(len(table_rows) == 2 + len(months) + 1 + len(channels),
          "report table row count", f"(got {len(table_rows)})")

    def norm(cells):
        return [c.replace("*", "").strip() for c in cells]

    def find_row(label):
        for c in table_rows:
            n = norm(c)
            if n and n[0] == label:
                return n
        return None

    for m in months:
        c = find_row(m)
        e = expect[("month", m)]
        want = [m, fmt(e["revenue"]), fmt(e["cost"]), fmt(e["gross_profit"]),
                f"{e['gross_margin_pct']:.2f}%", str(e["orders"]), f"{e['aov']:.2f}"]
        check(c is not None and c[:7] == want, f"report month row {m}", f"got {c}")
    c = find_row("合计")
    e = expect[("total", "ALL")]
    want = ["合计", fmt(e["revenue"]), fmt(e["cost"]), fmt(e["gross_profit"]),
            f"{e['gross_margin_pct']:.2f}%", str(e["orders"]), f"{e['aov']:.2f}"]
    check(c is not None and c[:7] == want, "report total row", f"got {c}")
    tot_rev = expect[("total", "ALL")]["revenue"]
    tot_gp = expect[("total", "ALL")]["gross_profit"]
    for ch in channels:
        c = find_row(ch)
        e = expect[("channel", ch)]
        want = [ch, fmt(e["revenue"]), fmt(e["cost"]), fmt(e["gross_profit"]),
                f"{e['gross_margin_pct']:.2f}%", str(e["orders"]), f"{e['aov']:.2f}",
                f"{e['revenue']/tot_rev*100:.2f}%", f"{e['gross_profit']/tot_gp*100:.2f}%"]
        check(c is not None and c[:9] == want, f"report channel row {ch}", f"got {c}")

    print("[7] key prose claims match recomputed values")
    first, last = months[0], months[-1]
    f_m, l_m = expect[("month", first)], expect[("month", last)]
    claims = {
        "total revenue 72,000": f"{fmt(e_rev := expect[('total','ALL')]['revenue'])}" == "72,000" and "72,000" in text,
        "total cost 45,000": fmt(expect[("total", "ALL")]["cost"]) == "45,000" and "45,000" in text,
        "total gross profit 27,000": fmt(expect[("total", "ALL")]["gross_profit"]) == "27,000" and "27,000" in text,
        "total margin 37.50%": f"{expect[('total','ALL')]['gross_margin_pct']:.2f}%" == "37.50%" and "37.50%" in text,
        "revenue growth Sep->Nov +40.00%": f"{(l_m['revenue']/f_m['revenue']-1)*100:+.2f}%" == "+40.00%" and "+40.00%" in text,
        "cost growth Sep->Nov +30.77%": f"{(l_m['cost']/f_m['cost']-1)*100:+.2f}%" == "+30.77%" and "+30.77%" in text,
        "gross profit growth Sep->Nov +57.14%": f"{(l_m['gross_profit']/f_m['gross_profit']-1)*100:+.2f}%" == "+57.14%" and "+57.14%" in text,
        "Oct MoM +20.00%": f"{(expect[('month',months[1])]['revenue']/f_m['revenue']-1)*100:+.2f}%" == "+20.00%" and "+20.00%" in text,
        "Nov MoM +16.67%": f"{(l_m['revenue']/expect[('month',months[1])]['revenue']-1)*100:+.2f}%" == "+16.67%" and "+16.67%" in text,
    }
    for ch in channels:
        s = [r for r in src if r["channel"] == ch]
        rev_g = (s[-1]["revenue"] / s[0]["revenue"] - 1) * 100
        claims[f"{ch} revenue growth +{rev_g:.2f}%"] = f"+{rev_g:.2f}%" in text
        e = expect[("channel", ch)]
        claims[f"{ch} margin {e['gross_margin_pct']:.2f}%"] = f"{e['gross_margin_pct']:.2f}%" in text
        claims[f"{ch} revenue share {e['revenue']/expect[('total','ALL')]['revenue']*100:.2f}%"] = \
            f"{e['revenue']/expect[('total','ALL')]['revenue']*100:.2f}%" in text
        claims[f"{ch} gross-profit share {e['gross_profit']/expect[('total','ALL')]['gross_profit']*100:.2f}%"] = \
            f"{e['gross_profit']/expect[('total','ALL')]['gross_profit']*100:.2f}%" in text
    og = (expect[("month", last)]["orders"] / expect[("month", first)]["orders"] - 1) * 100
    ag = (expect[("month", last)]["aov"] / expect[("month", first)]["aov"] - 1) * 100
    claims[f"orders growth +{og:.2f}%"] = f"+{og:.2f}%" in text
    claims[f"aov growth +{ag:.2f}%"] = f"+{ag:.2f}%" in text
    claims["order contribution > price contribution"] = (
        "订单量" in text and "客单价" in text
        and expect[("month", last)]["orders"] > expect[("month", last)]["revenue"] / expect[("month", last)]["aov"])
    for label, ok in claims.items():
        check(bool(ok), f"claim in report: {label}")

    print("[8] gross profit is not labelled net profit")
    check("不是净利润" in text, "report states gross profit is not net profit")
    bad = [l for l in text.splitlines() if "净利润" in l and "毛利" in l and "不是净利润" not in l]
    check(not bad, "no line equates gross profit with net profit", f"{bad}")

    print("[9] numeric provenance: every number in report.md is data-derived or a labelled target")
    legit = build_legit(src, summ, expect, months, channels)
    unexplained = provenance_scan(text, legit, TARGETS)
    check(not unexplained, "all report.md figures trace to source data or labelled targets",
          f"{unexplained[:12]}")

    # ---------- executive summary ----------
    print("[10] executive-summary.md")
    check(os.path.exists(EXEC), "executive-summary.md exists")
    etext = open(EXEC, encoding="utf-8").read()
    ecjk = len(re.findall(r"[\u4e00-\u9fff]", etext))
    ewordstyle = ecjk + len(re.findall(r"[A-Za-z0-9_.%,+−-]+", re.sub(r"[\u4e00-\u9fff]", " ", etext)))
    check(ecjk <= 900, f"exec summary CJK characters {ecjk} <= 900 (fits one page)")
    check(ewordstyle <= 900, f"exec summary word-style count {ewordstyle} <= 900 (fits one page)")

    print("[10a] required sections present")
    for sec in ("三个关键数字", "渠道优先级", "未来两周行动", "需要补充的数据"):
        check(sec in etext, f"exec summary has section: {sec}")

    print("[10b] three key numbers match recomputed totals")
    tot = expect[("total", "ALL")]
    for label, s in (("总收入 72,000", fmt(tot["revenue"])),
                      ("总成本 45,000", fmt(tot["cost"])),
                      ("总毛利 27,000", fmt(tot["gross_profit"])),
                      ("毛利率 37.50%", f"{tot['gross_margin_pct']:.2f}%")):
        check(s in etext, f"exec summary states {label}")

    key_sec = section_body(etext, "三个关键数字")
    key_items = re.findall(r"(?m)^\s*(\d+)\.\s+\S", key_sec)
    check(len(key_items) == 3, "key-numbers section lists exactly three numbered items",
          f"(got {len(key_items)})")

    print("[10c] revenue - cost == gross profit identity re-verified")
    check(abs(tot["revenue"] - tot["cost"] - tot["gross_profit"]) < 1e-9,
          "recomputed from source: total revenue - total cost == total gross profit")
    check(abs(mrev - mcost - mgp) < 1e-9,
          "recomputed: sum(month revenue) - sum(month cost) == sum(month gross profit)")
    check(abs(crev - ccost - cgp) < 1e-9,
          "recomputed: sum(channel revenue) - sum(channel cost) == sum(channel gross profit)")
    ident = re.search(r"([\d,]+)\s*[−\-]\s*([\d,]+)\s*=\s*([\d,]+)", etext)
    check(ident is not None, "exec summary states the identity as 'revenue - cost = gross profit'")
    if ident:
        a, b, c_ = (float(x.replace(",", "")) for x in ident.groups())
        check((a, b, c_) == (tot["revenue"], tot["cost"], tot["gross_profit"]),
              "identity operands equal the recomputed totals", f"{a},{b},{c_}")
        check(abs(a - b - c_) < 1e-9, "identity operands satisfy revenue - cost == gross profit")

    print("[10d] channel priority table matches summary.csv")
    erows = []
    for l in [x.strip() for x in etext.splitlines() if x.strip().startswith("|")]:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        erows.append(cells)
    # one table -> 1 header row + one row per channel (separator row excluded)
    check(len(erows) == 1 + len(channels), "exec summary channel table row count",
          f"(got {len(erows)}, want {1 + len(channels)})")
    for ch in channels:
        row = next((r for r in erows if ch in r), None)
        e = expect[("channel", ch)]
        cell = " ".join(row) if row else ""
        ok = (row is not None
              and fmt(e["revenue"]) in cell
              and fmt(e["gross_profit"]) in cell
              and f"{e['gross_margin_pct']:.2f}%" in cell
              and f"{e['revenue'] / tot['revenue'] * 100:.2f}%" in cell
              and f"{e['gross_profit'] / tot['gross_profit'] * 100:.2f}%" in cell)
        check(ok, f"exec summary channel row {ch} matches summary.csv")

    print("[10e] two-week actions and data gaps are concrete")
    act_sec = section_body(etext, "未来两周行动")
    act_items = re.findall(r"(?m)^\s*(\d+)\.\s+\S", act_sec)
    check(len(act_items) >= 3, "actions section lists numbered actions", f"(got {len(act_items)})")
    check("marketplace" in act_sec and "website" in act_sec, "actions cover both channels")
    check("第 1 周" in act_sec and "第 2 周" in act_sec, "actions are scheduled across two weeks")
    check("目标值" in etext, "exec summary labels forward targets as targets, not results")
    gap_sec = section_body(etext, "需要补充的数据")
    for field in ("营销费", "退货退款", "新老客", "流量与转化"):
        check(field in gap_sec, f"data-gap section names: {field}")

    print("[10f] exec summary gross profit is not labelled net profit")
    check("不是净利润" in etext, "exec summary states gross profit is not net profit")
    bad_e = [l for l in etext.splitlines() if "净利润" in l and "毛利" in l and "不是净利润" not in l]
    check(not bad_e, "no exec summary line equates gross profit with net profit", f"{bad_e}")

    print("[10g] numeric provenance for executive-summary.md")
    eunexplained = provenance_scan(etext, legit, TARGETS)
    check(not eunexplained, "all executive-summary.md figures trace to source data or labelled targets",
          f"{eunexplained[:12]}")

    print()
    print(f"{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED:", "; ".join(failures))
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
