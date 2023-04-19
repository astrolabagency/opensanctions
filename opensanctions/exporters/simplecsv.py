import io
import csv
from typing import List
from followthemoney.types import registry
from followthemoney.util import join_text

from opensanctions.core import Dataset, Entity
from opensanctions.exporters.common import Exporter


class SimpleCSVExporter(Exporter):
    TITLE = "Targets as simplified CSV"
    NAME = "targets.simple"
    EXTENSION = "csv"
    MIME_TYPE = "text/csv"

    HEADERS = [
        "id",
        "schema",
        "name",
        "aliases",
        "birth_date",
        "countries",
        "addresses",
        "identifiers",
        "sanctions",
        "phones",
        "emails",
        "dataset",
        "first_seen",
        "last_seen",
    ]

    def concat_values(self, values):
        output = io.StringIO()
        writer = csv.writer(
            output,
            dialect=csv.unix_dialect,
            delimiter=";",
            lineterminator="",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(sorted(values))
        return output.getvalue()

    def sanction_text(self, sanction):
        value = join_text(
            *sanction.get("program"),
            *sanction.get("reason"),
            *sanction.get("status"),
            *sanction.get("startDate"),
            *sanction.get("endDate"),
            sep=" - ",
        )
        return value or ""

    def setup(self):
        super().setup()
        self.fh = open(self.path, "w")
        self.writer = csv.writer(self.fh, dialect=csv.unix_dialect)
        self.writer.writerow(self.HEADERS)

    def feed(self, entity: Entity):
        if not entity.target:
            return
        countries = set(entity.get_type_values(registry.country))
        identifiers = set(entity.get_type_values(registry.identifier))
        names = set(entity.get_type_values(registry.name))
        names.discard(entity.caption)
        sanctions = set()
        addresses = set(entity.get("address"))

        for _, adjacent in self.loader.get_adjacent(entity):
            if adjacent.schema.is_a("Sanction"):
                sanctions.add(self.sanction_text(adjacent))

            if adjacent.schema.is_a("Address"):
                addresses.add(adjacent.caption)

            if adjacent.schema.is_a("Identification"):
                identifiers.update(adjacent.get("number"))
                countries.update(adjacent.get("country"))

        datasets: List[str] = []
        for dataset in entity.datasets:
            ds = Dataset.require(dataset)
            datasets.append(ds.title)
        row = [
            entity.id,
            entity.schema.name,
            entity.caption,
            self.concat_values(names),
            self.concat_values(entity.get("birthDate", quiet=True)),
            self.concat_values(countries),
            self.concat_values(addresses),
            self.concat_values(identifiers),
            self.concat_values(sanctions),
            self.concat_values(entity.get_type_values(registry.phone)),
            self.concat_values(entity.get_type_values(registry.email)),
            self.concat_values(datasets),
            entity.first_seen,
            entity.last_seen,
        ]
        self.writer.writerow(row)

    def finish(self):
        self.fh.close()
        super().finish()
