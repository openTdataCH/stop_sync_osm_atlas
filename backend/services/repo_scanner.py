import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Extensions to consider for auto-linking (synchronized with docs.py)
CODE_EXTENSIONS = {
    '.py', '.sql', '.sh', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg',
    '.js', '.ts', '.tsx', '.jsx', '.css', '.html',
}

# Directories to ignore during scanning. Code below documentation/ (the PDF
# generator and the diagram kit) is indexed; generated output is not.
IGNORE_DIRS = {
    '.git', 'node_modules', 'venv', '.venv', '__pycache__',
    'htmlcov', '.pytest_cache', 'generated', 'data', 'coverage', '.gemini',
    'vendor', 'dist', 'build'
}

class RepoScanner:
    """A map of file name -> paths in the portal's layout: the application's files, and the engine's below ``engine/``.

    The engine is read from ``engine_dir`` wherever that checkout is (inside the application or beside it), so an
    engine path such as ``src/osm_public_transport_matcher/routes.py`` resolves in every layout that has its source.
    """
    def __init__(self, root_dir: str, engine_dir: Optional[str] = None):
        self.root_dir = os.path.abspath(root_dir)
        self.engine_dir = os.path.abspath(engine_dir) if engine_dir else None
        self._file_map: Dict[str, List[str]] = {}
        self.scan()

    def scan(self):
        """Perform the repository scan."""
        logger.info(f"Scanning repository for code files in {self.root_dir}")
        file_map: Dict[str, List[str]] = {}
        # With an engine checkout given, an ``engine/`` folder inside the application is read only as that checkout.
        self._walk(self.root_dir, '', file_map, skip_top={'engine'} if self.engine_dir else set())
        if self.engine_dir and os.path.isdir(self.engine_dir):
            self._walk(self.engine_dir, 'engine', file_map, skip_top=set())
        self._file_map = file_map
        logger.info(f"Scan complete. Found {len(file_map)} unique filenames.")

    @staticmethod
    def _walk(top: str, prefix: str, file_map: Dict[str, List[str]], skip_top: set):
        for root, dirs, files in os.walk(top):
            # In-place modification to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')
                       and not (root == top and d in skip_top)]
            rel_root = os.path.relpath(root, top)
            rel_root = prefix if rel_root == '.' else os.path.join(prefix, rel_root)
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() in CODE_EXTENSIONS:
                    file_map.setdefault(file, []).append(os.path.join(rel_root, file))

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
