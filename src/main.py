import os
from typing import Annotated


from functools import lru_cache, wraps
from datetime import datetime, timedelta, timezone

import PIL.Image
import uvicorn
import httpx
from io import BytesIO
import PIL

from fastapi import FastAPI, Query
from loguru import logger

import dateutil.parser
from jsonpath_ng import parse

from rss_feed import (
    RSSFeed, RSSResponse, Item, Category, GUID, Enclosure, Image, XCalCategories, Channel
)

cache_ttl = 3600
cache_max_size = 3000

app = FastAPI(
    title=os.environ.get("APP_TITLE"),
    description=os.environ.get("APP_DESCRIPTION"),
    version=os.environ.get("APP_VERSION"),
    contact={
        "name": os.environ.get("APP_CONTACT_NAME"),
        "url": os.environ.get("APP_CONTACT_URL"),
    },
    license_info={
        "name": os.environ.get("APP_LICENSE_NAME"),
        "url": os.environ.get("APP_LICENSE_URL"),
    },
)


def get_preferred_or_first(root, pathIfExist, pathOfPreferred, pathOfFirst):
    try:
        if parse(pathIfExist).find(root)[0].value is not None:
            try:
                value = parse(pathOfPreferred).find(root)[0].value.strip()
            except:
                value = parse(pathOfFirst).find(root)[0].value.strip()
        else:
            value = None
    except:
        value = None
    return value


@app.get("/status", tags=["status"])
def get_status():
    return {"status": "OK"}


def aware_utcnow():
    """to be used instead of datetime.utcnow() in Python >= 3.12"""
    return datetime.now(timezone.utc)


# taken from https://stackoverflow.com/questions/31771286/python-in-memory-cache-with-time-to-live
def timed_lru_cache(seconds: int = 90, maxsize: int = 15):
    def wrapper_cache(func):
        func = lru_cache(maxsize=maxsize)(func)
        func.lifetime = timedelta(seconds=seconds)
        func.expiration = aware_utcnow() + func.lifetime

        @wraps(func)
        def wrapped_func(*args, **kwargs):
            if aware_utcnow() >= func.expiration:
                func.cache_clear()
                func.expiration = aware_utcnow() + func.lifetime

            return func(*args, **kwargs)

        return wrapped_func

    return wrapper_cache


@timed_lru_cache(cache_ttl, cache_max_size)
def get_linked_events_for_location(location, preferred_language):

    location_names = []
    for loc in location.split(","):
        try:
            resp = httpx.get(f'https://api.hel.fi/linkedevents/v1/place/{loc}/')
            location_names.append(get_preferred_or_first(resp.json(),
                '$.name',
                f'$.name.{preferred_language}',
                '$.name.*'))
        except:
            pass

    response = httpx.get(f'https://api.hel.fi/linkedevents/v1/event/?location={location}&include=location,keywords&days=31&sort=start_time')
    items = []
    for data in parse('$.data[*]').find(response.json()):
        event = data.value
        categories = []
        for keyword in [match.value for match in parse('$.keywords[*]').find(event)]:
            categories.append(Category(
                content=get_preferred_or_first(keyword,  '$.name', f'$.name.{preferred_language}', '$.name.*').capitalize(),
                domain=parse('$.@id').find(keyword)[0].value
            ))

        imageUrl=get_preferred_or_first(event, '$.images[*].url', f'$.images[*].url', '$.images[*].url')
        if imageUrl is not None:
            try:
                imageName=get_preferred_or_first(event, '$.images[*].name', f'$.images[*].name', '$.images[*].name')
                imageAlt=get_preferred_or_first(event, '$.images[*].alt_text', f'$.images[*].alt_text', '$.images[*].alt_text')
                image_raw = httpx.get(imageUrl)
                loaded_image = PIL.Image.open(BytesIO(image_raw.content))
                width, height = loaded_image.size
                image = Image(
                    url=imageUrl,
                    title=imageName,
                    link=imageUrl,
                    description=imageAlt,
                    width=width,
                    height=height
                )
                enclosure = Enclosure(
                    url=imageUrl,
                    length=image_raw.num_bytes_downloaded,
                    type=f"image/{loaded_image.format.lower()}"
                )
            except:
                enclosure = None
                image = None
        else:
            enclosure = None
            image = None

        eventUrl = get_preferred_or_first(event, '$.info_url.*', f'$.info_url.{preferred_language}', '$.info_url.*')
        if eventUrl is None or eventUrl == "":
            eventUrl = get_preferred_or_first(event, '$.location.info_url.*', f'$.location.info_url.{preferred_language}', '$.location.info_url.*')

        title=get_preferred_or_first(event, '$.name.*', f'$.name.{preferred_language}', '$.name.*')
        organizer = get_preferred_or_first(event, '$.provider.*', f'$.provider.{preferred_language}', '$.provider.*')
        if organizer is None or organizer == "":
            organizer = get_preferred_or_first(event, '$.location.name.*', f'$.location.name.{preferred_language}', '$.location.name.*')

        items.append(
            Item(
                title=title,
                link=eventUrl,
                description=get_preferred_or_first(event, '$.short_description', f'$.short_description.{preferred_language}', '$.short_description.*'),
                author=get_preferred_or_first(event, '$.location.email', '$.location.email', '$.location.email'),
                category=categories,
                enclosure=enclosure,
                guid=GUID(
                    content=f'https://api.hel.fi/linkedevents/v1/event/{get_preferred_or_first(event, '$.id', '$.id', '$.id')}',
                    is_permalink=None,
                ),
                pub_date=dateutil.parser.parse(
                    get_preferred_or_first(event, '$.last_modified_time', f'$.last_modified_time', '$.last_modified_time')
                ),
                xcal_title=title,
                xcal_featured=image,
                xcal_dtstart=dateutil.parser.parse(
                    get_preferred_or_first(event, '$.start_time', f'$.start_time', '$.start_time')
                ),
                xcal_dtend=dateutil.parser.parse(
                    get_preferred_or_first(event, '$.end_time', f'$.end_time', '$.end_time')
                ),
                xcal_content=get_preferred_or_first(event, '$.short_description', f'$.short_description.{preferred_language}', '$.short_description.*'),
                xcal_organizer=organizer,
                xcal_organizer_url=get_preferred_or_first(event, '$.info_url.name.*', f'$.info_url.name.{preferred_language}', '$.info_url.name.*'),
                xcal_location=get_preferred_or_first(event, '$.location.name.*', f'$.location.name.{preferred_language}', '$.location.name.*'),
                xcal_location_address=get_preferred_or_first(event, '$.location.street_address.*', f'$.location.street_address.{preferred_language}', '$.location.street_address.*'),
                xcal_location_city=get_preferred_or_first(event, '$.location.address_locality.*', f'$.location.address_locality.{preferred_language}', '$.location.address_locality.*'),
                xcal_url=eventUrl,
                xcal_cost=get_preferred_or_first(event, '$.offers[*].price', '$.offers[*].price[*].{preferred_language}', '$.offers[*].price[*].*'),
                xcal_categories=XCalCategories(content=categories),
            )
        )

    channel = {
        'title': ", ".join(location_names),
        'link': 'https://example.org',
        'description': ", ".join(location_names),
        'language': '',
        'pub_date': aware_utcnow(),
        'last_build_date': aware_utcnow(),
        'ttl': cache_ttl,
        'item': items,
    }

    return RSSFeed(content=channel)


@app.get("/events", tags=["events"])
def get_events(location:  Annotated[str, Query(pattern='^tprek:[0-9]+(,tprek:[0-9]+)*$')], preferred_language: Annotated[str, Query(pattern='^fi|sv|en$')]):
    return RSSResponse(get_linked_events_for_location(location, preferred_language))


def server():
    #    LOGGING_CONFIG["formatters"]["default"][
    #        "fmt"
    #    ] = "%(asctime)s [%(name)s] %(levelprefix)s %(message)s"
    #    LOGGING_CONFIG["formatters"]["access"][
    #        "fmt"
    #    ] = '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    server()
