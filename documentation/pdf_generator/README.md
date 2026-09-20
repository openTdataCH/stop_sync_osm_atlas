# Documentation PDF Generator

This folder contains the script and CSS that generate one PDF from the app- and engine-owned Markdown documentation.

## How it works

The PDF build follows a three-stage process:
1. **Local Mermaid rendering**: `scripts/render_docs_mermaid.mjs` discovers Mermaid blocks and renders content-addressed SVGs with the project's pinned Mermaid package and local Chromium. The render page blocks HTTP(S) requests. The Docker build performs this in its own Node stage; no diagram source is sent over the network at runtime.
2. **Markdown to HTML**: `build_docs_pdf.py` gathers top-level `.md` files from `documentation/` and `engine/documentation/`, orders them as overview → engine → application, replaces local links with anchors, injects stats placeholders, rewrites repository links to GitHub blob URLs, and embeds the pre-rendered Mermaid SVGs.
3. **WeasyPrint rendering**: It renders the combined HTML plus `docs_print.css` into the final PDF.

## Usage

**Prerequisites:**
- The Python dependencies used by the web/docs stack must be installed, including `mistune` and `weasyprint`.
- Node dependencies must be installed with `npm ci`.
- A local Chrome or Chromium executable is required only when Mermaid assets are missing or have changed. The production image installs Chromium in the dedicated diagram build stage.

You can run the script via the VS Code Tasks:
- `Tasks: Run Task` -> `Docs: Build PDF`

Or directly from your terminal:
```bash
npm run docs:build-pdf
```

The combined command first updates only missing diagram assets and then runs the Python PDF generator. `npm run docs:check-mermaid` performs a fast completeness check without launching a browser. The Python generator deliberately does not fall back to a network service; a missing SVG fails with the command needed to create it.

## Generated Files

The generated HTML bundle, local Mermaid/SVG assets, and final PDF are placed inside `documentation/generated/`. This directory is ignored by Git. Docker copies the build-stage Mermaid assets into the application image so runtime PDF exports need neither Node nor network access.
