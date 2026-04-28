from enum import Enum, IntEnum, StrEnum


class ChannelPresets(Enum):
    """
    Predefined LoRa channel configurations for mesh communication.

    Each preset defines spreading factor (sf), coding rate, and bandwidth
    to optimize for different range and speed trade-offs. Presets are named
    by range (SHORT, MEDIUM, LONG) and performance tier (TURBO, FAST, MODERATE, SLOW).

    Attributes:
        SHORT_TURBO: High speed over short range.
        SHORT_FAST: Balanced speed over short range.
        SHORT_SLOW: Low speed, resilient over short range.
        MEDIUM_FAST: High speed over medium range.
        MEDIUM_SLOW: Low speed, resilient over medium range.
        LONG_TURBO: High speed over long range.
        LONG_FAST: Balanced speed over long range.
        LONG_MODERATE: Moderate speed and resilience over long range.
        LONG_SLOW: Low speed, maximum resilience over long range.
    """

    SHORT_TURBO = {"sf": 7, "coding_rate": 4 / 5, "bandwidth_khz": 500}
    SHORT_FAST = {"sf": 7, "coding_rate": 4 / 5, "bandwidth_khz": 250}
    SHORT_SLOW = {"sf": 8, "coding_rate": 4 / 5, "bandwidth_khz": 250}
    MEDIUM_FAST = {"sf": 9, "coding_rate": 4 / 5, "bandwidth_khz": 250}
    MEDIUM_SLOW = {"sf": 10, "coding_rate": 4 / 5, "bandwidth_khz": 250}
    LONG_TURBO = {"sf": 11, "coding_rate": 4 / 8, "bandwidth_khz": 500}
    LONG_FAST = {"sf": 11, "coding_rate": 4 / 5, "bandwidth_khz": 250}
    LONG_MODERATE = {"sf": 11, "coding_rate": 4 / 8, "bandwidth_khz": 125}
    LONG_SLOW = {"sf": 12, "coding_rate": 4 / 8, "bandwidth_khz": 125}


class StatusCodes(IntEnum):
    """
    HTTP status codes for mesh network responses.

    Standard HTTP-like status codes used to communicate the result of mesh network
    requests. These codes indicate whether a request was successful, encountered a
    client error, or a server error. As IntEnum members, they behave as integers
    and can be used directly in comparisons and operations.

    Attributes:
        SUCCESS: Request completed successfully.
        BAD_REQUEST: The request was malformed or invalid.
        UNAUTHORIZED: The request requires authentication.
        FORBIDDEN: The authenticated user doesn't have permission for this resource.
        NOT_FOUND: The requested resource or endpoint does not exist.
        NOT_IMPLEMENTED: The requested functionality is not implemented.
        INTERNAL_SERVER_ERROR: An unexpected error occurred on the server.
        BAD_GATEWAY: Invalid response from upstream server.
        SERVICE_UNAVAILABLE: The service is temporarily unavailable.
        GATEWAY_TIMEOUT: Upstream server failed to respond in time.
    """

    SUCCESS = 200
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    INTERNAL_SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504


class ReturnTypes(StrEnum):
    """
    Supported content types for responses from endpoint handlers.

    Defines the format in which responses are sent to mesh clients:
    - HTML: Binary-encoded responses with minification and compression for web clients
    - TEXT: Plain text responses for Meshtastic app clients
    - BOTH: Endpoints that support both HTML and text response formats
    """

    HTML = "html"
    TEXT = "text"
    BOTH = "both"
