from datetime import datetime
from pantomime import parse_mimetype
from typing import Optional, TypedDict, Generator, cast
from sqlalchemy.future import select
from sqlalchemy.sql.expression import delete

from opensanctions import settings
from opensanctions.core.dataset import Dataset
from opensanctions.core.db import Conn, upsert_func, resource_table


class Resource(TypedDict):
    path: str
    name: str
    dataset: str
    checksum: str
    url: str
    timestamp: datetime
    mime_type: Optional[str]
    mime_type_label: Optional[str]
    title: Optional[str]
    size: int


def save_resource(
    conn: Conn,
    path: str,
    dataset: Dataset,
    checksum: str,
    mime_type: Optional[str],
    size: int,
    title: Optional[str],
):
    if size == 0:
        q = delete(resource_table)
        q = q.where(resource_table.c.dataset == dataset.name)
        q = q.where(resource_table.c.path == path)
        conn.execute(q)
        return

    resource: Resource = {
        "dataset": dataset.name,
        "path": path,
        "mime_type": mime_type,
        "checksum": checksum,
        "timestamp": settings.RUN_TIME,
        "size": size,
        "title": title,
    }
    istmt = upsert_func(resource_table).values([resource])
    stmt = istmt.on_conflict_do_update(
        index_elements=["path", "dataset"],
        set_=dict(
            mime_type=istmt.excluded.mime_type,
            checksum=istmt.excluded.checksum,
            timestamp=istmt.excluded.timestamp,
            size=istmt.excluded.size,
            title=istmt.excluded.title,
        ),
    )
    conn.execute(stmt)
    return resource


def all_resources(conn: Conn, dataset: Dataset) -> Generator[Resource, None, None]:
    q = select(resource_table)
    q = q.filter(resource_table.c.dataset == dataset.name)
    q = q.order_by(resource_table.c.path.asc())
    result = conn.execute(q)
    for row in result.fetchall():
        resource = cast(Resource, row._asdict())
        # Add mime type label for the web UI. Should this live here?
        mime_type = resource["mime_type"]
        if mime_type is not None:
            mime = parse_mimetype(mime_type)
            resource["mime_type_label"] = mime.label
        resource["name"] = resource["path"]
        resource["url"] = dataset.make_public_url(resource["path"])
        yield resource


def clear_resources(conn: Conn, dataset: Dataset):
    pq = delete(resource_table)
    pq = pq.where(resource_table.c.dataset == dataset.name)
    conn.execute(pq)
