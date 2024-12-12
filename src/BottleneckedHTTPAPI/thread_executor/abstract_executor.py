from typing import Optional, Any
import os
import hashlib
import threading
import logging
import traceback
import abc
import time

from .request_and_response import AbstractRequest, AbstractResponse, ErrorResponse, CancelledResponse

class PoolFullException(Exception):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)

class AbstractSingleThreadExecutor(abc.ABC):
    """
    Abstract executor that runs computations in a single thread.
    Responses and results can be accessed from any thread.
    """
    # Logger for logging events
    logger: logging.Logger

    # Locks for thread-safe operations
    __lock_external: threading.Lock
    __lock_internal: threading.Lock
    __status_lock: threading.Lock

    # Attributes for storing the execution tokens
    __seed: bytes
    __itoken: int
    __strtoken: Optional[str]

    # External requests and responses
    __external_requests_to_cancel: list[str]
    __external_requests_queue_data: dict[str, AbstractRequest]
    __external_requests_queue: list[str]
    __external_responses: dict[str, AbstractResponse]
    __external_request_response_previous_action: dict[str, float] # keeps track of the lifecycle, and the keys of this dictionary serves as the set of tokens (UID)

    # Internal requests and responses
    __internal_requests_queue: list[str]
    __internal_requests_data: dict[str, AbstractRequest]
    __internal_responses: dict[str, AbstractResponse]

    # Control variables
    running: bool
    _thread: Optional[threading.Thread]
    loop_sleep: float
    old_cleanup_time: float
    internal_iter_count: int
    max_handle_requests_and_responses: int

    def __init__(
        self,
        logger: logging.Logger,
        loop_sleep: float = 0.1,
        old_cleanup_time: float = 300.0,
        max_handle_requests_and_responses: int = 1000
    ):
        """
        Initializes the executor.

        Args:
            logger (logging.Logger): Logger for logging events.
            loop_sleep (float): Time in seconds the thread sleeps between iterations.
            old_cleanup_time (float): Time in seconds to cleanup the response if idle for too long. Idle means the duration between the cleanup and end of processing response.
            max_handle_requests_and_responses (int): Maximum requests/responses to handle
        """
        self.logger = logger
        self.loop_sleep = loop_sleep
        self.old_cleanup_time = old_cleanup_time
        self.internal_iter_count = 0
        self.max_handle_requests_and_responses = max_handle_requests_and_responses

        # Initialize locks for thread safety
        self.__lock_external = threading.Lock()
        self.__lock_internal = threading.Lock()
        self.__status_lock = threading.Lock()

        # Initialize token generation attributes
        self.__seed = os.urandom(16)
        self.__itoken = 0
        self.__strtoken = None
        self.generate_next_token()

        # External requests and responses
        self.__external_requests_to_cancel = []
        self.__external_requests_queue_data = {}
        self.__external_requests_queue = []
        self.__external_responses = {}
        self.__external_request_response_previous_action = {}

        # Internal requests and responses
        self.__internal_requests_queue = []
        self.__internal_requests_data = {}
        self.__internal_responses = {}

        # Control variables
        self.running = False
        self._thread = None
    
    def _process_iteration(self):
        """
        Processes a single iteration of the executor loop.
        Handles moving requests, processing them, and handling responses.
        """
        self.internal_iter_count += 1

        # Move the requests to and from the internal and external queues
        self.__move_external_to_internal()
        self.__move_internal_to_external()

        # Handle cleanup
        if self.internal_iter_count % 10 == 0:
            self.cleanup_old_responses()

        # Handle cancellations
        self.__handle_cancellations()

        # Process internal requests
        with self.__lock_internal:
            # ok, now give the impl to handle all data at the same time
            queue_copy = self.__internal_requests_queue.copy() # shallow copy the data so the internal queue and data will only be handled by this class.
            data_copy = self.__internal_requests_data.copy()
            try:
                self._handle_all_requests(queue_copy, data_copy)
            except BaseException as e:
                self.logger.critical("Error occured in API implementation of _handle_all_requests! This may be irrecoverable! The loop is stopping...")
                self.logger.critical("\n".join(traceback.format_exception(e)))
                self.stop(await_thread_stop=False)
    
    def __move_external_to_internal(self):
        """
        Moves all external requests to the internal queue.
        Must be called from the executor thread.
        DO NOT use this in subclasses impl or externally!
        """
        # Copy over
        prev_external_requests: list[str]
        prev_external_data: dict[str, AbstractRequest] = {}
        with self.__lock_external:
            prev_external_requests = self.__external_requests_queue.copy()
            self.__external_requests_queue.clear()
            for token in prev_external_requests:
                prev_external_data[token] = self.__external_requests_queue_data.pop(token)
        
        # Ok, now add to internal
        with self.__lock_internal:
            for token in prev_external_requests:
                self.__internal_requests_queue.append(token)
                self.__internal_requests_data[token] = prev_external_data[token]

    def __move_internal_to_external(self):
        """
        Moves all internal responses to the external responses.
        Must be called from the executor thread.
        DO NOT use this in subclasses impl or externally!
        """
        responses: dict[str, AbstractResponse]
        with self.__lock_internal:
            responses = self.__internal_responses.copy()
            self.__internal_responses.clear()
        
        with self.__lock_external:
            ctime = time.time()
            for token in responses:
                response: AbstractResponse = responses[token]
                self.__external_responses[token] = response
                # update the time
                self.__external_request_response_previous_action[token] = ctime

    def __handle_cancellations(self):
        """
        Handles cancellation of requests marked for cancellation.
        DO NOT use this in subclasses impl or externally!
        """
        to_cancel: list[str]
        with self.__lock_external:
            to_cancel = self.__external_requests_to_cancel.copy()
            self.__external_requests_to_cancel.clear()

        if len(to_cancel) == 0:
            return
        
        with self.__lock_internal:
            for token in to_cancel:
                # If the request is still in the internal queue, remove it
                if token in self.__internal_requests_queue:
                    self.__internal_requests_queue.remove(token)
                    dat = self.__internal_requests_data.pop(token)
                    self._handle_request_cancel(token, dat) # Tell implementation to cleanup resources for the request if necessary
                    response = CancelledResponse()
                    response._set_static_state(dat._static_state)
                    self.__internal_responses[response] = response
        
        with self.__lock_external:
            ctime = time.time()
            for token in to_cancel:
                # If the request is still in the external queue, remove it
                if token in self.__external_requests_queue:
                    self.__external_requests_queue.remove(token)
                    dat = self.__external_requests_queue_data.pop(token)
                    response = CancelledResponse()
                    response._set_static_state(dat._static_state)
                    self.__external_responses[response] = response
                    # update the time
                    self.__external_request_response_previous_action[response.token] = ctime

    def get_logger(self) -> logging.Logger:
        """
        Retrieves the logger. ONLY use this in subclass impl!

        Returns:
            logging.Logger: The logger instance.
        """
        return self.logger
    
    def accept(self, token: str, response: AbstractResponse):
        """
        Accepts the request in handle_request. Note that this MUST be the last call.
        ONLY call this in the implementation of the handle_request branch in subclass.
        """
        if token not in self.__internal_requests_queue:
            raise ValueError("Cannot accept/reject the same token twice!")
        
        # remove from queue, and put the response
        self.__internal_requests_queue.remove(token)
        dat = self.__internal_requests_data.pop(token)
        self.__internal_responses[token] = response
        response._set_static_state(dat._static_state)
    
    def reject(self, token: str, error_reason: str):
        """
        Rejects the request in handle_request. Note that this MUST be the last call.
        ONLY call this in the implementation of the handle_request branch in subclass.
        """
        if token not in self.__internal_requests_queue:
            raise ValueError("Cannot accept/reject the same token twice!")
        
        # remove from queue, and put an error reason
        self.__internal_requests_queue.remove(token)
        dat = self.__internal_requests_data.pop(token)
        self.__internal_responses[token] = ErrorResponse(error_msg=error_reason)
        self.__internal_responses[token]._set_static_state(dat._static_state)

    @abc.abstractmethod
    def initialize(self) -> bool:
        """
        Initializes resources required by the executor.
        Must be implemented by subclasses, and DO NOT call this externally!

        Returns:
            bool: Whether the initialization was successful. If not, close it.
        """
        raise NotImplementedError("Must be implemented by subclasses!")

    @abc.abstractmethod
    def shutdown(self):
        """
        Cleans up resources used by the executor.
        Must be implemented by subclasses, and DO NOT call this externally!
        """
        raise NotImplementedError("Must be implemented by subclasses!")
    
    @abc.abstractmethod
    def _handle_all_requests(self, all_requests_queue: list[str], all_requests_data: dict[str, AbstractRequest]) -> None:
        """
        Abstract method to handle the processing of all the requests.
        Must be implemented by subclasses, and DO NOT call this externally!
        It is guaranteed that _handle_all_requests and _handle_request_cancel
        will be run in the same thread, and therefore not run at the
        same time to create race conditions.

        Also, the request queue and requests data here are shallow copies of the ones
        stored internally in the AbstractSingleThreadExecutor class. Therefore, modifying
        them won't affect the actual status. Use the .accept() and .reject() methods,
        which tells the executor to accept or reject the queue and data and internally
        changes the request to the response (or error response). 

        Since they are shallow copy, it is safe to loop through them even when some .accept()
        or .reject() are called, since the references are fixed. Modifying the contents of
        each individual AbstractRequest will indeed be permanent since deep copy isn't used.

        Args:
            all_requests_queue (str): The tokens in queue order preserved of all the requests.
            all_requests_data (dict[str, AbstractRequest]): The requests.

        Throws:
            Exception: CANNOT throw any exception. Implementations must catch all exceptions, and use the
                       self.reject(...) when on the request when there is an error.
        """
        raise NotImplementedError("Must be implemented by subclasses!")
    
    @abc.abstractmethod
    def _handle_request_cancel(self, token: str, request: AbstractRequest) -> None:
        """
        Abstract method to handle the cancellation of a request.
        Must be implemented by subclasses, and DO NOT call this externally!
        It is guaranteed that _handle_all_requests and _handle_request_cancel
        will be run in the same thread, and therefore not run at the
        same time to create race conditions.

        Args:
            token (str): The token of the request.
            request (AbstractRequest): The request to that is to be cancelled.
        """
        raise NotImplementedError("Must be implemented by subclasses!")

    def start(self, wait_for_init_complete: bool=True) -> Optional[bool]:
        """
        Starts the executor thread.
        Can be called from any thread.

        Returns:
            bool: Whether the initialization was successful. Only returns that for blocking call.
        """
        with self.__status_lock:
            if not self.running:
                tmp_lock = threading.Lock()

                self.running = True
                self._thread = threading.Thread(target=executor_thread_runner, args=(self, tmp_lock))
                self._thread.start()
                self.logger.info("Executor thread started.")

                if wait_for_init_complete:
                    time.sleep(0.1)
                    tmp_lock.acquire(blocking=True)
                    tmp_lock.release()
                    return self.running
        
        return None

    def stop(self, await_thread_stop: bool = True):
        """
        Stops the executor thread gracefully.
        Can be called from any thread.

        Args:
            await_thread_stop (bool): If True, waits for the thread to finish.
        """
        with self.__status_lock:
            if self.running:
                self.running = False
                self.logger.info("Stopping executor thread.")
                if await_thread_stop and self._thread is not None:
                    self._thread.join()
                    self.logger.info("Executor thread stopped.")

    def poll_response(self, tok: str) -> Optional[AbstractResponse]:
        """
        Retrieves the response for a given token if available.

        Args:
            tok (str): The token of the request.

        Returns:
            Optional[AbstractResponse]: The response if available, else None.
        """
        with self.__lock_external:
            if tok not in self.__external_request_response_previous_action:
                return ErrorResponse("Invalid token! Tokens must be obtained via queue_request!")
            response = self.__external_responses.pop(tok, None)
            if response is not None: # If found, remove the token from the lifecycle
                self.__external_request_response_previous_action.pop(tok)
            return response
    
    def generate_next_token(self):
        """
        Generates a unique token for each request. Used internally - do not call this, even for subclasses!
        """
        self.__itoken += 1
        if self.__strtoken is None:
            self.__strtoken = hashlib.sha256(self.__itoken.to_bytes(16, byteorder="big", signed=True) + self.__seed).hexdigest()
        else:
            ntoken = None
            while ntoken is None or (ntoken in self.__external_request_response_previous_action):
                ptoken = self.__strtoken.encode() if (ntoken is None) else ntoken.encode()
                ntoken = hashlib.sha256(ptoken + self.__itoken.to_bytes(16, byteorder="big", signed=True) + self.__seed).hexdigest()
            self.__strtoken = ntoken

    def queue_request(self, x: AbstractRequest) -> str:
        """
        Queues a new request for execution.

        Args:
            x (AbstractRequest): The request to queue.

        Returns:
            str: The token assigned to the request.
        
        Raises:
            ValueError: If the handling of requests and responses pool is already full.
        """
        with self.__lock_external:
            if len(self.__external_request_response_previous_action) >= self.max_handle_requests_and_responses:
                raise PoolFullException("Handling of requests/responses already full! Use cleanup_old_responses to cleanup the responses being processed.")

            token = self.__strtoken
            self.__external_requests_queue.append(token)
            self.__external_requests_queue_data[token] = x
            self.__external_request_response_previous_action[token] = time.time()
            self.generate_next_token()
            return token
    
    def cleanup_old_responses(self, time_override: Optional[float]=None):
        """
        Handles cleanup of external responses, due to expiration. Can be called in any thread.

        Args:
            time_override (Optional[float]): Override the time of being too old, if necessary.
        """
        cleanup_time: float = self.old_cleanup_time if time_override is None else time_override
        with self.__lock_external:
            ctime = time.time()
            ext_keys = set(self.__external_responses.keys())
            for token in ext_keys:
                prev_time: float = self.__external_request_response_previous_action[token]
                if (ctime - prev_time) > cleanup_time: # ok, cleanup now
                    self.logger.debug("Cleaned up token {}".format(token))
                    self.__external_request_response_previous_action.pop(token)
                    self.__external_responses.pop(token)

    def is_running(self) -> bool:
        """
        Checks if the executor is running. Can be called in any thread.

        Returns:
            bool: True if running, False otherwise.
        """
        with self.__status_lock:
            return self.running

    def cancel_request(self, tok: str) -> None:
        """
        Cancels a request identified by the token. Can be called in any thread.

        Args:
            tok (str): The token of the request to cancel.
        """
        with self.__lock_external:
            self.__external_requests_to_cancel.append(tok)

def executor_thread_runner(executor: AbstractSingleThreadExecutor, init_complete_lock: threading.Lock):
    """
    The main loop that runs in the executor thread.
    It initializes the executor, then continuously processes requests until stopped.
    """
    try:
        success: bool = False
        with init_complete_lock:
            success = executor.initialize()
        if not success:
            executor.running = False
        while executor.running:
            start_time = time.time()
            try:
                executor._process_iteration()
            except Exception as e:
                executor.logger.error(f"Error during executor iteration: {e}")
                executor.logger.error(traceback.format_exc())
            elapsed = time.time() - start_time
            sleep_time = max(executor.loop_sleep - elapsed, 0)
            if sleep_time > 0:
                time.sleep(sleep_time)
    finally:
        try:
            executor.shutdown()
        except Exception as e:
            executor.logger.error(f"Error during executor shutdown: {e}")
            executor.logger.debug(traceback.format_exc())