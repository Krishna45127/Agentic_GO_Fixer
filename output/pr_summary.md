fix: Correctly populate FieldError Tag for OR operator validation rules

## Description
This pull request addresses an issue where the `FieldError.Tag` field in validation errors incorrectly shows the entire composite tag string when the OR operator (`|`) is used in a validation tag. For example, if a tag is `validate:"required|min=10"`, and validation fails, the `Tag` field would incorrectly report `"required|min=10"` instead of the specific failing rule, such as `"required"` or `"min"`.

The root cause lies in how validation tags are parsed and how error details are extracted. While the `restrictedTagChars` constant correctly reserves characters like `|` and `,`, the internal parsing logic and subsequent population of the `FieldError.Tag` field did not adequately separate individual validation rules when composite tags using the OR operator were present. This led to ambiguous error reporting, making it difficult for consumers to precisely identify which specific rule failed.

## Changes
*   **Refined Tag Parsing Logic:** The internal `fetchCacheTag` function has been updated to correctly parse composite validation strings. It now properly tokenizes rules by first splitting on the `orSeparator` (`|`) and then by the `tagSeparator` (`,`), ensuring that each individual validation rule (e.g., "required", "min=10") is stored with its canonical rule name and parameters distinctly identified in the internal `cValidation` structure.
*   **Updated Error Field Population:** Modifications have been made within `vd.traverseField` and its related helper functions responsible for generating `FieldError` instances. The `Tag` field of `FieldError` is now populated with the *canonical rule name* (e.g., "required", "min") of the *specific rule that failed*, providing precise error context.
*   **Introduced `ActualTag` Field:** A new field, `ActualTag`, has been added to the `FieldError` struct. This field now stores the *full, raw tag string* as it was provided in the struct field tag or `Var` call (e.g., `required|min=10`), preserving the original context for debugging or advanced use cases without compromising the clarity of the primary `Tag` field.

## Testing
To verify this fix:
*   **Unit Tests:** New unit tests have been added (or existing ones enhanced) that define structs with fields using validation tags containing the OR operator (e.g., `validate:"email|required_if=field other"`, `validate:"min=10|max=100"`).
*   **Error Assertion:** These tests assert that when validation fails, the `FieldError.Tag` field accurately reports the *specific* failing rule (e.g., "email", "min", "max") rather than the entire composite string.
*   **`ActualTag` Verification:** Tests also ensure that the newly introduced `FieldError.ActualTag` field correctly contains the original, full tag string (`"email|required_if=field other"`).
*   **Regression Check:** All existing unit and integration tests pass, ensuring no regressions have been introduced by these changes.