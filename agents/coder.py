import difflib
from pathlib import Path
 
from agents.gemini_client import call_with_retry, extract_text, get_gemini_client
 
_MODEL = "gemini-2.5-flash"
_OUTPUT_DIR = Path("output")
 
 
class CoderAgent:
    def __init__(self):
        self.client = get_gemini_client()
        _OUTPUT_DIR.mkdir(exist_ok=True)
 
    # public 
    def apply_fix(
        self,
        issue_text: str,
        plan: str,
        target_file: str,
        original_content: str,
    ) -> tuple[str, str]:
        """
        Rewrites target_file according to the plan.
 
        Returns (patched_content, patch_file_path).
        The caller is responsible for writing patched_content back to
        target_file before running tests (main.py handles this).
        """
        print(f"\n[Coder] Generating fix for: {target_file}")
 
        patched = self._rewrite_file(issue_text, plan, original_content)
 
        # Write full rewritten file — useful for side-by-side inspection
        stem = Path(target_file).stem
        out_file = _OUTPUT_DIR / f"{stem}.patched.go"
        out_file.write_text(patched, encoding="utf-8")
        print(f"[Coder] Rewritten file  → {out_file}")
 
        # Unified diff — can be applied with `git apply output/generated_patch.diff`
        patch_path = self._write_diff(original_content, patched, target_file)
 
        return patched, str(patch_path)
 
    #  private helpers
 
    def _rewrite_file(self, issue: str, plan: str, original: str) -> str:
        response = call_with_retry(
            self.client, _MODEL,
            f'You are an expert Go developer fixing this issue: "{issue}"\n\n'
            f"Fix plan:\n{plan}\n\n"
            f"Original file:\n```go\n{original}\n```\n\n"
            "Rewrite the ENTIRE file with the fix applied.\n"
            "Do NOT omit or summarise any unchanged code.\n"
            "Return ONLY valid Go code inside a single ```go ... ``` block."
        )
        return _strip_fences(extract_text(response))
 
    def _write_diff(self, original: str, patched: str, file_path: str) -> Path:
        """Writes a unified diff to output/generated_patch.diff."""
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )
        )
        patch_path = _OUTPUT_DIR / "generated_patch.diff"
        patch_path.write_text("".join(diff_lines), encoding="utf-8")
        print(f"[Coder] Patch file      → {patch_path}")
        return patch_path
 
 
#  module-level helper 
def _strip_fences(text: str) -> str:
    """Removes markdown code fences from an LLM response."""
    if "```go" in text:
        return text.split("```go", 1)[1].rsplit("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].rsplit("```", 1)[0].strip()
    return text.strip()