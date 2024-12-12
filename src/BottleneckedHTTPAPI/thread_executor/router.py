from typing import Union, Any, Callable, Optional
import hashlib

from .abstract_executor import AbstractSingleThreadExecutor, PoolFullException
from .request_and_response import AbstractRequest, AbstractResponse, ErrorResponse

class SingleThreadExecutorRouterWrapper:
    """
    Wrapper around an executor to allow preprocessing and postprocessing of the
    requests and responses in different threads. Allows registering callbacks
    for different functions to handle the execution.
    """
    registered_processors: dict[tuple[Union[str, int, float]], tuple[Callable[[Any], tuple[AbstractRequest, Any]], Callable[[AbstractResponse, Any], None]]]

    _registered_processors_to_exec: dict[tuple[Union[str, int, float]], str] # optional
    _exec_hash_to_exec: dict[str, str] # optional
    _exec_to_exec_hash: dict[str, str] # optional
    _hashlen: int # optional
    _executor_pool: Union[AbstractSingleThreadExecutor, dict[str, AbstractSingleThreadExecutor]]
    _rp_length: int

    def __init__(self,
                 executor_pool: Union[AbstractSingleThreadExecutor, dict[str, AbstractSingleThreadExecutor]]):
        """
        When using this class, DO NOT pass the static_state inside the preprocess_callback! It will be overridden.

        Args:
            executor_pool: Can be a single executor for a unique single execution, or a key-value pair of executors for orchestrating
                           multiple executors (not necessarily the same implementation).
        """
        if not isinstance(executor_pool, AbstractSingleThreadExecutor):
            if (not isinstance(executor_pool, dict)) or not all(isinstance(k, str) for k in executor_pool):
                raise ValueError("For multiple execution, expect a dictionary of str-AbstractSingleThreadExecutor pairs!")
            if not all(isinstance(executor_pool[k], AbstractSingleThreadExecutor) for k in executor_pool):
                raise ValueError("For multiple execution, expect a dictionary of str-AbstractSingleThreadExecutor pairs!")
            
            # populate the hash maps
            self._exec_hash_to_exec = {}
            self._exec_to_exec_hash = {}
            self._hashlen = None
            for k in executor_pool:
                khash = hashlib.sha256(k).hexdigest()
                if self._hashlen is not None and len(khash) != self._hashlen:
                    raise ValueError("incorrect hash")
                self._hashlen = len(khash)
                if khash in self._exec_hash_to_exec:
                    raise ValueError("wtf improbable hash collision")
                self._exec_hash_to_exec[khash] = k
                self._exec_to_exec_hash[k] = khash
        else:
            self._exec_hash_to_exec = {}
            self._exec_to_exec_hash = {}
            
        self._executor_pool = executor_pool
        self._rp_length = None
        self.registered_processors = {}
        self._registered_processors_to_exec = {}
    
    def is_single_executor(self) -> bool:
        """
        Returns whether a single executor is used.
        """
        return isinstance(self._executor_pool, AbstractSingleThreadExecutor)

    def register_processor_pair(
        self,
        value: tuple[Union[str, int, float]],
        preprocess_callback: Callable[[Any], tuple[AbstractRequest, Any]],
        postprocess_callback: Callable[[AbstractResponse, Any], None],
        executor_tag: Optional[str]=None
    ):
        """
        Register a processor pair (preprocessor and postprocessor) that is triggered when
        the given value is met. The preprocessor and postprocessor must be functions that
        are stateless, and the only states that can possibly be stored is through the
        AbstractRequest, and it will be passed to AbstractResponse's static_state automatically
        when a response is created, by this class and the AbstractSingleThreadExecutor.
        The preprocess callback therefore must return a tuple of (request, static_state).

        Note that postprocess_callback can be used to further postprocess the AbstractResponse to be
        used as a return value of poll_response, or it can be directly used to process the AbstractResponse,
        the implementation can choose to do both. Note that responses with .has_error() won't be processed
        by postprocess_callback.

        Args:
            value: The value to be matched (exactly), as a criterion for choosing the pair of function(s).
            preprocess_callback: The stateless function for preprocessing. Can take in anything (see queue_request's request_kwargs),
                                 and must return a tuple[AbstractRequest, Any]. Can throw ValueError if an value error occurs.
            postprocess_callback: The stateless function for postprocessing. Must take in two variables, the first response: AbstractResponse,
                                  the second static_state: Any. Returns None (it will be ignored). Do NOT raise exceptions here, it doesn't
                                  help! Instead try to catch all exceptions, and use the errorify function of AbstractResponse.
            executor_tag: The string which represents the key for the desired executor in the executor pool. Ignored if single execution mode
                          is used, and required if multiple execution mode is used.

        Returns:
            str: The token assigned to the request.
        
        Raises:
            ValueError: If the value provided is invalid or repeated.
        """
        if not isinstance(value, tuple):
            raise ValueError("Value must be a tuple!")
        if (len(value) == 0) or (self._rp_length is not None and len(value) != self._rp_length):
            raise ValueError("Length must match the prior lengths!")
        if not all(isinstance(v, (str, int, float)) for v in value):
            raise ValueError("The value must be a list of str int float.")
        if value in self.registered_processors:
            raise ValueError("Cannot have repeated values.")
        if not self.is_single_executor():
            if executor_tag is None or not isinstance(executor_tag, str):
                raise ValueError("When using executor pool mode, the executor tag must be given to specify which to use!")
            if executor_tag not in self._executor_pool:
                raise ValueError("Invalid executor tag! Must be a key of executor_pool.")
            self._registered_processors_to_exec[value] = executor_tag
        
        self._rp_length = len(value)
        self.registered_processors[value] = (preprocess_callback, postprocess_callback)
    
    def has_value(self, value: Union[list[Union[str, int, float]], tuple[Union[str, int, float]]]) -> bool:
        """Whether a value is validly contained as one of the criterion for the pre/postprocessing pair."""
        if isinstance(value, list):
            value = tuple(value)
        return value in self.registered_processors

    def queue_request(
        self,
        value: Union[list[Union[str, int, float]], tuple[Union[str, int, float]]],
        **request_kwargs: dict[str, Any]
    ) -> str:
        """
        Queues a new request for execution.

        Args:
            value: The criterion for determining which pair of functions to route to
            request_kwargs: The arguments to be passed to the preprocess_callback.

        Returns:
            str: The token assigned to the request.
        
        Raises:
            PoolFullException: If the handling of requests and responses pool is already full.
            NotImplementedError: If the value doesn't exist (criterion not registered by register_processor_pair).
            BaseException: Any exception that can raised by the selected preprocess_callback. The internal state of the executor will still be intact if this happens.
        """
        if not (isinstance(value, list) or isinstance(value, tuple)):
            raise ValueError("Value must be a list or tuple!")
        if isinstance(value, list):
            value = tuple(value)
        if (len(value) == 0) or (self._rp_length is not None and len(value) != self._rp_length):
            raise ValueError("Length must match the prior lengths!")
        if not all(isinstance(v, (str, int, float)) for v in value):
            raise ValueError("The value must be a list of str int float.")
        if value not in self.registered_processors:
            raise NotImplementedError("Value {} not found! Must register it in register_processor_pair".format(value))
        
        preprocess_fn: Callable[[Any], tuple[AbstractRequest, Any]] = self.registered_processors[value][0]

        request: AbstractRequest
        static_state: Any
        request, static_state = preprocess_fn(**request_kwargs)
        request._static_state = {"static_state": static_state, "vtuple": value}

        # list executors
        if self.is_single_executor():
            return self._executor_pool.queue_request(request)
        else:
            chosen_exec: AbstractSingleThreadExecutor = self._executor_pool[self._registered_processors_to_exec[value]]
            typehash: str = self._exec_to_exec_hash[self._registered_processors_to_exec[value]]
            pretok = chosen_exec.queue_request(request)
            return typehash + pretok # concatenate as the token

    
    def queue_request_suppress_exc(
        self,
        value: Union[list[Union[str, int, float]], tuple[Union[str, int, float]]],
        **request_kwargs: dict[str, Any]
    ) -> tuple[str, bool]:
        """
        Queues a new request for execution, but suppressing the exceptions that are specified in queue_request.
        Expected that no exceptions to be raised here. If so, there's a bug in the implementation of the router
        or AbstractExecutor class.

        Args:
            value: The criterion for determining which pair of functions to route to
            request_kwargs: The arguments to be passed to the preprocess_callback.

        Returns:
            str: The token assigned to the request, or the error message.
            bool: Whether it was successful or an error.
        """
        if not (isinstance(value, list) or isinstance(value, tuple)):
            raise ValueError("Value must be a list or tuple!")
        if isinstance(value, list):
            value = tuple(value)
        if (len(value) == 0) or (self._rp_length is not None and len(value) != self._rp_length):
            raise ValueError("Length must match the prior lengths!")
        if not all(isinstance(v, (str, int, float)) for v in value):
            raise ValueError("The value must be a list of str int float.")
        if value not in self.registered_processors:
            return "Not Implemented Yet.", False
        
        preprocess_fn: Callable[[Any], tuple[AbstractRequest, Any]] = self.registered_processors[value][0]

        request: AbstractRequest
        static_state: Any
        try:
            request, static_state = preprocess_fn(**request_kwargs)
        except BaseException:
            return "Internal error when preprocessing the request.", False
        request._static_state = {"static_state": static_state, "vtuple": value}

        # list executors
        try:
            if self.is_single_executor():
                resp = self._executor_pool.queue_request(request)
            else:
                chosen_exec: AbstractSingleThreadExecutor = self._executor_pool[self._registered_processors_to_exec[value]]
                typehash: str = self._exec_to_exec_hash[self._registered_processors_to_exec[value]]
                pretok = chosen_exec.queue_request(request)
                resp = typehash + pretok # concatenate as the token
        except PoolFullException:
            return "The execution pool is full. Please wait.", False
        return resp, True
    
    def poll_response(self, token: str) -> Optional[AbstractResponse]:
        """
        Retrieves the response for a given token if available. If the response doesn't
        have error (see .has_error(), .is_successful_response() of AbstractResponse),
        further process the response by calling the corresponding postprocess_callback.
        Returns the AbstractResponse if the request is finished processing, otherwise
        returns None.

        Args:
            token (str): The token of the request.

        Returns:
            Optional[AbstractResponse]: The response if available, else None.
        
        Raises:
            Should not raise any error or exceptions, unless there's a bug in the implementation
            of the postprocess_callback, or a bug in the Router / Executor itself.
        """
        executor: AbstractSingleThreadExecutor
        token: str
        if self.is_single_executor():
            executor = self._executor_pool
        else:
            if self._hashlen >= token:
                return ErrorResponse(token, "Invalid token format.")
            exec_hash = token[:self._hashlen]
            token = token[self._hashlen:]
            if exec_hash not in self._exec_hash_to_exec:
                return ErrorResponse(token, "Invalid token format.")
            executor = self._executor_pool[self._exec_hash_to_exec[exec_hash]]
        response: Optional[AbstractResponse] = executor.poll_response(token)
        if response is None:
            return None
        
        if response.has_error():
            return response # no need to keep processing
        
        # format now
        static_state: Any
        value: list[Union[str, int, float]]
        static_state = response._static_state["static_state"]
        value = response._static_state["vtuple"]
        postprocess_fn: Callable[[AbstractResponse, Any], None] = self.registered_processors[value][1]
        postprocess_fn(response, static_state)

        # return
        return response
    
    def cancel_request(self, token: str):
        """
        Cancels the request from the token. If the token is invalid, omit it.

        Args:
            token (str): The token to cancel.
        """
        executor: AbstractSingleThreadExecutor
        if self.is_single_executor():
            executor = self._executor_pool
        else:
            if self._hashlen >= token:
                return
            exec_hash = token[:self._hashlen]
            token = token[self._hashlen:]
            if exec_hash not in self._exec_hash_to_exec:
                return
            executor = self._executor_pool[self._exec_hash_to_exec[exec_hash]]
        
        executor.cancel_request(token)