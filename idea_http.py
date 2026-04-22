#!/usr/bin/env python3

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = os.environ.get("IDEA_API_BASE", "http://localhost:63344")


def build_url(endpoint: str, project_path: str | None = None) -> str:
    if project_path is None:
        project_path = os.environ.get("IDEA_PROJECT_PATH")
    query = ""
    if project_path:
        query = "?" + urllib.parse.urlencode({"path": project_path})
    return f"{BASE_URL}{endpoint}{query}"


def request_json(
    method: str,
    endpoint: str,
    payload: dict | None = None,
    *,
    project_path: str | None = None,
):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        build_url(endpoint, project_path=project_path),
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        if detail:
            raise RuntimeError(detail) from exc
        raise RuntimeError(str(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def print_json(value) -> None:
    json.dump(value, sys.stdout, indent=4)
    sys.stdout.write("\n")
