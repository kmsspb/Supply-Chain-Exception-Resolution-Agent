"""Public errors contain safe messages, never upstream response bodies."""


class ResolutionError(Exception):
    status_code = 500
    code = "internal_error"
    message = "The analysis could not be completed."

    def __init__(self):
        super().__init__(self.message)
        self.run_id: str | None = None
        self.metadata: dict = {}


class ExceptionNotFound(ResolutionError):
    status_code = 404
    code = "exception_not_found"
    message = "The requested exception was not found."


class MissingEvidence(ResolutionError):
    status_code = 422
    code = "missing_evidence"
    message = "Required supporting evidence is unavailable."


class CorruptData(ResolutionError):
    code = "corrupt_local_data"
    message = "Local source data could not be read or validated."


class InvalidProviderOutput(ResolutionError):
    status_code = 502
    code = "invalid_provider_output"
    message = "The reasoner returned invalid output or unsupported evidence references."


class ProviderRefusal(InvalidProviderOutput):
    code = "provider_refusal"
    message = "The model declined to analyse this exception."


class IncompleteProviderOutput(InvalidProviderOutput):
    code = "incomplete_provider_output"
    message = "The model response was incomplete."


class ProviderUnavailable(ResolutionError):
    status_code = 503
    code = "provider_unavailable"
    message = "The configured reasoning provider is unavailable."


class ConfigurationError(ProviderUnavailable):
    code = "provider_configuration_error"
    message = "Reasoner configuration is missing or invalid; check the documented environment variables."


class ProviderTimeout(ResolutionError):
    status_code = 504
    code = "provider_timeout"
    message = "The reasoning provider timed out."
