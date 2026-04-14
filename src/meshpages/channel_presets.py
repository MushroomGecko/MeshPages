from enum import Enum


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
