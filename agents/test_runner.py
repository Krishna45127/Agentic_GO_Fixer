import subprocess
from dataclasses import dataclass, field
from pathlib import Path
 
 
# data classes 
 
@dataclass
class CheckResult:
    """Result of a single shell command."""
    command: str
    passed: bool
    stdout: str
    stderr: str
    return_code: int
 
    def short_summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        label = f"{status}  `{self.command}`"
        if not self.passed and (self.stdout or self.stderr):
            # Truncate at 600 chars to keep PR summaries readable
            detail = (self.stdout + self.stderr).strip()[:600]
            return f"{label}\n```\n{detail}\n```"
        return label
 
 
@dataclass
class ValidationResult:
    """Aggregated result of all checks."""
    all_passed: bool
    checks: list[CheckResult] = field(default_factory=list)
 
    def summary(self) -> str:
        return "\n".join(c.short_summary() for c in self.checks)
 
 
# runner 
 
class TestRunner:
    """
    Runs go vet and go test inside a cloned Go repository.
 
    The repo must already have the patched file written to disk before
    run() is called — main.py applies the patch before invoking this.
    """
 
    _COMMANDS = [
        "go vet ./...",
        "go test ./...",
    ]
    _TIMEOUT = 180  # seconds — generous for large repos like validator
 
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.is_dir():
            raise ValueError(
                f"Repo path not found: {self.repo_path}\n"
                "Make sure you have cloned the Go repository locally."
            )
 
    def run(self) -> ValidationResult:
        """
        Executes all checks sequentially.
        Returns a ValidationResult regardless of pass/fail — never raises.
        """
        print(f"\n[TestRunner] Running checks in: {self.repo_path}")
        checks: list[CheckResult] = []
 
        for cmd in self._COMMANDS:
            result = self._run_one(cmd)
            checks.append(result)
            # Stop early on vet failure — a compile error makes test output meaningless
            if not result.passed and cmd.startswith("go vet"):
                print("[TestRunner] go vet failed — skipping go test")
                break
"""
TestRunner — runs `go vet` and `go test` inside the cloned Go repository.
 
The repo must already have the patched file on disk before run() is called;
main.py applies the patch before invoking this runner.
"""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
 
 
# data classes 
 
@dataclass
class CheckResult:
    """Result of a single shell command."""
    command: str
    passed: bool
    stdout: str
    stderr: str
    return_code: int
 
    def short_summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        label = f"{status}  `{self.command}`"
        if not self.passed and (self.stdout or self.stderr):
            # Truncate at 600 chars to keep PR summaries readable
            detail = (self.stdout + self.stderr).strip()[:600]
            return f"{label}\n```\n{detail}\n```"
        return label
 
 
@dataclass
class ValidationResult:
    """Aggregated result of all checks."""
    all_passed: bool
    checks: list[CheckResult] = field(default_factory=list)
 
    def summary(self) -> str:
        return "\n".join(c.short_summary() for c in self.checks)
 
 
# runner  
 
class TestRunner:
    """
    Runs go vet and go test inside a cloned Go repository.
 
    The repo must already have the patched file written to disk before
    run() is called — main.py applies the patch before invoking this.
    """
 
    _COMMANDS = [
        "go vet ./...",
        "go test ./...",
    ]
    _TIMEOUT = 180  # seconds — generous for large repos like validator
 
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.is_dir():
            raise ValueError(
                f"Repo path not found: {self.repo_path}\n"
                "Make sure you have cloned the Go repository locally."
            )
 
    def run(self) -> ValidationResult:
        """
        Executes all checks sequentially.
        Returns a ValidationResult regardless of pass/fail — never raises.
        """
        print(f"\n[TestRunner] Running checks in: {self.repo_path}")
        checks: list[CheckResult] = []
 
        for cmd in self._COMMANDS:
            result = self._run_one(cmd)
            checks.append(result)
            # Stop early on vet failure — a compile error makes test output meaningless
            if not result.passed and cmd.startswith("go vet"):
                print("[TestRunner] go vet failed — skipping go test")
                break
 
        all_passed = all(c.passed for c in checks)
        return ValidationResult(all_passed=all_passed, checks=checks)
 
    # private helpers 
 
    def _run_one(self, command: str) -> CheckResult:
        print(f"[TestRunner] $ {command}")
 
        try:
            proc = subprocess.run(
                command.split(),
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=self._TIMEOUT,
            )
        except FileNotFoundError:
            return CheckResult(
                command=command,
                passed=False,
                stdout="",
                stderr="Error: 'go' command not found. Is Go installed and on PATH?",
                return_code=-1,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                command=command,
                passed=False,
                stdout="",
                stderr=f"Error: command timed out after {self._TIMEOUT}s.",
                return_code=-1,
            )
 
        passed = proc.returncode == 0
        status = "PASSED" if passed else "FAILED"
        print(f"[TestRunner] {status}: {command}")
        if not passed and proc.stderr:
            print(f"[TestRunner] stderr snippet: {proc.stderr[:300]}")
 
        return CheckResult(
            command=command,
            passed=passed,
            stdout=proc.stdout,
            stderr=proc.stderr,
            return_code=proc.returncode,
        )