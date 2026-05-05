# Documentation PDF Generator

This folder contains a script and associated CSS to generate a PDF from the repository's markdown documentation.

## How it works

The `build_docs_pdf.py` script follows a two-stage process:
1. **Markdown to HTML**: It gathers the `.md` files in the `documentation/` folder, replaces local links with anchors, injects stats placeholders, rewrites repo links to GitHub blob URLs, and converts Mermaid diagrams to local SVGs through the Kroki API.
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

The generated HTML bundle, extracted SVG diagrams, and the final PDF are placed inside the `documentation/generated/` folder. This folder is ignored by git.
