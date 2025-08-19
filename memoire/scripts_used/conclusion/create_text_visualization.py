#!/usr/bin/env python3
"""
Create a text-based visualization of the Python code distribution
"""

def create_text_chart(data, title, max_width=60):
    """Create a text-based horizontal bar chart."""
    print(f"\n{title}")
    print("=" * len(title))
    
    # Find the maximum value for scaling
    max_value = max(data.values())
    
    for category, value in data.items():
        # Calculate bar length
        bar_length = int((value / max_value) * max_width)
        bar = "█" * bar_length
        
        # Format the line
        percentage = (value / sum(data.values())) * 100
        print(f"{category:<25} {bar:<{max_width}} {value:>6} ({percentage:4.1f}%)")

def main():
    # Data from the analysis
    files_data = {
        'Memoire Scripts': 22,
        'Backend Blueprints': 6,
        'Matching Process': 10,
        'Data Processing': 2,
        'Data Acquisition': 2,
        'Other': 6,
        'Backend Core': 4,
        'Database & Migration': 7,
        'Backend Services': 8,
        'Analysis Scripts': 1
    }
    
    code_lines_data = {
        'Memoire Scripts': 2491,
        'Backend Blueprints': 2173,
        'Matching Process': 1912,
        'Data Processing': 944,
        'Data Acquisition': 610,
        'Other': 395,
        'Backend Core': 361,
        'Database & Migration': 358,
        'Backend Services': 323,
        'Analysis Scripts': 112
    }
    
    print("PYTHON CODE DISTRIBUTION - BACHELOR PROJECT")
    print("=" * 50)
    print(f"Total Files: {sum(files_data.values())}")
    print(f"Total Lines of Code: {sum(code_lines_data.values()):,}")
    
    create_text_chart(files_data, "DISTRIBUTION BY NUMBER OF FILES")
    create_text_chart(code_lines_data, "DISTRIBUTION BY LINES OF CODE")
    
    print("\nKEY INSIGHTS:")
    print("-" * 40)
    print("• Memoire Scripts (25.7%): Largest portion - analysis scripts for thesis")
    print("• Backend Blueprints (22.5%): Core web application API endpoints") 
    print("• Matching Process (19.8%): Core algorithms for data matching")
    print("• Data Processing (9.8%): Database import and evaluation scripts")
    print("• Data Acquisition (6.3%): Scripts to fetch external data sources")
    print("• Backend Services (3.3%): Supporting services (email, crypto, etc.)")
    print("• Backend Core (3.7%): Main Flask application structure")
    print("• Database & Migration (3.7%): Database setup and schema changes")

if __name__ == '__main__':
    main()
