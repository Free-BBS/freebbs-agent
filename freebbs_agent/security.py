from ipaddress import ip_address

from flask import jsonify, request


def is_loopback_addr(value: str | None) -> bool:
    if not value:
        return False

    try:
        return ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


def reject_non_loopback_requests():
    if is_loopback_addr(request.remote_addr):
        return None

    return jsonify({"error": {"code": "forbidden", "message": "loopback access only"}}), 403


def add_local_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin.startswith("http://127.0.0.1:") or origin == "http://127.0.0.1":
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response
