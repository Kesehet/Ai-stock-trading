# ruff: noqa: I001
from datetime import UTC, datetime, timedelta

from app.evidence.classifier import classify_event
from app.evidence.models import EvidenceKind, MarketEventType, SourceTier
from app.evidence.sources import RSSSourceConfig, parse_rss
from app.evidence.store import EvidenceStore


RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Exchange announcements</title>
    <item>
      <title>TCS - Outcome of Board Meeting and Dividend</title>
      <link>https://example.test/tcs/1</link>
      <guid>tcs-1</guid>
      <description><![CDATA[Board approved an interim dividend.]]></description>
      <pubDate>Fri, 21 Aug 2026 05:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def _items(retrieved_at: datetime):
    config = RSSSourceConfig(
        name="NSE announcements",
        url="https://example.test/rss",
        source_tier=SourceTier.OFFICIAL,
        trust_score=1.0,
        kind=EvidenceKind.ANNOUNCEMENT,
    )
    return parse_rss(RSS_FIXTURE, config, retrieved_at)


def test_rss_is_normalized_and_classified() -> None:
    retrieved_at = datetime(2026, 8, 21, 5, 1, tzinfo=UTC)
    item = _items(retrieved_at)[0]

    assert item.title == "TCS - Outcome of Board Meeting and Dividend"
    assert item.body == "Board approved an interim dividend."
    assert item.available_at == retrieved_at
    assert item.trust_score == 1.0

    event = classify_event(item)
    assert event.event_type == MarketEventType.BOARD_MEETING
    assert event.evidence_ids == (item.id,)


def test_store_deduplicates_same_feed_item(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 21, 5, 1, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.db")
    first = _items(retrieved_at)[0]
    duplicate = _items(retrieved_at)[0]

    assert first.fingerprint == duplicate.fingerprint
    assert store.put(first) is True
    assert store.put(duplicate) is False


def test_point_in_time_query_blocks_future_evidence(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 21, 5, 1, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.db")
    item = _items(retrieved_at)[0]
    assert store.put(item) is True

    before_available = retrieved_at - timedelta(seconds=1)
    after_available = retrieved_at + timedelta(seconds=1)

    assert store.list_as_of(before_available) == []
    visible = store.list_as_of(after_available)
    assert len(visible) == 1
    assert visible[0].fingerprint == item.fingerprint
