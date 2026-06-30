"""
PlannerAgent — inspects the repository and produces a step-by-step fix plan.

Improved flow:
  1. Extract multiple search keywords locally (no LLM call needed).
  2. Score all indexed files with CodeRetriever.rank_candidates() across three
     dimensions: filename, symbol, and text match.
  3. Send the top-5 candidates to Gemini — let it pick the most relevant file
     and explain why.
  4. Read the selected file from disk, validate the content, then generate a
     numbered, line-referenced fix plan.

Why this is better than single-keyword → first-file:
  - Multiple keywords capture more of the issue's intent.
  - Three-dimensional scoring distributes signal: a filename match is
    different evidence from a symbol match or raw text hit.
  - Gemini sees a curated shortlist rather than one guess, so its file
    selection is informed by alternatives and can account for Go idioms the
    scorer doesn't know about.
"""
import json
import re

from agents.gemini_client import call_with_retry, extract_text, get_gemini_client
from repo.retriever import CodeRetriever

_MODEL = "gemini-2.5-flash"

# Common English words that add noise when used as search terms against Go
# source files.  These are filtered from the plain-word extraction step.
_STOPWORDS = {
    "issue", "error", "panic", "crash", "field", "value", "when", "with",
    "that", "this", "have", "should", "would", "could", "there", "their",
    "which", "about", "after", "before", "using", "struct", "given",
    "return", "cause", "causes", "function", "method", "called", "always",
    "never", "fails", "failure", "problem", "works", "broken", "below",
    "above", "check", "valid", "invalid", "empty", "false", "where",
}


class PlannerAgent:
    def __init__(self, retriever: CodeRetriever):
        self.retriever = retriever
        self.client = get_gemini_client()

    # public 

    def plan_fix(self, issue_text: str) -> dict | str:
        """
        Returns a dict on success:
            {
                "plan":                str   step-by-step fix with line refs,
                "target_file":         str   path of the file to modify,
                "original_content":    str   raw file content (no line numbers),
                "keywords":            list  terms extracted from the issue,
                "candidates":          list  top-5 scored candidate files,
                "selection_reasoning": str   why this file was chosen,
            }
        Returns an error string when the pipeline cannot locate or read a file.
        """
        # Step 1 — extract keywords without an LLM call
        keywords = self._extract_keywords(issue_text)
        if not keywords:
            return "Could not extract search keywords from the issue text."

        print(f"[Planner] Keywords : {keywords}")

        # Step 2 — rank all indexed files; take the top 5
        candidates = self.retriever.rank_candidates(keywords, top_n=5)
        if not candidates:
            return "No relevant files found for the extracted keywords."

        print(f"[Planner] Top {len(candidates)} candidate(s):")
        for i, c in enumerate(candidates, 1):
            print(
                f"  {i}. {c['file_path']}"
                f"  (total={c['total_score']},"
                f" file={c['filename_score']},"
                f" sym={c['symbol_score']},"
                f" text={c['text_score']})"
            )

        # Step 3 — ask Gemini to pick the most relevant file from the shortlist
        selection = self._select_file(issue_text, candidates)
        target_file = candidates[selection["index"]]["file_path"]

        print(f"[Planner] Selected : {target_file}")
        print(f"[Planner] Reason   : {selection['reasoning']}")

        # Step 4 — read the file and VALIDATE before touching any LLM
        print(f"[Planner] Reading  : {target_file}")
        annotated = self.retriever.read_file(target_file, line_numbers=True)


        if annotated.startswith("Error:"):
            return (
                f"[Planner] Cannot read selected file — aborting before LLM call.\n"
                f"{annotated}\n\n"
                "The index most likely contains stale CWD-relative paths.\n"
                "Fix: re-run  python repo/analyzer.py <repo_path>  to rebuild\n"
                "the index with absolute paths, then re-run main.py."
            )
    

        raw = self.retriever.read_file(target_file, line_numbers=False)

        # Step 5 — generate a concrete, line-referenced fix plan
        print("[Planner] Generating fix plan…")
        plan = self._generate_plan(issue_text, target_file, annotated)

        return {
            "plan":                plan,
            "target_file":         target_file,
            "original_content":    raw,
            "keywords":            keywords,
            "candidates":          candidates,
            "selection_reasoning": selection["reasoning"],
        }

    # private helpers 

    def _extract_keywords(self, issue_text: str) -> list[str]:
        """
        Extracts candidate search keywords from the issue without an LLM call.

        Extraction priority (highest signal first):
          1. Backtick-enclosed content — e.g. `excluded_if`, `validate.V8n`.
             All identifier-like sub-tokens are pulled from the full match so
             longer tags (``validate:"excluded_if=Field"``) still yield the
             useful parts.
          2. snake_case identifiers — at least one underscore: excluded_if,
             has_field, zero_value.
          3. CamelCase / PascalCase — two or more capitalised segments:
             HasField, ExcludedIf, NilPointer.
          4. Plain lower-case words of 5+ characters, minus stopwords.

        Returns up to 8 unique terms (order-preserving dedup).
        """
        collected: list[str] = []

        # 1. Backtick content — extract identifier-like sub-tokens
        for full_match in re.findall(r'`([^`]+)`', issue_text):
            collected += re.findall(r'[A-Za-z][A-Za-z0-9_]*', full_match)

        # 2. snake_case (must contain at least one underscore)
        collected += re.findall(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b', issue_text)

        # 3. CamelCase / PascalCase (at least two capitalised segments)
        collected += re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', issue_text)

        # 4. Plain lower-case words ≥ 5 chars, excluding noise words
        plain = re.findall(r'\b[a-z]{5,}\b', issue_text.lower())
        collected += [w for w in plain if w not in _STOPWORDS]

        # Deduplicate while preserving order; cap at 8 terms
        seen: set[str] = set()
        result: list[str] = []
        for kw in collected:
            kw = kw.strip()
            if kw and kw not in seen:
                seen.add(kw)
                result.append(kw)

        return result[:8]

    def _select_file(
        self, issue_text: str, candidates: list[dict]
    ) -> dict:
        """
        Sends the top candidate files to Gemini and asks it to select the
        most likely location of the bug.

        The prompt includes the automated score breakdown so Gemini can
        reason about why each file surfaced, and is instructed to prefer
        implementation files over test files.

        Returns { "index": int (0-based), "reasoning": str }.
        Falls back to index 0 (highest-scored file) if the response cannot
        be parsed.
        """
        # Build a compact numbered list — one line per candidate
        lines = []
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"{i}. {c['file_path']}"
                f"  [score={c['total_score']},"
                f" filename={c['filename_score']},"
                f" symbols={c['symbol_score']},"
                f" text={c['text_score']},"
                f" test_file={c['is_test_file']}]"
            )
        candidate_list = "\n".join(lines)

        response = call_with_retry(
            self.client, _MODEL,
            "You are an expert Go developer doing code review.\n\n"
            "GitHub issue:\n"
            f"{issue_text}\n\n"
            "These files were ranked by an automated scorer (filename / symbol / text match):\n"
            f"{candidate_list}\n\n"
            "Select the single file most likely to contain the bug.\n"
            "Prefer implementation files over test files unless the bug is clearly in a test.\n"
            "A high symbol_score means the file defines relevant functions; "
            "a high filename_score means the filename itself matches the issue keywords.\n\n"
            "Respond ONLY with valid JSON — no markdown, no extra text:\n"
            '{"selected": 1, "reasoning": "one-sentence explanation"}\n'
            "where 'selected' is the 1-based index from the list above."
        )

        text = _strip_json_fences(extract_text(response))
        try:
            data = json.loads(text)
            idx = int(data.get("selected", 1)) - 1
            idx = max(0, min(idx, len(candidates) - 1))  # clamp to valid range
            return {"index": idx, "reasoning": data.get("reasoning", "")}
        except (json.JSONDecodeError, ValueError, TypeError):
            # Fallback: the top-scored candidate is the safest default
            return {
                "index": 0,
                "reasoning": "fallback to top-scored candidate (LLM response unparseable)",
            }

    def _generate_plan(
        self, issue_text: str, file_path: str, annotated_content: str
    ) -> str:
        """
        Produces a numbered plan referencing specific line numbers.
        The plan is intentionally concrete — CoderAgent uses it verbatim.

        By the time this method is called, annotated_content is guaranteed to
        be actual Go source (the guard in plan_fix() has already rejected error
        strings), so Gemini receives real code, not an error message.
        """
        response = call_with_retry(
            self.client, _MODEL,
            "You are an expert Go developer.\n"
            "Produce a numbered, step-by-step plan to fix the issue below.\n"
            "Reference exact line numbers from the file. Be concrete — "
            "the next step will use this plan to rewrite the file.\n\n"
            f"Issue:\n{issue_text}\n\n"
            f"File: {file_path}\n```go\n{annotated_content}\n```"
        )
        return extract_text(response)


# ── module-level helper ───────────────────────────────────────────────────────

def _strip_json_fences(text: str) -> str:
    """
    Removes markdown code fences that Gemini sometimes wraps around JSON.

    Handles:
      ```json { ... } ```
      ``` { ... } ```
      plain { ... }
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text