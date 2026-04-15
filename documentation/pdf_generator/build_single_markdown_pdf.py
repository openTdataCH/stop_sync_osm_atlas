from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import mistune
from weasyprint import CSS, HTML


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Reuse the existing diagram rendering and markdown helpers.
from documentation.pdf_generator import build_docs_pdf as docs_builder


def _default_output_path(input_markdown: Path) -> Path:
    return docs_builder.OUTPUT_DIR / f"{input_markdown.stem}.pdf"


def _build_single_markdown_pdf(input_markdown: Path, output_pdf: Path, title: str | None = None) -> Path:
    if not input_markdown.exists():
        raise FileNotFoundError(f"Input markdown file not found: {input_markdown}")

    docs_builder.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    docs_builder.DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    markdown_content = input_markdown.read_text(encoding="utf-8")
    stats = docs_builder.load_stats_for_docs()

    markdown_content = docs_builder.replace_stats_placeholders(markdown_content, stats, html_escape=True)
    markdown_content = docs_builder.convert_github_alerts_to_html(markdown_content)
    markdown_content = docs_builder._rewrite_repo_links(markdown_content)
    markdown_content = docs_builder._rewrite_mermaid_blocks(markdown_content)

    if "[[canonical_palette]]" in markdown_content:
        markdown_content = markdown_content.replace(
            "[[canonical_palette]]",
            docs_builder.get_canonical_palette_html(),
        )

    # Preserve LaTeX backslashes before Mistune parsing.
    markdown_content = re.sub(r"\$\$.*?\$\$", docs_builder._protect_math, markdown_content, flags=re.DOTALL)
    markdown_content = re.sub(r"(?<!\$)\$[^\s$](?:.*?[^\s$])?\$(?!\$)", docs_builder._protect_math, markdown_content)

    markdown_parser = mistune.create_markdown(escape=False, plugins=["strikethrough", "table", "url"])
    body_html = markdown_parser(markdown_content)

    html_title = title or input_markdown.stem.replace("_", " ")
    full_html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <title>{html_title}</title>
</head>
<body>
{body_html}
</body>
</html>
"""

    html_doc = HTML(string=full_html, base_url=str(REPO_ROOT.absolute()))
    css_doc = CSS(filename=str(docs_builder.STYLE_PATH.absolute()))
    html_doc.write_pdf(target=str(output_pdf.absolute()), stylesheets=[css_doc])
    return output_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a print-ready PDF from one markdown file.")
    parser.add_argument("input", help="Path to the markdown file to render.")
    parser.add_argument("-o", "--output", help="Output PDF path. Defaults to documentation/generated/<input-stem>.pdf")
    parser.add_argument("--title", help="Optional HTML/PDF title.")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve() if args.output else _default_output_path(input_path)

    try:
        pdf_path = _build_single_markdown_pdf(input_path, output_path, title=args.title)
        print(f"PDF successfully generated at {pdf_path}")
    except Exception as error:
        print(f"PDF generation failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
