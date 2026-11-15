"""The browser's label: the cookie `senda_client`, a random UUID the server hands out. It keeps chats and plans apart."""

from __future__ import annotations

import uuid

from fastapi import Request, Response

COOKIE = "senda_client"
YEAR_S = 365 * 24 * 3600


def uuid_of(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def client_of(request: Request, response: Response) -> uuid.UUID:
    """The label of this browser; a new one is set on `response` when the browser has none."""
    found = uuid_of(request.cookies.get(COOKIE, ""))
    if found is not None:
        return found
    label = uuid.uuid4()
    response.set_cookie(COOKIE, str(label), max_age=YEAR_S, path="/api", httponly=True, samesite="lax")
    return label


def carry(response: Response, answer: Response) -> Response:
    """Copy the cookie a dependency set to a response the route built itself."""
    for cookie in response.headers.getlist("set-cookie"):
        answer.headers.append("set-cookie", cookie)
    return answer
