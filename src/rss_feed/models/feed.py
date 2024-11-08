from datetime import datetime, timezone
import pytz
import html
import re
from typing import List, Optional

from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, attr, element

from .category import Category
from .cloud import Cloud
from .image import Image
from .item import Item
from .textinput import TextInput

# FIXME: Remove harcoded timezone
local_tz = pytz.timezone('Europe/Helsinki')


class Hours(BaseXmlModel, tag="hour"):
    content: List[int] = element(tag="hour", default=None)


class Days(BaseXmlModel, tag="day"):
    content: List[str] = element(tag="day", default=None)


class Channel(BaseXmlModel, tag="channel"):
    @field_serializer("pub_date", "last_build_date")
    def convert_datetime_to_RFC_822(dt: datetime) -> str:
        dt.replace(tzinfo=timezone.utc)
        local_dt = dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
        ctime = local_dt.ctime()
        return f"{ctime[0:3]}, {local_dt.day:02d} {ctime[4:7]}" + local_dt.strftime(
            " %Y %H:%M:%S %z"
        )

    @field_serializer("title", "link", "description", "language", "copyright", "managing_editor", "webmaster", "generator", "docs", "rating")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    # Required Feed elements
    title: str = element(tag="title", default="")
    link: str = element(tag="link", default=None)
    description: str = element(tag="description", default=None)

    # Optional feed elements
    language: Optional[str] = element(tag="language", default=None)
    copyright: Optional[str] = element(tag="copyright", default=None)
    managing_editor: Optional[str] = element(tag="managingEditor", default=None)
    webmaster: Optional[str] = element(tag="webmaster", default=None)
    pub_date: Optional[datetime] = element(tag="pubDate", default=None)
    last_build_date: Optional[datetime] = element(tag="lastBuildDate", default=None)
    category: Optional[List[Category]] = element(tag="category", default_factory=list)
    generator: str = element(tag="generator", default="Linked Events RSS")
    docs: str = element(
        tag="docs", default="https://validator.w3.org/feed/docs/rss2.html"
    )
    cloud: Optional[Cloud] = element(tag="cloud", default=None)
    ttl: int = element(tag="ttl", default=60)
    image: Optional[Image] = element(tag="image", default=None)
    rating: Optional[str] = element(tag="rating", default=None)
    text_input: Optional[TextInput] = element(tag="textInput", default=None)
    skip_hours: Optional[Hours] = element(tag="skipHours", default=None)
    skip_days: Optional[Days] = element(tag="skipDays", default=None)

    # RSS Items
    item: List[Item] = element(tag="item", default_factory=list)


class RSSFeed(
        BaseXmlModel,
        tag="rss",
        nsmap={
            "ev": "http://purl.org/rss/2.0/modules/event/",
            "xcal": "urn:ietf:params:xml:ns:xcal"
        }):
    version: str = attr(name="version", default="2.0")
    content: Channel
