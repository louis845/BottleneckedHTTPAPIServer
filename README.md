# Bottlenecked HTTP Server

This Python package contains utility functions to create a HTTP server that runs computations bottlenecked by a single (separate) thread, or multiple threads. It supports polling for responses and so on, and is quite lightweight without many complex features therefore making it fast to use and unnecessary to setup complex things.

The following modules are imported independently from each other:

## BottleneckedHTTPAPI.thread_executor
See [docs/thread_executor.md](docs/thread_executor.md)

## BottleneckedHTTPAPI.http_server
See [docs/http_server.md](docs/http_server.md)

## Installation

To integrate the BottleneckedHTTPAPI into your project, install it via pip install.

```bash
pip install /path/to/BottleneckedHTTPAPI.tgz
```

Alternatively, use setup.py to install it.

*Note: Ensure you have Python 3.10 or higher installed. No special packages required.*