from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from .media import MediaItem
from .profile import Profile


class Option(BaseModel):
    id: int
    name: str
    count: Optional[int]
    isVoted: bool


class Voting(BaseModel):
    finishedAt: Optional[str]
    options: list[Option]
    total: int


class Post(BaseModel):
    author: Profile
    canComment: bool
    canDelete: bool | None = None
    canEdit: bool | None = None
    canReport: bool
    canToggleFavorite: bool
    canViewMedia: bool
    commentsCount: int | None = None
    expiredAt: datetime | None = None
    favoritesCount: int | None = None
    hasUrl: bool | None = None
    hasVoting: bool | None = None
    id: int
    isAddedToBookmarks: bool | None = None
    isArchived: bool | None = None
    isCouplePeopleMedia: bool | None = None
    isDeleted: bool | None = None
    isFavorite: bool | None = None
    isMediaReady: bool
    isOpened: bool
    isPinned: bool | None = None
    isPrivateArchived: bool | None = None
    linkedPosts: list = []
    linkedUsers: list = []
    lockedText: bool | None = None
    media: list[MediaItem] = []
    mediaCount: int = 0
    mentionedUsers: list | None = None
    postedAt: Optional[datetime] = None
    postedAtPrecise: str
    preview: list = []
    price: Decimal | None = None
    rawText: str | None = None
    responseType: str
    streamId: str | int | None = None
    text: str | None = ""
    tipsAmount: str | None = ""
    tipsAmountRaw: Decimal | None = None
    voting: Voting | list | None = None

    def get_date(self):
        if self.postedAt is None:
            return "1970-01-01"  # Epoch failsafe if date is not present
        return self.postedAt.strftime("%Y-%m-%d")

    def is_viewable(self):
        return self.canViewMedia

    def get_profile_id(self):
        return self.author.id
