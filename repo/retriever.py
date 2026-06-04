import json
import os
import re
import sys
from pathlib import Path
 
 
# Default index lives next to this module — consistent with analyzer.py
DEFAULT_INDEX = Path(__file__).parent / "index.json"
 
 
def _normalize(name: str) -> str:
    """Strips non-alphanumeric characters and lowercases a string.
 
    Allows fuzzy matching across naming conventions, e.g.
    'excluded_if'  →  'excludedif'  matches  'hasExcludedIf'  →  'hasexcludedif'
    """
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()
 
 
class CodeRetriever:
    """Searches the repository index and reads source files on demand."""
 
    def __init__(self, index_path: str | Path = DEFAULT_INDEX):
        self.index = self._load_index(Path(index_path))
 
    # ── Index loading ─────────────────────────────────────────────────────────
 
    def _load_index(self, path: Path) -> list[dict]:
        if not path.exists():
            print(f"Error: index not found at '{path}'. Run analyzer.py first.")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
 
    # ── Ranking ───────────────────────────────────────────────────────────────
 
    def rank_candidates(
        self, query_terms: list[str], top_n: int = 5
    ) -> list[dict]:
        """
        Scores every indexed file against query_terms and returns the top_n.
 
        Three independent scoring dimensions (additive):
 
          filename_score — +2.0 per term whose normalized form appears in the
                           bare filename (e.g. 'excluded_if' hits
                           'baked_in.go' → 0, but hits 'excluded_if.go' → 2).
                           Strong signal: Go devs name files after what they own.
 
          symbol_score   — +1.0 per function/type symbol that contains the
                           normalized term as a substring.  Catches the common
                           gap between tag name (excluded_if) and its handler
                           (hasExcludedIf, requireExcludedIf, …).
 
          text_score     — +0.1 per line in the file that contains the raw
                           term, capped at 3.0 per term.  Provides broad
                           coverage without wildly inflating the score of a
                           file that merely imports or comments the keyword.
 
        Returns list[dict] sorted descending by total_score, each entry:
            { file_path, file_name, is_test_file,
              total_score, filename_score, symbol_score, text_score }
        """
        scored: list[dict] = []
 
        for entry in self.index:
            file_path = entry["file_path"]
            file_name = entry.get("file_name", os.path.basename(file_path))
            all_symbols = entry.get("functions", []) + entry.get("types", [])
 
            filename_score: float = 0.0
            symbol_score: float  = 0.0
            text_score: float    = 0.0
 
            for term in query_terms:
                norm = _normalize(term)
                if not norm:
                    continue
 
                # --- filename dimension ---
                if norm in _normalize(file_name):
                    filename_score += 2.0
 
                # --- symbol dimension ---
                for sym in all_symbols:
                    if norm in _normalize(sym):
                        symbol_score += 1.0
 
            # --- text dimension (one file read for all terms) ---
            if os.path.exists(file_path):
                try:
                    lines = Path(file_path).read_text(
                        encoding="utf-8", errors="ignore"
                    ).splitlines()
                    for term in query_terms:
                        hits = sum(1 for ln in lines if term in ln)
                        text_score += min(hits * 0.1, 3.0)   # cap per term
                except OSError:
                    pass
 
            total = filename_score + symbol_score + text_score
            if total > 0:
                scored.append({
                    "file_path":      file_path,
                    "file_name":      file_name,
                    "is_test_file":   entry.get("is_test_file", False),
                    "total_score":    round(total, 2),
                    "filename_score": round(filename_score, 2),
                    "symbol_score":   round(symbol_score, 2),
                    "text_score":     round(text_score, 2),
                })
 
        scored.sort(key=lambda x: x["total_score"], reverse=True)
        return scored[:top_n]
 
    # ── Legacy search helpers (kept for backwards compatibility) ──────────────
 
    def search_by_name(self, query: str) -> list[dict]:
        """
        Fuzzy symbol search over the index.
 
        Normalizes both the query and each stored symbol, then does a
        case-insensitive substring match.
 
        Returns a list of { file_path, matched_symbols } dicts.
        """
        normalized_query = _normalize(query)
        results = []
 
        for entry in self.index:
            all_symbols = entry.get("functions", []) + entry.get("types", [])
            matches = [s for s in all_symbols if normalized_query in _normalize(s)]
            if matches:
                results.append({
                    "file_path": entry["file_path"],
                    "matched_symbols": matches,
                })
 
        return results
 
    def search_text(self, query: str) -> list[dict]:
        """
        Literal grep over the contents of every indexed file.
 
        Returns one result per matching line:
          { file_path, line_number, line_text }
        """
        results = []
 
        for entry in self.index:
            file_path = entry["file_path"]
            if not os.path.exists(file_path):
                continue
            try:
                lines = Path(file_path).read_text(encoding="utf-8").splitlines()
                for i, line in enumerate(lines, start=1):
                    if query in line:
                        results.append({
                            "file_path": file_path,
                            "line_number": i,
                            "line_text": line.strip(),
                        })
            except OSError:
                continue
 
        return results
 
    # ── File reader ───────────────────────────────────────────────────────────
 
    def read_file(self, file_path: str, line_numbers: bool = True) -> str:
        """
        Returns the contents of a source file.
 
        When line_numbers=True, each line is prefixed with its 1-based line
        number, which helps the LLM reference specific locations in its plan.
        """
        if not os.path.exists(file_path):
            return f"Error: '{file_path}' does not exist."
 
        try:
            lines = Path(file_path).read_text(encoding="utf-8").splitlines(keepends=True)
            if line_numbers:
                return "".join(f"{i:4d} | {line}" for i, line in enumerate(lines, start=1))
            return "".join(lines)
        except OSError as e:
            return f"Error reading '{file_path}': {e}"
 
 
# ── Quick CLI for testing the retriever independently ─────────────────────────
 
if __name__ == "__main__":
    retriever = CodeRetriever()
    query = input("Search term: ").strip()
 
    name_results = retriever.search_by_name(query)
    print(f"\n── Symbol search: '{query}' ──")
    for r in name_results:
        print(f"  {r['file_path']}  →  {', '.join(r['matched_symbols'])}")
    if not name_results:
        print("  No symbol matches.")
 
    text_results = retriever.search_text(query)
    print(f"\n── Text search: '{query}' ──")
    for r in text_results[:5]:
        print(f"  {r['file_path']} L{r['line_number']}: {r['line_text']}")
    if len(text_results) > 5:
        print(f"  ... and {len(text_results) - 5} more.")
    if not text_results:
        print("  No text matches.")