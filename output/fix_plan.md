# Fix Plan

**Target file:** `D:\agentic_go_fixer\validator\validator_instance.go`

The issue "OR operator produces invalid tag names in validation errors" indicates that when a validation tag string contains the OR operator (e.g., `validate:"tag1|tag2"`), the resulting `FieldError`'s `Tag` field incorrectly shows the entire string (`"tag1|tag2"`) instead of the specific validation rule that failed (e.g., `"tag1"` or `"tag2"`). This points to a problem in how validation tags are parsed and how error details are extracted.

The `restrictedTagChars` constant (line 50) correctly includes `|` and `,`. This is appropriate for preventing these characters from being part of *registered* alias names or custom validation function names, as they are reserved for syntax. The comments on lines 246 and 757 accurately describe this intent. The problem is not with the restriction of tag *names*, but with the correct *parsing* of composite validation strings and the subsequent population of error fields.

The `Validate` methods in `validator_instance.go` (e.g., `VarCtx`, `VarWithValueCtx`, `VarWithKeyCtx`) call `v.fetchCacheTag(tag)` to parse the input validation string and then `vd.traverseField(...)` to perform validation and generate errors. The fix involves ensuring that `fetchCacheTag` correctly tokenizes the rules and that `vd.traverseField` correctly populates the `Tag` field of `FieldError` with the specific rule name.

Here's a step-by-step plan to fix the issue:

1.  **Refine Tag Parsing Logic (within `fetchCacheTag` function):**
    *   **Action:** Ensure the internal `fetchCacheTag` function (conceptually invoked on lines 620, 673, and 724) is updated to correctly parse the input `tag` string. This involves:
        *   Splitting the `tag` string first by the `orSeparator` (`|`) to handle OR conditions.
        *   Then, splitting each segment by the `tagSeparator` (`,`) for AND conditions.
        *   Each resulting individual validation rule (e.g., "required", "min=10", "email") must be stored in an internal structure (e.g., `cValidation`) with its canonical *rule name* (e.g., "required", "min", "email") clearly identified. The parameters (e.g., "10" for "min=10") should be stored separately.
    *   **Reason:** This ensures that the internal representation of validation rules correctly separates individual rules, even when combined with OR operators. The `cTag` object returned by `fetchCacheTag` must contain distinct rule definitions.

2.  **Update Error Field Population (within `vd.traverseField` and its callees):**
    *   **Action:** Modify the logic within the `vd.traverseField` function (conceptually invoked on lines 626, 678, and 735) and any helper functions responsible for creating `FieldError` instances. When a validation rule fails and a `FieldError` is generated, its `Tag` field must be populated with the *canonical rule name* (e.g., "required", "min") of the *specific rule that failed*.
    *   **Reason:** The `Tag` field in `FieldError` should represent the actual validation rule (e.g., `min`, `required`), not the entire composite tag string (`min=10|max=20`). This provides accurate and unambiguous error information to the consumer.

3.  **Introduce `ActualTag` for Original Context (if not present):**
    *   **Action:** If the `FieldError` struct does not already contain it, add a field (e.g., `ActualTag` or `OriginalTag`) to store the *full, raw tag string* as it was provided in the struct field tag or `Var` call (e.g., `required|min=10`).
    *   **Reason:** While `Tag` should hold the canonical rule name, it can be useful for debugging or advanced scenarios to have access to the original, unparsed tag string. This provides full context without compromising the clarity of the primary `Tag` field. This change would be in the `validator/errors.go` file (not provided) if the field needs to be added.
