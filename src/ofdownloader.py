import click
import os
import pathlib
import shutil
from urllib.parse import urlparse

import requests
import util
from loguru import logger as log
from models.media import MediaItem
from models.profile import Profile
from models.purchase import Purchase
from ofapi import OFClient, OFDRMClient
from ofdb import OFDB

DRM_SUPPORT = False
POSTS_LIMIT = 50


@click.pass_context
def get_filter(ctx):
    text_filter = ctx.params.get("filter", "")
    if text_filter is None:
        return None
    return text_filter.lower()


class OFDownloader:
    def __init__(self):
        self.api = OFClient()
        self.drm = OFDRMClient()

        # Database
        self.db = OFDB()

        # Options
        self.albums = False  #
        self.use_subfolders = True  #
        self.processed_count = 0
        self.new_files: dict[str, list[str]] = {}

    def _get_media_path(self, media: MediaItem, mediaType: str, album: str, postdate: str, source: str):
        # Pull just the extension out of the source URL
        suffix = pathlib.Path(urlparse(source).path).suffix
        filename = f"{postdate}_{media.id}{suffix}"
        if self.albums and album and media.type == "photo":
            path = os.path.join("photos", f"{postdate}_{album}", filename)
        else:
            path = os.path.join(f"{media.type}s", filename)
        if self.use_subfolders and mediaType != "posts":
            path = os.path.join(mediaType, path)
        return path

    def retrieve_file(self, source: str, dest: pathlib.Path):
        path = pathlib.Path(dest)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with requests.Session() as session:
            request = session.get(source, stream=True, timeout=(5, None))
            request.raise_for_status()
            with open(path, "wb") as destFile:
                shutil.copyfileobj(request.raw, destFile)
        return True

    def download_media(
        self, subscription: Profile, media: MediaItem, mediaType: str, postdate: str, album="", post_id=0
    ) -> tuple[pathlib.Path | None, bool]:
        # TODO: This is very messy, needs to be extracted into components
        source = media.get_source()
        if source is None:
            log.debug(f"No source or files for media {media.id}")
            return None, False
        if not media.is_downloadable():
            return None, False
        if media.is_drm():
            if not DRM_SUPPORT:
                return None, False
            pssh = util.parse_pssh_from_mpd(source)
            if pssh is None:
                return None, False
            license = self.drm.get_drm_license(pssh, media.id, post_id)
            exit()

        path = self._get_media_path(media, mediaType, album, postdate, source)
        final_path = pathlib.Path("subscriptions") / subscription.username / path
        # TODO: Remove hack to avoid double downloads until local DB is implemented
        if mediaType == "messages":
            purchasedPath = pathlib.Path(str(final_path).replace("messages", "purchased")).parent
            for matchPath in purchasedPath.glob(f"*_{media.id}*"):
                if matchPath.exists():
                    log.debug(f"Skipping {path} because already exists in {matchPath}")
                    return matchPath, False
        if self.retrieve_file(source, final_path):
            return final_path, True
        return final_path, False

    def _get_posts(self, subscription: Profile, mediaType: str):
        if mediaType == "messages":
            posts = self.api.get_messages(subscription)
        elif mediaType in "purchased":
            posts = self.api.get_purchases()
        elif mediaType == "posts":
            posts = self.api.get_posts(subscription)
        else:
            raise NotImplementedError(f"Unhandled mediaType: {mediaType}")
        return posts

    def get_content(self, subscription: Profile, mediaType: str):
        self.processed_count = 0  # Reset to zero
        posts = self._get_posts(subscription, mediaType)
        log.info("Found " + str(len(posts)) + " " + mediaType)
        for post in posts:
            if not post.is_viewable():
                continue

            if isinstance(post, Purchase) and post.fromUser is not None:
                if post.fromUser.username != subscription.username:
                    # Skip purchases that are not from the subscription we're querying
                    continue
            filter = get_filter()
            if filter and post.text:
                if filter not in post.text.lower():
                    continue
                log.info(f"Filter catching text: {post.text}")
            postdate = post.get_date()
            album = ""
            if len(post.media) > 1:  # Don't put single photo posts in a subfolder
                album = str(post.id)  # Album ID
            self.db.upsert_content(post)
            for media in post.media:
                # TODO: Find a sub with stories
                # if mediaType == "stories":
                #     postdate = str(media["createdAt"][:10])
                if not media.canView:
                    continue
                if media.get_source() is None:
                    continue
                path, is_new = self.download_media(subscription, media, mediaType, postdate, album, post.id)
                self.processed_count += 1
                if self.processed_count % 100 == 0:
                    log.info(f"Processed files: {self.processed_count}")
                if is_new:
                    self.new_files.setdefault(subscription.name, [])
                    self.new_files[subscription.name].append(str(path))
                if path is not None:
                    # if not media.id == "3118351114":
                    #     continue
                    self.db.upsert_media_item(str(path), subscription.id, media, mediaType, postdate, album, post.id)

        log.info(f"Total files processed: {self.processed_count}")
        return True

    def cleanup_bad_downloads(self, subscriptions):
        return

    @log.catch
    def run(self, target: str, subscriptions):
        subscription_list = self.api.get_subscriptions()

        log.info(f"Subscriptions: {subscription_list}")
        for subscription in subscription_list:
            if subscriptions != "all":
                if subscription.username not in subscriptions.split(","):
                    log.debug(f"Not part of subscription targets, skipping {subscription.username}")
                    continue
            subs_dir = os.path.join("subscriptions", subscription.username)
            if os.path.isdir(subs_dir):
                log.info(f"{subscription.username} exists. Downloading new media, skipping pre-existing.")
            else:
                log.info(f" New subscription, downloading content to {subs_dir}")
            if target == "all":
                # TODO: Archived/stories
                # self.get_content(subscription, "archived")
                # self.get_content(subscription, "stories")
                self.get_content(subscription, "posts")
                self.get_content(subscription, "purchased")
                self.get_content(subscription, "messages")
                continue
            self.get_content(subscription, target)
        return True
