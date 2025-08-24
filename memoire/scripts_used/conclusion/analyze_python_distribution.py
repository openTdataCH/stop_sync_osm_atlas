#!/usr/bin/env python3
"""
Python Files Distribution Analysis

This script analyzes how Python code is distributed across different modules
in the bachelor project repository and creates visualizations.
"""

import os
import re
from pathlib import Path
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import json


def count_lines_in_file(file_path):
    """Count different types of lines in a Python file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")
        return {'total': 0, 'non_empty': 0, 'comments': 0, 'code': 0}
    
    total_lines = len(lines)
    non_empty_lines = 0
    comment_lines = 0
    
    # Comment patterns for Python
    comment_patterns = [r'^\s*#', r'^\s*"""', r'^\s*\'\'\'']
    
    in_multiline_comment = False
    
    for line in lines:
        stripped_line = line.strip()
        
        if stripped_line:
            non_empty_lines += 1
            
            # Check for multiline comment start/end
            if not in_multiline_comment:
                if re.search(r'^\s*"""', stripped_line) or re.search(r'^\s*\'\'\'', stripped_line):
                    in_multiline_comment = True
            
            if in_multiline_comment:
                comment_lines += 1
                if re.search(r'"""', stripped_line) or re.search(r'\'\'\'', stripped_line):
                    # Check if it ends on the same line it started
                    if not (re.search(r'^\s*""".*"""', stripped_line) or re.search(r'^\s*\'\'\'.*\'\'\'', stripped_line)):
                        in_multiline_comment = False
                continue
            
            # Check for single-line comments
            is_comment = False
            for pattern in comment_patterns:
                if re.match(pattern, stripped_line):
                    is_comment = True
                    break
            
            if is_comment:
                comment_lines += 1
    
    code_lines = non_empty_lines - comment_lines
    
    return {
        'total': total_lines,
        'non_empty': non_empty_lines,
        'comments': comment_lines,
        'code': code_lines
    }


def categorize_python_files(root_dir):
    """Categorize Python files by their location and purpose."""
    
    categories = {
        'Backend Core': {
            'description': 'Main Flask application and core backend functionality',
            'patterns': ['backend/app.py', 'backend/models.py', 'backend/extensions.py', 
                        'backend/auth_models.py', 'backend/query_*.py'],
            'files': []
        },
        'Backend Blueprints': {
            'description': 'Flask blueprints for different API endpoints',
            'patterns': ['backend/blueprints/'],
            'files': []
        },
        'Backend Services': {
            'description': 'Backend service modules (email, crypto, audit, etc.)',
            'patterns': ['backend/services/', 'backend/serializers/', 'backend/queries/'],
            'files': []
        },
        'Matching Process': {
            'description': 'Core matching algorithms and spatial processing',
            'patterns': ['matching_process/'],
            'files': []
        },
        'Data Acquisition': {
            'description': 'Scripts to fetch external data (Atlas, OSM)',
            'patterns': ['get_atlas_data.py', 'get_osm_data.py'],
            'files': []
        },
        'Data Processing': {
            'description': 'Data import and processing utilities',
            'patterns': ['import_data_db.py', 'evaluate_gtfs_matching.py'],
            'files': []
        },
        'Analysis Scripts': {
            'description': 'Analysis and evaluation scripts',
            'patterns': ['analyze_*.py', 'count_lines_of_code.py'],
            'files': []
        },
        'Memoire Scripts': {
            'description': 'Scripts used for thesis/memoire analysis and plots',
            'patterns': ['memoire/scripts_used/'],
            'files': []
        },
        'Database & Migration': {
            'description': 'Database setup and migration scripts',
            'patterns': ['create_auth_tables.py', 'manage.py', 'migrations/'],
            'files': []
        }
    }
    
    root_path = Path(root_dir)
    
    # Find all Python files (excluding system/virtual env paths)
    python_files = []
    exclude_patterns = [
        'venv/', '.venv/', 'env/', '.env/',
        'site-packages/', '__pycache__/', '.git/',
        'anaconda', 'miniconda', '.conda'
    ]
    
    for file_path in root_path.rglob('*.py'):
        if file_path.is_file():
            # Skip if path contains excluded patterns
            path_str = str(file_path)
            if any(pattern in path_str for pattern in exclude_patterns):
                continue
                
            relative_path = file_path.relative_to(root_path)
            python_files.append({
                'path': str(relative_path),
                'full_path': file_path,
                'stats': count_lines_in_file(file_path)
            })
    
    # Categorize files
    uncategorized = []
    
    for file_info in python_files:
        file_path = file_info['path']
        categorized = False
        
        for category_name, category_info in categories.items():
            for pattern in category_info['patterns']:
                if pattern in file_path or file_path.startswith(pattern.rstrip('/')):
                    category_info['files'].append(file_info)
                    categorized = True
                    break
            if categorized:
                break
        
        if not categorized:
            uncategorized.append(file_info)
    
    # Add uncategorized files if any
    if uncategorized:
        categories['Other'] = {
            'description': 'Uncategorized Python files',
            'patterns': [],
            'files': uncategorized
        }
    
    return categories


def create_distribution_plots(categories):
    """Create visualizations of the Python code distribution."""
    
    # Calculate statistics for each category
    category_stats = {}
    for name, info in categories.items():
        if not info['files']:
            continue
            
        total_files = len(info['files'])
        total_lines = sum(f['stats']['total'] for f in info['files'])
        total_code = sum(f['stats']['code'] for f in info['files'])
        
        category_stats[name] = {
            'files': total_files,
            'total_lines': total_lines,
            'code_lines': total_code,
            'description': info['description']
        }
    
    # Create the plots - only 2 plots now
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    fig.suptitle('Python Code Distribution Analysis - Bachelor Project', fontsize=16, fontweight='bold')
    
    # Colors for consistency across plots
    colors = plt.cm.Set3(np.linspace(0, 1, len(category_stats)))
    
    categories_list = list(category_stats.keys())
    
    # 1. Files per category (Bar chart)
    files_count = [category_stats[cat]['files'] for cat in categories_list]
    bars1 = ax1.bar(range(len(categories_list)), files_count, color=colors)
    ax1.set_title('Number of Python Files by Category', fontweight='bold', pad=20)
    ax1.set_xlabel('Category')
    ax1.set_ylabel('Number of Files')
    ax1.set_xticks(range(len(categories_list)))
    ax1.set_xticklabels(categories_list, rotation=45, ha='right')
    
    # Add value labels on bars
    for bar, count in zip(bars1, files_count):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                f'{count}', ha='center', va='bottom')
    
    # 2. Code lines per category (Bar chart)
    code_lines = [category_stats[cat]['code_lines'] for cat in categories_list]
    bars2 = ax2.bar(range(len(categories_list)), code_lines, color=colors)
    ax2.set_title('Lines of Code by Category', fontweight='bold', pad=20)
    ax2.set_xlabel('Category')
    ax2.set_ylabel('Lines of Code')
    ax2.set_xticks(range(len(categories_list)))
    ax2.set_xticklabels(categories_list, rotation=45, ha='right')
    
    # Add value labels on bars
    for bar, count in zip(bars2, code_lines):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 50,
                f'{count}', ha='center', va='bottom')
    
    plt.tight_layout()
    
    # Save the plot
    output_path = 'python_distribution_analysis.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved as: {output_path}")
    
    # Close the plot to free memory
    plt.close()
    
    return category_stats


def print_detailed_analysis(categories, category_stats):
    """Print detailed analysis of the Python code distribution."""
    
    print("=" * 80)
    print("PYTHON CODE DISTRIBUTION ANALYSIS")
    print("=" * 80)
    
    total_files = sum(stats['files'] for stats in category_stats.values())
    total_code = sum(stats['code_lines'] for stats in category_stats.values())
    
    print(f"Total Python files analyzed: {total_files}")
    print(f"Total lines of Python code: {total_code:,}")
    print()
    
    # Sort categories by code lines (descending)
    sorted_categories = sorted(category_stats.items(), 
                              key=lambda x: x[1]['code_lines'], reverse=True)
    
    print(f"{'Category':<25} {'Files':<6} {'Code Lines':<12} {'%':<6} {'Description'}")
    print("-" * 100)
    
    for category_name, stats in sorted_categories:
        percentage = (stats['code_lines'] / total_code) * 100
        description = categories[category_name]['description']
        
        print(f"{category_name:<25} {stats['files']:<6} {stats['code_lines']:<12,} "
              f"{percentage:<5.1f}% {description}")
    
    print("-" * 100)
    print(f"{'TOTAL':<25} {total_files:<6} {total_code:<12,} {'100.0%':<6}")
    print()
    
    # Show top files in each major category
    print("\nTOP FILES BY CATEGORY (by lines of code):")
    print("=" * 80)
    
    for category_name, stats in sorted_categories[:5]:  # Top 5 categories
        if stats['files'] == 0:
            continue
            
        print(f"\n{category_name.upper()}:")
        print("-" * 60)
        
        # Sort files in this category by code lines
        files = sorted(categories[category_name]['files'], 
                      key=lambda x: x['stats']['code'], reverse=True)
        
        for i, file_info in enumerate(files[:5]):  # Top 5 files
            path = file_info['path']
            code_lines = file_info['stats']['code']
            total_lines = file_info['stats']['total']
            
            # Truncate long paths
            if len(path) > 50:
                path = "..." + path[-47:]
            
            print(f"  {i+1}. {path:<50} {code_lines:>5} lines ({total_lines} total)")


def save_analysis_json(categories, category_stats):
    """Save the analysis results to a JSON file for further processing."""
    
    # Prepare data for JSON serialization
    analysis_data = {
        'summary': category_stats,
        'detailed': {}
    }
    
    for category_name, category_info in categories.items():
        if not category_info['files']:
            continue
            
        analysis_data['detailed'][category_name] = {
            'description': category_info['description'],
            'files': []
        }
        
        for file_info in category_info['files']:
            analysis_data['detailed'][category_name]['files'].append({
                'path': file_info['path'],
                'total_lines': file_info['stats']['total'],
                'code_lines': file_info['stats']['code'],
                'comment_lines': file_info['stats']['comments']
            })
    
    output_path = 'python_distribution_analysis.json'
    with open(output_path, 'w') as f:
        json.dump(analysis_data, f, indent=2)
    
    print(f"Analysis data saved as: {output_path}")


def main():
    root_dir = '.'
    
    print("Analyzing Python code distribution...")
    print(f"Scanning directory: {os.path.abspath(root_dir)}")
    print()
    
    # Categorize files
    categories = categorize_python_files(root_dir)
    
    # Create visualizations
    category_stats = create_distribution_plots(categories)
    
    # Print detailed analysis
    print_detailed_analysis(categories, category_stats)
    
    # Save JSON data
    save_analysis_json(categories, category_stats)


if __name__ == '__main__':
    main()
