"""Candidate stores around the origin: active, priced in their zone and within the radius."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_basket.config import Settings
from smart_basket.routing.base import GeoPoint, TravelMode


@dataclass(frozen=True, slots=True)
class CandidateStore:
    """A store the optimizer may visit, with the distance used to rank candidates."""

    store_id: int
    chain_id: int
    name: str
    chain: str
    address: str | None
    latitude: float
    longitude: float
    zone_id: int
    distance_m: float


def candidate_stores(
    session: Session, origin: GeoPoint, mode: TravelMode, settings: Settings
) -> list[CandidateStore]:
    """Stores with current prices in their zone within the mode's radius, nearest first."""
    radius = settings.walk_radius_m if mode is TravelMode.WALK else settings.car_radius_m
    rows = session.execute(
        text(
            """
            with origin as (
                select st_setsrid(st_makepoint(:lon, :lat), 4326)::geography as point
            )
            select s.id, s.chain_id, s.name, s.address, c.name as chain, s.zone_id,
                   st_y(s.geom::geometry) as latitude,
                   st_x(s.geom::geometry) as longitude,
                   st_distance(s.geom, origin.point) as distance_m
            from store s
            join chain c on c.id = s.chain_id
            cross join origin
            where s.is_active
              and exists (
                  select 1 from price_current pc where pc.zone_id = s.zone_id
              )
              and st_dwithin(s.geom, origin.point, :radius)
            order by distance_m, s.id
            limit :limit
            """
        ),
        {
            "lat": origin.latitude,
            "lon": origin.longitude,
            "radius": radius,
            "limit": settings.candidate_stores,
        },
    ).mappings()
    return [
        CandidateStore(
            store_id=row["id"],
            chain_id=row["chain_id"],
            name=row["name"],
            chain=row["chain"],
            address=row["address"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            zone_id=row["zone_id"],
            distance_m=row["distance_m"],
        )
        for row in rows
    ]
