import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache, wraps
from io import BytesIO
from typing import Annotated

import dateutil.parser
import httpx
import PIL
import PIL.Image
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from jsonpath_ng import parse
from loguru import logger

from rss_feed import (GUID, Category, Enclosure, Image, Item, RSSFeed,
                      RSSResponse, XCalCategories)

load_dotenv.find_dotenv('.env.example')

feed_base_url = os.getenv("FEED_BASE_URL")
linked_events_base_url = os.getenv("LINKED_EVENTS_BASE_URL")
event_url_template = os.getenv("EVENT_URL_TEMPLATE")
cache_ttl = os.getenv("CACHE_TTL")
cache_max_size = os.getenv("CACHE_MAX_SIZE")

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
            except BaseException:
                value = parse(pathOfFirst).find(root)[0].value.strip()
        else:
            value = None
    except BaseException:
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


def get_locations(location_string, preferred_language):
    locations = {}
    for loc in location_string.split(","):
        try:
            resp = httpx.get(f'{linked_events_base_url}/place/{loc}/')
            if resp.status_code != 200:
                raise HTTPException(status_code=404, detail=f"Place not found: {loc}")
            aid = get_preferred_or_first(resp.json(), '$.@id', '$.@id', '$.@id')
            name = get_preferred_or_first(resp.json(), '$.name', f'$.name.{preferred_language}', '$.name.*')
            street_address = get_preferred_or_first(resp.json(), '$.street_address.*', f'$.street_address.{preferred_language}', '$.street_address.*')
            locality = get_preferred_or_first(resp.json(), '$.address_locality.*', f'$.address_locality.{preferred_language}', '$.address_locality.*')
            email = get_preferred_or_first(resp.json(), '$.email', '$.email', '$.email')
            info_url = get_preferred_or_first(resp.json(), '$.info_url.*', f'$.info_url.{preferred_language}', '$.info_url.*')
            locations[aid] = dict(name=name, street_address=street_address, locality=locality, email=email, info_url=info_url)
        except BaseException:
            raise HTTPException(status_code=404, detail=f"Place not found: {loc}")
    return locations


@timed_lru_cache(cache_ttl, cache_max_size)
def get_linked_events_for_location(
    location_string, preferred_language: str = 'fi',
    fetch_image_data: bool = False,
    include_categories: bool = False
):

    locations = get_locations(location_string=location_string, preferred_language=preferred_language)

    response = httpx.get(
        f'{linked_events_base_url}/event/' +
        f'?location={location_string}' +
        f'{'&include=keywords' if include_categories else ''}' +
        '&days=31&sort=start_time'
    )

    items = []
    for data in parse('$.data[*]').find(response.json()):
        event = data.value
        categories = []
        if include_categories:
            for keyword in [match.value for match in parse('$.keywords[*]').find(event)]:
                categories.append(Category(
                    content=get_preferred_or_first(keyword,  '$.name', f'$.name.{preferred_language}', '$.name.*').capitalize(),
                    domain=parse('$.@id').find(keyword)[0].value
                ))

        imageUrl = get_preferred_or_first(event, '$.images[*].url', '$.images[*].url', '$.images[*].url')
        if imageUrl is not None:
            try:
                imageName = get_preferred_or_first(event, '$.images[*].name', '$.images[*].name', '$.images[*].name')
                imageAlt = get_preferred_or_first(event, '$.images[*].alt_text', '$.images[*].alt_text', '$.images[*].alt_text')
                if fetch_image_data:
                    image_raw = httpx.get(imageUrl)
                    if image_raw.status_code != 200:
                        raise HTTPException(status_code=404, detail=f"Image not found: {imageUrl}")
                    length = image_raw.num_bytes_downloaded
                    loaded_image = PIL.Image.open(BytesIO(image_raw.content))
                    width, height = loaded_image.size
                    type = f"image/{loaded_image.format.lower()}"
                else:
                    length = 0
                    width = None
                    height = None
                    type = ""
                enclosure = Enclosure(url=imageUrl, length=length, type=type)
                image = Image(url=imageUrl, title=imageName, link=imageUrl, description=imageAlt, width=width, height=height)
            except BaseException:
                enclosure = None
                image = None
        else:
            enclosure = None
            image = None

        id = get_preferred_or_first(event, '$.id', '$.id', '$.id')
        location_id = get_preferred_or_first(event, '$.location.@id', '$.location.@id', '$.location.@id')

        if event_url_template is not None:
            eventUrl = event_url_template.format(id=id)
        else:
            eventUrl = get_preferred_or_first(event, '$.info_url.*', f'$.info_url.{preferred_language}', '$.info_url.*')
            if eventUrl is None or eventUrl == "":
                eventUrl = locations[location_id].get("info_url")

        title = get_preferred_or_first(event, '$.name.*', f'$.name.{preferred_language}', '$.name.*')

        organizer = get_preferred_or_first(event, '$.provider.*', f'$.provider.{preferred_language}', '$.provider.*')
        if organizer is None or organizer == "":
            organizer = get_preferred_or_first(event, '$.location.name.*', f'$.location.name.{preferred_language}', '$.location.name.*')

        items.append(
            Item(
                title=title,
                link=eventUrl,
                description=get_preferred_or_first(event, '$.short_description', f'$.short_description.{preferred_language}', '$.short_description.*'),
                author=locations[location_id].get("email"),
                category=categories,
                enclosure=enclosure,
                guid=GUID(content=f'{linked_events_base_url}/event/{id}', is_permalink=None),
                pub_date=dateutil.parser.parse(
                    get_preferred_or_first(event, '$.last_modified_time', '$.last_modified_time', '$.last_modified_time')
                ),
                xcal_title=title,
                xcal_featured=image,
                xcal_dtstart=dateutil.parser.parse(
                    get_preferred_or_first(event, '$.start_time', '$.start_time', '$.start_time')
                ),
                xcal_dtend=dateutil.parser.parse(
                    get_preferred_or_first(event, '$.end_time', '$.end_time', '$.end_time')
                ),
                xcal_content=get_preferred_or_first(event, '$.short_description', f'$.short_description.{preferred_language}', '$.short_description.*'),
                xcal_organizer=organizer,
                xcal_organizer_url=get_preferred_or_first(event, '$.info_url.name.*', f'$.info_url.name.{preferred_language}', '$.info_url.name.*'),
                xcal_location=locations[location_id].get("name"),
                xcal_location_address=locations[location_id].get("street_address"),
                xcal_location_city=locations[location_id].get("locality"),
                xcal_url=eventUrl,
                xcal_cost=get_preferred_or_first(event, '$.offers[*].price', '$.offers[*].price[*].{preferred_language}', '$.offers[*].price[*].*'),
                xcal_categories=XCalCategories(content=categories),
            )
        )

    channel = {
        'title': ", ".join([value.get("name") for key, value in locations.items() if value.get("name")]),
        'link':
            f'{feed_base_url}/events?location={location_string}' +
            f'&preferred_language={preferred_language}' +
            f'{'&fetch_image_data=true' if fetch_image_data else ''}' +
            f'{'&include_categories=true' if include_categories else ''}',
        'description': ", ".join([value.get("name") for key, value in locations.items() if value.get("name")]),
        'language': '',
        'pub_date': aware_utcnow(),
        'last_build_date': aware_utcnow(),
        'ttl': cache_ttl,
        'item': items,
    }

    return RSSFeed(content=channel)


@app.get("/events", tags=["events"])
def get_events(
    location:  Annotated[str, Query(pattern='^[a-z]*:[0-9]+(,[a-z]*:[0-9]+)*$')],
    preferred_language: Annotated[str, Query(pattern='^fi|sv|en$')],
    fetch_image_data: bool | None = False,
    include_categories: bool | None = False
):
    return RSSResponse(
        get_linked_events_for_location(
            location,
            preferred_language,
            fetch_image_data,
            include_categories)
    )


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
