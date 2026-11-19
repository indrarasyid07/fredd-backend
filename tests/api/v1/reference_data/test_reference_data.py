"""Reference data: platform regions with boundaries, point lookup, commodities and units.

Regions are synthetic (code 99, in open sea south of Java) so tests never depend on the full
Kemendagri seed: a 1x1 degree province split into two regencies, one with two districts.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reference_data import service
from app.modules.reference_data.models import ReferenceData
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in

URL = "/api/v1/reference-data"


def _square(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def _feature(code: str, name: str, box: tuple[float, float, float, float]) -> dict[str, Any]:
    x0, y0, x1, y1 = box
    return {
        "type": "Feature",
        "properties": {"code": code, "name": name, "centroid": [(x0 + x1) / 2, (y0 + y1) / 2]},
        "geometry": _square(*box),
    }


FEATURES = [
    _feature("99", "Provinsi Uji", (100.0, -12.0, 101.0, -11.0)),
    _feature("99.01", "Kabupaten Barat", (100.0, -12.0, 100.5, -11.0)),
    _feature("99.02", "Kabupaten Timur", (100.5, -12.0, 101.0, -11.0)),
    _feature("99.01.01", "Kecamatan Utara", (100.0, -11.5, 100.5, -11.0)),
    _feature("99.01.02", "Kecamatan Selatan", (100.0, -12.0, 100.5, -11.5)),
]


@pytest.fixture
async def regions(db: AsyncSession) -> None:
    await service.seed_platform_regions(db, FEATURES)
    await service.seed_platform_items(
        db, "commodity", [{"code": "rice", "value": "Padi", "aliases": ["Pari", "gabah"]}]
    )
    await service.seed_platform_items(db, "unit", [{"code": "ha", "value": "ha"}])


@pytest.fixture
async def reviewer(client: AsyncClient, db: AsyncSession, organization: Workspace) -> AsyncClient:
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    return await sign_in(client, "rani@contoh.id", organization.id)


async def test_seed_builds_the_tree_and_is_idempotent(db: AsyncSession, regions: None) -> None:
    await service.seed_platform_regions(db, FEATURES)

    count = await db.scalar(select(func.count()).where(ReferenceData.code.like("99%")))
    assert count == len(FEATURES)
    rows = {
        r.code: r
        for r in await db.scalars(select(ReferenceData).where(ReferenceData.code.like("99%")))
    }
    assert rows["99.01.02"].parent_id == rows["99.01"].id
    assert rows["99.01"].parent_id == rows["99"].id
    assert (rows["99"].level, rows["99.01"].level, rows["99.01.01"].level) == (
        "province",
        "regency",
        "district",
    )


@pytest.mark.parametrize(
    ("lat", "lng", "district", "regency"),
    [
        (-11.2, 100.2, "99.01.01", "99.01"),  # inside
        (-11.8, 100.2, "99.01.02", "99.01"),  # the other district
        (-11.5, 100.8, None, "99.02"),  # a regency without districts
        (-10.99, 100.2, "99.01.01", "99.01"),  # ~1 km outside: nearest within 2 km
    ],
)
async def test_locate_places_a_point(
    db: AsyncSession, regions: None, lat: float, lng: float, district: str | None, regency: str
) -> None:
    path = await service.locate(db, lat=lat, lng=lng)
    assert (path.district.code if path.district else None) == district
    assert path.regency is not None and path.regency.code == regency
    assert path.province is not None and path.province.code == "99"


async def test_locate_far_from_land_finds_nothing(db: AsyncSession, regions: None) -> None:
    path = await service.locate(db, lat=-10.5, lng=100.5)  # ~55 km away
    assert (path.district, path.regency, path.province) == (None, None, None)


async def test_locate_endpoint(reviewer: AsyncClient, regions: None) -> None:
    response = await reviewer.get(f"{URL}/locate", params={"lat": -11.2, "lng": 100.2})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["district"]["value"] == "Kecamatan Utara"
    assert data["province"]["code"] == "99"


async def test_list_children_with_geometry(reviewer: AsyncClient, regions: None) -> None:
    province = (await reviewer.get(URL, params={"type": "region", "q": "provinsi uji"})).json()
    [row] = province["data"]
    assert (row["level"], row["centroid"]) == ("province", {"lat": -11.5, "lng": 100.5})
    assert row["geometry"] is None

    response = await reviewer.get(
        URL, params={"type": "region", "parent_id": row["id"], "geometry": "true"}
    )
    body = response.json()
    assert [r["code"] for r in body["data"]] == ["99.01", "99.02"]
    assert body["data"][0]["geometry"]["type"] == "MultiPolygon"
    assert body["data"][0]["source"] == "platform"


async def test_pages_follow_the_cursor(reviewer: AsyncClient, regions: None) -> None:
    params: dict[str, Any] = {"type": "region", "q": "kecamatan", "limit": 1}
    first = (await reviewer.get(URL, params=params)).json()
    assert first["meta"]["pagination"]["has_more"] is True
    params["cursor"] = first["meta"]["pagination"]["next_cursor"]
    second = (await reviewer.get(URL, params=params)).json()
    assert [r["code"] for r in first["data"] + second["data"]] == ["99.01.01", "99.01.02"]
    assert second["meta"]["pagination"] == {"next_cursor": None, "limit": 1, "has_more": False}


async def test_commodities_match_aliases(reviewer: AsyncClient, regions: None) -> None:
    response = await reviewer.get(URL, params={"type": "commodity", "q": "pari"})
    [row] = response.json()["data"]
    assert (row["code"], row["value"], row["aliases"]) == ("rice", "Padi", ["gabah", "pari"])
    assert row["level"] is None and row["centroid"] is None


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"type": "region", "geometry": "true", "limit": 51}, "geometry_limit_too_high"),
        ({"type": "commodity", "geometry": "true"}, "geometry_only_for_regions"),
        ({"type": "planet"}, "invalid_format"),
    ],
)
async def test_invalid_queries(
    reviewer: AsyncClient, regions: None, params: dict[str, Any], code: str
) -> None:
    response = await reviewer.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == code


async def test_other_workspaces_rows_are_hidden(
    reviewer: AsyncClient, db: AsyncSession, regions: None
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    db.add(ReferenceData(workspace_id=other.id, type="farmer_group", value="Tani Makmur"))
    await db.flush()

    response = await reviewer.get(URL, params={"type": "farmer_group"})
    assert response.json()["data"] == []
    hidden = await db.scalar(select(ReferenceData.id).where(ReferenceData.value == "Tani Makmur"))
    response = await reviewer.get(URL, params={"type": "region", "parent_id": str(hidden)})
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "reference_item_not_found"


async def test_needs_an_active_workspace(logged_in: AsyncClient) -> None:
    response = await logged_in.get(URL, params={"type": "unit"})
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "workspace_required"


async def test_needs_a_session(client: AsyncClient) -> None:
    response = await client.get(URL, params={"type": "unit"})
    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "not_authenticated"
