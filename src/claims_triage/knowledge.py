"""Small, transparent TF-IDF vector index over local knowledge documents."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .domain import AppError, Json, money, parse_date

KINDS = {
    "coverage_types",
    "limit",
    "active_period",
    "inception",
    "near_limit",
    "repeat",
    "late_report",
    "human_gate",
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))


class FileVectorKnowledge:
    def __init__(self, directory: Path):
        try:
            payload = (directory / "rules.json").read_bytes()
            markdown = (directory / "underwriting_rules.md").read_bytes()
            self.version = hashlib.sha256(payload + markdown).hexdigest()
            self.rules: list[Json] = json.loads(payload)
            if len(self.rules) != 8 or {r["kind"] for r in self.rules} != KINDS:
                raise ValueError("Incomplete knowledge catalog")
            ids = [r["id"] for r in self.rules]
            if len(set(ids)) != len(ids) or any(f"## {rid} ".encode() not in markdown for rid in ids):
                raise ValueError("Knowledge IDs mismatch")
            for rule in self.rules:
                if not all(isinstance(rule[k], str) and rule[k] for k in ("id", "kind", "title", "text")):
                    raise ValueError("Missing rule content")
                params = rule["parameters"]
                if rule["kind"] in {"inception", "repeat", "late_report"}:
                    if type(params.get("days")) is not int or not 0 <= params["days"] <= 3650:
                        raise ValueError("Invalid threshold")
                elif rule["kind"] == "near_limit":
                    if type(params.get("percent")) not in (int, float) or not 0 < params["percent"] < 100:
                        raise ValueError("Invalid percent")
                elif rule["kind"] == "coverage_types":
                    if not params or any(
                        not isinstance(v, list) or not v or any(not isinstance(x, str) for x in v)
                        for v in params.values()
                    ):
                        raise ValueError("Invalid peril mapping")
                rule.update(source="knowledge/rules.json#" + rule["id"], version=self.version)
            counts = [Counter(tokens(r["kind"] + " " + r["title"] + " " + r["text"])) for r in self.rules]
            vocab = set().union(*(set(c) for c in counts))
            self.idf = {
                word: math.log((1 + len(counts)) / (1 + sum(word in c for c in counts))) + 1 for word in vocab
            }
            self.vectors = [self._vector(c) for c in counts]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AppError(
                "invalid_knowledge", "Knowledge files are missing, incomplete, or invalid.", 503
            ) from exc

    def _vector(self, counts: Counter[str]) -> dict[str, float]:
        vector = {word: count * self.idf[word] for word, count in counts.items() if word in self.idf}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1
        return {word: value / norm for word, value in vector.items()}

    def search(self, query: str, limit: int = 8) -> list[Json]:
        query_vector = self._vector(Counter(tokens(query)))
        scored = [
            (sum(value * query_vector.get(word, 0) for word, value in vector.items()), rule)
            for rule, vector in zip(self.rules, self.vectors, strict=True)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [dict(rule, score=round(score, 6)) for score, rule in scored[:limit]]

    def applicable_rules(self, claim: Json, policy: Json) -> list[Json]:
        # This tiny catalog is exhaustively retrieved, ranked by vector similarity.
        # Never drop low-similarity mandatory policy rules through a top-k cutoff.
        return self.search(
            f"{claim['claim_type']} {policy['coverage_type']} coverage limit active period inception repeat late report human review",
            len(self.rules),
        )


def load_policies(path: Path) -> dict[str, Json]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        policies = {}
        for row in rows:
            number = row["policy_number"]
            if not re.fullmatch(r"POL-\d{1,20}", number) or number in policies:
                raise ValueError("Invalid policy identifier")
            if row["coverage_type"] not in {"homeowners", "auto"}:
                raise ValueError("Unsupported policy coverage")
            money(row["policy_limit"])
            if parse_date(row["active_from"]) > parse_date(row["active_to"]):
                raise ValueError("Invalid policy dates")
            policies[number] = row
        if not policies:
            raise ValueError("Empty catalog")
        return policies
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AppError("invalid_policies", "Synthetic policy catalog is missing or invalid.", 503) from exc
