class HubjectRemoteCommandError(Exception):
    def __init__(self, error_code: str, message: str, data=None):
        self.error_code = error_code
        self.data = data
        super().__init__(message)
