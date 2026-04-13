# Code Review Dimensions — Deep Dive

Expanded checklists and examples for each review dimension.

## Correctness

### Logic Errors
- Off-by-one in loops and array indexing
- Incorrect boolean logic (De Morgan's law violations)
- Wrong comparison operators (`<` vs `<=`)
- Floating point equality comparisons
- Integer overflow/underflow

### Null/None Handling
- Missing null checks before dereference
- Optional chaining where null is unexpected
- Default value appropriateness
- Nullable type annotations accuracy

### Race Conditions
- Shared mutable state without synchronization
- Check-then-act patterns
- Double-checked locking issues
- Event ordering assumptions

### Error Paths
- Unhandled exceptions
- Resource cleanup in error paths
- Error propagation vs. swallowing
- Transaction rollback on failure

---

## Scope Fit

### Single Purpose
- Each changeset does ONE thing
- Related changes grouped logically
- No unrelated "while I'm here" fixes

### Drive-By Refactors
- Formatting changes mixed with logic
- Renaming mixed with behavior changes
- Dependency updates mixed with features

### Intent Match
- Changes accomplish stated goal
- No scope creep beyond requirement
- Clear connection to issue/ticket

---

## Design

### Layer Placement
- Business logic not in controllers
- Data access isolated from domain
- Presentation separate from logic

### Pattern Adherence
- Follows established project patterns
- Consistent with similar code
- Uses appropriate design patterns

### Abstraction Level
- Not over-engineered (YAGNI)
- Not under-abstracted (DRY violations)
- Interfaces where appropriate

### Interface Quality
- Clear contracts
- Minimal surface area
- Sensible defaults

---

## Testing

### Coverage
- Happy path tested
- Error conditions tested
- Boundary values tested
- Integration points tested

### Test Quality
- Tests are readable and maintainable
- Tests document behavior
- Appropriate use of mocks/stubs
- No flaky tests introduced

### Edge Cases
- Empty inputs
- Maximum values
- Null/undefined inputs
- Concurrent access scenarios

---

## Readability

### Naming
- Names reveal intent
- Consistent vocabulary
- Appropriate length (not too short/long)
- No misleading names

### Function Length
- Functions do one thing
- Easy to read in one screen
- Clear entry and exit points

### Comments
- Explain "why", not "what"
- No commented-out code
- API documentation complete
- Complex algorithms explained

### Organization
- Logical grouping of related code
- Consistent file structure
- Clear module boundaries

---

## Security

### Input Validation
- All user input validated
- Appropriate sanitization
- Length limits enforced
- Type checking applied

### Authentication/Authorization
- Auth checks present
- Authorization verified at correct level
- Session handling secure
- Token management proper

### Injection Prevention
- SQL parameterized queries
- Command injection prevention
- XSS prevention
- Template injection prevention

### Secrets Management
- No hardcoded credentials
- Secrets not logged
- Secure secret storage
- Proper key rotation support

### Data Protection
- Sensitive data encrypted at rest
- Secure transmission (TLS)
- Appropriate access controls
- PII handling compliance

---

## Performance

### Database
- N+1 query patterns avoided
- Appropriate indexes exist
- Query complexity reasonable
- Connection pooling used

### Memory
- No unbounded collections
- Large objects properly managed
- Memory leaks prevented
- Caching strategy appropriate

### Algorithms
- Appropriate time complexity
- No unnecessary iterations
- Efficient data structures
- Lazy evaluation where appropriate

### I/O
- Async where beneficial
- Batching used appropriately
- Connection reuse
- Timeout handling

---

## Documentation

### API Documentation
- Public interfaces documented
- Parameters described
- Return values explained
- Exceptions documented

### Breaking Changes
- Migration path provided
- Deprecation warnings added
- Version notes updated
- Changelog maintained

### README Updates
- Setup instructions current
- Examples updated
- Dependencies documented
- Configuration explained

### Code Comments
- Complex logic explained
- Assumptions documented
- Edge cases noted
- TODOs tracked
