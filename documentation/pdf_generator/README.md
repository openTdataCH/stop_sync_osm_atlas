# Documentation PDF Generator

This folder contains the script and CSS that generate one PDF from the app- and engine-owned Markdown documentation.

## How it works

The `build_docs_pdf.py` script follows a two-stage process:
1. **Markdown to HTML**: It gathers top-level `.md` files from `documentation/` and `engine/documentation/`, orders them as overview → engine → application, replaces local links with anchors, injects stats placeholders, rewrites repository links to GitHub blob URLs, and converts Mermaid diagrams to local SVGs through the Kroki API.
2. **WeasyPrint rendering**: It renders the combined HTML plus `docs_print.css` into the final PDF.

## Usage

**Prerequisites:**
- The Python dependencies used by the web/docs stack must be installed, including `mistune` and `weasyprint`.
- The generator needs network access to `https://kroki.io/mermaid/svg` so Mermaid blocks can be rendered to SVG.

You can run the script via the VS Code Tasks:
- `Tasks: Run Task` -> `Docs: Build PDF`

Or directly from your terminal:
```bash
python3 documentation/pdf_generator/build_docs_pdf.py
```

## Generated Files

The generated HTML bundle, extracted SVG diagrams, and final PDF are placed inside `documentation/generated/`. This directory is ignored by Git and excluded from the application image.
