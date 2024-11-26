from rest_framework.exceptions import APIException


class WrongRole(APIException):
    def __init__(self, msg="Your role does not allow that."):
        super().__init__(msg)


class OCPIProtocolError(APIException):
    errno = None

    def __init__(self, msg, errno=None):
        from ocpi22 import logging

        logging.error(msg)
        super().__init__(msg)
        self.errno = errno


class OCPIMismatch(APIException):
    def __init__(self, msg="OCPI protocol mismatch"):
        super().__init__(msg)


class NoCommonVersion(APIException):
    pass


class TariffNotFoundError(Exception):
    def __init__(
        self,
        evse_id=None,
        standard=None,
        message="No Tariffs found for the given connector",
    ):
        self.evse_id = evse_id
        self.standard = standard
        self.error_message = f"Evse {self.evse_id}, connector {self.standard} does not have assigned or default tariffs"
        self.message = (
            message
            if self.evse_id is None or self.standard is None
            else self.error_message
        )
        super().__init__(self.message)
