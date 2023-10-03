from rest_framework.exceptions import APIException


class WrongRole(APIException):
    def __init__(self, msg="Your role does not allow that."):
        super().__init__(msg)
