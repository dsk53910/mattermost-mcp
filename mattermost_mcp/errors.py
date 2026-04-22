class MattermostError(Exception):
    """Base exception for Mattermost MCP server."""


class MattermostApiError(MattermostError):
    def __init__(self, status_code: int, message: str, details=None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class MattermostConnectionError(MattermostError):
    """Raised when the server cannot reach Mattermost."""


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data=None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data
