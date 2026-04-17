"""
core/report/html_template.py

Jinja2 HTML template helpers for report rendering.
The PDF renderer (pdf_renderer.py) uses inline HTML strings for portability,
but this module provides a Jinja2-based alternative for use cases where
a full template engine is preferred — e.g. email delivery, web preview,
or white-labelled reports with custom branding.

Usage:
    from core.report.html_template import render_report_html
    html = render_report_html(report, brand_name="Kalshi")
"""
from __future__ import annotations

from api.schemas.report import ReportOutput, Severity

# Jinja2 is bundled with FastAPI's dependencies — safe to import
try:
    from jinja2 import Environment, BaseLoader
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False

SEVERITY_COLORS = {
    Severity.critical: ("#7f1d1d", "#fecaca"),
    Severity.high:     ("#78350f", "#fde68a"),
    Severity.medium:   ("#1e3a5f", "#bfdbfe"),
    Severity.low:      ("#14532d", "#bbf7d0"),
}

REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Contract Audit Report — {{ report.id }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         font-size: 14px; color: #111; max-width: 860px; margin: 0 auto; padding: 40px 24px; }
  h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; }
  .meta { color: #666; font-size: 12px; margin-bottom: 32px; }
  .score-row { display: flex; align-items: center; gap: 20px; padding: 20px;
               border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 28px; }
  .score-num { font-size: 48px; font-weight: 700; line-height: 1; color: {{ score_color }}; }
  .score-label { font-size: 18px; font-weight: 600; color: {{ score_color }}; }
  .pills { display: flex; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
  .pill { padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  h2 { font-size: 16px; font-weight: 600; margin: 24px 0 12px;
       border-bottom: 1px solid #e5e5e5; padding-bottom: 6px; }
  .finding { border: 1px solid #e5e5e5; border-radius: 8px; margin-bottom: 16px;
             padding: 16px; page-break-inside: avoid; }
  .finding-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .badge { padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .cat { font-size: 11px; color: #666; }
  .desc { margin: 8px 0; line-height: 1.6; }
  .label { font-size: 10px; font-weight: 700; text-transform: uppercase;
           letter-spacing: 0.06em; color: #888; margin: 10px 0 4px; }
  .clause { background: #f8f8f8; border-left: 3px solid #ccc; padding: 8px 12px;
             border-radius: 0 4px 4px 0; font-size: 13px; }
  .rewrite { background: #f0fdf4; border-left: 3px solid #4ade80; padding: 8px 12px;
              border-radius: 0 4px 4px 0; font-size: 13px; }
  .evidence { font-size: 12px; color: #555; margin-top: 8px; }
  .evidence li { margin-bottom: 2px; }
  .rewritten { background: #f9fafb; border: 1px solid #e5e5e5; border-radius: 8px;
               padding: 16px; font-size: 13px; white-space: pre-wrap; font-family: monospace; }
  .footer { font-size: 11px; color: #aaa; margin-top: 40px; padding-top: 12px;
            border-top: 1px solid #e5e5e5; }
</style>
</head>
<body>
  <h1>Contract Audit Report{% if brand_name %} — {{ brand_name }}{% endif %}</h1>
  <div class="meta">
    Report ID: {{ report.id }} &nbsp;|&nbsp;
    Generated: {{ report.created_at.strftime('%Y-%m-%d %H:%M UTC') }}
  </div>

  <div class="score-row">
    <div class="score-num">{{ report.resolution_clarity_score }}</div>
    <div>
      <div class="score-label">{{ report.score_label }}</div>
      <div style="font-size:12px;color:#888;margin-top:2px">Resolution Clarity Score (0–100)</div>
      <div class="pills">
        {% if report.critical_count > 0 %}
        <span class="pill" style="background:#fecaca;color:#7f1d1d">{{ report.critical_count }} Critical</span>
        {% endif %}
        {% if report.high_count > 0 %}
        <span class="pill" style="background:#fde68a;color:#78350f">{{ report.high_count }} High</span>
        {% endif %}
        {% if report.medium_count > 0 %}
        <span class="pill" style="background:#bfdbfe;color:#1e3a5f">{{ report.medium_count }} Medium</span>
        {% endif %}
        {% if report.low_count > 0 %}
        <span class="pill" style="background:#bbf7d0;color:#14532d">{{ report.low_count }} Low</span>
        {% endif %}
      </div>
    </div>
  </div>

  <h2>Findings ({{ report.findings | length }} total)</h2>
  {% for f in report.findings %}
  {% set sev_color = severity_colors[f.severity][0] %}
  {% set sev_bg = severity_colors[f.severity][1] %}
  <div class="finding">
    <div class="finding-header">
      <span class="badge" style="background:{{ sev_bg }};color:{{ sev_color }}">
        {{ f.severity.value.upper() }}
      </span>
      <span class="cat">{{ f.category.value.replace('_', ' ').title() }}</span>
    </div>
    <div class="desc">{{ f.description }}</div>
    <div class="label">Affected clause</div>
    <div class="clause">{{ f.affected_clause }}</div>
    <div class="label">Suggested rewrite</div>
    <div class="rewrite">{{ f.rewrite }}</div>
    {% if f.evidence %}
    <div class="label">Evidence</div>
    <ul class="evidence">
      {% for ev in f.evidence[:5] %}<li>{{ ev }}</li>{% endfor %}
    </ul>
    {% endif %}
  </div>
  {% endfor %}

  {% if report.rewritten_contract %}
  <h2>Composite Rewritten Contract</h2>
  <div class="rewritten">{{ report.rewritten_contract }}</div>
  {% endif %}

  <div class="footer">
    Audit duration: {{ '%.1f'|format(report.audit_duration_seconds) }}s &nbsp;|&nbsp;
    Model: {{ report.model_version }} &nbsp;|&nbsp;
    Generated by Contract Auditor
  </div>
</body>
</html>
"""


def render_report_html(
    report: ReportOutput,
    brand_name: str | None = None,
) -> str:
    """
    Render a full HTML report using Jinja2.

    Args:
        report: The ReportOutput to render
        brand_name: Optional platform name for white-labelling (e.g. "Kalshi")

    Returns:
        Full HTML string
    """
    if not _JINJA2_AVAILABLE:
        raise ImportError(
            "jinja2 is required for HTML template rendering. "
            "It is included in the project dependencies."
        )

    score = report.resolution_clarity_score
    if score >= 70:
        score_color = "#166534"
    elif score >= 50:
        score_color = "#92400e"
    else:
        score_color = "#991b1b"

    env = Environment(loader=BaseLoader())
    template = env.from_string(REPORT_TEMPLATE)
    return template.render(
        report=report,
        brand_name=brand_name,
        score_color=score_color,
        severity_colors=SEVERITY_COLORS,
    )
