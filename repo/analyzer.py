import os
import re
import json
import sys
from pathlib import Path


# --- Compiled regex patterns for Go symbol extraction ---
# Matches:  func FuncName(  or  func (r Receiver) FuncName(
_FUNC_RE = re.compile(r"func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(")
# Matches:  type Name struct  or  type Name interface
_TYPE_RE = re.compile(r"type\s+([A-Za-z0-9_]+)\s+(?:struct|interface)")

# Index is always written next to this file, regardless of working directory
INDEX_PATH = Path(__file__).parent / "index.json"


def _extract_symbols(source: str) -> tuple[list[str], list[str]]:
    """
    Parses a Go source string and returns (functions, types).
    Both lists are deduplicated.
    """
    functions = list(set(_FUNC_RE.findall(source)))
    types = list(set(_TYPE_RE.findall(source)))
    return functions, types


def build_index(repo_path: str) -> list[dict]:
    """
    Walks every .go file in repo_path and returns a list of file metadata dicts.
    Hidden directories (e.g. .git) are skipped automatically.

    FIX: file_path is now stored as an absolute path via os.path.abspath().
    The original os.path.join(root, filename) produced a CWD-relative path
    (e.g. "../validator/baked_in.go").  That path resolved correctly when
    analyzer.py ran, but became invalid when main.py executed from a different
    working directory — causing os.path.exists() to return False and
    read_file() to return an error string instead of source code.
    """
    index = []

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for filename in files:
            if not filename.endswith(".go"):
                continue

            # ── FIX (line 42 original) ────────────────────────────────────────
            # BEFORE: file_path = os.path.join(root, filename)
            #   → stores "../validator/baked_in.go" (relative to CWD at index time)
            # AFTER:  os.path.abspath() resolves to the full on-disk path once,
            #   → stores "/home/user/AGENTIC_GO_FIXER/validator/baked_in.go"
            #   → os.path.exists() and Path.read_text() work from ANY CWD
            file_path = os.path.abspath(os.path.join(root, filename))
            try:
                source = Path(file_path).read_text(encoding="utf-8")
                functions, types = _extract_symbols(source)
                index.append({
                    "file_path":    file_path,
                    "file_name":    filename,            # bare filename for scoring
                    "is_test_file": filename.endswith("_test.go"),
                    "functions":    functions,
                    "types":        types,
                })
            except OSError as e:
                print(f"Warning: skipping {file_path}: {e}")

    return index


def save_index(index: list[dict], output_path: Path = INDEX_PATH) -> None:
    """Writes the symbol index to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def main() -> None:
    default_path = "../validator"
    target_repo = sys.argv[1] if len(sys.argv) > 1 else default_path

    if not os.path.isdir(target_repo):
        print(f"Error: '{target_repo}' is not a directory.")
        print("Usage: python repo/analyzer.py <path_to_go_repo>")
        sys.exit(1)

    print(f"Indexing: {os.path.abspath(target_repo)}")
    index = build_index(target_repo)
    save_index(index)
    print(f"Indexed {len(index)} Go files  →  {INDEX_PATH}")


if __name__ == "__main__":
    main()