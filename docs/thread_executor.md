# Thread Executor API

A robust and thread-safe Python framework for executing computations within a single dedicated thread. This executor allows external threads to queue computation requests and retrieve results seamlessly, ensuring that all processing occurs in a controlled, single-threaded environment. To import, use

```python
import BottleneckedHTTPAPI.thread_executor
```

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
  - [Overview](#overview)
  - [Creating Custom Requests](#creating-custom-requests)
  - [Implementing a Concrete Executor](#implementing-a-concrete-executor)
  - [Running the Executor](#running-the-executor)
- [Router](#router)

## Features

- **Single-Threaded Execution**: All computations are handled within a single dedicated thread, ensuring deterministic behavior and avoiding race conditions.
- **Thread-Safe API**: External threads can safely queue requests and poll for responses without worrying about concurrency issues.
- **Flexible Request Handling**: Easily extendable to handle various types of compute requests by subclassing.
- **Graceful Shutdown**: Supports graceful stopping of the executor thread, ensuring all resources are properly released.
- **Comprehensive Logging**: Integrated logging for monitoring and debugging purposes.

## Usage

### Overview

The executor framework consists of two main components:

1. **Request and Response Classes**: Define the structure of computation requests and their corresponding responses.
2. **Abstract Executor**: Manages the lifecycle of requests, ensuring they are processed in a single thread and results are accessible externally.

### Creating Custom Requests and Responses

To define a specific computation, subclass the `AbstractRequest` class and implement the `execute` method.

```python
from abstract_executor.request_and_response import AbstractRequest, AbstractResponse

class ConcreteRequest(AbstractRequest):
    """
    A concrete implementation of AbstractRequest that stores data.
    """

    data: int

    def __init__(self, data: int):
        super().__init__()

class ConcreteResponse(AbstractResponse):
    """
    A concrete implementation of AbstractResponse that stores data.
    """
    data: int

    def __init__(self, token: str, data: int):
        super().__init__(token)
        self.data = data
```

### Implementing a Concrete Executor

Subclass the `AbstractSingleThreadExecutor` and implement the `handle_request` method to define how each request is processed.

```python
# concrete_executor.py

from abstract_executor.abstract_executor import AbstractSingleThreadExecutor
from abstract_executor.request_and_response import AbstractRequest
import logging

class ConcreteExecutor(AbstractSingleThreadExecutor):
    """
    A concrete executor that processes ConcreteRequest instances.
    """

    def _handle_all_requests(self, all_requests_queue: list[str], dat: dict[str, AbstractRequest]) -> None:
        """
        Processes all concrete requests

        Args:
            request (AbstractRequest): The request to process.

        Returns:
            bool: Whether to keep looping through all the requests in the current iteration.
        """
        all_requests_data: dict[str, ConcreteRequest] = dat
        for token in all_requests_queue: # loop according to the queue FIFO
            request = all_requests_data[token]

            # accept the request if successful
            self.accept(token, ConcreteResponse(token, request.data * 2))

            # reject the request if not successful (note: accept/reject can only be called once on the same token)
            self.reject(token, "Some error happened!")

            # otherwise, its possible to not accept or reject if still waiting or undetermined
    
    def _handle_request_cancel(self, token: str, req: AbstractRequest) -> None:
        """
        Handles the cancellation of a concrete request, that is cancelled
        via cancel_request.
        """
        request: ConcreteRequest = req
        # some logic to cleanup if necessary
```

### Running the Executor

Here's how you can utilize the executor to process requests and retrieve results.

```python
import logging
import time
from concrete_executor import ConcreteExecutor
from concrete_request_and_response import ConcreteRequest, ConcreteResponse

# Setup logger
logger = logging.getLogger("ConcreteExecutor")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(levelname)s] %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Initialize executor
executor = ConcreteExecutor(logger=logger, loop_sleep=0.5)
executor.start()

# Queue some requests
stored_tokens = []
for i in range(5):
    req = ConcreteRequest(data=i)
    token = executor.queue_request(req)
    logger.info(f"Queued request {token} with data {i}.")
    stored_tokens.append(token)

# Allow some time for processing
time.sleep(3)

# Get the response
for token in stored_tokens:
    response = executor.poll_response(token)
    if response:
        if response.has_error(): # Class is either ErrorResponse or CancelledResponse
            # optionally check is_cancelled() to specifically see if the error is due to cancellation or others
            logger.error(f"Request {token} failed with error: {response.get_error_msg()}")
        else: # Class is ConcreteResponse
            logger.info(f"Request {token} completed with result: {response.data}")

# Stop the executor
executor.stop()
```

## Router
The **`SingleThreadExecutorRouterWrapper`** class is a straightforward class that handles the routing of different inputs into different specialized stateless functions.

```python
from BottleneckedHTTPAPI.thread_executor import SingleThreadExecutorRouterWrapper

# init
executor = ...
wrapper = SingleThreadExecutorRouterWrapper(executor)

# define and register functions
def func1(x: int, y: float, data: int) -> ConcreteRequest:
    ...
    return request, {"sum": x + y, "diff": x - y}

def func1_postprocess(response: ConcreteResponse, static_info: dict[str, float]):
    isum: float = static_info["sum"]
    idiff: float = static_info["diff"]
    response.result_str = str(response.data * isum * idiff)
    ...

wrapper.register_processor_pair(["normal"], func1, func1_postprocess)

def func2(rep: int, s: str, data: int) -> ConcreteRequest:
    ...
    return request, {"rep": rep, "s": s}

def func2_postprocess(response: ConcreteResponse, static_info: dict[str, float]):
    rep: int = static_info["rep"]
    s: str = static_info["s"]
    response.result_str = str(response.data) + s.repeat(rep)
    ...

wrapper.register_processor_pair(["repeats"], func2, func2_postprocess)

# Queue some requests
stored_tokens = []
stored_tokens.append(wrapper.queue_request(["normal"], x=3, y=0.4, data=2))
stored_tokens.append(wrapper.queue_request(["repeats"], data=2, rep=3, s="abc"))

# Allow some time for processing
time.sleep(5.0)

# Get the response
for token in stored_tokens:
    response = wrapper.poll_response(token)
    if response:
        if response.has_error(): # Class is either ErrorResponse or CancelledResponse
            # optionally check is_cancelled() to specifically see if the error is due to cancellation or others
            logger.error(f"Request {token} failed with error: {response.get_error_msg()}")
        else: # Class is ConcreteResponse
            logger.info(f"Request {token} completed with result: {response.result_str}")

# Stop the executor
executor.stop()
```

To let the router manage and route not only the functions, but also choose from different executors, it is possible to pass a dictionary of `dict[str, AbstractSingleThreadExecutor]` to the constructor, and an additional argument **`executor_tag`** in the **`register_processor_pair`** function, corresponding to the key for the executor in the dictionary. The router will automatically manage the routing to the correct executor, and use a composite token to represent and ensure the token is unique across different executors.