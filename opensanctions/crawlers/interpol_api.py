from requests.exceptions import HTTPError
from normality import collapse_spaces, stringify

from opensanctions.core import Context
from opensanctions import helpers as h

MAX_RESULTS = 160
SEEN = set()
COUNTRIES_URL = "https://www.interpol.int/en/How-we-work/Notices/View-Red-Notices"
FORMATS = ["%Y/%m/%d", "%Y/%m", "%Y"]


def get_countries(context):
    doc = context.fetch_html(COUNTRIES_URL)
    path = ".//select[@id='arrestWarrantCountryId']//option"
    options = []
    for option in doc.findall(path):
        code = stringify(option.get("value"))
        if code is None:
            continue
        label = collapse_spaces(option.text_content())
        options.append((code, label))
    return list(sorted(options))


def crawl_notice(context, notice):
    url = notice.get("_links", {}).get("self", {}).get("href")
    if url in SEEN:
        return
    SEEN.add(url)
    try:
        notice = context.fetch_json(url, cache_days=7)
    except HTTPError as err:
        context.log.warning(
            "HTTP error",
            url=str(err.request.url),
            error=err.response.status_code,
        )
        return
    first_name = notice["forename"] or ""
    last_name = notice["name"] or ""
    entity = context.make("Person")
    entity.id = context.make_slug(notice.get("entity_id"))
    entity.add("name", first_name + " " + last_name)
    entity.add("firstName", first_name)
    entity.add("lastName", last_name)
    entity.add("sourceUrl", url)
    entity.add("nationality", notice.get("nationalities"))
    entity.add("gender", notice.get("sex_id"))
    entity.add("birthPlace", notice.get("place_of_birth"))

    dob_raw = notice["date_of_birth"]
    entity.add("birthDate", h.parse_date(dob_raw, FORMATS))
    if "v1/red" in url:
        entity.add("topics", "crime")

    for idx, warrant in enumerate(notice.get("arrest_warrants", []), 1):
        # TODO: make this a Sanction:
        entity.add("program", warrant["issuing_country_id"])
        entity.add("notes", warrant["charge"])

    context.emit(entity, target=True)


def crawl_country(context: Context, country, age_max=120, age_min=0):
    params = {
        "ageMin": int(age_min),
        "ageMax": int(age_max),
        # "arrestWarrantCountryId": country,
        "nationality": country,
        "resultPerPage": MAX_RESULTS,
    }
    try:
        data = context.fetch_json(context.source.data.url, params=params)
    except HTTPError as err:
        context.log.warning(
            "HTTP error",
            url=str(err.request.url),
            country=country,
            error=err.response.status_code,
        )
        return
    # if res.status_code != 200:

    # if not res.from_cache:
    #     time.sleep(0.5)
    # data = res.json()
    notices = data.get("_embedded", {}).get("notices", [])
    for notice in notices:
        crawl_notice(context, notice)
    total = data.get("total")
    # pprint((country, total, age_max, age_min))
    if total > MAX_RESULTS:
        age_range = age_max - age_min
        if age_range > 1:
            age_split = age_min + (age_range // 2)
            crawl_country(context, country, age_max, age_split)
            crawl_country(context, country, age_split, age_min)
        elif age_range == 1:
            crawl_country(context, country, age_max, age_max)
            crawl_country(context, country, age_min, age_min)


def crawl(context: Context):
    countries = get_countries(context)
    context.log.info("Loading interpol API cache...")
    context.cache.preload("https://ws-public.interpol.int/notices/%")
    for country, label in countries:
        context.log.info("Crawl %r" % label, code=country)
        crawl_country(context, country)
