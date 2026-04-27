"""
Custom type markers for MeshPages parameter validation and routing.

These classes serve as type hints for endpoint parameters, allowing the framework
to identify and handle specific parameter types during request processing.

Usage:
    @app.page("/endpoint")
    def handler(client_id: ClientID):
        return f"Client: {client_id}"

    # In request handlers, you can check parameter types:
    parameter_types = route_info.get("parameter_types", {})
    if parameter_types.get("client_id") == ClientID:
        # Apply ClientID-specific validation or transformation
        pass
"""


class MeshType:
    """
    Base class for mesh types.

    Used to identify and handle parameters representing mesh types.
    Allows the framework to apply MeshType-specific validation or processing.
    All other mesh types should inherit from this class.

    Subclasses should set a `.value` attribute in `__init__` to enable comparison
    and string representation.
    """

    def __init__(self):
        self.value = None

    def __eq__(self, other):
        if isinstance(other, MeshType):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"{self.__class__.__name__}({self.value!r})"


class ClientID(MeshType):
    """
    Marker type for client identifiers.

    Used to identify and handle parameters representing client IDs.
    Allows the framework to apply ClientID-specific validation or processing.
    """

    def __init__(self, packet: dict):
        self.value = str(packet.get("fromId", ""))
