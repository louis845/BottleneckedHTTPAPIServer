import socket
import ssl
import threading
import logging
import traceback
import os
from typing import Optional

from . import http_parse
from . import http_write

class _ThreadFlags:
    """Keep track of the state of a client thread."""
    __EXIT_REASON_DEFAULT = "Unset"
    address: tuple[str, int]
    exit_reason: str
    stop_flag: bool

    def __init__(self, address: tuple[str, int]) -> None:
        self.exit_reason = _ThreadFlags.__EXIT_REASON_DEFAULT
        self.address = address
        self.stop_flag = False

class ThreadedHTTPServer:
    """Threaded HTTP server implementation."""
    SERVER_RUNNING: bool
    security_params_set: bool
    context: Optional[ssl.SSLContext]
    routes: dict[str, callable]

    host: str
    port: int
    logger: logging.Logger
    timeout: float
    max_recv_calls_per_request: int
    max_content_length: int
    
    def __init__(self,
                 host: str, port: int,
                 logger: logging.Logger,
                 timeout: float=5.0,
                 max_recv_calls_per_request: int=1024,
                 max_content_length: int=512 * 1024 * 1024) -> None:
        """
        Initialize the API server with the given host and port.

        :param host: The host to bind the server to.
        :param port: The port to bind the server to.
        :param logger: Logger to use for logging.
        :param timeout: Timeout for socket operations. Default is 5 seconds.
        :param max_recv_calls_per_request: Maximum number of recv calls to make for a single request. Default is 1024, correpsonding to 4MB (4096 bytes * 1024).
        :param max_content_length: Maximum allowed length of the request body, in bytes. Default is 512MB.
        """
        self.SERVER_RUNNING = False
        self.security_params_set = False
        self.context = None
        self.routes = {}

        self.host = host
        self.port = port
        self.logger = logger
        self.timeout = timeout
        self.max_recv_calls_per_request = max_recv_calls_per_request
        self.max_content_length = max_content_length
    
    def set_security_parameters(
        self,
        certfile: Optional[str] = None,
        keyfile: Optional[str] = None,
        cafile: Optional[str] = None
    ) -> None:
        """
        Set up TLS parameters. This should be called before starting the server.

        :param certfile: The path to the server certificate file.
        :param keyfile: The path to the server private key file.
        :param cafile: The path to the CA certificate file.
        """
        # check values
        if self.security_params_set:
            raise RuntimeError("Connection security parameters can only be set once.")
        if (certfile is None) != (keyfile is None):
            raise ValueError("certfile and keyfile must both be provided or both be None.")
        if cafile is not None and certfile is None:
            raise ValueError("cafile can only be provided if certfile and keyfile are provided.\nThis means client authentication is enabled only if the server is able to present a certificate.")
        
        # check file paths
        if certfile and not (os.path.exists(certfile) and os.access(certfile, os.R_OK)):
            raise FileNotFoundError(f"Certificate file {certfile} does not exist or is not readable.")
        if keyfile and not (os.path.exists(keyfile) and os.access(keyfile, os.R_OK)):
            raise FileNotFoundError(f"Key file {keyfile} does not exist or is not readable.")
        if cafile and not (os.path.exists(cafile) and os.access(cafile, os.R_OK)):
            raise FileNotFoundError(f"CA file {cafile} does not exist or is not readable.")
        
        # create SSL context if necessary
        requireTLS = certfile is not None
        if requireTLS:
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.load_cert_chain(certfile=certfile, keyfile=keyfile) # add the parameters so the server can present itself to the client
            if cafile:
                self.context.load_verify_locations(cafile=cafile) # add the CA file so the server can verify the client
                self.context.verify_mode = ssl.CERT_REQUIRED # require the client to present a certificate
            
            self.context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_2 | ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3 # disable older protocols
        else:
            self.context = None
        self.security_params_set = True
    
    def route(self, path: str) -> None:
        """
        Decorator to route a function to a specific path. The routes should
        be initialized before starting the server, and cannot be changed.
        

        :param path: The path to route the function to.
        """
        if self.SERVER_RUNNING:
            raise ValueError("Cannot add routes while the server is running.")
        def decorator(func):
            self.routes[path] = func
            return func
        return decorator

    def __run_impl(self, server_socket: socket.socket) -> None:
        """
        Run in same thread as .run(). This is the main server loop.
        """
        self.SERVER_RUNNING = True
        client_threads: list[tuple[threading.Thread, _ThreadFlags]] = []
        try:
            while self.SERVER_RUNNING:
                # remove the finished threads
                idx = 0
                while idx < len(client_threads):
                    if not client_threads[idx][0].is_alive():
                        reason = client_threads[idx][1]
                        client_threads.pop(idx)
                        self.logger.debug("Client thread for {}:{} finished. Reason: {}".format(reason.address[0], reason.address[1], reason.exit_reason))
                    else:
                        idx += 1 # go next if its alive
                
                # accept a new connection
                try:
                    client_socket, addr = server_socket.accept()
                except socket.timeout:
                    continue
                
                self.logger.debug("Accepted connection from {}:{}".format(addr[0], addr[1]))
                client_socket.settimeout(self.timeout) # set the timeout for the client socket
                if self.context is not None: # wrap the socket in an SSL context, if necessary
                    try:
                        client_socket = self.context.wrap_socket(client_socket, server_side=True)
                    except ssl.SSLError as e: # handle SSL errors, and close and skip the connection
                        self.logger.error("Error setting up TLS connection from {}:{}".format(addr[0], addr[1]))
                        self.logger.error(traceback.format_exc())
                        client_socket.close() # close the socket
                        continue # skip the connection
                    except socket.timeout: # handle timeouts, and close and skip the connection
                        self.logger.error("Timeout setting up TLS connection from {}:{}".format(addr[0], addr[1]))
                        client_socket.close() # close the socket
                        continue
                
                # all set, handle the client in a new thread
                thread_flags = _ThreadFlags(addr)
                thrd = threading.Thread(target=self.__handle_connection, args=(client_socket, addr, self, thread_flags))
                thrd.start()
                client_threads.append((thrd, thread_flags))
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received. Shutting down server.")
        except Exception as e:
            self.logger.error("Unexpected error in server loop.")
            self.logger.error(traceback.format_exc())
        finally:
            self.SERVER_RUNNING = False
            try:
                server_socket.close() # close the server socket
            except Exception:
                self.logger.error("Error closing server socket.")
                self.logger.error(traceback.format_exc())
        
        self.logger.info("Waiting for all client threads to finish...")
        self.logger.info("Remaining client threads: {}".format(len(client_threads)))
        for thrd, reason in client_threads:
            reason.stop_flag = True # signal the threads to stop
        for thrd, reason in client_threads:
            thrd.join()
        self.logger.info("All client threads finished. Server shutdown complete.")
    
    def __handle_connection(self, client_socket: socket.socket, addr: tuple[str, int], server: 'ThreadedHTTPServer', flags: _ThreadFlags) -> None:
        """
        Run in a separate thread to handle a client connection.
        """
        try:
            # read the request
            request: Optional[http_parse.HttpRequest] = http_parse.parse_http_request(client_socket, self.max_recv_calls_per_request, self.max_content_length)
            if request is None:
                flags.exit_reason = "Bad request."
                try:
                    http_write.send_http_response(client_socket, 400, {}, "Bad Request")
                except Exception:
                    pass
                return # no data available yet, return
            if request.has_error():
                flags.exit_reason = "Error parsing request. Error: {}".format(request.error_msg())
                try:
                    http_write.send_http_response(client_socket, 500, {}, "Internal Server Error")
                except Exception:
                    pass
                return # error parsing request, return
            
            # get the path
            path = request.get_path()
            if path is None:
                flags.exit_reason = "No path in request."
                try:
                    http_write.send_http_response(client_socket, 400, {}, "Bad Request")
                except Exception:
                    pass
                return
            
            # get the function
            func = server.routes.get(path, None)
            if func is None:
                flags.exit_reason = "Path not found."
                try:
                    http_write.send_http_response(client_socket, 404, {}, "Not Found")
                except Exception as e:
                    pass
                return
            
            # call the function, let the function handle the HTTP response
            try:
                func(request, client_socket)
                flags.exit_reason = "All okay."
            except Exception as e:
                flags.exit_reason = "Error calling function."
                self.logger.debug("Error calling function for path {}: {}".format(path, e))
                self.logger.debug("\n".join(traceback.format_exception(type(e), e, e.__traceback__)))
                try:
                    http_write.send_http_response(client_socket, 500, {}, "Internal Server Error")
                except Exception:
                    pass
                return # error calling function, return
            
        except Exception as e:
            flags.exit_reason = "Unexpected error."
            server.logger.error("Unexpected error in client thread.")
            server.logger.error(traceback.format_exc())
        finally:
            try:
                client_socket.close() # close the client socket
            except Exception:
                pass

    def run(self, allow_reuse: bool=False) -> None:
        """
        Start the API server to accept connections. A blocking call, doesn't return until the server is stopped (Ctrl+C).
        Doesn't start a new thread, so it should be called in a separate thread if necessary.
        """
        if not self.security_params_set:
            raise RuntimeError("Connection security parameters must be set before starting the server.")
        self.SERVER_RUNNING = True

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            if allow_reuse:
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port)) # bind to the host and port
            server_socket.listen(5) # allow up to 5 connections in the queue
            server_socket.settimeout(0.5) # set a timeout for the accept call to 0.5 seconds
            if self.logger is not None:
                self.logger.info(f"Server listening on {self.host}:{self.port} {'with TLS' if (self.context is not None) else 'without TLS'}")
            
            # loop to accept connections
            self.__run_impl(server_socket)