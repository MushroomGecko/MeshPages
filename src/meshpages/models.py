from typing import Union

import pydantic


class ResponsePacket(pydantic.BaseModel):
    """
    Network packet response structure.

    Attributes:
        status_code (int): HTTP-like status code indicating success or error.
        current_chunk_id (int): Current chunk index in multi-part response.
        total_chunks (int): Total number of chunks in the complete response.
        content (Union[bytes, str]): The payload data, either raw bytes or string.
    """

    status_code: int
    current_chunk_id: int
    total_chunks: int
    content: Union[bytes, str]


class User(pydantic.BaseModel):
    """
    Mesh network user/request model.

    Attributes:
        from_id (str): The sender's node ID.
        result (str): The response or result data from the user's request.
        intended_return_type (str): Expected data type of the result.
        status_code (int): Status code indicating success or error of the request.
        time_received (float): Timestamp when the request was received (epoch seconds).
    """

    from_id: str
    result: str
    intended_return_type: str
    status_code: int
    time_received: float


class Config(pydantic.BaseModel):
    """
    LoRa radio configuration parameters.

    Attributes:
        sf (int): Spreading factor (7-12), higher values increase range at cost of airtime.
        coding_rate (float): Error correction coding rate (4/5, 4/6, 4/7, 4/8), higher is faster.
        bandwidth_khz (int): Channel bandwidth in kilohertz (125, 250, or 500 kHz).
    """

    sf: int
    coding_rate: float
    bandwidth_khz: int


class PacketHistory(pydantic.BaseModel):
    """
    Historical record of a transmitted packet.

    Attributes:
        timestamp (float): When the packet was transmitted (epoch seconds).
        airtime_ms (float): Time the packet occupied the radio channel (milliseconds).
    """

    timestamp: float
    airtime_ms: float
