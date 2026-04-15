"""
Tests for ZepEntityReader classification fallback logic

Kiểm tra rằng khi nodes không có custom labels, classification mapping
được sử dụng làm fallback để bao gồm nodes vào kết quả lọc.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.services.zep_entity_reader import (
    ZepEntityReader,
    EntityNode,
    FilteredEntities,
)


def make_node(uuid, name, labels=None, summary="", attributes=None):
    """Tạo mock node object"""
    node = MagicMock()
    node.uuid_ = uuid
    node.name = name
    node.labels = labels or ["Entity", "Node"]
    node.summary = summary
    node.attributes = attributes or {}
    return node


def make_edge(uuid, name, fact, source_uuid, target_uuid, attributes=None):
    """Tạo mock edge object"""
    edge = MagicMock()
    edge.uuid_ = uuid
    edge.name = name
    edge.fact = fact
    edge.source_node_uuid = source_uuid
    edge.target_node_uuid = target_uuid
    edge.attributes = attributes or {}
    return edge


@pytest.fixture
def reader_with_mocked_fetch():
    """ZepEntityReader với fetch_all_nodes/edges được mock"""
    with patch('app.services.zep_entity_reader.Zep'):
        reader = ZepEntityReader(api_key="test-key")

        # Mock các phương thức get_all_nodes và get_all_edges
        reader.get_all_nodes = MagicMock()
        reader.get_all_edges = MagicMock(return_value=[])

        yield reader


def test_filter_without_classifications_excludes_unlabeled(reader_with_mocked_fetch):
    """Không có classifications thì nodes không custom labels bị loại"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-3", "name": "Bob", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=None,
        enrich_with_edges=False,
        classifications=None
    )

    # Không有 custom labels và không có classifications => 0 entities
    assert result.filtered_count == 0
    assert result.total_count == 3


def test_filter_with_classifications_includes_nodes(reader_with_mocked_fetch):
    """Có classifications thì nodes không custom labels được bao gồm"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-3", "name": "Bob", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]

    classifications = {
        "uuid-1": "Person",
        "uuid-2": "Company",
        "uuid-3": "Person",
    }

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=None,
        enrich_with_edges=False,
        classifications=classifications
    )

    # Có classifications => 3 entities
    assert result.filtered_count == 3
    assert result.total_count == 3
    assert len(result.entities) == 3

    # Kiểm tra entity types
    assert "Person" in result.entity_types
    assert "Company" in result.entity_types


def test_filter_with_classifications_respects_defined_types(reader_with_mocked_fetch):
    """Classifications vẫn tuân theo defined_entity_types filter"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-3", "name": "Bob", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]

    classifications = {
        "uuid-1": "Person",
        "uuid-2": "Company",
        "uuid-3": "Person",
    }

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=["Person"],  # Chỉ lấy Person
        enrich_with_edges=False,
        classifications=classifications
    )

    # Chỉ 2 Person nodes được bao gồm
    assert result.filtered_count == 2
    assert result.entity_types == {"Person"}


def test_filter_prefers_zep_labels_over_classifications(reader_with_mocked_fetch):
    """Zep custom labels được ưu tiên hơn classifications"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node", "Person"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]

    classifications = {
        "uuid-1": "Company",  # Classification khác với label thật
        "uuid-2": "Company",
    }

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=None,
        enrich_with_edges=False,
        classifications=classifications
    )

    # uuid-1 có custom label "Person" nên dùng label, không dùng classification "Company"
    assert result.filtered_count == 2
    assert "Person" in result.entity_types  # Từ label của uuid-1
    assert "Company" in result.entity_types  # Từ classification của uuid-2


def test_filter_empty_classifications_same_as_none(reader_with_mocked_fetch):
    """Classifications rỗng (dict rỗng) tương đương None"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=None,
        enrich_with_edges=False,
        classifications={}
    )

    # Dict rỗng không giúp ích gì => 0 entities
    assert result.filtered_count == 0


def test_filter_partial_classifications_only_classified_included(reader_with_mocked_fetch):
    """Chỉ nodes có trong classifications mới được bao gồm"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-3", "name": "Bob", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]

    classifications = {
        "uuid-1": "Person",
        # uuid-2 và uuid-3 không có classification
    }

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=None,
        enrich_with_edges=False,
        classifications=classifications
    )

    # Chỉ 1 node được bao gồm
    assert result.filtered_count == 1
    assert result.entities[0].uuid == "uuid-1"


def test_filter_with_enrich_edges_includes_related_edges(reader_with_mocked_fetch):
    """Test enrich_with_edges=True bao gồm related edges"""
    reader = reader_with_mocked_fetch
    reader.get_all_nodes.return_value = [
        {"uuid": "uuid-1", "name": "Alice", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
        {"uuid": "uuid-2", "name": "Acme Corp", "labels": ["Entity", "Node"], "summary": "", "attributes": {}},
    ]
    reader.get_all_edges.return_value = [
        {"uuid": "edge-1", "name": "works_at", "fact": "Alice works at Acme",
         "source_node_uuid": "uuid-1", "target_node_uuid": "uuid-2", "attributes": {}},
    ]

    classifications = {"uuid-1": "Person", "uuid-2": "Company"}

    result = reader.filter_defined_entities(
        graph_id="test-graph",
        defined_entity_types=None,
        enrich_with_edges=True,
        classifications=classifications
    )

    assert result.filtered_count == 2
    # Alice có outgoing edge đến Acme Corp
    alice = next(e for e in result.entities if e.uuid == "uuid-1")
    assert len(alice.related_edges) == 1
    assert alice.related_edges[0]["direction"] == "outgoing"
