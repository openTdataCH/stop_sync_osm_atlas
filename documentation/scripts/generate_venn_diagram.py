import sys
import os

svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 300" width="100%" height="300">
  <style>
    .circle1 { fill: #3498db; fill-opacity: 0.5; stroke: #2980b9; stroke-width: 2; }
    .circle2 { fill: #e74c3c; fill-opacity: 0.5; stroke: #c0392b; stroke-width: 2; }
    .text-label { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 16px; font-weight: bold; fill: #333; }
    .text-value { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px; fill: #555; }
    .text-center { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 16px; font-weight: bold; fill: #111; }
  </style>

  <!-- Left Circle (Bucket A) -->
  <circle cx="180" cy="150" r="100" class="circle1" />
  
  <!-- Right Circle (Bucket B) -->
  <circle cx="320" cy="150" r="100" class="circle2" />

  <!-- Labels -->
  <text x="120" y="140" text-anchor="middle" class="text-label">Bucket A</text>
  <text x="120" y="160" text-anchor="middle" class="text-value">Only in A:</text>
  <text x="120" y="180" text-anchor="middle" class="text-value">Stops = 5</text>

  <text x="380" y="140" text-anchor="middle" class="text-label">Bucket B</text>
  <text x="380" y="160" text-anchor="middle" class="text-value">Only in B:</text>
  <text x="380" y="180" text-anchor="middle" class="text-value">Stops = 6</text>

  <text x="250" y="140" text-anchor="middle" class="text-center">Intersection</text>
  <text x="250" y="160" text-anchor="middle" class="text-center">(A &amp; B)</text>
  <text x="250" y="180" text-anchor="middle" class="text-center">Stops = 3</text>
  
  <!-- Explanation text at bottom -->
  <text x="250" y="275" text-anchor="middle" class="text-value">Total Unique Stops = 5 + 3 + 6 = 14</text>
  <text x="250" y="295" text-anchor="middle" class="text-value">Sum of Counts = (5+3) + (6+3) = 17 (Incorrectly Double Counts)</text>
</svg>
"""

output_path = os.path.join(os.path.dirname(__file__), '../images/bucket_venn_diagram.svg')
with open(output_path, 'w') as f:
    f.write(svg_content)
print(f"Generated {output_path}")
