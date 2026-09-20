"""Proves the DB-level backstops added on top of the service-layer checks:
the immutability trigger, the partial unique index, and the category-table
CHECK constraints. Each test deliberately goes around the API (raw SQL
against `db_session`) to prove the database itself refuses the bad state,
not just the service code that normally guards it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_parameters import _create_habitation, _create_parameter_set


async def _fill_and_commit(client, headers, psid):
    await client.put(
        f"/api/v1/parameter-sets/{psid}/categories/demography",
        json={"population": 1000, "annual_growth_rate_pct": 1.5},
        headers=headers,
    )
    await client.put(
        f"/api/v1/parameter-sets/{psid}/waste-baseline",
        json={"per_capita_generation_kg_day": 0.4},
        headers=headers,
    )
    await client.post(f"/api/v1/parameter-sets/{psid}/validate", headers=headers)
    commit_resp = await client.post(f"/api/v1/parameter-sets/{psid}/commit", headers=headers)
    assert commit_resp.status_code == 200, commit_resp.text


async def test_raw_sql_cannot_edit_demography_on_a_validated_set(client, planner_headers, db_session):
    habitation_id = await _create_habitation(client, planner_headers, "Triggerville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)
    await _fill_and_commit(client, planner_headers, psid)

    # _assert_editable() in service.py would refuse this with a 409 through
    # the API; going around it with raw SQL proves the BEFORE UPDATE trigger
    # is the one actually stopping the write, not just application code.
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE demography SET population = 999999 WHERE parameter_set_id = CAST(:psid AS uuid)"),
            {"psid": psid},
        )
        await db_session.flush()
    await db_session.rollback()


async def test_raw_sql_cannot_create_a_second_validated_set_for_one_habitation(
    client, planner_headers, db_session
):
    habitation_id = await _create_habitation(client, planner_headers, "Uniqueville")
    psid_1 = await _create_parameter_set(client, planner_headers, habitation_id)
    await _fill_and_commit(client, planner_headers, psid_1)

    psid_2 = await _create_parameter_set(client, planner_headers, habitation_id)

    # commit_parameter_set() always archives the previous VALIDATED set in
    # the same transaction, so the API path can never reach this state. The
    # partial unique index is what stops it even if that safeguard were
    # bypassed — e.g. by a bug in a future module that writes status
    # directly.
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE parameter_sets SET status = 'VALIDATED' WHERE id = CAST(:id AS uuid)"),
            {"id": psid_2},
        )
        await db_session.flush()
    await db_session.rollback()


async def test_population_must_be_positive(client, planner_headers, db_session):
    habitation_id = await _create_habitation(client, planner_headers, "Negpopville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("INSERT INTO demography (parameter_set_id, population) VALUES (CAST(:psid AS uuid), -5)"),
            {"psid": psid},
        )
        await db_session.flush()
    await db_session.rollback()


async def test_waste_baseline_requires_a_generation_value(client, planner_headers, db_session):
    habitation_id = await _create_habitation(client, planner_headers, "Nogenville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("INSERT INTO waste_baseline (parameter_set_id) VALUES (CAST(:psid AS uuid))"),
            {"psid": psid},
        )
        await db_session.flush()
    await db_session.rollback()


async def test_composition_must_sum_to_100(client, planner_headers, db_session):
    habitation_id = await _create_habitation(client, planner_headers, "Badmixville")
    psid = await _create_parameter_set(client, planner_headers, habitation_id)

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "INSERT INTO waste_baseline (parameter_set_id, per_capita_generation_kg_day, composition) "
                "VALUES (CAST(:psid AS uuid), 0.4, CAST(:comp AS jsonb))"
            ),
            {"psid": psid, "comp": '{"organic": 50, "plastic": 10}'},  # sums to 60, not 100
        )
        await db_session.flush()
    await db_session.rollback()
