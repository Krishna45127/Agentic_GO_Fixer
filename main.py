"""
Agentic AI Go Fixer — main entry point.
 
Pipeline:
  1 — Plan:     Keywords extracted locally; top-5 files scored across three
                dimensions; Gemini selects the most relevant; fix plan generated.
  2 — Code:     LLM rewrites the target file; unified diff saved to output/.
  3 — Validate: go vet + go test run against the patched repo.
                On failure the original file is restored automatically.
  4 — PR:       LLM writes a conventional-commit PR title and body.
 
All artefacts are saved to --output (default: output/).
"""
import argparse
import json
import sys
from pathlib import Path
 
from dotenv import load_dotenv
 
from repo.retriever import CodeRetriever
from agents.planner import PlannerAgent
from agents.coder import CoderAgent
from agents.test_runner import TestRunner
from agents.pr_generator import PRGenerator
 
DEFAULT_REPO = "validator"
DEFAULT_OUTPUT = Path("output")
 
 
def main() -> None:
    load_dotenv()
    args = _parse_args()
 
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
 
    _banner("Agentic AI Go Fixer")
    print(f"  Issue  : {args.issue}")
    print(f"  Repo   : {args.repo}")
    print(f"  Output : {out_dir}/")
 
    # Initialise agents up-front so misconfiguration fails fast
    retriever = CodeRetriever()
    try:
        planner = PlannerAgent(retriever=retriever)
        coder   = CoderAgent()
        pr_gen  = PRGenerator()
    except ValueError as exc:
        print(f"\n[Error] {exc}")
        sys.exit(1)
 
    # Save the issue text as an artefact
    (out_dir / "issue.md").write_text(
        f"# Issue\n\n{args.issue}\n", encoding="utf-8"
    )
 
    # ── 1 : Plan ──────────────────────────────────────────────────────────────
    _banner("1 — Plan")
    plan_result = planner.plan_fix(args.issue)
 
    if isinstance(plan_result, str):
        print(f"\n[Error] {plan_result}")
        sys.exit(1)
 
    print(f"\n{plan_result['plan']}")
 
    # Save retrieval metadata — now includes the full candidate shortlist,
    # scores, selected file, and the LLM's selection reasoning.
    _save_json(out_dir / "retrieved_files.json", {
        "issue":               args.issue,
        "keywords":            plan_result.get("keywords", []),
        "candidates":          plan_result.get("candidates", []),
        "selected_file":       plan_result["target_file"],
        "selection_reasoning": plan_result.get("selection_reasoning", ""),
    })
 
    (out_dir / "fix_plan.md").write_text(
        f"# Fix Plan\n\n**Target file:** `{plan_result['target_file']}`\n\n"
        f"{plan_result['plan']}\n",
        encoding="utf-8",
    )
 
    # ── 2 : Code ──────────────────────────────────────────────────────────────
    _banner("2 — Code")
    patched_content, patch_path = coder.apply_fix(
        issue_text=args.issue,
        plan=plan_result["plan"],
        target_file=plan_result["target_file"],
        original_content=plan_result["original_content"],
    )
 
    # Keep the original content in memory before overwriting — needed for rollback
    original_content = plan_result["original_content"]
    target = Path(plan_result["target_file"])
 
    target.write_text(patched_content, encoding="utf-8")
    print(f"[Main]  Patch applied to repo: {target}")
 
    _copy_if_exists(Path(patch_path), out_dir / "generated_patch.diff")
 
    # ── 3 : Validate ──────────────────────────────────────────────────────────
    _banner("3 — Validate")
    runner     = TestRunner(repo_path=args.repo)
    validation = runner.run()
 
    result_label = "ALL PASSED ✓" if validation.all_passed else "CHECKS FAILED ✗"
    print(f"\nResult : {result_label}")
    print(validation.summary())
 
    (out_dir / "test_results.txt").write_text(
        f"Result: {result_label}\n\n{validation.summary()}\n", encoding="utf-8"
    )
 
    # ── Rollback on failure ────────────────────────────────────────────────────
    # If go vet or go test fails, restore the repo to a clean state so the
    # developer doesn't inherit a broken workspace.  The patch is still saved
    # in output/generated_patch.diff for manual review.
    if not validation.all_passed:
        target.write_text(original_content, encoding="utf-8")
        print(f"\n[Main]  ⚠  Checks failed — original file restored: {target}")
        print("[Main]  The patch is preserved in output/generated_patch.diff")
 
    # ── 4 : PR Summary ────────────────────────────────────────────────────────
    _banner("4 — PR Summary")
    pr_path = pr_gen.generate(
        issue_text=args.issue,
        plan=plan_result["plan"],
        validation=validation,
    )
    _copy_if_exists(Path(pr_path), out_dir / "pr_summary.md")
 
    # ── Done ──────────────────────────────────────────────────────────────────
    _banner("Done")
    print(f"  Artefacts saved to {out_dir}/")
    for f in sorted(out_dir.iterdir()):
        if f.is_file():
            print(f"    {f.name}")
 
    if not validation.all_passed:
        print(
            "\n  ⚠  Some checks failed — original file has been restored.\n"
            "  Review output/generated_patch.diff before re-applying the fix."
        )
 
 
# ── helpers ───────────────────────────────────────────────────────────────────
 
def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
 
 
def _copy_if_exists(src: Path, dst: Path) -> None:
    """Copies src → dst only when src exists and differs from dst."""
    if src.exists() and src != dst:
        dst.write_bytes(src.read_bytes())
 
 
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Agentic AI Contributor for Go Projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python main.py --issue "excluded_if panics on nil pointer"\n'
            '  python main.py --repo ./myrepo --issue "nil pointer in validator"\n'
            '  python main.py --issue "..." --output sample_output\n'
        ),
    )
    p.add_argument("--issue",  required=True, help="GitHub issue text to fix")
    p.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Path to the cloned Go repo (default: {DEFAULT_REPO})",
    )
    p.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Directory for output artefacts (default: {DEFAULT_OUTPUT})",
    )
    return p.parse_args()
 
 
def _banner(title: str) -> None:
    width = 52
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")
 
 
if __name__ == "__main__":
    main()