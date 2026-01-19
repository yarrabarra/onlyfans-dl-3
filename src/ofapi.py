import click


from typing import Type, Literal, Any
from datetime import datetime, timedelta
from loguru import logger as log
from pydantic import ValidationError
from collections.abc import Mapping

from apiclient import APIClient, endpoint
from apiclient.response_handlers import JsonResponseHandler

from models.messages import MessageList, Message
from models.purchase import Purchase
from models.profile import Profile
from models.post import Post

from api.strategy import SignedRequestsStrategy

DRM_ENABLED = False
try:
    from pywidevine.cdm import Cdm
    from pywidevine.device import Device
    from pywidevine.pssh import PSSH

    DRM_ENABLED = True
except Exception as e:
    log.error(f"Unable to import pywidevine, disabling DRM client: {e}")

POST_LIMIT = 50

# Type Alias
Offsetables = Profile | Purchase | Post | MessageList


def to_str(item: str | int | float):
    """Needed as floats are expected with six digit precision in API response"""
    if isinstance(item, str):
        return item
    elif isinstance(item, float):
        return "{:.6f}".format(item)
    return str(item)


@click.pass_context
def get_max_days_offset(ctx):
    max_post_days_value = ctx.params["max_post_days"]
    delta = (datetime.today() - timedelta(max_post_days_value)).timestamp()
    return delta // 1  # cheap floor that retains float


@click.pass_context
def get_label_id(ctx):
    return ctx.params.get("label_id")


@endpoint(base_url="https://onlyfans.com/api2/v2")
class Endpoint:
    posts = "/users/{id}/posts"
    archived = "/users/{id}/posts/archived"
    stories = "/users/{id}/stories"
    messages = "/chats/{id}/messages"
    purchased = "/posts/paid/all"
    profile = "/users/{id}"
    subscriptions = "/subscriptions/subscribes"
    # https://onlyfans.com/api2/v2/users/media/3020233153/drm/post/738465453?type=widevine
    # https://onlyfans.com/api2/v2/users/media/3020233153/drm/post/738465453?type=widevine
    drm_license = "/users/media/{media_id}/drm/post/{post_id}"


class OFClient(APIClient):
    def __init__(self, **kwargs):
        self.request_strategy = SignedRequestsStrategy()
        super().__init__(request_strategy=self.request_strategy, response_handler=JsonResponseHandler, **kwargs)

    def get_request_timeout(self):
        return 120.0  # Good things can take a while

    def _get_by_offset(
        self,
        endpoint,
        itemType: Type[Offsetables],
        pageType: Literal["offset", "afterPublishTime", "id"],
        paramOverride: Mapping[str, str | int] | None = None,
        items: list[Offsetables] | None = None,
        pageOffset: int | float = 0,
    ) -> list[Any]:
        """A recursive function to query endpoints by offsets"""

        getParams = {"limit": POST_LIMIT, "order": "desc"}
        if paramOverride is not None:
            getParams.update(paramOverride)

        if items is None:
            items = []
        if pageOffset > 0:
            getParams[pageType] = to_str(pageOffset)

        log.debug(f"Fetching endpoint {endpoint} - {pageType}: {pageOffset}")
        request = self.get(endpoint, getParams)
        # TODO: Handle this hack better in "infinite" format?
        # if isinstance(request, dict) and "list" in request:
        #     request = request["list"]

        if isinstance(request, dict):
            try:
                base_list = [itemType.model_validate(request)]
            except ValidationError:
                with open(f"debug/validation_error/{pageType}.json", "w") as debug_result:
                    import json

                    json.dump(request, debug_result, indent=2)
                    raise
        else:
            base_list = []
            # Iterate so we can catch and log individual failures
            for item in request:
                try:
                    base_list.append(itemType.model_validate(item))
                except ValidationError:
                    from pprint import pprint

                    pprint(item)
                    raise

        items.extend(base_list)
        # Recursive query
        if len(base_list) >= POST_LIMIT:
            if pageType == "offset":
                pageOffset += POST_LIMIT
            elif pageType == "afterPublishTime":
                if not isinstance(items[-1], Post):
                    raise ValueError("Incorrect value used")
                pageOffset = float(items[-1].postedAtPrecise)
            elif pageType == "id":
                if not isinstance(items[-1], MessageList):
                    raise ValueError("Incorrect value used")
                if not items[-1].hasMore:
                    return items
                pageOffset = items[-1].list[-1].id
            items.extend(self._get_by_offset(endpoint, itemType, pageType, paramOverride, items, pageOffset))
        return items

    def get_subscriptions(self) -> list[Profile]:
        return self._get_by_offset(Endpoint.subscriptions, Profile, "offset", {"type": "active"})

    def get_purchases(self) -> list[Purchase]:
        return self._get_by_offset(Endpoint.purchased, Purchase, "offset")

    def get_posts(self, subscription: Profile) -> list[Post]:
        pageOffset = get_max_days_offset()
        params = {"order": "publish_date_asc"}

        # Conditionally filter by a label, we don't have a way to look this up yet so just use ID
        label = get_label_id()
        if label:
            params["label"] = label

        log.info(params)

        return self._get_by_offset(
            Endpoint.posts.format(id=subscription.id),
            Post,
            "afterPublishTime",
            params,
            pageOffset=pageOffset,
        )

    def get_messages(self, subscription: Profile) -> list[Message]:
        results = []
        response = self._get_by_offset(Endpoint.messages.format(id=subscription.id), MessageList, "id")
        for item in response:
            if not isinstance(item, MessageList):
                raise ValueError("Incorrect type returned from query")
            results.extend(item.list)
        return results

    def get_profile(self, profile_name: str):
        # <profile_name> = "me" -> info about yourself
        response = self.get(Endpoint.profile.format(id=profile_name))
        return Profile.model_validate(response)


class OFDRMClient(APIClient):
    # A dedicated client just for yeeting requests into the void

    def __init__(self, **kwargs):
        self.request_strategy = SignedRequestsStrategy()
        super().__init__(request_strategy=self.request_strategy, **kwargs)

    def get_drm_license(self, pssh_secret: str, media_id: int, post_id: int):
        # Used for signing media licensing requests?

        pssh = PSSH(pssh_secret)
        endpoint = Endpoint.drm_license.format(media_id=media_id, post_id=post_id)
        device = Device.load(r"WVD/google_android_sdk_built_for_x86_64_14.0.0_ac23a0a1_4464_l3.wvd")
        cdm = Cdm.from_device(device)
        session_id = cdm.open()
        challenge = cdm.get_license_challenge(session_id, pssh)

        licence = self.post(endpoint, data=challenge, params={"type": "widevine"})  # type: ignore
        cdm.parse_license(session_id, licence.content)
        for key in cdm.get_keys(session_id):
            print(f"[{key.type}] {key.kid.hex}:{key.key.hex()}")
            if key.type == "CONTENT":
                print(f"\n--key {key.kid.hex}:{key.key.hex()}")
        cdm.close(session_id)
        return cdm
