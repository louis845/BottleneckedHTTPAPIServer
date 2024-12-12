from typing import Optional, Union
import socket
import ssl
import traceback

class HttpRequest:
    """
    Represents an HTTP/1.1 request.

    Attributes:
        method (str): HTTP method (e.g., GET, POST).
        path (str): Request path.
        version (str): HTTP version (should be 'HTTP/1.1').
        headers (Dict[str, str]): Dictionary of HTTP headers.
        body (bytes): Request body.
        _error (Optional[str]): Error message if parsing failed.
    """
    method: Optional[str]
    path: Optional[str]
    version: Optional[str]
    headers: Optional[dict[str, str]] # header keys are translated to lowercase
    body: Optional[bytes]
    _error: Optional[str]
    
    def __init__(self):
        self.method = None
        self.path = None
        self.version = None
        self.headers = None
        self.body = None
        self._error = None

    def has_error(self) -> bool:
        """Check if there was an error during parsing."""
        return self._error is not None

    def error_msg(self) -> Optional[str]:
        """Get the error message if there was an error."""
        return self._error

    def get_method(self) -> Optional[str]:
        """Get the HTTP method."""
        if self.has_error():
            return None
        return self.method

    def get_path(self) -> Optional[str]:
        """Get the request path."""
        if self.has_error():
            return None
        return self.path

    def get_version(self) -> Optional[str]:
        """Get the HTTP version."""
        if self.has_error():
            return None
        return self.version

    def get_headers(self) -> Optional[dict[str, str]]:
        """Get the HTTP headers."""
        if self.has_error():
            return None
        return self.headers

    def get_header(self, key: str) -> Optional[str]:
        """Get a specific HTTP header."""
        if self.has_error() or self.headers is None:
            return None
        if key.lower() not in self.headers:
            return None
        return self.headers.get(key.lower())

    def get_body(self) -> Optional[bytes]:
        """Get the request body."""
        if self.has_error():
            return None
        return self.body
    
    def closing_requested(self) -> Optional[bool]:
        if self.has_error():
            return None
        connection = self.get_header("connection")
        if connection is None:
            return False
        return connection.lower() == "close"

def parse_http_request(sock: Union[socket.socket, ssl.SSLSocket],
                       max_reads: int,
                       max_content_length: int) -> Optional[HttpRequest]:
    """
    Parse an HTTP/1.1 request from the given socket, and read whatever content is available.

    Args:
        sock (socket.socket): The TCP or TLS socket to read from.
        max_reads (int): The maximum number of times to read from the socket.
        max_content_length (int): The maximum allowed length of the request body, in bytes (Content-Length header).

    Returns:
        Optional[HttpRequest]: An HttpRequest object if a request is successfully parsed,
                            None if no data is available yet (timeout on first read),
                            or an HttpRequest object with an error message if parsing failed.
    """
    BUFFER_SIZE = 4096  # Number of bytes to read at once
    HEADER_TERMINATOR = b'\r\n\r\n'
    buffer = bytearray()
    request = HttpRequest()
    reads = 0
    try:
        # Read until we have headers terminated by CRLF CRLF
        while HEADER_TERMINATOR not in buffer:
            try:
                chunk = sock.recv(BUFFER_SIZE)
                if not chunk:
                    # Connection closed by client
                    if reads == 0:
                        return None
                    else:
                        request._error = "Connection closed by client before completing the request."
                        return request
                buffer.extend(chunk)
            except socket.timeout:
                if reads == 0:
                    # Timeout on first read means no data available yet
                    return None
                else:
                    # Timeout during reading headers
                    request._error = "Timeout occurred while reading the HTTP request headers."
                    return request
            
            reads += 1
            if (reads >= max_reads) and (HEADER_TERMINATOR not in buffer): # If max reads reached and headers not ended, return error
                request._error = "Maximum number of reads reached before completing the request."
                return request

        # Split headers and remaining buffer
        header_end = buffer.index(HEADER_TERMINATOR) + len(HEADER_TERMINATOR)
        header_bytes = buffer[:header_end]
        remaining = buffer[header_end:]

        # Decode headers
        try:
            header_text = header_bytes.decode('iso-8859-1')
        except UnicodeDecodeError:
            request._error = "Failed to decode HTTP headers."
            return request

        # Split request into lines
        lines = header_text.split("\r\n")
        if len(lines) < 1:
            request._error = "Empty HTTP request."
            return request

        # Parse request line
        request_line = lines[0]
        parts = request_line.split()
        if len(parts) != 3:
            request._error = "Invalid HTTP request line."
            return request
        method, path, version = parts
        request.method = method
        request.path = path
        request.version = version

        # Validate HTTP version
        if version != "HTTP/1.1":
            request._error = f"Unsupported HTTP version: {version}."
            return request

        # Parse headers
        headers = {}
        for header_line in lines[1:]:
            if header_line == '':
                continue  # Skip empty lines (shouldn't be any before HEADER_TERMINATOR)
            if ':' not in header_line:
                request._error = f"Invalid header format: '{header_line}'."
                return request
            key, value = header_line.split(':', 1)
            headers[key.strip().lower()] = value.strip()
        request.headers = headers

        # Determine if there is a body
        content_length = headers.get('content-length')
        if content_length is not None:
            try:
                body_length = int(content_length)
                if body_length < 0:
                    raise ValueError
            except ValueError:
                request._error = "Invalid Content-Length header."
                return request
            if body_length > max_content_length:
                request._error = "Request body too large."
                return request

            # Read the body from the remaining buffer, and the socket if necessary
            body = remaining
            bytes_needed = body_length - len(body)
            while bytes_needed > 0:
                try:
                    chunk = sock.recv(min(BUFFER_SIZE, bytes_needed))
                    if not chunk:
                        request._error = "Connection closed by client while reading the body."
                        return request
                    body.extend(chunk)
                    bytes_needed -= len(chunk)
                except socket.timeout:
                    request._error = "Timeout occurred while reading the HTTP request body."
                    return request
                reads += 1
                if (reads >= max_reads) and (bytes_needed > 0): # If max reads reached and body not complete, return error
                    request._error = "Maximum number of reads reached before completing the request body."
                    return request

            request.body = bytes(body[:body_length])
        else:
            # No body; ensure that methods that require a body have Content-Length
            methods_with_body = {'POST', 'PUT', 'PATCH', 'DELETE'}
            if request.method.upper() in methods_with_body:
                request._error = "Missing Content-Length header for request with a body."
                return request
            request.body = b''

        return request

    except Exception as e:
        # Catch all unexpected exceptions and store traceback
        request._error = ''.join(traceback.format_exception_only(type(e), e)).strip()
        return request