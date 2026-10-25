class DataSentryError(Exception):
    """Base exception for DataSentry."""


class DataValidationError(DataSentryError):
    """Raised when the input data is invalid."""


class ConfigError(DataSentryError):
    """Raised when configuration is invalid."""


class PersistenceError(DataSentryError):
    """Raised when SQLite persistence fails."""


class ReportError(DataSentryError):
    """Raised when report generation fails."""
