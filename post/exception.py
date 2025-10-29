class FetchError(Exception):
    def __init__(self, message: str, source: list[Exception]):
        super().__init__(message)
        self.source = source
