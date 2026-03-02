class TerminalError(Exception):
    pass


class TerminalNotFoundError(TerminalError):
    pass


class TerminalAlreadyExistsError(TerminalError):
    pass


class TerminalValidationError(TerminalError):
    pass


class FinancialAdviceConfirmationError(Exception):
    pass


class FinancialAdviceConfirmationAlreadyExistsError(FinancialAdviceConfirmationError):
    pass


class FinancialAdviceConfirmationValidationError(FinancialAdviceConfirmationError):
    pass
