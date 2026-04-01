"""Exception classes for the observer."""

from pathlib import Path


class ObserverError(Exception):
    """Base exception for observer errors."""


class DatabaseError(ObserverError):
    """Raised when a database operation fails."""

    def __init__(self, operation: str, detail: str) -> None:
        super().__init__(f"Database error during {operation}: {detail}")


class TranscriptError(ObserverError):
    """Raised when a transcript file cannot be processed."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"Transcript error for {path}: {detail}")


class ExtractionError(ObserverError):
    """Raised when LLM extraction fails."""


class DatabaseNotConfiguredError(ObserverError):
    """Raised when the database URL is not configured."""

    def __init__(self) -> None:
        super().__init__("Database is not configured. Run `observer setup` to initialize.")


class DatabaseClosedError(ObserverError):
    """Raised when attempting to use a closed database connection."""

    def __init__(self) -> None:
        super().__init__("Database has been closed")


class UnsupportedDialectError(ObserverError):
    """Raised when a non-SQLite database URL is provided."""

    def __init__(self, dialect: str) -> None:
        super().__init__(
            f"Unsupported database dialect {dialect!r}. "
            "Observer requires SQLite (the default). "
            "Check OBSERVER_DB_URL if you overrode the connection URL."
        )


class EmbeddingShapeError(ObserverError):
    """Raised when the embedding model produces an unexpected output shape."""

    def __init__(self, expected: tuple, actual: tuple) -> None:
        super().__init__(f"Embedding shape mismatch: expected {expected}, got {actual}")


class RegistrationError(ObserverError):
    """Raised when session registration fails."""

    def __init__(self, cwd: str) -> None:
        super().__init__(f"Not a git repository: {cwd}")


class ExtractionTimeoutError(ExtractionError):
    """Raised when the claude -p subprocess times out."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"claude -p timed out after {timeout}s (after retry)")


class ExtractionSubprocessError(ExtractionError):
    """Raised when the claude -p subprocess exits with a non-zero code."""

    def __init__(self, code: int, stderr: str) -> None:
        super().__init__(f"claude -p exited with code {code}: {stderr}")


class ExtractionParseError(ExtractionError):
    """Raised when the claude -p JSON output cannot be parsed."""

    def __init__(self, output: str) -> None:
        super().__init__(f"Failed to parse claude -p output: {output}")


class ExtractionResponseError(ExtractionError):
    """Raised when the claude -p response is missing the expected result field."""

    def __init__(self, keys: list) -> None:
        super().__init__(f"Missing 'result' in claude -p response: {keys}")


class PromptAttributeError(AttributeError):
    """Raised when a prompt template attribute is not found in the module."""

    def __init__(self, module: str, name: str) -> None:
        super().__init__(f"module {module!r} has no attribute {name!r}")


class TranscriptNotSavedError(ValueError):
    """Raised when a transcript must be saved before ingestion."""

    def __init__(self) -> None:
        super().__init__("Transcript must be saved before ingestion")


class TranscriptFileNotFoundError(FileNotFoundError):
    """Raised when a transcript file does not exist at the expected path."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Transcript file not found: {path}")
