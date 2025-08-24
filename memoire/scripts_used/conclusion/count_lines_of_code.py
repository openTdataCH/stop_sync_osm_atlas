#!/usr/bin/env python3
"""
Lines of Code Counter

This script counts lines of code in the repository for Python, HTML, JavaScript, and CSS files.
It provides detailed statistics including total lines, non-empty lines, and comment lines.
"""

import os
import re
from pathlib import Path
from collections import defaultdict
import argparse


def count_lines_in_file(file_path, file_type):
    """
    Count different types of lines in a file.
    
    Returns:
        dict: Contains 'total', 'non_empty', 'comments', 'code' line counts
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")
        return {'total': 0, 'non_empty': 0, 'comments': 0, 'code': 0}
    
    total_lines = len(lines)
    non_empty_lines = 0
    comment_lines = 0
    
    # Define comment patterns for different file types
    comment_patterns = {
        'python': [r'^\s*#', r'^\s*"""', r'^\s*\'\'\''],
        'html': [r'^\s*<!--', r'<!--.*-->'],
        'javascript': [r'^\s*//', r'^\s*/\*', r'^\s*\*'],
        'css': [r'^\s*/\*', r'^\s*\*']
    }
    
    patterns = comment_patterns.get(file_type, [])
    
    in_multiline_comment = False
    multiline_start_patterns = {
        'python': [r'^\s*"""', r'^\s*\'\'\''],
        'html': [r'^\s*<!--'],
        'javascript': [r'^\s*/\*'],
        'css': [r'^\s*/\*']
    }
    
    multiline_end_patterns = {
        'python': [r'"""', r'\'\'\''],
        'html': [r'-->'],
        'javascript': [r'\*/'],
        'css': [r'\*/']
    }
    
    for line in lines:
        stripped_line = line.strip()
        
        # Count non-empty lines
        if stripped_line:
            non_empty_lines += 1
            
            # Check for multiline comment start/end
            if file_type in multiline_start_patterns:
                if not in_multiline_comment:
                    for pattern in multiline_start_patterns[file_type]:
                        if re.search(pattern, stripped_line):
                            in_multiline_comment = True
                            break
                
                if in_multiline_comment:
                    comment_lines += 1
                    for pattern in multiline_end_patterns[file_type]:
                        if re.search(pattern, stripped_line):
                            in_multiline_comment = False
                            break
                    continue
            
            # Check for single-line comments
            is_comment = False
            for pattern in patterns:
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


def get_file_type(file_path):
    """Determine file type based on extension."""
    extension = Path(file_path).suffix.lower()
    
    type_mapping = {
        '.py': 'python',
        '.html': 'html',
        '.htm': 'html',
        '.js': 'javascript',
        '.css': 'css'
    }
    
    return type_mapping.get(extension)


def scan_directory(root_dir, exclude_dirs=None):
    """
    Scan directory for relevant files and count lines.
    
    Args:
        root_dir: Root directory to scan
        exclude_dirs: List of directory names to exclude
    
    Returns:
        dict: Statistics organized by file type
    """
    if exclude_dirs is None:
        exclude_dirs = {'.git', '__pycache__', 'node_modules', '.pytest_cache', 
                       'venv', 'env', '.venv', 'migrations/versions'}
    
    stats = defaultdict(lambda: {
        'files': 0,
        'total_lines': 0,
        'non_empty_lines': 0,
        'comment_lines': 0,
        'code_lines': 0,
        'file_details': []
    })
    
    root_path = Path(root_dir)
    
    for file_path in root_path.rglob('*'):
        # Skip if it's not a file
        if not file_path.is_file():
            continue
            
        # Skip if in excluded directory
        if any(excluded in str(file_path) for excluded in exclude_dirs):
            continue
            
        file_type = get_file_type(file_path)
        if not file_type:
            continue
            
        # Count lines in this file
        line_counts = count_lines_in_file(file_path, file_type)
        
        # Update statistics
        stats[file_type]['files'] += 1
        stats[file_type]['total_lines'] += line_counts['total']
        stats[file_type]['non_empty_lines'] += line_counts['non_empty']
        stats[file_type]['comment_lines'] += line_counts['comments']
        stats[file_type]['code_lines'] += line_counts['code']
        
        # Store file details for detailed output
        relative_path = file_path.relative_to(root_path)
        stats[file_type]['file_details'].append({
            'path': str(relative_path),
            'lines': line_counts
        })
    
    return dict(stats)


def print_summary(stats):
    """Print a summary of the line count statistics."""
    
    print("=" * 80)
    print("LINES OF CODE SUMMARY")
    print("=" * 80)
    
    # Calculate totals
    total_files = sum(data['files'] for data in stats.values())
    total_total_lines = sum(data['total_lines'] for data in stats.values())
    total_non_empty_lines = sum(data['non_empty_lines'] for data in stats.values())
    total_comment_lines = sum(data['comment_lines'] for data in stats.values())
    total_code_lines = sum(data['code_lines'] for data in stats.values())
    
    # Print by file type
    file_types = ['python', 'html', 'javascript', 'css']
    
    print(f"{'File Type':<12} {'Files':<6} {'Total':<8} {'Non-Empty':<10} {'Comments':<9} {'Code':<8}")
    print("-" * 80)
    
    for file_type in file_types:
        if file_type in stats:
            data = stats[file_type]
            print(f"{file_type.capitalize():<12} {data['files']:<6} {data['total_lines']:<8} "
                  f"{data['non_empty_lines']:<10} {data['comment_lines']:<9} {data['code_lines']:<8}")
    
    print("-" * 80)
    print(f"{'TOTAL':<12} {total_files:<6} {total_total_lines:<8} "
          f"{total_non_empty_lines:<10} {total_comment_lines:<9} {total_code_lines:<8}")
    print("=" * 80)


def print_detailed_report(stats):
    """Print detailed file-by-file report."""
    
    print("\nDETAILED FILE REPORT")
    print("=" * 80)
    
    file_types = ['python', 'html', 'javascript', 'css']
    
    for file_type in file_types:
        if file_type not in stats:
            continue
            
        print(f"\n{file_type.upper()} FILES:")
        print("-" * 60)
        print(f"{'File':<50} {'Total':<6} {'Code':<6}")
        print("-" * 60)
        
        # Sort files by code lines (descending)
        files = sorted(stats[file_type]['file_details'], 
                      key=lambda x: x['lines']['code'], reverse=True)
        
        for file_info in files:
            path = file_info['path']
            lines = file_info['lines']
            
            # Truncate long paths
            if len(path) > 47:
                path = "..." + path[-44:]
                
            print(f"{path:<50} {lines['total']:<6} {lines['code']:<6}")


def main():
    parser = argparse.ArgumentParser(description='Count lines of code in the repository')
    parser.add_argument('--directory', '-d', default='.', 
                       help='Directory to scan (default: current directory)')
    parser.add_argument('--detailed', action='store_true',
                       help='Show detailed file-by-file report')
    parser.add_argument('--exclude', nargs='*', default=[],
                       help='Additional directories to exclude')
    
    args = parser.parse_args()
    
    # Default exclusions
    exclude_dirs = {'.git', '__pycache__', 'node_modules', '.pytest_cache', 
                   'venv', 'env', '.venv', 'migrations/versions'}
    
    # Add user-specified exclusions
    exclude_dirs.update(args.exclude)
    
    print(f"Scanning directory: {os.path.abspath(args.directory)}")
    print(f"Excluding directories: {', '.join(sorted(exclude_dirs))}")
    print()
    
    # Scan and count
    stats = scan_directory(args.directory, exclude_dirs)
    
    if not stats:
        print("No Python, HTML, JavaScript, or CSS files found!")
        return
    
    # Print results
    print_summary(stats)
    
    if args.detailed:
        print_detailed_report(stats)


if __name__ == '__main__':
    main()
