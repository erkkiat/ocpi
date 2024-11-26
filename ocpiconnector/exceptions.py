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
    pass
