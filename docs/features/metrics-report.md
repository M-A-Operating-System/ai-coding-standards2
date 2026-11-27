# Feature: Metrics Report

## Scenario: WeasyPrint embeds all chart images in a full metrics report PDF
**Given** `build_html()` generates HTML for a 16-metric report containing 32 chart images encoded as base64 PNGs
**When** `weasyprint.HTML(string=html).write_pdf(output)` renders the HTML to a PDF file
**Then** the PDF at `output` contains exactly 32 embedded images as reported by a PDF image-inspection tool (e.g. `pdfimages -list`)

## Scenario: HTML template does not use the broken flex-and-percentage-width CSS combination
**Given** `_HTML_HEADER` from `pipeline/metrics_report.py` is used to render a metrics report
**When** the CSS rules for `.row` and `.row img` are inspected in the rendered HTML
**Then** `.row` does not set `display: flex` simultaneously with `.row img` using both a percentage `width` and `height: auto`
