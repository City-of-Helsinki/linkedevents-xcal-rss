from datetime import datetime, timezone
import pytz
import html
import re
from typing import List, Optional

from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, element

from .category import Category
from .enclosure import Enclosure
from .guid import GUID
from .image import Image
from .source import Source

# FIXME: Remove harcoded timezone
local_tz = pytz.timezone('Europe/Helsinki')


class XCalCategories(BaseXmlModel):
    content: List[Category] = element(
        tag="category", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )


class EventMeta(BaseXmlModel):
    # FIXME: The timestamp format is non-standard so that also the time part would be supported by Finna
    @field_serializer("dtstart", "dtend")
    def convert_timestamp(dt: datetime) -> str:
        local_dt = dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
        return local_dt.strftime("%Y-%m-%d%Z%H:%M:%S")

    dtstart: Optional[datetime] = element(
        tag="dtstart", default=None, nsmap={"": "http://purl.org/rss/2.0/modules/event/"}
    )
    dtend: Optional[datetime] = element(
        tag="dtend", default=None, nsmap={"": "http://purl.org/rss/2.0/modules/event/"}
    )


class Item(BaseXmlModel):
    @field_serializer("pub_date")
    def convert_datetime_to_RFC_822(dt: datetime) -> str:
        dt.replace(tzinfo=timezone.utc)
        dt.replace(tzinfo=timezone.utc)
        local_dt = dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
        ctime = local_dt.ctime()
        return f"{ctime[0:3]}, {local_dt.day:02d} {ctime[4:7]}" + local_dt.strftime(
            " %Y %H:%M:%S %z"
        )

    @field_serializer(
            "title", "description", "author", "comments", "event_location", "event_location_address",
            "event_location_city", "event_organizer", "event_organizer_url", "event_cost",
            "xcal_title", "xcal_content", "xcal_url", "xcal_cost", "xcal_location", "xcal_location_address",
            "xcal_location_city", "xcal_organizer", "xcal_organizer_url"
        )
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    # FIXME: The timestamp format is non-standard so that also the time part would be supported by Finna

    @field_serializer("xcal_dtstart", "xcal_dtend")
    def convert_timestamp(dt: datetime) -> str:
        local_dt = dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
        return local_dt.strftime("%Y-%m-%d%Z%H:%M:%S")

    # Basic RSS Item fields
    title: str = element(tag="title")
    link: Optional[str] = element(
        tag="link",
        default=None,
    )
    description: Optional[str] = element(
        tag="description",
        default=None,
    )
    author: Optional[str] = element(
        tag="author",
        default=None,
    )
    category: Optional[List[Category]] = element(tag="category", default_factory=list)
    comments: Optional[str] = element(
        tag="comments",
        default=None,
    )
    enclosure: Optional[Enclosure] = element(
        serialization_alias="enclosure",
        default=None,
    )
    guid: Optional[GUID] = element(
        tag="guid",
        default=None,
    )
    pub_date: Optional[datetime] = element(
        tag="pubDate",
        default=None,
    )
    source: Optional[Source] = element(
        tag="source",
        default=None,
    )

    # RSS extension item fields
    event_location: Optional[str] = element(
        tag="location",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )
    event_location_address: Optional[str] = element(
        tag="location-address",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )
    event_location_city: Optional[str] = element(
        tag="location-city",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )
    event_organizer: Optional[str] = element(
        tag="organizer",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )
    event_organizer_url: Optional[str] = element(
        tag="organizer-url",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )
    event_cost: Optional[str] = element(
        tag="cost",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )
    event_meta: Optional[EventMeta] = element(
        tag="event_meta",
        nsmap={"": "http://purl.org/rss/2.0/modules/event/"},
        default=None,
    )

    # Finna can handle following XCal fields in its feed component
    # FIXME: Check if elements that have counterparts in the RSS spec need to be duplicated with xcal elements
    # FIXME: Especially the categories element seems to be only referenced in Finna wiki page
    # https://www.kiwi.fi/display/Finna/Muut+asetukset#Muutasetukset-xCal-tapahtumatiedot
    xcal_title: Optional[str] = element(
        tag="title",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_featured: Optional[Image] = element(
        tag="featured",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_dtstart: Optional[datetime] = element(
        tag="dtstart",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_dtend: Optional[datetime] = element(
        tag="dtend",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_content: Optional[str] = element(
        tag="content",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_url: Optional[str] = element(
        tag="url",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_cost: Optional[str] = element(
        tag="cost",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_categories: Optional[XCalCategories] = element(
        tag="categories",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_location: Optional[str] = element(
        tag="location",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_location_address: Optional[str] = element(
        tag="location-address",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_location_city: Optional[str] = element(
        tag="location-city",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_organizer: Optional[str] = element(
        tag="organizer",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
    xcal_organizer_url: Optional[str] = element(
        tag="organizer-url",
        nsmap={"": "urn:ietf:params:xml:ns:xcal"},
        default=None,
    )
