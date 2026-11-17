from schema_rag.retrieval.graph import SchemaGraph


def test_graph_finds_connector_between_seeds(catalog):
    assert SchemaGraph(catalog).connectors(["customers", "order_items"]) == ["orders"]


def test_graph_respects_max_edges(catalog):
    graph = SchemaGraph(catalog)

    assert graph.shortest_path("customers", "products", 3) is not None
    assert graph.shortest_path("customers", "products", 2) is None


def test_graph_ignores_unconnected_seeds(catalog):
    assert SchemaGraph(catalog).connectors(["customers", "shipments"]) == []
