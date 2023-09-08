class WrongRole(Exception):
    def __init__(self, msg="Your role does not allow that."):
        super().__init__(msg)
