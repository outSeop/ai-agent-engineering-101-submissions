"""Opt-in assembly for one read-only public catalogue per customer request."""
from bounded_public_catalogue_host import BoundedPublicCatalogue, instruction_from, SEMANTIC_NAME
import json
from broker_public_catalogue_host_candidate import mask
from card_source_read_lane import safe_directory
from public_catalogue_phase_metrics import PhaseMetrics
from public_catalogue_protocol import CatalogueProtocol
from public_catalogue_request_host import ScopedPublicCatalogue
from public_catalogue_snapshot_host import read_snapshot
from public_reservation_sidecar import read as read_stock_state


SEARCH_INSTRUCTION=(
    'Search verified representative stock. Args may contain q, skus, exclude_skus, category, grade, '
    'max_price, min_remaining_seconds, sort, limit (at most 8). '
    'For another page submit the complete next_args from the latest page. For new filters start at offset 0. '
    'Use search_products for alternative products, exclusions or narrower filters. The optional op field must be search.'
)


def managed_options(operator,freeze,official,catalogue_pins,*,check=False):
    state=operator/"runtime/native-customer-context"
    source=freeze/"catalogue"
    instruction_from(source,catalogue_pins,official)
    semantic=freeze/"semantic"
    manifest=json.loads((freeze/"MANIFEST.json").read_bytes())
    semantic_pins={name.removeprefix("semantic/"):digest
                   for name,digest in manifest["file_sha256"].items() if name.startswith("semantic/")}
    instruction_from(semantic,semantic_pins,official,SEMANTIC_NAME)
    if check:
        return {}
    scratch=safe_directory(safe_directory(state)/"scratch")
    sealed_tool=BoundedPublicCatalogue(source,operator/"kit",scratch,catalogue_pins,
        semantic_source=semantic,semantic_pins=semantic_pins)
    protocol=CatalogueProtocol(mask)

    def request_factory(_legacy_execute):
        return ScopedPublicCatalogue(lambda:read_snapshot(state/"latest.json"),sealed_tool,protocol,SEARCH_INSTRUCTION,
            stock_state_supplier=lambda raw,document:read_stock_state(state/"stock-state.json",raw,document))

    return {"catalogue_source_factory":request_factory,
            "public_phase_report":PhaseMetrics(state/"public-catalogue-semantic-metrics.json")}

