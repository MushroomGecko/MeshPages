import time
from math import pow
from queue import Queue
from typing import Union

from meshpages.channel_presets import ChannelPresets
from meshpages.models import Config, PacketHistory


class AirTrafficControl:
    """
    Manages radio channel utilization to prevent congestion in mesh networks.

    This class implements backoff algorithms to regulate transmission rates based
    on target channel utilization. It tracks packet transmission history and
    calculates required delays to maintain healthy network bandwidth distribution.
    """

    def __init__(
        self,
        config: Union[Config, ChannelPresets] = ChannelPresets.LONG_FAST,
        target_utilization_percent: float = 50.0,  # in percent
        window_seconds: float = 15.0,  # in seconds
        meshtastic_overhead_bytes: int = 20,  # in bytes
    ):
        """
        Initialize the air traffic control manager.

        Parameters:
            config (Union[Config, ChannelPresets]): LoRa radio configuration. Defaults to LONG_FAST preset.
            target_utilization_percent (float): Target channel utilization as percentage (0-100). Defaults to 50%.
            window_seconds (float): Time window for calculating utilization (seconds). Defaults to 15 seconds.
            meshtastic_overhead_bytes (int): Protocol overhead bytes per packet. Defaults to 20.
        """
        if isinstance(config, ChannelPresets):
            self.config = Config(**config.value)
        else:
            self.config = config
        # Queue to store packet history with transmission timing information
        self.packet_history = Queue[PacketHistory]()
        # Maximum theoretical transmission speed given the current LoRa configuration
        self.data_rate = self._calculate_data_rate()
        # Target channel utilization as a decimal fraction (e.g., 0.5 for 50%)
        self.target_utilization = target_utilization_percent / 100.0
        # Time window for measuring recent channel activity
        self.window_seconds = window_seconds
        # Protocol overhead added to each packet during transmission
        self.meshtastic_overhead_bytes = meshtastic_overhead_bytes

    def add_packet_sent(self, packet_size_bytes: int) -> None:
        """
        Record a transmitted packet in the history.

        Parameters:
            packet_size_bytes (int): Size of the packet payload in bytes.

        Returns:
            None

        Calculates transmission time including protocol overhead and stores
        the packet history for utilization tracking.
        """
        # Calculate total transmission time: (payload + overhead) / data_rate = airtime
        seconds_to_transmit = (packet_size_bytes + self.meshtastic_overhead_bytes) / self.data_rate
        self.packet_history.put(
            PacketHistory(
                timestamp=time.time(),
                airtime_ms=seconds_to_transmit * 1000,
            )
        )
        self._clean_old_packets()

    def apply_backoff_delay(self) -> float:
        """
        Apply backoff delay if channel utilization exceeds target.

        If current utilization is below target, returns 0 (no delay needed).
        Otherwise, calculates and applies a delay to bring utilization down to target.

        Parameters:
            None

        Returns:
            float: Delay applied in seconds (0.0 if no delay was necessary).
        """
        current_utilization = self._get_current_utilization()
        if current_utilization < self.target_utilization:
            return 0.0

        # Calculate the time window needed to reduce utilization to target level
        total_airtime_ms = sum(packet.airtime_ms for packet in self.packet_history.queue)
        required_window_ms = total_airtime_ms / self.target_utilization

        delay_seconds = (required_window_ms / 1000) - self.window_seconds
        if delay_seconds > 0.0:
            time.sleep(delay_seconds)
        return delay_seconds

    def _calculate_data_rate(self) -> float:
        """
        Calculate the effective data rate based on LoRa configuration.

        Uses spreading factor, coding rate, and bandwidth to compute the
        theoretical maximum data rate in bytes per second.

        Parameters:
            None

        Returns:
            float: Data rate in bytes per second (minimum 0.000001 to prevent division errors).
        """
        sf = self.config.sf
        coding_rate = self.config.coding_rate
        bandwidth_khz = self.config.bandwidth_khz

        # LoRa bandwidth parameter is specified in kilohertz; convert to Hz for calculation
        bandwidth_hz = bandwidth_khz * 1000

        # LoRa chirp duration: time for one symbol to transmit (2^SF symbols per second at given bandwidth)
        chirp_duration = pow(2, sf) / bandwidth_hz
        # Bits transmitted per second based on spreading factor and chirp duration
        bits_per_second = sf / chirp_duration
        # Effective data rate accounting for error correction overhead via coding rate parameter
        # Divide by 8 to convert bits per second to bytes per second
        data_rate_bytes_per_second = (bits_per_second * coding_rate) / 8

        # Prevent division by zero errors in future calculations by enforcing a minimum rate
        return max(data_rate_bytes_per_second, 0.000001)

    def _clean_old_packets(self) -> int:
        """
        Remove packets outside the utilization window from history.

        Removes all packets with timestamps older than window_seconds to maintain
        an accurate sliding window of recent transmissions.

        Parameters:
            None

        Returns:
            int: Number of packets remaining in the history.
        """
        now = time.time()
        # Access internal queue deque directly to inspect oldest packet without removing it first
        while not self.packet_history.empty() and now - self.packet_history.queue[0].timestamp > self.window_seconds:
            self.packet_history.get()
        return len(self.packet_history.queue)

    def _get_current_utilization(self) -> float:
        """
        Calculate current channel utilization within the window.

        Parameters:
            None

        Returns:
            float: Utilization as a fraction (0.0 to 1.0+), where 1.0 represents 100% occupancy.
        """
        self._clean_old_packets()
        if self.packet_history.empty():
            return 0.0

        # Sum airtime of all packets within the window to get total occupied channel time
        total_airtime_ms = sum(packet.airtime_ms for packet in self.packet_history.queue)
        window_ms = self.window_seconds * 1000
        return total_airtime_ms / window_ms
