from urllib.parse import urlparse
import requests
import hashlib
import json

from typing import Callable
from datetime import datetime

from apiclient import APIClient
from apiclient.request_strategies import RequestStrategy
from apiclient.response import Response
from apiclient.utils.typing import OptionalDict
from loguru import logger as log

from util import get_session_config
from urllib.parse import urlencode
from models.dynamicrule import DynamicRule

USE_DYNAMIC = True


def _get_api_headers() -> dict[str, str]:
    session_vars = get_session_config()
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "app-token": "33d57ade8c02dbc5a333db99ff9ae26a",
        "User-Agent": session_vars["USER_AGENT"],
        "x-bc": str(session_vars["X_BC"]),
        "user-id": str(session_vars["USER_ID"]),
        "Cookie": f"auth_id={str(session_vars['USER_ID'])}; sess={session_vars['SESS_COOKIE']}",
    }


def _get_dynamic_rules() -> DynamicRule:
    log.info("Fetching dynamic rules..")
    if USE_DYNAMIC:
        DYNAMIC_RULE_URL = "https://raw.githubusercontent.com/DATAHOARDERS/dynamic-rules/main/onlyfans.json"
        result = requests.get(DYNAMIC_RULE_URL).json()
    else:
        with open("src/api/fallback.json") as json_file:
            result = json.load(json_file)
    return DynamicRule.model_validate(result)


class SignedRequestsStrategy(RequestStrategy):
    """Requests strategy that uses a signed header"""

    api_headers: dict[str, str]

    def __init__(self) -> None:
        super().__init__()
        self.api_headers = _get_api_headers()
        self.dynamic_rules = _get_dynamic_rules()

    def set_client(self, client: "APIClient"):
        super().set_client(client)
        # Set a global `requests.session` on the parent client instance.
        if self.get_session() is None:
            self.set_session(requests.session())

    def _make_request(
        self,
        request_method: Callable,
        endpoint: str,
        params: OptionalDict = None,
        headers: OptionalDict = None,
        data: OptionalDict = None,
        **kwargs,
    ) -> Response:
        """Inject a signed header into the request and delegate the rest back to the superclass"""
        if headers is None:
            headers = {}

        headers.update(self.api_headers)
        headers.update(self._create_signed_headers(endpoint, params))
        return super()._make_request(request_method, endpoint, params, headers, data, **kwargs)

    def _create_signed_headers(self, endpoint, queryParams: dict | None):
        path = urlparse(endpoint).path
        if queryParams:
            query = urlencode(queryParams)
            path = f"{path}?{query}"
        unixtime = str(int(datetime.now().timestamp()))
        msg = "\n".join([self.dynamic_rules.static_param, unixtime, path, self.api_headers["user-id"]])
        hash_object = hashlib.sha1(msg.encode("utf-8"))
        sha_1_sign = hash_object.hexdigest()
        sha_1_b = sha_1_sign.encode("ascii")
        checksum = (
            sum([sha_1_b[number] for number in self.dynamic_rules.checksum_indexes])
            + self.dynamic_rules.checksum_constant
        )
        return {"sign": self.dynamic_rules.format.format(sha_1_sign, abs(checksum)), "time": unixtime}
