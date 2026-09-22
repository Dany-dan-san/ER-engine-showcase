from __future__ import annotations

import json
import os
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import pandas as pd


REQUIRED_COMPARISON_COLUMNS = {
    "pair_key",
    "ID_1",
    "ID_2",
    "rf2_probability",
    "rf2_match",
    "rf2_threshold",
}


class GraphResolutionError(RuntimeError):
    """Raised when RF2 pairwise evidence cannot be resolved into entities."""


class UnionFind:
    """Small deterministic union-find helper for reconstructing groups."""

    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root

    def groups(self, order: dict[str, int]) -> list[list[str]]:
        grouped: dict[str, list[str]] = {}
        for item in self.parent:
            grouped.setdefault(self.find(item), []).append(item)

        groups = [
            sorted(group, key=order.__getitem__)
            for group in grouped.values()
        ]
        return sorted(groups, key=lambda group: order[group[0]])


@dataclass(frozen=True)
class CCSolution:
    groups: list[list[str]]
    pair_decisions: list[dict[str, object]]
    objective_value: float
    positive_cut_edges: int
    negative_kept_edges: int
    solver_status: str
    termination_condition: str


def _json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(
        frame.to_json(
            orient="records",
            force_ascii=False,
            date_format="iso",
        )
    )


def _prepare_inputs(
    listings: pd.DataFrame,
    comparisons: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    list[str],
    dict[str, int],
    float | None,
]:
    if "ID" not in listings.columns:
        raise GraphResolutionError(
            "The listing table must contain an 'ID' column."
        )

    working_listings = listings.copy()

    if working_listings["ID"].isna().any():
        raise GraphResolutionError("Every listing must have a non-empty ID.")

    working_listings["ID"] = (
        working_listings["ID"]
        .astype(str)
        .str.strip()
    )

    if (working_listings["ID"] == "").any():
        raise GraphResolutionError("Every listing must have a non-empty ID.")

    if working_listings["ID"].duplicated().any():
        duplicated = working_listings.loc[
            working_listings["ID"].duplicated(keep=False),
            "ID",
        ].tolist()
        raise GraphResolutionError(
            f"Listing IDs must be unique. Duplicates: {duplicated}"
        )

    node_order = working_listings["ID"].tolist()
    order = {
        node_id: index
        for index, node_id in enumerate(node_order)
    }

    working_comparisons = comparisons.copy()

    if working_comparisons.empty:
        for column in REQUIRED_COMPARISON_COLUMNS:
            if column not in working_comparisons.columns:
                working_comparisons[column] = pd.Series(dtype="object")
        return (
            working_listings,
            working_comparisons,
            node_order,
            order,
            None,
        )

    missing_columns = REQUIRED_COMPARISON_COLUMNS - set(
        working_comparisons.columns
    )
    if missing_columns:
        raise GraphResolutionError(
            "The scored comparison table is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    for column in ("ID_1", "ID_2"):
        working_comparisons[column] = (
            working_comparisons[column]
            .astype(str)
            .str.strip()
        )

    known_nodes = set(node_order)
    referenced_nodes = set(working_comparisons["ID_1"]) | set(
        working_comparisons["ID_2"]
    )
    unknown_nodes = sorted(referenced_nodes - known_nodes)
    if unknown_nodes:
        raise GraphResolutionError(
            "The comparison table refers to unknown listing IDs: "
            + ", ".join(unknown_nodes)
        )

    if (
        working_comparisons["ID_1"]
        == working_comparisons["ID_2"]
    ).any():
        raise GraphResolutionError(
            "Self-pairs are not valid RF2 comparisons."
        )

    working_comparisons["rf2_probability"] = pd.to_numeric(
        working_comparisons["rf2_probability"],
        errors="coerce",
    )
    working_comparisons["rf2_match"] = pd.to_numeric(
        working_comparisons["rf2_match"],
        errors="coerce",
    )
    working_comparisons["rf2_threshold"] = pd.to_numeric(
        working_comparisons["rf2_threshold"],
        errors="coerce",
    )

    numeric_columns = [
        "rf2_probability",
        "rf2_match",
        "rf2_threshold",
    ]
    if working_comparisons[numeric_columns].isna().any().any():
        bad = working_comparisons[numeric_columns].columns[
            working_comparisons[numeric_columns].isna().any()
        ].tolist()
        raise GraphResolutionError(
            "The scored comparison table contains missing or invalid values in: "
            + ", ".join(bad)
        )

    invalid_probability = ~working_comparisons[
        "rf2_probability"
    ].between(0, 1)
    if invalid_probability.any():
        raise GraphResolutionError(
            "RF2 probabilities must lie between 0 and 1."
        )

    invalid_match = ~working_comparisons["rf2_match"].isin([0, 1])
    if invalid_match.any():
        raise GraphResolutionError("rf2_match must contain only 0 or 1.")

    thresholds = working_comparisons["rf2_threshold"].unique().tolist()
    if len(thresholds) != 1:
        raise GraphResolutionError(
            "All RF2 comparison rows must use one common threshold."
        )

    threshold = float(thresholds[0])
    if not 0 <= threshold <= 1:
        raise GraphResolutionError(
            "The RF2 threshold must lie between 0 and 1."
        )

    expected_match = (
        working_comparisons["rf2_probability"] >= threshold
    ).astype(int)
    actual_match = working_comparisons["rf2_match"].astype(int)
    if not expected_match.equals(actual_match):
        raise GraphResolutionError(
            "rf2_match is inconsistent with rf2_probability and "
            f"the retained threshold ({threshold})."
        )

    def canonical_pair(row: pd.Series) -> tuple[str, str]:
        left = str(row["ID_1"])
        right = str(row["ID_2"])
        if order[left] < order[right]:
            return left, right
        return right, left

    canonical_pairs = working_comparisons.apply(
        canonical_pair,
        axis=1,
    )
    working_comparisons["_pair"] = canonical_pairs

    if working_comparisons["_pair"].duplicated().any():
        duplicates = working_comparisons.loc[
            working_comparisons["_pair"].duplicated(keep=False),
            ["ID_1", "ID_2"],
        ].to_dict(orient="records")
        raise GraphResolutionError(
            f"Each unordered listing pair must appear once. Duplicates: {duplicates}"
        )

    working_comparisons["rf2_match"] = actual_match

    return (
        working_listings,
        working_comparisons,
        node_order,
        order,
        threshold,
    )


def _positive_components(
    node_order: list[str],
    comparisons: pd.DataFrame,
    order: dict[str, int],
) -> list[list[str]]:
    adjacency = {
        node_id: set()
        for node_id in node_order
    }

    for row in comparisons.itertuples(index=False):
        if int(getattr(row, "rf2_match")) != 1:
            continue
        left = str(getattr(row, "ID_1"))
        right = str(getattr(row, "ID_2"))
        adjacency[left].add(right)
        adjacency[right].add(left)

    seen: set[str] = set()
    components: list[list[str]] = []

    for start in node_order:
        if start in seen:
            continue

        stack = [start]
        seen.add(start)
        component: list[str] = []

        while stack:
            node = stack.pop()
            component.append(node)

            neighbors = sorted(
                adjacency[node],
                key=order.__getitem__,
                reverse=True,
            )
            for neighbor in neighbors:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)

        components.append(
            sorted(component, key=order.__getitem__)
        )

    return components


def _internal_comparisons(
    component_nodes: list[str],
    comparisons: pd.DataFrame,
) -> pd.DataFrame:
    node_set = set(component_nodes)
    internal = comparisons.loc[
        comparisons["ID_1"].isin(node_set)
        & comparisons["ID_2"].isin(node_set)
    ].copy()

    expected_pair_count = (
        len(component_nodes)
        * (len(component_nodes) - 1)
        // 2
    )

    if len(internal) != expected_pair_count:
        raise GraphResolutionError(
            "An RF2-positive component does not have probabilities for every "
            "internal unordered pair. "
            f"Nodes={component_nodes}; expected={expected_pair_count}; "
            f"received={len(internal)}."
        )

    return internal


def _solve_incomplete_component(
    *,
    component_id: str,
    component_nodes: list[str],
    internal: pd.DataFrame,
    order: dict[str, int],
) -> CCSolution:
    try:
        import pyomo.environ as pyo
        from pyomo.opt import SolverStatus, TerminationCondition
    except ImportError as exc:
        raise GraphResolutionError(
            "Correlation clustering requires Pyomo. Add 'pyomo' to "
            "requirements.txt and rebuild the Docker image."
        ) from exc

    maximum_nodes = int(
        os.getenv("CC_MAX_COMPONENT_NODES", "40")
    )
    if len(component_nodes) > maximum_nodes:
        raise GraphResolutionError(
            f"Incomplete component {component_id} contains "
            f"{len(component_nodes)} nodes, above the configured exact-CC "
            f"limit of {maximum_nodes}. Increase CC_MAX_COMPONENT_NODES only "
            "after assessing solver memory and runtime."
        )

    pair_probability: dict[tuple[str, str], float] = {}
    pair_match: dict[tuple[str, str], int] = {}
    pair_key: dict[tuple[str, str], str] = {}

    for row in internal.to_dict(orient="records"):
        pair = row["_pair"]
        pair_probability[pair] = float(row["rf2_probability"])
        pair_match[pair] = int(row["rf2_match"])
        pair_key[pair] = str(row["pair_key"])

    pairs = sorted(
        pair_probability,
        key=lambda pair: (order[pair[0]], order[pair[1]]),
    )
    positive_pairs = [
        pair for pair in pairs
        if pair_match[pair] == 1
    ]
    negative_pairs = [
        pair for pair in pairs
        if pair_match[pair] == 0
    ]

    def ordered_pair(left: str, right: str) -> tuple[str, str]:
        if order[left] < order[right]:
            return left, right
        return right, left

    model = pyo.ConcreteModel(
        name=f"GER_CC_{component_id}"
    )
    model.N = pyo.Set(
        initialize=component_nodes,
        ordered=True,
    )
    model.P = pyo.Set(
        dimen=2,
        initialize=pairs,
        ordered=True,
    )
    model.Ppos = pyo.Set(
        dimen=2,
        initialize=positive_pairs,
        ordered=True,
    )
    model.Pneg = pyo.Set(
        dimen=2,
        initialize=negative_pairs,
        ordered=True,
    )
    model.p = pyo.Param(
        model.P,
        initialize=pair_probability,
        within=pyo.UnitInterval,
    )
    model.z = pyo.Var(
        model.P,
        domain=pyo.Binary,
    )

    model.objective = pyo.Objective(
        expr=(
            sum(
                model.p[pair] * (1 - model.z[pair])
                for pair in model.Ppos
            )
            + sum(
                (1 - model.p[pair]) * model.z[pair]
                for pair in model.Pneg
            )
        ),
        sense=pyo.minimize,
    )

    model.triangle_consistency = pyo.ConstraintList()
    for first, second, third in combinations(component_nodes, 3):
        first_second = ordered_pair(first, second)
        second_third = ordered_pair(second, third)
        first_third = ordered_pair(first, third)

        model.triangle_consistency.add(
            model.z[first_second]
            + model.z[second_third]
            - model.z[first_third]
            <= 1
        )
        model.triangle_consistency.add(
            model.z[first_second]
            + model.z[first_third]
            - model.z[second_third]
            <= 1
        )
        model.triangle_consistency.add(
            model.z[first_third]
            + model.z[second_third]
            - model.z[first_second]
            <= 1
        )

    solver_name = os.getenv("CC_SOLVER", "glpk")
    solver = pyo.SolverFactory(solver_name)

    if not solver.available(exception_flag=False):
        raise GraphResolutionError(
            f"The correlation-clustering solver {solver_name!r} is not "
            "available. For GLPK, install the Linux package 'glpk-utils' "
            "inside the Docker image."
        )

    timeout_seconds = int(
        os.getenv("CC_SOLVER_TIMEOUT_SECONDS", "30")
    )
    if solver_name.casefold() == "glpk":
        solver.options["tmlim"] = timeout_seconds

    results = solver.solve(
        model,
        tee=False,
        load_solutions=True,
    )

    solver_status = str(results.solver.status)
    termination_condition = str(
        results.solver.termination_condition
    )

    if (
        results.solver.status != SolverStatus.ok
        or results.solver.termination_condition
        != TerminationCondition.optimal
    ):
        raise GraphResolutionError(
            f"Correlation clustering failed for {component_id}. "
            f"Solver status={solver_status}; "
            f"termination={termination_condition}."
        )

    union_find = UnionFind(component_nodes)
    pair_decisions: list[dict[str, object]] = []
    positive_cut_edges = 0
    negative_kept_edges = 0

    for pair in pairs:
        z_value_raw = pyo.value(model.z[pair])
        if z_value_raw is None:
            raise GraphResolutionError(
                f"The solver returned no z decision for pair {pair}."
            )

        z_value = int(round(float(z_value_raw)))
        probability = pair_probability[pair]
        rf2_match = pair_match[pair]

        if z_value == 1:
            union_find.union(pair[0], pair[1])

        if rf2_match == 1:
            pair_type = "internal_positive_edge"
            contradiction_cost = probability * (1 - z_value)
            if z_value == 0:
                positive_cut_edges += 1
        else:
            pair_type = "internal_negative_gap"
            contradiction_cost = (1 - probability) * z_value
            if z_value == 1:
                negative_kept_edges += 1

        pair_decisions.append(
            {
                "component_id": component_id,
                "pair_key": pair_key[pair],
                "ID_1": pair[0],
                "ID_2": pair[1],
                "rf2_probability": probability,
                "rf2_match": rf2_match,
                "internal_pair_type": pair_type,
                "z_same_group": z_value,
                "contradiction_cost": contradiction_cost,
            }
        )

    groups = union_find.groups(order)

    return CCSolution(
        groups=groups,
        pair_decisions=pair_decisions,
        objective_value=float(pyo.value(model.objective)),
        positive_cut_edges=positive_cut_edges,
        negative_kept_edges=negative_kept_edges,
        solver_status=solver_status,
        termination_condition=termination_condition,
    )


def resolve_graph_entities(
    listings: pd.DataFrame,
    comparisons: pd.DataFrame,
) -> dict[str, object]:
    """
    Apply the GER-CC regime to scored RF2 pairwise evidence.

    1. Build the RF2-positive graph from rf2_match == 1 edges.
    2. Keep complete positive components as one entity.
    3. Send incomplete positive components to exact weighted correlation
       clustering with triangle-consistency constraints.
    4. Keep listings without any positive relation as singleton entities.
    """
    (
        working_listings,
        working_comparisons,
        node_order,
        order,
        threshold,
    ) = _prepare_inputs(listings, comparisons)

    positive_components = _positive_components(
        node_order,
        working_comparisons,
        order,
    )

    component_summaries: list[dict[str, object]] = []
    pending_groups: list[dict[str, object]] = []
    cc_pair_decisions: list[dict[str, object]] = []

    complete_component_count = 0
    incomplete_component_count = 0
    singleton_component_count = 0

    for component_number, nodes in enumerate(
        positive_components,
        start=1,
    ):
        component_id = f"COMP_{component_number:03d}"

        if len(nodes) == 1:
            singleton_component_count += 1
            groups = [nodes]
            component_type = "singleton"
            resolution_method = "singleton_no_positive_relation"
            internal_pair_count = 0
            positive_pair_count = 0
            negative_pair_count = 0
            objective_value = 0.0
            positive_cut_edges = 0
            negative_kept_edges = 0
            solver_status = "not_required"
            termination_condition = "not_required"
        else:
            internal = _internal_comparisons(
                nodes,
                working_comparisons,
            )
            positive_pair_count = int(
                (internal["rf2_match"] == 1).sum()
            )
            negative_pair_count = int(
                (internal["rf2_match"] == 0).sum()
            )
            internal_pair_count = len(internal)

            if negative_pair_count == 0:
                complete_component_count += 1
                groups = [nodes]
                component_type = "complete"
                resolution_method = "complete_positive_component"
                objective_value = 0.0
                positive_cut_edges = 0
                negative_kept_edges = 0
                solver_status = "not_required"
                termination_condition = "not_required"
            else:
                incomplete_component_count += 1
                solution = _solve_incomplete_component(
                    component_id=component_id,
                    component_nodes=nodes,
                    internal=internal,
                    order=order,
                )
                groups = solution.groups
                component_type = "incomplete_problematic"
                resolution_method = "correlation_clustering"
                objective_value = solution.objective_value
                positive_cut_edges = solution.positive_cut_edges
                negative_kept_edges = solution.negative_kept_edges
                solver_status = solution.solver_status
                termination_condition = solution.termination_condition
                cc_pair_decisions.extend(solution.pair_decisions)

        component_summary = {
            "component_id": component_id,
            "component_type": component_type,
            "resolution_method": resolution_method,
            "node_count": len(nodes),
            "node_ids": nodes,
            "internal_pair_count": internal_pair_count,
            "positive_pair_count": positive_pair_count,
            "negative_pair_count": negative_pair_count,
            "final_group_count": len(groups),
            "objective_value": objective_value,
            "positive_cut_edges": positive_cut_edges,
            "negative_kept_edges": negative_kept_edges,
            "solver_status": solver_status,
            "termination_condition": termination_condition,
            "final_entity_ids": [],
        }
        component_summaries.append(component_summary)

        for local_group_number, group_nodes in enumerate(
            groups,
            start=1,
        ):
            pending_groups.append(
                {
                    "component_id": component_id,
                    "component_type": component_type,
                    "resolution_method": resolution_method,
                    "local_group_number": local_group_number,
                    "listing_ids": sorted(
                        group_nodes,
                        key=order.__getitem__,
                    ),
                }
            )

    listing_records = {
        str(record["ID"]): record
        for record in _json_records(working_listings)
    }

    entities: list[dict[str, object]] = []
    membership_metadata: dict[str, dict[str, object]] = {}
    component_by_id = {
        summary["component_id"]: summary
        for summary in component_summaries
    }

    for entity_number, pending in enumerate(
        pending_groups,
        start=1,
    ):
        entity_id = f"ENTITY_{entity_number:03d}"
        listing_ids = list(pending["listing_ids"])
        group_size = len(listing_ids)
        entity_listings = [
            listing_records[listing_id]
            for listing_id in listing_ids
        ]

        entity = {
            "entity_id": entity_id,
            "component_id": pending["component_id"],
            "component_type": pending["component_type"],
            "resolution_method": pending["resolution_method"],
            "local_group_number": pending["local_group_number"],
            "group_size": group_size,
            "is_singleton": group_size == 1,
            "listing_ids": listing_ids,
            "listings": entity_listings,
        }
        entities.append(entity)

        component_by_id[pending["component_id"]][
            "final_entity_ids"
        ].append(entity_id)

        for listing_id in listing_ids:
            membership_metadata[listing_id] = {
                "entity_id": entity_id,
                "entity_size": group_size,
                "is_singleton": group_size == 1,
                "component_id": pending["component_id"],
                "component_type": pending["component_type"],
                "resolution_method": pending["resolution_method"],
            }

    regrouped_listings: list[dict[str, object]] = []
    memberships: list[dict[str, object]] = []

    for listing_id in node_order:
        metadata = membership_metadata[listing_id]
        listing_record = listing_records[listing_id]

        memberships.append(
            {
                "ID": listing_id,
                **metadata,
            }
        )
        regrouped_listings.append(
            {
                **metadata,
                **listing_record,
            }
        )

    duplicate_entity_count = sum(
        int(entity["group_size"] > 1)
        for entity in entities
    )
    singleton_entity_count = sum(
        int(entity["group_size"] == 1)
        for entity in entities
    )

    return {
        "regime": "GER-CC",
        "rf2_threshold": threshold,
        "rf2_positive_component_count": len(positive_components),
        "complete_component_count": complete_component_count,
        "incomplete_problematic_component_count": (
            incomplete_component_count
        ),
        "singleton_component_count": singleton_component_count,
        "final_entity_count": len(entities),
        "duplicate_entity_count": duplicate_entity_count,
        "singleton_entity_count": singleton_entity_count,
        "components": component_summaries,
        "entities": entities,
        "memberships": memberships,
        "regrouped_listings": regrouped_listings,
        "cc_pair_decisions": cc_pair_decisions,
    }
