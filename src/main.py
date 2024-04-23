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

from multiprocessing import Pool
import time


from rss_feed import (GUID, Category, Enclosure, Image, Item, RSSFeed, RSSResponse, XCalCategories)

load_dotenv()


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


feed_base_url = os.getenv("FEED_BASE_URL")
linked_events_base_url = os.getenv("LINKED_EVENTS_BASE_URL")
event_url_template = os.getenv("EVENT_URL_TEMPLATE")
cache_ttl = int(os.getenv("CACHE_TTL"))
cache_max_size = int(os.getenv("CACHE_MAX_SIZE"))
uvicorn_workers = int(os.getenv("UVICORN_WORKERS"))
kirkanta_base_url = os.getenv("KIRKANTA_BASE_URL")
consortium_id = int(os.getenv("CONSORTIUM_ID"))
api_client_pool_size = int(os.getenv("API_CLIENT_POOL_SIZE"))
load_images_from_api = strtobool(os.getenv("LOAD_IMAGES_FROM_API"))
load_keywords_from_api = strtobool(os.getenv("LOAD_KEYWORDS_FROM_API"))
skip_super_events = strtobool(os.getenv("SKIP_SUPER_EVENTS"))


logger = logging.getLogger("feedgen.stdout")
logger.setLevel(logging.getLevelName(os.getenv("LOG_LEVEL")))
stream_handler = logging.StreamHandler(sys.stdout)
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(processName)s: %(process)d] [%(threadName)s: %(thread)d] %(name)s: %(message)s")
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)


memcached_client = base.Client('unix:/run/memcached/memcached.sock')


@asynccontextmanager
async def lifespan(app: FastAPI):
    job = scheduler.add_job(populate_cache, 'interval', id='populate_cache', seconds=cache_ttl)
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


def get_and_store_events(id):
    try:
        for lang in ["fi", "en", "sv"]:
            memcached_client.set(
                f"{id},{lang}",
                get_linked_events_for_location(
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
        logger.error(f"Data fetch error {e}")
        pass


def populate_cache():
    start_time = time.time()
    logger.info("Started feed update job.")

    libraries = httpx.get(
        '{kirkanta_base_url}/library?consortium={consortium}&with=customData'.format(
            kirkanta_base_url=kirkanta_base_url,
            consortium=consortium_id)
        ).json()

    total = int(parse('$.total').find(libraries)[0].value)
    parsed = 0

    ids = [id.value for id in parse("$.items[*].customData[?(@.id == 'le_rss_locations')].value").find(libraries) if not None]

    while parsed < total:
        libraries = httpx.get(
            '{kirkanta_base_url}/library?consortium={consortium}&with=customData&skip={skip}'.format(
                kirkanta_base_url=kirkanta_base_url,
                consortium=consortium_id,
                skip=parsed)
        ).json()
        parsed += len([id.value for id in parse("$.items[*]").find(libraries)])
        ids += [id.value for id in parse("$.items[*].customData[?(@.id == 'le_rss_locations')].value").find(libraries)]

    with Pool(api_client_pool_size) as fetcher_pool:
        fetcher_pool.map(get_and_store_events, ids)

    logger.info(f"Completed feed update job in {time.time() - start_time} seconds.")


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


def parse_to_itemlist(linked_events_json, preferred_language, locations):
    items = []
    include_categories = load_keywords_from_api
    fetch_image_data = load_images_from_api
    for data in parse('$.data[*]').find(linked_events_json):
        event = data.value
        is_super_event = get_preferred_or_first(event, "$.super_event_type", "$.super_event_type", "$.super_event_type") is not None
        id = get_preferred_or_first(event, '$.id', '$.id', '$.id')

        if (is_super_event and skip_super_events):
            logger.debug(f"Skipped: super event {id}")
        else:
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
    return items


def get_linked_events_for_location(
    location_string, preferred_language: str = 'fi',
    fetch_image_data: bool = True,
    include_categories: bool = True
):
    locations = get_locations(location_string=location_string, preferred_language=preferred_language)

    items = []
    page_number = 1
    next = True

    while next:
        response = httpx.get(
            f"{linked_events_base_url}/event/?location={location_string}{"&include=keywords" if include_categories else ""}&days=31&sort=start_time&page={page_number}"
        )
        items += parse_to_itemlist(response.json(), preferred_language, locations)
        next_page = parse('$.meta.next').find(response.json())[0].value
        if next_page is None:
            next = False
        else:
            next = True
            next_page_url = urllib.parse.urlparse(next_page, allow_fragments=False).query
            page_number = int(urllib.parse.parse_qs(next_page_url)["page"][0])

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
    workers=uvicorn_workers
)
server = uvicorn.Server(config=config)


if __name__ == "__main__":
    server.run()
