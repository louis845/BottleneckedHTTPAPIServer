import abc
from typing import Optional, Any

class AbstractRequest(abc.ABC):
    """
    Abstract base class representing a request to be processed by the executor.
    """
    _static_state: Optional[Any]

    def __init__(self, static_state: Optional[Any]=None):
        """
        When using a bare AbstractSingleThreadExecutor, you can set the
        static_state however you want. The static state will be moved by
        AbstractSingleThreadExecutor's internal handler functions to the
        AbstractResponse when a response is completed, so it is unnecessary
        to manually set the static state of the AbstractResponse when creating.

        When using the SingleThreadExecutorRouterWrapper, the static state
        will be OVERWRITTEN, so do not set it. Instead, use the return value
        of the callback functions to set the static state.
        """
        self._static_state = static_state
    
class AbstractResponse:
    """
    Class representing a response from the executor after processing a request.
    """
    cancelled: bool
    error_msg: Optional[str]
    _static_state: Optional[Any]
    
    def __init__(
        self,
        cancelled: bool = False,
        error_msg: Optional[str] = None
    ):
        self.cancelled = cancelled
        self.error_msg = error_msg
        self._static_state = None

    def has_error(self) -> bool:
        """
        Whether there is an error. Can be freely used.
        """
        return self.error_msg is not None
    
    def get_error_msg(self):
        """
        Get the error message. Can be freely used iff there is an error.
        """
        if not self.has_error():
            raise ValueError("Only works when there is an error!")
        return self.error_msg
    
    def is_cancelled(self) -> bool:
        """
        Whether the error is due to cancellation. Can be freely used.
        """
        return self.cancelled
    
    def errorify(self, error_msg: str) -> None:
        """
        Mark a successful response into a response with error. Can be freely used.
        Mainly used for postprocessing functions (SingleThreadExecutorRouterWrapper).
        """
        self.error_msg = error_msg

    def is_successful_response(self) -> bool:
        """
        Is the response successful (Equivalent to not has_error). Can be freely used.
        """
        return not (self.has_error() or self.is_cancelled())

    def _set_static_state(self, static_state: Optional[Any]) -> None:
        """
        Used internally, do not call.
        """
        self._static_state = static_state
    
    def get_static_state(self) -> Optional[Any]:
        """
        Gets whether there is a static state. Even if not explicitly set in the constructor,
        the AbstractSingleThreadExecutor will set it.
        """
        return self._static_state

class ErrorResponse(AbstractResponse):
    """
    Class representing an error response.
    """
    def __init__(self, error_msg: str):
        super().__init__(False, error_msg)
    
class CancelledResponse(AbstractResponse):
    """
    Class representing a cancelled response.
    """
    def __init__(self):
        super().__init__(True, "Response is cancelled!")