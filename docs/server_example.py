import sys
sys.path.append("../src")
import logging
import socket
import ssl
from typing import Union

import BottleneckedHTTPAPI.http_server as http_server

if __name__ == "__main__":
    # initialize logger to console
    logger = logging.getLogger("http_server")
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    logger.addHandler(console_handler)

    # setup server
    host = "127.0.0.1"
    port = 8080
    server = http_server.ThreadedHTTPServer(
        host=host,
        port=port,
        logger=logger,
        timeout=5.0
    )
    server.set_security_parameters() # no TLS, but can be added if needed

    # setup routes. each function takes in [HttpRequest, Union[socket, ssl.SSLSocket]] and returns None
    @server.route("/hello")
    def hello(request: http_server.HttpRequest, sock: Union[socket.socket, ssl.SSLSocket]) -> None:
        print("Received a hello request!", sock)
        http_server.send_http_response(sock, 200, {
            "Content-Type": "text/plain"
        }, b"Hello, World!")
    
    @server.route("/bye")
    def bye(request: http_server.HttpRequest, sock: Union[socket.socket, ssl.SSLSocket]) -> None:
        print("Received a bye request!")
        http_server.send_http_response(sock, 200, {
            "Content-Type": "text/plain"
        }, b"Goodbye, World!")

    @server.route("/ping")
    def ping(request: http_server.HttpRequest, sock: Union[socket.socket, ssl.SSLSocket]) -> None:
        print("Received a ping request!")
        response = request.body if request.body is not None else b"Pong!"
        http_server.send_http_response(sock, 200, {
            "Content-Type": "text/plain"
        }, response)

    # start server
    server.run(allow_reuse=True)