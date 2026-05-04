import os
import logging
from typing import Dict, List, Set, Optional

logger = logging.getLogger(__name__)

# Extensions to consider for auto-linking (synchronized with docs.py)
CODE_EXTENSIONS = {
    '.py', '.sql', '.sh', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg',
    '.js', '.ts', '.tsx', '.jsx', '.css', '.html',
}

# Directories to ignore during scanning
IGNORE_DIRS = {
    '.git', 'node_modules', 'venv', '.venv', '__pycache__', 
    'htmlcov', '.pytest_cache', 'documentation', 'data', 'coverage', '.gemini',
    'vendor', 'dist', 'build'
}

class RepoScanner:
    """
    Scans the repository to build a map of filename -> relative paths.
    """
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self._file_map: Dict[str, List[str]] = {}
        self._path_to_file: Dict[str, str] = {}
        self.scan()

    def scan(self):
        """Perform the repository scan."""
        logger.info(f"Scanning repository for code files in {self.root_dir}")
        file_map = {}
        
        for root, dirs, files in os.walk(self.root_dir):
            # In-place modification to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
            
            rel_root = os.path.relpath(root, self.root_dir)
            if rel_root == '.':
                rel_root = ''
                
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() in CODE_EXTENSIONS:
                    if file not in file_map:
                        file_map[file] = []
                    
                    rel_path = os.path.join(rel_root, file)
                    file_map[file].append(rel_path)

        self._file_map = file_map
        logger.info(f"Scan complete. Found {len(file_map)} unique filenames.")

    def get_paths(self, filename: str) -> List[str]:
        """Returns all relative paths found for a given filename."""
        return self._file_map.get(filename, [])

    def resolve_path(self, path_query: str) -> Optional[str]:
        """
        Tries to resolve a path query to a unique repository file.
        path_query can be a filename (e.g. 'app.py') or a partial path (e.g. 'backend/app.py').
        """
        # If it's a full relative path that we know about
        for paths in self._file_map.values():
            if path_query in paths:
                return path_query

        # If it's just a filename
        filename = os.path.basename(path_query)
        paths = self._file_map.get(filename, [])
        
        if len(paths) == 1:
            return paths[0]
        
        # If multiple paths exist, check if path_query matches the end of any of them
        matches = [p for p in paths if p.endswith(path_query)]
        if len(matches) == 1:
            return matches[0]
            
        return None

    def get_all_files(self) -> Dict[str, List[str]]:
        return self._file_map
