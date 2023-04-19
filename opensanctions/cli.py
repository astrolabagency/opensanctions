import click
import shutil
import logging
from typing import Optional
from zavod.logs import get_logger
from nomenklatura.tui import dedupe_ui
from nomenklatura.judgement import Judgement
from nomenklatura.resolver import Identifier

from opensanctions import settings
from opensanctions.core import Dataset, Context, setup
from opensanctions.exporters.statements import export_statements_path
from opensanctions.exporters.statements import import_statements_path
from opensanctions.core.audit import audit_resolver
from opensanctions.core.loader import Database
from opensanctions.core.resolver import export_pairs, get_resolver
from opensanctions.core.xref import blocking_xref
from opensanctions.core.statements import max_last_seen
from opensanctions.core.statements import resolve_all_canonical, resolve_canonical
from opensanctions.core.enrich import enrich
from opensanctions.core.analytics import build_analytics
from opensanctions.core.db import engine_tx
from opensanctions.exporters import export, export_metadata
from opensanctions.util import write_json

log = get_logger(__name__)
datasets = click.Choice(Dataset.names())


@click.group(help="OpenSanctions ETL toolkit")
@click.option("-v", "--verbose", is_flag=True, default=False)
@click.option("-q", "--quiet", is_flag=True, default=False)
def cli(verbose=False, quiet=False):
    level = logging.INFO
    if quiet:
        level = logging.WARNING
    if verbose:
        level = logging.DEBUG
    setup(log_level=level)


@cli.command("crawl", help="Crawl entities into the given dataset")
@click.argument("dataset", default=Dataset.ALL, type=datasets)
def crawl(dataset):
    """Crawl all datasets within the given scope."""
    scope = Dataset.require(dataset)
    for source in scope.sources:
        ctx = Context(source)
        ctx.crawl()


@cli.command("export", help="Export entities from the given dataset")
@click.argument("dataset", default=Dataset.ALL, type=datasets)
@click.option("-i", "--index", is_flag=True, default=False)
@click.option("-r", "--recurse", is_flag=True, default=False)
def export_(dataset: str, index: bool = False, recurse: bool = False):
    export(dataset, recurse=recurse)
    if index:
        export_metadata()


@cli.command("export-index", help="Export global dataset index")
def export_metadata_():
    export_metadata()


@cli.command("enrich", help="Import matched entities from an external source")
@click.argument("dataset", type=datasets)
@click.argument("external", type=datasets)
@click.option("-t", "--threshold", type=click.FLOAT, default=0.6)
def enrich_(dataset: str, external: str, threshold: float):
    enrich(dataset, external, threshold)


@cli.command("clear", help="Delete all stored data for the given source")
@click.argument("dataset", default=Dataset.ALL, type=datasets)
def clear(dataset):
    dataset = Dataset.require(dataset)
    for source in dataset.sources:
        Context(source).clear()


@cli.command("clear-workdir", help="Delete the working path and cached source data")
@click.argument("dataset", default=Dataset.ALL, type=datasets)
def clear_workdir(dataset: Optional[str] = None):
    ds = Dataset.require(dataset)
    for part in ds.datasets:
        path = settings.DATASET_PATH.joinpath(part.name)
        if not path.exists():
            continue
        log.info("Clear path: %s" % path)
        shutil.rmtree(path)


@cli.command("resolve", help="Apply de-duplication to the statements table")
def resolve():
    resolver = get_resolver()
    with engine_tx() as conn:
        resolve_all_canonical(conn, resolver)


@cli.command("xref", help="Generate dedupe candidates from the given dataset")
@click.argument("dataset", default=Dataset.DEFAULT, type=datasets)
@click.option("-l", "--limit", type=int, default=10000)
@click.option("-a", "--auto", type=float, default=0.990)
def xref(dataset, limit, auto):
    dataset = Dataset.require(dataset)
    blocking_xref(dataset, limit=limit, auto_threshold=auto)


@cli.command("xref-prune", help="Remove dedupe candidates")
def xref_prune():
    resolver = get_resolver()
    resolver.prune()
    resolver.save()


@cli.command("dedupe", help="Interactively judge xref candidates")
@click.option("-d", "--dataset", type=datasets, default=Dataset.DEFAULT)
def dedupe(dataset):
    resolver = get_resolver()
    dataset = Dataset.require(dataset)
    db = Database(dataset, resolver, external=True)
    loader = db.view(dataset)
    dedupe_ui(resolver, loader, url_base="https://opensanctions.org/entities/%s/")


@cli.command("export-pairs", help="Export pairwise judgements")
@click.argument("dataset", default=Dataset.DEFAULT, type=datasets)
@click.option("-o", "--outfile", type=click.File("wb"), default="-")
def export_pairs_(dataset, outfile):
    dataset = Dataset.require(dataset)
    for obj in export_pairs(dataset):
        write_json(obj, outfile)


@cli.command("explode", help="Destroy a cluster of deduplication matches")
@click.argument("canonical_id", type=str)
def explode(canonical_id):
    resolver = get_resolver()
    resolved_id = resolver.get_canonical(canonical_id)
    with engine_tx() as conn:
        for entity_id in resolver.explode(resolved_id):
            log.info("Restore separate entity", entity=entity_id)
            resolve_canonical(conn, resolver, entity_id)
    resolver.save()


@cli.command("merge", help="Merge multiple entities as duplicates")
@click.argument("entity_ids", type=str, nargs=-1)
@click.option("-f", "--force", is_flag=True, default=False)
def merge(entity_ids, force: bool = False):
    if len(entity_ids) < 2:
        return
    resolver = get_resolver()
    canonical_id = resolver.get_canonical(entity_ids[0])
    for other_id in entity_ids[1:]:
        other_id = Identifier.get(other_id)
        other_canonical_id = resolver.get_canonical(other_id)
        if other_canonical_id == canonical_id:
            continue
        check = resolver.check_candidate(canonical_id, other_id)
        if not check:
            edge = resolver.get_resolved_edge(canonical_id, other_id)
            if force is True:
                if edge is not None:
                    log.warn("Removing existing edge", edge=edge)
                    resolver._remove_edge(edge)
            else:
                log.error(
                    "Cannot merge",
                    canonical_id=canonical_id,
                    other_id=other_id,
                    edge=edge,
                )
                return
        log.info("Merge: %s -> %s" % (other_id, canonical_id))
        canonical_id = resolver.decide(canonical_id, other_id, Judgement.POSITIVE)
    resolver.save()
    log.info("Canonical: %s" % canonical_id)


@cli.command("audit", help="Sanity-check the resolver configuration")
def audit():
    audit_resolver()


@cli.command("latest", help="Show the latest data timestamp")
@click.argument("dataset", default=Dataset.DEFAULT, type=datasets)
def latest(dataset):
    ds = Dataset.require(dataset)
    with engine_tx() as conn:
        latest = max_last_seen(conn, ds)
        if latest is not None:
            print(latest.isoformat())


@cli.command("build-analytics", help="Build analytics data tables")
@click.argument("dataset", default=Dataset.DEFAULT, type=datasets)
def build_analytics_(dataset):
    ds = Dataset.require(dataset)
    build_analytics(ds)


@cli.command("export-statements", help="Export statement data as a CSV file")
@click.argument("outfile", type=click.Path(writable=True))
def export_statements_csv(outfile):
    export_statements_path(outfile)


@cli.command("import-statements", help="Import statement data from a CSV file")
@click.argument("infile", type=click.Path(readable=True, exists=True))
def import_statements(infile):
    import_statements_path(infile)


if __name__ == "__main__":
    cli()
