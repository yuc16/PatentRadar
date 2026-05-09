"""Domain exceptions."""


class PatentRadarError(RuntimeError):
    """Base project error."""


class PatentFetchError(PatentRadarError):
    """Raised when patent data cannot be fetched or parsed."""


class LLMOutputError(PatentRadarError):
    """Raised when an LLM response cannot be validated."""
