"""Recommendation pipeline: candidates, catalog products, optimizer, route and persistence.

Joins the pure optimizer with the catalog and the routing engine (decision 0013, FR-13).
"""

from smart_basket.recommender.service import NoCandidateStores, RecommendationQuery, recommend

__all__ = ["NoCandidateStores", "RecommendationQuery", "recommend"]
