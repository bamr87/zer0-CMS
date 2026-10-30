"""Audit reports: the Markdown AIEO's `generate_reports.py` wrote — one per site, and a summary that ranks the sites,
draws the score distribution and a pattern heatmap, and lists the most common gaps — rendered from audits in the
platform, and the same as HTML.

The renderers are AIEO's, ported line for line, with the time they stamp passed in: given the audits imported from
`apps/aieo/reports/` they write AIEO's reports byte for byte (`tests/aieo/test_reports.py`). A report is an
artifact of an audit (or of a batch, or of a site's audits): the API returns it to download, and `manage.py aieo
report` writes it to files.
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import markdown


def url_to_filename(url: str) -> str:
    """AIEO's name for a site's report: the host without www, dots as underscores, the path appended."""
    parsed = urlparse(url)
    name = parsed.netloc.replace("www.", "").replace(".", "_")
    path = parsed.path.strip("/").replace("/", "_")
    return f"{name}_{path}" if path else name


def data_of(audit) -> dict:
    """An audit as the report reads it: AIEO's result JSON, its patterns in the order their scorer gave them (kept
    beside them by Audit.save, since Postgres's jsonb reorders an object's keys)."""
    result = dict(audit.result or {})
    order, scores = result.pop("pattern_order", None), result.get("pattern_scores")
    if order and isinstance(scores, dict):
        result["pattern_scores"] = {name: scores[name] for name in order if name in scores} | scores
    return {
        **result,
        "url": audit.url or audit.target,
        "timestamp": result.get("timestamp") or (audit.audited_at.isoformat() if audit.audited_at else ""),
        "status": "success" if audit.status == audit.READY else "error",
        "error": audit.error,
        "score": audit.score if audit.score is not None else 0,
        "grade": audit.grade or "?",
        "word_count": result.get("word_count", 0),
        "scoring_method": audit.scoring_method or result.get("scoring_method", "unknown"),
        "screenshot_file": result.get("screenshot_file", ""),
        "_name": url_to_filename(audit.url) if audit.url else str(audit.public_id),
    }


def html(text: str) -> str:
    return markdown.markdown(text, extensions=["tables", "fenced_code"])


def score_bar(score: float, max_score: float, width: int = 20) -> str:
    ratio = score / max_score if max_score else 0
    filled = round(ratio * width)
    return f"`{'█' * filled}{'░' * (width - filled)}`"


def grade_emoji(grade: str) -> str:
    return {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}.get(grade, "⚪")


def severity_icon(severity: str) -> str:
    return {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")


def site_label(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/")
    return f"{host}/{path}" if path else host


def report_link(data: dict) -> str:
    return f"{data['_name']}/{data['_name']}.md"


def format_score(score) -> str:
    val = round(float(score), 1)
    return str(int(val)) if val == int(val) else str(val)


def site_report(data: dict, now: datetime) -> str:
    """One site's report (AIEO's `render_site_report`)."""
    url = data.get("url", "unknown")
    label = site_label(url)
    score = float(data.get("score", 0))
    grade = data.get("grade", "?")
    timestamp = data.get("timestamp", "")
    patterns = data.get("pattern_scores", {})
    gaps = data.get("gaps", [])
    model, provider = data.get("model", ""), data.get("provider", "")
    screenshot = data.get("screenshot_file", "")
    visual = data.get("visual_analysis", {})

    lines = []
    w = lines.append
    w(f"# AIEO Audit Report: {label}")
    w("")
    w("| Field | Value |")
    w("|-------|-------|")
    w(f"| **URL** | {url} |")
    w(f"| **Score** | {format_score(score)} / 100 {grade_emoji(grade)} |")
    w(f"| **Grade** | {grade} |")
    w(f"| **Word Count** | {data.get('word_count', 0):,} |")
    w(f"| **Content Type** | {data.get('content_type', 'unknown')} |")
    w(f"| **Scoring Method** | {data.get('scoring_method', 'unknown')} |")
    if model:
        w(f"| **AI Model** | {provider}/{model} |")
    w(f"| **Audited** | {timestamp[:19] if timestamp else 'n/a'} |")
    w("")
    if data.get("overall_assessment", ""):
        w(f"> {data['overall_assessment']}")
        w("")
    if screenshot:
        w("## Page Screenshot")
        w("")
        w(f"![Screenshot of {label}]({screenshot})")
        w("")
    if visual:
        w("## Visual Analysis")
        w("")
        if visual.get("design_score") is not None:
            w(f"**Design Score:** {visual['design_score']} / 10")
            w("")
        for key, heading in [
            ("layout_quality", "Layout Quality"),
            ("visual_hierarchy", "Visual Hierarchy"),
            ("readability", "Readability"),
            ("trust_signals", "Trust Signals"),
            ("mobile_readiness", "Mobile Readiness"),
            ("scannability", "Scannability"),
        ]:
            if visual.get(key):
                w(f"**{heading}:** {visual[key]}")
                w("")
        if visual.get("design_recommendations", []):
            w("**Design Recommendations:**")
            w("")
            for rec in visual["design_recommendations"]:
                w(f"- {rec}")
            w("")
    if data.get("executive_summary", ""):
        w("## Executive Summary")
        w("")
        w(data["executive_summary"])
        w("")
    if data.get("priority_actions", []):
        w("## Priority Action Plan")
        w("")
        w("The top changes that will have the biggest impact on AI citability:")
        w("")
        for i, action in enumerate(data["priority_actions"], 1):
            impact, effort = action.get("impact", ""), action.get("effort", "")
            impact_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "⚪")
            effort_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(effort, "⚪")
            w(f"### {i}. {action.get('title', '')}")
            w("")
            w(f"**Impact:** {impact_icon} {impact.title()}  |  **Effort:** {effort_icon} {effort.title()}")
            w("")
            w(action.get("description", ""))
            w("")
    if data.get("sample_improvements", []):
        w("## Sample Improvements")
        w("")
        w("Concrete before/after examples you can adapt for your site:")
        w("")
        for j, sample in enumerate(data["sample_improvements"], 1):
            w(f"### {j}. {sample.get('section', f'Example {j}')}")
            w("")
            addressed = sample.get("patterns_addressed", [])
            if addressed:
                w(f"**Patterns addressed:** {', '.join(f'`{p.replace(chr(95), chr(32)).title()}`' for p in addressed)}")
                w("")
            if sample.get("current", ""):
                w("**Before (current):**")
                w("")
                w(f"> {sample['current']}")
                w("")
            if sample.get("improved", ""):
                w("**After (improved):**")
                w("")
                w(f"> {sample['improved']}")
                w("")
    w("## Detailed Pattern Scores")
    w("")
    for name, p in sorted(patterns.items(), key=lambda kv: kv[1].get("max", 0), reverse=True):
        s, mx = float(p.get("score", 0)), float(p.get("max", 0))
        detected = "✅ Detected" if p.get("detected") else "❌ Not detected"
        pct = int(s / mx * 100) if mx else 0
        w(f"### {name.replace('_', ' ').title()} — {format_score(s)} / {format_score(mx)} ({pct}%)")
        w("")
        w(f"{score_bar(s, mx, 25)}  {detected}")
        w("")
        if p.get("evidence", []):
            w("**Evidence:**")
            w("")
            for item in p["evidence"]:
                w(f"- {item}")
            w("")
        if p.get("recommendation", ""):
            w(f"**Recommendation:** {p['recommendation']}")
            w("")
    if gaps:
        w("## Gap Analysis")
        w("")
        w("| Severity | Pattern | Score | Max | Recommendation |")
        w("|:--------:|---------|------:|----:|----------------|")
        order = {"high": 0, "medium": 1, "low": 2}
        for g in sorted(gaps, key=lambda g: order.get(g.get("severity", "low"), 3)):
            severity = f"{severity_icon(g.get('severity', ''))} {g.get('severity', '').title()}"
            category = g.get("category", "").replace("_", " ").title()
            ps, pm = format_score(g.get("pattern_score", 0)), format_score(g.get("pattern_max", 0))
            w(f"| {severity} | {category} | {ps} | {pm} | {g.get('description', '')} |")
        w("")
    w("---")
    w(f"*Generated by AIEO • {now.strftime('%Y-%m-%d %H:%M')}*")
    w("")
    return "\n".join(lines)


def summary_report(reports: list[dict], now: datetime) -> str:
    """The summary across sites (AIEO's `render_summary_report`): rankings, distribution, heatmap, common gaps."""
    lines = []
    w = lines.append
    successful = [r for r in reports if r.get("status") == "success"]
    failed = [r for r in reports if r.get("status") != "success"]
    scores = [float(r["score"]) for r in successful]
    average = sum(scores) / len(scores) if scores else 0
    best = max(successful, key=lambda r: float(r["score"]), default=None)
    worst = min(successful, key=lambda r: float(r["score"]), default=None)

    w("# AIEO Audit Summary Report")
    w("")
    w(f"**{len(reports)} sites audited** on {now.strftime('%Y-%m-%d %H:%M')}")
    w("")
    w("## Overview")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Sites Audited | {len(reports)} |")
    w(f"| Successful | {len(successful)} |")
    w(f"| Failed | {len(failed)} |")
    w(f"| Average Score | {format_score(average)} / 100 |")
    if best:
        w(f"| Highest Score | {format_score(best['score'])} — {site_label(best['url'])} |")
    if worst:
        w(f"| Lowest Score | {format_score(worst['score'])} — {site_label(worst['url'])} |")
    model = successful[0].get("model", "") if successful else ""
    if model:
        w(f"| AI Model | {model} |")
    w("")
    w("## Site Rankings")
    w("")
    w("| Rank | Site | Score | Grade | Words | Gaps | Method |")
    w("|-----:|------|------:|:-----:|------:|-----:|--------|")
    ranked = sorted(successful, key=lambda r: float(r["score"]), reverse=True)
    for i, r in enumerate(ranked, 1):
        w(
            f"| {i} | [{site_label(r['url'])}]({r['url']}) | {format_score(r['score'])} | {grade_emoji(r['grade'])} "
            f"{r['grade']} | {r['word_count']:,} | {len(r.get('gaps', []))} | {r.get('scoring_method', '?')} |"
        )
    w("")
    if failed:
        w("### Failed Sites")
        w("")
        for r in failed:
            w(f"- {r['url']} — {r.get('error', 'unknown error')}")
        w("")
    w("## Site-by-Site Highlights")
    w("")
    for r in ranked:
        grade = r.get("grade", "?")
        w(
            f"### [{site_label(r['url'])}]({report_link(r)}) — {format_score(r['score'])}/100 ({grade_emoji(grade)} {grade})"
        )
        w("")
        if r.get("overall_assessment", ""):
            w(f"> {r['overall_assessment']}")
            w("")
        if r.get("priority_actions", []):
            w("**Top actions:**")
            w("")
            for action in r["priority_actions"][:3]:
                icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(action.get("impact", ""), "⚪")
                w(f"- {icon} **{action.get('title', '')}** — {action.get('description', '')}")
            w("")
    w("## Score Distribution")
    w("")
    w("```")
    buckets = [0] * 5
    for s in scores:
        buckets[min(int(s // 20), 4)] += 1
    top = max(buckets) if buckets else 1
    for label, count in zip(["0-19", "20-39", "40-59", "60-79", "80-100"], buckets, strict=True):
        bar = "█" * round(count / top * 30) if top else ""
        w(f"  {label:>6}  {bar} {count}")
    w("```")
    w("")
    w("## Pattern Heatmap")
    w("")
    w("How each pattern scores across all sites (percentage of max):")
    w("")
    every: dict[str, list[float]] = {}
    for r in successful:
        for name, p in r.get("pattern_scores", {}).items():
            every.setdefault(name, []).append((float(p["score"]) / float(p["max"]) * 100) if p.get("max") else 0)
    weakest_first = sorted(every.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
    w(f"| Pattern | Avg | {' | '.join(site_label(r['url'])[:12] for r in ranked)} |")
    w(f"|---------|----:|{'|'.join([' ---:'] * len(ranked))} |")
    for name, _ in weakest_first:
        cells = []
        for r in ranked:
            p = r.get("pattern_scores", {}).get(name, {})
            cells.append(f"{(float(p.get('score', 0)) / float(p.get('max', 1)) * 100) if p.get('max') else 0:.0f}%")
        w(f"| {name.replace('_', ' ').title()} | {sum(every[name]) / len(every[name]):.0f}% | {' | '.join(cells)} |")
    w("")
    w("## Most Common Gaps")
    w("")
    frequency: dict[str, dict] = {}
    for r in successful:
        for g in r.get("gaps", []):
            entry = frequency.setdefault(
                g.get("category", "unknown"),
                {"count": 0, "severity": g.get("severity", "low"), "description": g.get("description", "")},
            )
            entry["count"] += 1
    w("| Gap | Affected Sites | Severity | Recommendation |")
    w("|-----|---------------:|:--------:|----------------|")
    for category, info in sorted(frequency.items(), key=lambda kv: kv[1]["count"], reverse=True):
        severity = f"{severity_icon(info['severity'])} {info['severity'].title()}"
        w(
            f"| {category.replace('_', ' ').title()} | {info['count']} / {len(successful)} | {severity} | "
            f"{info['description']} |"
        )
    w("")
    w("## Key Takeaways")
    w("")
    weak = [name for name, pcts in weakest_first if (sum(pcts) / len(pcts)) < 30]
    strong = [name for name, pcts in weakest_first if (sum(pcts) / len(pcts)) >= 70]
    for title, names in (("Weakest Patterns Across All Sites", weak), ("Strongest Patterns Across All Sites", strong)):
        if names:
            w(f"### {title}")
            w("")
            for name in names:
                w(
                    f"- **{name.replace('_', ' ').title()}** — avg {sum(every[name]) / len(every[name]):.0f}% of max score"
                )
            w("")
    w("## Individual Reports")
    w("")
    w(
        "Each report includes a detailed executive summary, priority action plan, and concrete before/after content "
        "improvement examples written by AI:"
    )
    w("")
    for r in ranked:
        w(f"- [{site_label(r['url'])}]({report_link(r)}) — {format_score(r['score'])} / 100")
    w("")
    w("---")
    w(f"*Generated by AIEO • {now.strftime('%Y-%m-%d %H:%M')}*")
    w("")
    return "\n".join(lines)


def write(audits, directory: Path, now: datetime) -> list[Path]:
    """Every audit's report in `<name>/<name>.md` and the summary in `REPORT.md`, as AIEO laid them out."""
    data = sorted((data_of(a) for a in audits), key=lambda d: d["_name"])
    written = []
    for item in data:
        target = directory / item["_name"] / f"{item['_name']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(site_report(item, now), encoding="utf-8")
        written.append(target)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "REPORT.md").write_text(summary_report(data, now), encoding="utf-8")
    return [*written, directory / "REPORT.md"]
