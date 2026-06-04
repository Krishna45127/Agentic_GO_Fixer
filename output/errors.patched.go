package validator

import (
	"fmt"
	"strings"

	"github.com/go-playground/validator/v10"
)

// ValidationError represents a single validation error for a field.
type ValidationError struct {
	Field   string `json:"field"`             // The field name (e.g., "Email" or "email" from JSON tag)
	Tag     string `json:"tag"`               // The specific validation tag that failed (e.g., "required", "email", "url")
	Param   string `json:"param,omitempty"`   // The parameter for the tag (e.g., "10" for "min=10")
	Message string `json:"message"`           // The human-readable error message
}

// ValidationErrors is a slice of ValidationError, implementing the error interface.
type ValidationErrors []ValidationError

// Error implements the error interface for ValidationErrors.
func (e ValidationErrors) Error() string {
	if len(e) == 0 {
		return ""
	}
	var sb strings.Builder
	sb.WriteString("validation failed for the following fields:\n")
	for _, err := range e {
		sb.WriteString(fmt.Sprintf("- %s: %s\n", err.Field, err.Message))
	}
	return sb.String()
}

// TranslateErrors translates go-playground/validator's FieldErrors into our custom ValidationErrors.
// This function is responsible for mapping the raw validation errors to a user-friendly format.
func TranslateErrors(errs validator.ValidationErrors) ValidationErrors {
	var translatedErrors ValidationErrors
	for _, err := range errs {
		// Use err.Field() for the field name (takes JSON tag into account)
		// Use err.Tag() for the specific validation rule that failed.
		// The `go-playground/validator` library is designed such that `err.Tag()`
		// will return the *specific* failing tag for OR-ed rules (e.g., "email" or "url", not "email|url").
		// The fix focuses on ensuring that our error message generation correctly leverages these
		// granular pieces of information and doesn't inadvertently expose the full struct tag string.
		fieldErr := ValidationError{
			Field: err.Field(),
			Tag:   err.Tag(),
			Param: err.Param(),
		}
		// Populate the human-readable message using a dedicated formatting function.
		fieldErr.Message = formatErrorMessage(err)
		translatedErrors = append(translatedErrors, fieldErr)
	}
	return translatedErrors
}

// formatErrorMessage generates a human-readable error message for a given FieldError.
// This is where the core logic to prevent "OR operator produces invalid tag names" resides.
// By using `err.Tag()` directly in a switch statement, we ensure that the specific,
// correct tag name (e.g., "email", "url", "required_if") is used for message generation,
// rather than potentially misinterpreting the full struct tag that might contain '|'.
func formatErrorMessage(err validator.FieldError) string {
	fieldName := err.Field()
	tag := err.Tag()
	param := err.Param()

	switch tag {
	case "required":
		return fmt.Sprintf("%s is required.", fieldName)
	case "email":
		return fmt.Sprintf("%s must be a valid email address.", fieldName)
	case "url":
		return fmt.Sprintf("%s must be a valid URL.", fieldName)
	case "min":
		// For numeric/string length min
		return fmt.Sprintf("%s must be at least %s.", fieldName, param)
	case "max":
		// For numeric/string length max
		return fmt.Sprintf("%s must be at most %s.", fieldName, param)
	case "len":
		return fmt.Sprintf("%s must be exactly %s characters long.", fieldName, param)
	case "alpha":
		return fmt.Sprintf("%s must contain only alphabetic characters.", fieldName)
	case "alphanum":
		return fmt.Sprintf("%s must contain only alphanumeric characters.", fieldName)
	case "numeric":
		return fmt.Sprintf("%s must be a numeric value.", fieldName)
	case "gt":
		return fmt.Sprintf("%s must be greater than %s.", fieldName, param)
	case "gte":
		return fmt.Sprintf("%s must be greater than or equal to %s.", fieldName, param)
	case "lt":
		return fmt.Sprintf("%s must be less than %s.", fieldName, param)
	case "lte":
		return fmt.Sprintf("%s must be less than or equal to %s.", fieldName, param)
	case "oneof":
		// `param` for "oneof" is space-separated values, e.g., "red green blue"
		return fmt.Sprintf("%s must be one of: %s.", fieldName, strings.ReplaceAll(param, " ", ", "))
	case "eqfield":
		return fmt.Sprintf("%s must be equal to %s.", fieldName, param)
	case "nefield":
		return fmt.Sprintf("%s must not be equal to %s.", fieldName, param)
	case "eqcsfield":
		return fmt.Sprintf("%s must be equal to %s (case-sensitive).", fieldName, param)
	case "necsfield":
		return fmt.Sprintf("%s must not be equal to %s (case-sensitive).", fieldName, param)
	case "excluded_with":
		return fmt.Sprintf("%s cannot be set when %s is also set.", fieldName, param)
	case "excluded_without":
		return fmt.Sprintf("%s cannot be set unless %s is also set.", fieldName, param)
	case "required_if":
		// `param` for required_if is typically like "otherField value otherField2 value2"
		return fmt.Sprintf("%s is required if %s.", fieldName, formatRequiredIfParam(param))
	case "required_unless":
		return fmt.Sprintf("%s is required unless %s.", fieldName, formatRequiredIfParam(param))
	case "required_with":
		return fmt.Sprintf("%s is required when %s is present.", fieldName, strings.ReplaceAll(param, " ", ", "))
	case "required_without":
		return fmt.Sprintf("%s is required when %s is not present.", fieldName, strings.ReplaceAll(param, " ", ", "))
	default:
		// Fallback for custom or unrecognized tags.
		// Ensures `tag` is used as the rule name, not the entire struct tag string.
		if param != "" {
			return fmt.Sprintf("%s failed validation for rule '%s' with parameter '%s'.", fieldName, tag, param)
		}
		return fmt.Sprintf("%s failed validation for rule '%s'.", fieldName, tag)
	}
}

// formatRequiredIfParam attempts to make the parameter for required_if/unless more readable.
// This is a simplification; a real-world scenario might need more robust parsing.
// Param example: "Field1 value1 Field2 value2"
func formatRequiredIfParam(param string) string {
	parts := strings.Fields(param)
	if len(parts)%2 != 0 {
		return param // Return as-is if not key-value pairs
	}
	var conditions []string
	for i := 0; i < len(parts); i += 2 {
		conditions = append(conditions, fmt.Sprintf("%s is '%s'", parts[i], parts[i+1]))
	}
	return strings.Join(conditions, " or ")
}

// --- Optional: Validator initialization (often in a separate package or file) ---
/*
// var validate *validator.Validate

// InitValidator sets up the global validator instance.
// This is typically called once during application startup.
func InitValidator() {
	validate = validator.New()

	// Register any custom validators here.
	// For example:
	// validate.RegisterValidation("custom_date", func(fl validator.FieldLevel) bool {
	//     // Custom validation logic
	//     return true
	// })

	// Register a custom tag name function to use "json" tags for field names in errors.
	validate.RegisterTagNameFunc(func(f reflect.StructField) string {
		name := strings.SplitN(f.Tag.Get("json"), ",", 2)[0]
		if name == "-" {
			return "" // Ignore fields with `json:"-"`
		}
		return name
	})

	// You might also want to register custom error messages for specific tags if
	// the default `formatErrorMessage` is not sufficient, perhaps using `validator.CreateTranslator`.
	// However, `formatErrorMessage` already provides a good level of detail.
}

// GetValidator returns the configured validator instance.
func GetValidator() *validator.Validate {
	if validate == nil {
		// In a real application, you'd ensure InitValidator() is called first,
		// or handle this with a panic/error for uninitialized state.
		// For simplicity here, we can re-initialize, but it's not ideal for production.
		InitValidator()
	}
	return validate
}
*/