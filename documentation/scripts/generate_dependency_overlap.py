#!/usr/bin/env python3
"""Generate a dependency overlap diagram for documentation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = ROOT / "documentation" / "images"

import re

def get_requirements(filename: str) -> list[str]:
    req_file = ROOT / filename
    if not req_file.exists():
        return []
    libs = []
    for line in req_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        match = re.match(r'^([^=<>\[]+)', line)
        if match:
            libs.append(match.group(1).strip())
    return libs

BASE_LIBS = get_requirements("requirements-base.txt")
WEB_LIBS = get_requirements("requirements-web.txt")
SCHED_LIBS = get_requirements("requirements-scheduler.txt")
TEST_LIBS = get_requirements("requirements-test.txt")

def generate_svg():
    width = 900
    
    # Define stages and their components using canonical brand colors from 5.6
    # Note: Reordered to show Scheduler before App as requested
    stages = {
        "Base Stage": {"libs": BASE_LIBS, "color": "#6C757D"},       # Neutral Gray
        "Scheduler Stage": {"libs": BASE_LIBS + SCHED_LIBS, "color": "#F0AD4E"}, # P2 Orange
        "App Stage": {"libs": BASE_LIBS + WEB_LIBS, "color": "#174092"},    # Primary Navy
        "Test Stage": {"libs": BASE_LIBS + WEB_LIBS + SCHED_LIBS + TEST_LIBS, "color": "#4CAF50"} # Success Green
    }
    
    # Collect all unique libraries, sorted by group priority: Base > Scheduler > Web > Test
    all_libs = []
    seen = set()
    for group in [BASE_LIBS, SCHED_LIBS, WEB_LIBS, TEST_LIBS]:
        for lib in sorted(group):
            if lib not in seen:
                all_libs.append(lib)
                seen.add(lib)
    
    # Layout constants
    margin_left = 220
    margin_top = 130
    cell_w = 140
    cell_h = 24
    
    # Calculate height dynamically based on number of libraries
    height = margin_top + (len(all_libs) * cell_h) + 80
    
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '  <rect width="100%" height="100%" fill="#ffffff"/>',
        '  <text x="40" y="50" font-size="24" font-family="sans-serif" font-weight="bold" fill="#1e293b">Dependency Stage Overlap Matrix</text>',
        '  <text x="40" y="75" font-size="14" font-family="sans-serif" fill="#64748b">Visualizing which libraries are included in each Docker build stage</text>',
    ]
    
    # Draw Stage headers
    for i, (stage_name, data) in enumerate(stages.items()):
        x = margin_left + i * cell_w
        svg.append(f'  <text x="{x + cell_w/2}" y="{margin_top - 20}" text-anchor="middle" font-size="12" font-family="sans-serif" font-weight="bold" fill="#334155">{stage_name}</text>')
        # Column line
        svg.append(f'  <line x1="{x + cell_w/2}" y1="{margin_top - 15}" x2="{x + cell_w/2}" y2="{margin_top + len(all_libs) * cell_h}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="4"/>')

    # Draw Library rows
    for i, lib in enumerate(all_libs):
        y = margin_top + i * cell_h
        # Alternating background
        if i % 2 == 0:
            svg.append(f'  <rect x="40" y="{y - cell_h/2}" width="{width - 80}" height="{cell_h}" fill="#f8fafc"/>')
        
        svg.append(f'  <text x="{margin_left - 20}" y="{y + 5}" text-anchor="end" font-size="12" font-family="monospace" fill="#1e293b">{lib}</text>')
        
        # Draw membership indicators
        for j, (stage_name, data) in enumerate(stages.items()):
            x = margin_left + j * cell_w
            if lib in data["libs"]:
                # Draw a pill/circle
                svg.append(f'  <circle cx="{x + cell_w/2}" cy="{y}" r="6" fill="{data["color"]}" />')
                # If it's a "source" library (not just inherited), maybe highlight it?
                # For now, just dots is clear.
    
    # Legend
    legend_y = height - 50
    svg.append(f'  <text x="40" y="{legend_y}" font-size="12" font-family="sans-serif" font-weight="bold">Legend (Primary Sources):</text>')
    
    sources = [
        ("Base", "#6C757D"),
        ("App/Web", "#174092"),
        ("Scheduler", "#F0AD4E"),
        ("Test", "#4CAF50")
    ]
    
    for i, (name, color) in enumerate(sources):
        x = 200 + i * 120
        svg.append(f'  <circle cx="{x}" cy="{legend_y - 4}" r="6" fill="{color}" />')
        svg.append(f'  <text x="{x + 15}" y="{legend_y}" font-size="12" font-family="sans-serif" fill="#64748b">{name}</text>')

    svg.append('</svg>')
    
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGES_DIR / "dependency_overlap.svg").write_text("\n".join(svg))
    print("Generated: documentation/images/dependency_overlap.svg")


def update_markdown():
    doc_path = ROOT / "documentation" / "7.1 Dependency Management & Build Strategy.md"
    if not doc_path.exists():
        return
        
    doc_content = doc_path.read_text()
    
    # Format the lists exactly how the test expects 
    def format_libs(libs):
        return ", ".join(f"`{lib}`" for lib in sorted(libs))

    descriptions = {
        "requirements-base.txt": "Shared core backend foundations requested by all containers",
        "requirements-web.txt": "Web-only stack for the API and UI",
        "requirements-scheduler.txt": "Heavy geospatial stack required for the data pipeline",
        "requirements-test.txt": "Testing frameworks"
    }

    new_lines = []
    new_lines.append("<!-- DEPENDENCIES_START -->")
    new_lines.append(f"- `requirements-base.txt`: {descriptions['requirements-base.txt']} ({format_libs(BASE_LIBS)}).")
    new_lines.append(f"- `requirements-web.txt`: {descriptions['requirements-web.txt']} ({format_libs(WEB_LIBS)}).")
    new_lines.append(f"- `requirements-scheduler.txt`: {descriptions['requirements-scheduler.txt']} ({format_libs(SCHED_LIBS)}).")
    new_lines.append(f"- `requirements-test.txt`: {descriptions['requirements-test.txt']} ({format_libs(TEST_LIBS)}).")
    new_lines.append("<!-- DEPENDENCIES_END -->")
    
    import re
    # Replace anything between the blocks
    pattern = re.compile(r"<!-- DEPENDENCIES_START -->.*?<!-- DEPENDENCIES_END -->", re.DOTALL)
    
    if pattern.search(doc_content):
        new_content = pattern.sub("\n".join(new_lines), doc_content)
    else:
        # Fallback: find the bullet points and replace them if markers aren't there
        pattern = re.compile(r"- `requirements-base\.txt`:.*?- `requirements-test\.txt`:[^\n]*\n", re.DOTALL)
        new_content = pattern.sub("\n".join(new_lines) + "\n", doc_content)
        
    if new_content != doc_content:
        doc_path.write_text(new_content)
        print("Updated: 7.1 Dependency Management & Build Strategy.md")


if __name__ == "__main__":
    generate_svg()
    update_markdown()

