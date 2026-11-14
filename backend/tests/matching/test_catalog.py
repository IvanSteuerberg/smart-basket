"""The classifier against the synthetic catalog: assignments, reviews, reports and decisions."""

import json

import pytest
from sqlalchemy import text

from smart_basket.config import Settings
from smart_basket.matching import (
    DecisionFileError,
    export_decisions,
    export_review,
    import_decisions,
    load_products,
    load_taxonomy,
    run,
    sync_decisions,
)

pytestmark = pytest.mark.db


def assignment(session, sku: str):
    return (
        session.execute(
            text(
                "select cp.canonical_id, cp.match_method, cp.match_confidence, "
                "  cat.key as category_key, c.name as canonical_name, c.variant_key "
                "from chain_product cp "
                "left join canonical_product c on c.id = cp.canonical_id "
                "left join category cat on cat.id = c.category_id "
                "where cp.chain_sku = :sku"
            ),
            {"sku": sku},
        )
        .mappings()
        .one()
    )


def count(session, table: str) -> int:
    return session.execute(text(f"select count(*) from {table}")).scalar_one()


def test_bananas_from_the_fruit_group_land_in_their_leaf(catalog):
    run(catalog.session)
    row = assignment(catalog.session, "M1")
    assert row["category_key"] == "platano"
    assert row["canonical_name"] == "Plátano"
    assert row["variant_key"] == ""
    assert row["match_method"] == "rule"
    assert row["match_confidence"] == pytest.approx(0.9)


def test_milk_without_lactose_gets_the_variant(catalog):
    run(catalog.session)
    row = assignment(catalog.session, "M2")
    assert row["category_key"] == "leche"
    assert row["variant_key"] == "sin_lactosa"
    assert row["canonical_name"] == "Leche — sin lactosa"


def test_a_flavour_gets_its_own_canonical(catalog):
    run(catalog.session)
    row = assignment(catalog.session, "M3")
    assert row["category_key"] == "petit_suisse"
    assert row["variant_key"] == "sabor:fresa"
    assert row["canonical_name"] == "Petit suisse — sabor fresa"


def test_the_longest_leaf_form_wins(catalog):
    run(catalog.session)
    assert assignment(catalog.session, "M9")["category_key"] == "leche_condensada"


def test_a_section_leaf_fills_a_vague_name(catalog):
    run(catalog.session)
    row = assignment(catalog.session, "M4")
    assert row["category_key"] == "platano"
    assert row["match_confidence"] == pytest.approx(0.8)


def test_a_sibling_leaf_inside_the_parent_group_is_allowed(catalog):
    run(catalog.session)
    row = assignment(catalog.session, "M6")
    assert row["category_key"] == "pavo"
    assert row["match_confidence"] == pytest.approx(0.9)


def test_every_product_ends_in_an_allowed_leaf_or_in_review(catalog):
    result = run(catalog.session)
    taxonomy = load_taxonomy(catalog.session)
    reviewed = {item.product_id for item in result.review}
    for product in load_products(catalog.session):
        if product.id in reviewed:
            assert product.canonical_id is None, product.sku
            continue
        leaf = catalog.session.execute(
            text(
                "select cat.key from canonical_product c "
                "join category cat on cat.id = c.category_id where c.id = :id"
            ),
            {"id": product.canonical_id},
        ).scalar_one()
        assert leaf in taxonomy.leaf_keys, product.sku
        assert leaf in taxonomy.section(product.category_id).allowed_leaves, product.sku


def test_an_outside_leaf_a_group_section_and_a_tie_go_to_review(catalog):
    result = run(catalog.session)
    reviewed = {item.product_id: item for item in result.review}
    expected = {catalog.products["M5"], catalog.products["M7"], catalog.products["M8"]}
    assert set(reviewed) == expected
    outside = reviewed[catalog.products["M5"]]
    assert outside.candidates[0].category_key == "galletas"
    assert outside.section == "Queso"
    assert assignment(catalog.session, "M5")["canonical_id"] is None
    group = reviewed[catalog.products["M7"]]
    assert {candidate.category_key for candidate in group.candidates} == {
        "platano",
        "manzana",
        "uva",
    }
    tie = reviewed[catalog.products["M8"]]
    assert {candidate.category_key for candidate in tie.candidates} == {"platano", "manzana"}


def test_the_summary_counts_every_product(catalog):
    result = run(catalog.session)
    assert str(result.summary) == "products 9, assigned 6 (66.7 %), review 3, unchanged 0"


def test_a_dry_run_decides_without_writing(catalog):
    result = run(catalog.session, dry_run=True)
    assert result.summary.assigned == 6
    assert result.summary.review == 3
    assert len(result.review) == 3
    assert count(catalog.session, "canonical_product") == 0
    assert count(catalog.session, "product_match") == 0
    assert count(catalog.session, "match_review") == 0


def test_two_runs_give_the_same_canonicals_and_no_extra_matches(catalog):
    first = run(catalog.session)
    canonicals = count(catalog.session, "canonical_product")
    matches = count(catalog.session, "product_match")
    second = run(catalog.session)
    assert first.summary.assigned == 6
    assert second.summary.assigned == 0
    assert second.summary.review == 0
    assert second.summary.unchanged == second.summary.products == 9
    assert count(catalog.session, "canonical_product") == canonicals
    assert count(catalog.session, "product_match") == matches
    assert {leaf.category_key for leaf in second.leaves} == {
        leaf.category_key for leaf in first.leaves
    }


def test_the_report_groups_products_by_leaf_and_carries_the_reviews(catalog, tmp_path):
    path = tmp_path / "report.json"
    run(catalog.session).write_report(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    leaves = {leaf["category_key"]: leaf for leaf in data["leaves"]}
    assert set(leaves) == {"leche", "leche_condensada", "petit_suisse", "platano", "pavo"}
    platano = leaves["platano"]
    assert platano["name"] == "Plátano"
    assert platano["assigned"] == 2
    assert platano["products"] == ["Plátano de Canarias IGP", "Fruta de temporada"]
    assert {item["product_id"] for item in data["review"]} == {
        catalog.products["M5"],
        catalog.products["M7"],
        catalog.products["M8"],
    }


def test_export_review_writes_the_pending_reviews(catalog, tmp_path):
    run(catalog.session)
    path = tmp_path / "review.json"
    assert export_review(catalog.session, path) == 3
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {item["sku"] for item in data} == {"M5", "M7", "M8"}
    assert all({"product_id", "sku", "name", "section", "candidates"} == set(item) for item in data)


def test_import_decisions_then_run_keeps_the_human_decision(catalog, tmp_path):
    run(catalog.session)
    galletas = catalog.products["M5"]
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {"product_id": galletas, "category_key": "galletas", "variant_key": ""},
                {
                    "product_id": catalog.products["M1"],
                    "category_key": "platano",
                    "variant_key": "",
                },
            ]
        ),
        encoding="utf-8",
    )
    assert import_decisions(catalog.session, path) == 2

    row = assignment(catalog.session, "M5")
    assert row["category_key"] == "galletas"
    assert row["match_method"] == "review"
    assert row["match_confidence"] == 1.0
    status = catalog.session.execute(
        text("select status from match_review where chain_product_id = :product"),
        {"product": galletas},
    ).scalar_one()
    assert status == "accepted"
    # The same canonical a rule had chosen still becomes a human decision.
    same = assignment(catalog.session, "M1")
    assert same["category_key"] == "platano"
    assert same["match_method"] == "review"
    assert same["match_confidence"] == 1.0
    matches = count(catalog.session, "product_match")

    second = run(catalog.session)
    row = assignment(catalog.session, "M5")
    assert row["category_key"] == "galletas"
    assert row["match_method"] == "review"
    assert galletas not in {item.product_id for item in second.review}
    assert assignment(catalog.session, "M1")["match_method"] == "review"
    assert count(catalog.session, "product_match") == matches


def test_an_unknown_key_is_an_error_that_names_the_line(catalog, tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "product_id": catalog.products["M1"],
                    "category_key": "platano",
                    "variant_key": "",
                },
                {
                    "product_id": catalog.products["M2"],
                    "category_key": "no_existe",
                    "variant_key": "",
                },
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DecisionFileError, match="line 2: unknown category key"):
        import_decisions(catalog.session, path)


def test_an_unknown_variant_or_product_is_an_error(catalog, tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "product_id": catalog.products["M1"],
                    "category_key": "platano",
                    "variant_key": "raro",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DecisionFileError, match="line 1: unknown variant key 'raro'"):
        import_decisions(catalog.session, path)

    path.write_text(
        json.dumps([{"product_id": 999_999, "category_key": "platano", "variant_key": ""}]),
        encoding="utf-8",
    )
    with pytest.raises(DecisionFileError, match="line 1: product 999999 does not exist"):
        import_decisions(catalog.session, path)


def test_a_pending_review_the_rules_now_resolve_is_assigned_and_dropped(catalog):
    # A review opened by an older rule: the next run decides the product again.
    product = catalog.products["M1"]
    catalog.session.execute(
        text("insert into match_review (chain_product_id, candidates) values (:p, '[]')"),
        {"p": product},
    )
    result = run(catalog.session)

    assert assignment(catalog.session, "M1")["category_key"] == "platano"
    assert product not in {item.product_id for item in result.review}
    pending = catalog.session.execute(
        text("select count(*) from match_review where chain_product_id = :p"), {"p": product}
    ).scalar_one()
    assert pending == 0


def test_a_pending_review_still_in_doubt_stays_and_counts_as_unchanged(catalog):
    run(catalog.session)
    second = run(catalog.session)
    assert second.summary.unchanged == second.summary.products
    assert {item.product_id for item in second.review} >= {catalog.products["M5"]}


def test_a_decision_without_variants_reads_them_from_the_name(catalog, tmp_path):
    # The human chose the leaf only; "sin lactosa" still makes its own canonical.
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps([{"product_id": catalog.products["M2"], "category_key": "leche"}]),
        encoding="utf-8",
    )
    assert import_decisions(catalog.session, path) == 1
    row = assignment(catalog.session, "M2")
    assert row["category_key"] == "leche"
    assert row["variant_key"] == "sin_lactosa"
    assert row["match_method"] == "review"


def test_import_decisions_by_chain_and_sku(catalog, tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "chain": "mercadona",
                    "sku": "M1",
                    "category_key": "platano",
                    "variant_key": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = import_decisions(catalog.session, path)
    assert result == 1
    row = assignment(catalog.session, "M1")
    assert row["category_key"] == "platano"
    assert row["match_method"] == "review"
    assert row["match_confidence"] == 1.0


def test_import_decisions_skip_missing_and_error(catalog, tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "chain": "mercadona",
                    "sku": "UNKNOWN_SKU",
                    "category_key": "platano",
                },
                {
                    "chain": "mercadona",
                    "sku": "M1",
                    "category_key": "platano",
                },
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        DecisionFileError, match="line 1: product 'mercadona' 'UNKNOWN_SKU' does not exist"
    ):
        import_decisions(catalog.session, path, skip_missing=False)

    summary = import_decisions(catalog.session, path, skip_missing=True)
    assert summary.applied == 1
    assert summary.skipped == 1
    assert assignment(catalog.session, "M1")["match_method"] == "review"


def test_import_decisions_fails_on_unknown_category_even_with_skip_missing(catalog, tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "chain": "mercadona",
                    "sku": "M1",
                    "category_key": "unknown_cat",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DecisionFileError, match="line 1: unknown category key 'unknown_cat'"):
        import_decisions(catalog.session, path, skip_missing=True)


def test_export_decisions_roundtrip(catalog, tmp_path):
    # Establish a review match
    in_path = tmp_path / "input.json"
    in_path.write_text(
        json.dumps(
            [
                {
                    "chain": "mercadona",
                    "sku": "M1",
                    "category_key": "platano",
                    "variant_key": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    import_decisions(catalog.session, in_path)

    out_path = tmp_path / "exported.json"
    count = export_decisions(catalog.session, out_path)
    assert count >= 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert any(
        item["chain"] == "mercadona" and item["sku"] == "M1" and item["category_key"] == "platano"
        for item in data
    )

    # Re-importing on the same base maintains the same assignment
    re_applied = import_decisions(catalog.session, out_path)
    assert re_applied == count
    row = assignment(catalog.session, "M1")
    assert row["category_key"] == "platano"
    assert row["match_method"] == "review"


def test_sync_decisions_without_file(catalog, capsys):
    settings = Settings(match_decisions_file=None)
    result = sync_decisions(catalog.session, settings)
    assert result is None
    captured = capsys.readouterr()
    assert "no decisions file" in captured.out


def test_sync_decisions_outside_data_dir_raises_error(catalog, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    settings = Settings(data_dir=data_dir, match_decisions_file=outside)
    with pytest.raises(ValueError, match="must be inside DATA_DIR"):
        sync_decisions(catalog.session, settings)


def test_sync_decisions_applies_and_runs(catalog, tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    dec_file = data_dir / "decisions.json"
    dec_file.write_text(
        json.dumps(
            [
                {"chain": "mercadona", "sku": "M5", "category_key": "galletas", "variant_key": ""},
                {"chain": "mercadona", "sku": "MISSING", "category_key": "platano"},
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(data_dir=data_dir, match_decisions_file=dec_file)
    result = sync_decisions(catalog.session, settings)
    assert result is not None
    captured = capsys.readouterr()
    assert "decisions applied: 1, skipped: 1" in captured.out
    assert assignment(catalog.session, "M5")["match_method"] == "review"
