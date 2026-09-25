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


class ConnectorBadResponse(ResolutionError):
    status_code = 502
    code = "connector_bad_response"
    message = "An enterprise connector returned an invalid response."


class ConnectorUnavailable(ResolutionError):
    status_code = 503
    code = "connector_unavailable"
    message = "An enterprise connector is unavailable."


class ConnectorCircuitOpen(ConnectorUnavailable):
    code = "connector_circuit_open"
    message = "An enterprise connector circuit is open."


class ConnectorTimeout(ResolutionError):
    status_code = 504
    code = "connector_timeout"
    message = "An enterprise connector timed out."


class InvalidIdempotencyKey(ResolutionError):
    status_code = 400
    code = "invalid_idempotency_key"
    message = "Idempotency-Key must contain 8 to 128 visible ASCII characters."


class ActionNotFound(ResolutionError):
    status_code = 404
    code = "action_not_found"
    message = "The requested action intent was not found."


class IdempotencyConflict(ResolutionError):
    status_code = 409
    code = "idempotency_conflict"
    message = "The idempotency key was already used with a different request."
