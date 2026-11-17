"""Foreign-key graph used to find the tables that connect retrieved tables."""

from collections import Counter, deque
from itertools import combinations

from schema_rag.models import ForeignKey, SchemaCatalog


class SchemaGraph:
    def __init__(self, catalog: SchemaCatalog) -> None:
        self.neighbors: dict[str, set[str]] = {table.name: set() for table in catalog.tables}
        self.keys: list[tuple[str, ForeignKey]] = []
        for table in catalog.tables:
            for key in table.foreign_keys:
                self.keys.append((table.name, key))
                if key.referenced_table in self.neighbors and key.referenced_table != table.name:
                    self.neighbors[table.name].add(key.referenced_table)
                    self.neighbors[key.referenced_table].add(table.name)

    def shortest_path(self, start: str, end: str, max_edges: int) -> list[str] | None:
        """Breadth-first search treats joins as usable in either direction."""
        queue = deque([[start]])
        seen = {start}
        while queue:
            path = queue.popleft()
            if path[-1] == end:
                return path
            if len(path) > max_edges:
                continue
            for neighbor in sorted(self.neighbors.get(path[-1], ())):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(path + [neighbor])
        return None

    def connectors(
        self, seeds: list[str], max_edges: int = 3, max_connectors: int = 5
    ) -> list[str]:
        """Tables on the short join paths between seeds, those used by most paths first.

        Adding every neighbor would pull in hub tables such as customer masters and
        flood the prompt, so only tables that actually link two seeds qualify.
        """
        votes: Counter[str] = Counter()
        for start, end in combinations(seeds, 2):
            path = self.shortest_path(start, end, max_edges)
            if path:
                votes.update(table for table in path[1:-1] if table not in seeds)
        ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
        return [table for table, _ in ranked[:max_connectors]]

    def keys_between(self, tables: list[str]) -> list[tuple[str, ForeignKey]]:
        selected = set(tables)
        return [
            (source, key)
            for source, key in self.keys
            if source in selected and key.referenced_table in selected
        ]
