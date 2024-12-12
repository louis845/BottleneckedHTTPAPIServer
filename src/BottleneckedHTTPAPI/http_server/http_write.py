import socket
import ssl
from typing import Union, Optional

# Mapping of standard HTTP status codes to reason phrases
STATUS_CODES: dict[int, str] = {
    100: "Continue",
    101: "Switching Protocols",
    102: "Processing",
    200: "OK",
    201: "Created",
    202: "Accepted",
    203: "Non-Authoritative Information",
    204: "No Content",
    205: "Reset Content",
    206: "Partial Content",
    207: "Multi-Status",
    208: "Already Reported",
    226: "IM Used",
    300: "Multiple Choices",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    305: "Use Proxy",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Payload Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    416: "Range Not Satisfiable",
    417: "Expectation Failed",
    418: "I'm a teapot",
    421: "Misdirected Request",
    422: "Unprocessable Content",
    423: "Locked",
    424: "Failed Dependency",
    426: "Upgrade Required",
    428: "Precondition Required",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    451: "Unavailable For Legal Reasons",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "HTTP Version Not Supported",
    506: "Variant Also Negotiates",
    507: "Insufficient Storage",
    508: "Loop Detected",
    510: "Not Extended",
    511: "Network Authentication Required",
}

def send_http_response(
    sock: Union[socket.socket, ssl.SSLSocket],
    status_code: int,
    headers: dict[str, str],
    body: Optional[Union[str, bytes]] = None
) -> None:
    """
    Constructs and sends an HTTP/1.1 response over the provided socket.

    Args:
        sock (Union[socket.socket, ssl.SSLSocket]): The socket to send the response through.
        status_code (int): The HTTP status code (e.g., 200, 404).
        headers (dict[str, str]): A dictionary of HTTP headers.
        body (Optional[bytes]): The response body as bytes. Defaults to None.
    """
    if status_code not in STATUS_CODES:
        raise ValueError(f"Invalid status code: {status_code}")

    # Start with the status line
    reason_phrase = STATUS_CODES[status_code]
    status_line = f"HTTP/1.1 {status_code} {reason_phrase}\r\n"

    # Ensure headers keys are case-insensitive
    headers_lower = {k.lower(): v for k, v in headers.items()}

    # If a body is present, set the Content-Length header
    if body is not None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        headers_lower['content-length'] = str(len(body))
    else:
        # If no body, Content-Length should be 0 for certain methods
        headers_lower['content-length'] = '0'

    # Ensure the Connection header is set to keep the connection alive by default
    if 'connection' not in headers_lower:
        headers_lower['connection'] = 'keep-alive'

    # Construct the headers section
    headers_section = ""
    for key, value in headers_lower.items():
        # Capitalize header keys for standard formatting
        header_key = '-'.join([word.capitalize() for word in key.split('-')])
        headers_section += f"{header_key}: {value}\r\n"

    # End headers with an additional CRLF
    headers_section += "\r\n"

    # Combine status line and headers
    response = status_line + headers_section
    response_bytes = response.encode('iso-8859-1')

    sock.sendall(response_bytes)

    # Append body if present
    if body:
        sock.sendall(body)