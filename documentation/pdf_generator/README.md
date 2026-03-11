# Documentation PDF Generator

This folder contains a script and associated CSS to generate a PDF from the repository's markdown documentation.

## How it works

The `build_docs_pdf.py` script follows a two-stage process:
1. **Pandoc**: It gathers all `.md` files in the `documentation/` folder, replaces local links with anchors, fetches pipeline statistics, converts Mermaid diagrams to SVGs (using the Kroki API), and compiles everything into a single, standalone HTML5 file.
2. **Headless Chrome**: It uses your locally installed Google Chrome (or Chromium) in headless mode to "print" this HTML to a high-quality (300+ DPI) PDF document.

## Usage

**Prerequisites:**
- `pandoc` must be installed and available in your `PATH`.
- **Google Chrome** or **Chromium** must be installed (typially found at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` on macOS).

You can run the script via the VS Code Tasks:
- `Tasks: Run Task` -> `Docs: Build PDF`

Or directly from your terminal:
```bash
python3 documentation/pdf_generator/build_docs_pdf.py
```

## Generated Files

All intermediate files (like the standalone HTML format and extracted SVG diagrams) and the final PDF are placed inside the `documentation/generated/` folder. This folder is ignored by git.
