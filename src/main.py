import os
import sys
import urllib
import urllib.parse
import logging

import dateutil.parser
import httpx
import PIL
import PIL.Image
import uvicorn

from datetime import datetime, timezone
from io import BytesIO
from typing import Annotated
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ProcessPoolExecutor

from jsonpath_ng.ext import parse
from pymemcache.client import base

from pebble import ProcessPool

import time
import sentry_sdk

from rss_feed import (GUID, Category, Enclosure, Image, Item, RSSFeed, RSSResponse, XCalCategories, EventMeta)

load_dotenv()

sentry_sdk.init(
     dsn=os.getenv("SENTRY_DSN"),
     environment=os.getenv("SENTRY_ENVIRONMENT"),
     traces_sample_rate=0.85,
)

def strtobool(value, raise_exc=False):
    _true_set = {'yes', 'true', 't', 'y', '1'}
    _false_set = {'no', 'false', 'f', 'n', '0'}

    if isinstance(value, str):
        value = value.lower()
        if value in _true_set:
            return True
        if value in _false_set:
            return False

    if raise_exc:
        raise ValueError('Expected "%s"' % '", "'.join(_true_set | _false_set))
    return None


FEED_BASE_URL = os.getenv("FEED_BASE_URL")
LINKED_EVENTS_BASE_URL = os.getenv("LINKED_EVENTS_BASE_URL")
EVENT_URL_TEMPLATE = os.getenv("EVENT_URL_TEMPLATE")
CACHE_TTL = int(os.getenv("CACHE_TTL"))
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE"))
UVICORN_WORKERS = int(os.getenv("UVICORN_WORKERS"))
KIRKANTA_BASE_URL = os.getenv("KIRKANTA_BASE_URL")
CONSORTIUM_ID = int(os.getenv("CONSORTIUM_ID"))
API_CLIENT_POOL_SIZE = int(os.getenv("API_CLIENT_POOL_SIZE"))
API_CLIENT_TIMEOUT_SECONDS = int(os.getenv("API_CLIENT_TIMEOUT_SECONDS", default=1))
LOAD_IMAGES_FROM_API = strtobool(os.getenv("LOAD_IMAGES_FROM_API"))
LOAD_KEYWORDS_FROM_API = strtobool(os.getenv("LOAD_KEYWORDS_FROM_API"))
SKIP_SUPER_EVENTS = strtobool(os.getenv("SKIP_SUPER_EVENTS"))
SUPPORTED_LANGUAGES = os.getenv("SUPPORTED_LANGUAGES", default="fi,en,sv").split(",")


logger = logging.getLogger("feedgen.stdout")
logger.setLevel(logging.getLevelName(os.getenv("LOG_LEVEL")))
stream_handler = logging.StreamHandler(sys.stdout)
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(processName)s: %(process)d] [%(threadName)s: %(thread)d] %(name)s: %(message)s")
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)


memcached_client = base.Client('unix:/run/memcached/memcached.sock')


@asynccontextmanager
async def lifespan(app: FastAPI):
    job = scheduler.add_job(populate_cache, 'interval', id='populate_cache', replace_existing=True, seconds=CACHE_TTL)
    for job in scheduler.get_jobs():
        job.modify(next_run_time=datetime.now())
    scheduler.start()
    yield
    scheduler.remove_job('populate_cache')
    scheduler.shutdown(wait=False)


scheduler = BackgroundScheduler(
    jobstores={'default': MemoryJobStore()},
    executors={'default': ProcessPoolExecutor(2)},
    job_defaults={'coalesce': True, 'max_instances': 1}
)


def get_and_store_events(id: str, lang: str):
    try:
        memcached_client.set(
            f"{id},{lang}",
            create_feed_for_location(
                f"{id}", lang, True, True)
            .to_xml(
                pretty_print=False,
                encoding="UTF-8",
                standalone=True,
                skip_empty=True
            )
        )
        logger.debug(f"Updated {id}, lang {lang}")
    except BaseException as e:
        logger.error(f"Data fetch error for {id}, lang {lang}: {e}")
        pass
    return id


def task_done(future):
    try:
        future.result()
    except TimeoutError:
        logger.error(f"Feed generation timeout: {future.id}, lang {future.lang}")
        future.cancel()
    except Exception as error:
        logger.error(error)


def populate_cache():
    start_time = time.time()
    logger.info("Started feed update job.")

    libraries = httpx.get(
        '{KIRKANTA_BASE_URL}/library?consortium={consortium}&with=customData'.format(
            KIRKANTA_BASE_URL=KIRKANTA_BASE_URL,
            consortium=CONSORTIUM_ID)
        ).json()

    total = int(parse('$.total').find(libraries)[0].value)
    parsed = 0

    ids = [id.value for id in parse("$.items[*].customData[?(@.id == 'le_rss_locations')].value").find(libraries) if not None]

    while parsed < total:
        libraries = httpx.get(
            '{KIRKANTA_BASE_URL}/library?consortium={consortium}&with=customData&skip={skip}'.format(
                KIRKANTA_BASE_URL=KIRKANTA_BASE_URL,
                consortium=CONSORTIUM_ID,
                skip=parsed)
        ).json()
        parsed += len([id.value for id in parse("$.items[*]").find(libraries)])
        ids += [id.value for id in parse("$.items[*].customData[?(@.id == 'le_rss_locations')].value").find(libraries)]

    logger.info(f"Updating feeds for {len(ids)} libraries ({len(set(ids))} unique locations)")

    with ProcessPool(max_workers=API_CLIENT_POOL_SIZE) as fetcher_pool:
        for id in set(ids):
            for lang in SUPPORTED_LANGUAGES:
                future = fetcher_pool.schedule(get_and_store_events, kwargs={"id": id, "lang": lang}, timeout=API_CLIENT_TIMEOUT_SECONDS)
                future.id = id
                future.lang = lang
                future.add_done_callback(task_done)

    logger.info(f"Completed feed update job in {time.time() - start_time} seconds.")


def get_preferred_or_first(root, pathOfPreferred, pathOfFirst):
    try:
        try:
            value = parse(pathOfPreferred).find(root)[0].value.strip()
        except BaseException:
            value = parse(pathOfFirst).find(root)[0].value.strip()
    except BaseException:
        value = None
    return value


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
    lifespan=lifespan
 )


@app.get("/status", tags=["status"])
def get_status():
    return {"status": "OK"}


def aware_utcnow():
    """to be used instead of datetime.utcnow() in Python >= 3.12"""
    return datetime.now(timezone.utc)


def get_locations(location_string, preferred_language):
    locations = {}
    for loc in location_string.split(","):
        try:
            resp = httpx.get(f'{LINKED_EVENTS_BASE_URL}/place/{loc}/', timeout=API_CLIENT_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                raise HTTPException(status_code=404, detail=f"Place not found: {loc}")
            aid = get_preferred_or_first(resp.json(), '$.@id', '$.@id')
            name = get_preferred_or_first(resp.json(), f'$.name.{preferred_language}', '$.name.*')
            street_address = get_preferred_or_first(resp.json(), f'$.street_address.{preferred_language}', '$.street_address.*')
            locality = get_preferred_or_first(resp.json(), f'$.address_locality.{preferred_language}', '$.address_locality.*')
            email = get_preferred_or_first(resp.json(), '$.email', '$.email')
            info_url = get_preferred_or_first(resp.json(), f'$.info_url.{preferred_language}', '$.info_url.*')
            locations[aid] = dict(name=name, street_address=street_address, locality=locality, email=email, info_url=info_url)
        except BaseException:
            raise HTTPException(status_code=404, detail=f"Place not found: {loc}")
    return locations


def parse_to_itemlist(linked_events_json, preferred_language, locations):
    items = []
    include_categories = LOAD_KEYWORDS_FROM_API
    fetch_image_data = LOAD_IMAGES_FROM_API
    for data in parse('$.data[*]').find(linked_events_json):
        event = data.value
        is_super_event = get_preferred_or_first(event, "$.super_event_type", "$.super_event_type") is not None
        id = get_preferred_or_first(event, '$.id', '$.id')

        if (is_super_event and SKIP_SUPER_EVENTS):
            logger.debug(f"Skipped: super event {id}")
        else:
            categories = []
            if include_categories:
                for keyword in [match.value for match in parse('$.keywords[*]').find(event)]:
                    categories.append(Category(
                        content=get_preferred_or_first(keyword, f'$.name.{preferred_language}', '$.name.*').capitalize(),
                        domain=parse('$.@id').find(keyword)[0].value
                    ))

            imageUrl = get_preferred_or_first(event, '$.images[*].url', '$.images[*].url')
            if imageUrl is not None:
                try:
                    imageName = get_preferred_or_first(event, '$.images[*].name', '$.images[*].name')
                    imageAlt = get_preferred_or_first(event, '$.images[*].alt_text', '$.images[*].alt_text')
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
                        width = 0
                        height = 0
                        type = "image"
                    enclosure = Enclosure(url=imageUrl, length=length, type=type)
                    image = Image(url=imageUrl, title=imageName, link=imageUrl, description=imageAlt, width=width, height=height)
                except BaseException:
                    enclosure = None
                    image = None
            else:
                enclosure = None
                image = None

            location_id = get_preferred_or_first(event, '$.location.@id', '$.location.@id')

            if EVENT_URL_TEMPLATE is not None:
                eventUrl = EVENT_URL_TEMPLATE.format(id=id)
            else:
                eventUrl = get_preferred_or_first(event, f'$.info_url.{preferred_language}', '$.info_url.*')
                if eventUrl is None or eventUrl == "":
                    eventUrl = locations[location_id].get("info_url")

            title = get_preferred_or_first(event, f'$.name.{preferred_language}', '$.name.*')

            organizer = get_preferred_or_first(event, f'$.provider.{preferred_language}', '$.provider.*')
            if organizer is None or organizer == "":
                organizer = get_preferred_or_first(event, f'$.location.name.{preferred_language}', '$.location.name.*')

            event_cost = get_preferred_or_first(event, '$.offers[*].price[*].{preferred_language}', '$.offers[*].price[*].*')

            try:
                event_start = dateutil.parser.parse(get_preferred_or_first(event, '$.start_time', '$.start_time'))
            except BaseException:
                logger.error(f"event: {id} missing start time, lang: {preferred_language}")

            try:
                event_end = dateutil.parser.parse(get_preferred_or_first(event, '$.end_time', '$.end_time'))
            except BaseException:
                logger.error(f"event: {id} missing end time, lang: {preferred_language}")

            try:
                pub_date = dateutil.parser.parse(get_preferred_or_first(event, '$.last_modified_time', '$.last_modified_time'))
            except BaseException:
                logger.error(f"event: {id} missing last modified time, lang: {preferred_language}")

            items.append(
                Item(
                    title=title,
                    link=eventUrl,
                    description=get_preferred_or_first(event, f'$.short_description.{preferred_language}', '$.short_description.*'),
                    author=locations[location_id].get("email"),
                    category=categories,
                    enclosure=enclosure,
                    guid=GUID(content=f'{LINKED_EVENTS_BASE_URL}/event/{id}', is_permalink=None),
                    pub_date=pub_date,
                    xcal_title=title,
                    xcal_featured=image,
                    xcal_dtstart=event_start,
                    xcal_dtend=event_end,
                    xcal_content=get_preferred_or_first(event, f'$.short_description.{preferred_language}', '$.short_description.*'),
                    xcal_organizer=organizer,
                    xcal_organizer_url=get_preferred_or_first(event, f'$.info_url.name.{preferred_language}', '$.info_url.name.*'),
                    xcal_location=locations[location_id].get("name"),
                    xcal_location_address=locations[location_id].get("street_address"),
                    xcal_location_city=locations[location_id].get("locality"),
                    xcal_url=eventUrl,
                    xcal_cost=event_cost,
                    xcal_categories=XCalCategories(content=categories),
                    event_location=locations[location_id].get("name"),
                    event_location_address=locations[location_id].get("street_address"),
                    event_location_city=locations[location_id].get("locality"),
                    event_organizer=organizer,
                    event_organizer_url=eventUrl,
                    event_cost=event_cost,
                    event_meta=EventMeta(dtstart=event_start, dtend=event_end)
                )
            )
    return items


def create_feed_for_location(
    location_string, preferred_language: str = 'fi',
    fetch_image_data: bool = True,
    include_categories: bool = True
):
    locations = get_locations(location_string=location_string, preferred_language=preferred_language)

    items = []
    page_number = 1
    next = True

    while next:
        apiurl = f"{LINKED_EVENTS_BASE_URL}/event/?location={location_string}{"&include=keywords" if include_categories else ""}&days=31&sort=start_time&page={page_number}"

        response = httpx.get(apiurl)
        try:
            items += parse_to_itemlist(response.json(), preferred_language, locations)
        except BaseException:
            logger.error(f"LinkedEvents API event item list parsing failed for: {apiurl}")
        try:
            next_page = parse('$.meta.next').find(response.json())[0].value
        except BaseException:
            logger.error(f"LinkedEvents API didn't return next_page: {apiurl}")
            next_page = None

        if next_page is None:
            next = False
        else:
            try:
                next_page_url = urllib.parse.urlparse(next_page, allow_fragments=False).query
                page_number = int(urllib.parse.parse_qs(next_page_url)["page"][0])
                next = True
            except BaseException:
                logger.error("Couldn't parse next page number.from Linked Events response.")
                next = False

    channel = {
        'title': ", ".join([value.get("name") for key, value in locations.items() if value.get("name")]),
        'link':
            f'{FEED_BASE_URL}/events?location={location_string}' +
            f'&preferred_language={preferred_language}' +
            f'{'&fetch_image_data=true' if fetch_image_data else ''}' +
            f'{'&include_categories=true' if include_categories else ''}',
        'description': ", ".join([value.get("name") for key, value in locations.items() if value.get("name")]),
        'language': '',
        'pub_date': aware_utcnow(),
        'last_build_date': aware_utcnow(),
        'ttl': CACHE_TTL,
        'item': items,
    }
    return RSSFeed(content=channel)


@app.get("/events", tags=["events"])
async def get_events(
    location:  Annotated[str, Query(pattern='^[a-z]*:[0-9]+(,[a-z]*:[0-9]+)*$')],
    preferred_language: Annotated[str, Query(pattern='^fi|sv|en$')]
):
    try:
        xml = memcached_client.get(f"{location},{preferred_language}")
        return RSSResponse(xml)
    except BaseException:
        raise HTTPException(status_code=404, detail="Feed not found")

log_config = uvicorn.config.LOGGING_CONFIG
log_config["formatters"]["default"]["fmt"] = log_formatter._fmt
log_config["formatters"]["access"]["fmt"] = log_formatter._fmt

config = uvicorn.Config(
    app=app,
    host="0.0.0.0",
    port=8000,
    log_config=log_config,
    workers=UVICORN_WORKERS
)
server = uvicorn.Server(config=config)


if __name__ == "__main__":
    server.run()
