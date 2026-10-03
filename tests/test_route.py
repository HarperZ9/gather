"""The gather.route/1 record: path, auth state, measured cost and rates."""
import pytest

from gather.item import make_item
from gather.route import ROUTE_SCHEMA, RouteRecord, route_of, stamp
from gather.source import Catalog


def item():
    return make_item(kind="metadata", id="a", title="A", text="body", source="video", ref="a",
                     method="yt-dlp", fetched_at=0.0)


def test_rates_come_from_the_serving_calls():
    rec = RouteRecord("youtube", "yt-dlp", elapsed_s=4.0, requests=2, bytes=1000)
    assert rec.rates() == {"bytes_per_s": 250.0, "requests_per_min": 30.0}
    assert rec.to_dict()["schema"] == ROUTE_SCHEMA


def test_zero_time_reports_no_rate_instead_of_dividing():
    assert RouteRecord("youtube", "yt-dlp", 0.0, 1, 10).rates() == {"bytes_per_s": None, "requests_per_min": None}


@pytest.mark.parametrize("kw", [{"auth": "secret-value"}, {"elapsed_s": -1}, {"bytes": -5}])
def test_bad_records_are_refused(kw):
    base = {"channel": "c", "path": "p", "elapsed_s": 1.0, "requests": 1, "bytes": 1}
    with pytest.raises(ValueError):
        RouteRecord(**{**base, **kw})


def test_stamp_keeps_the_content_hash_and_the_catalog_carries_the_route():
    original = item()
    rec = RouteRecord("youtube", "youtube-data-api", 0.5, 1, 300, auth="present", fallback_reason="rate-limited: x")
    (stamped,) = stamp([original], rec)
    assert stamped.provenance.sha256 == original.provenance.sha256 and stamped.verify()
    assert route_of(stamped)["fallback_reason"] == "rate-limited: x" and route_of(original) is None
    cat = Catalog()
    cat.add([original, stamped])
    rows = cat.rows()
    assert "route" not in rows[0] and rows[1]["route"]["path"] == "youtube-data-api"
