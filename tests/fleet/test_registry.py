"""Integrity checks on the curated fleet registry."""

from fleet.registry import FLEET, all_bmu_ids, bmu_to_site


def test_bmu_ids_are_unique_across_sites():
    ids = all_bmu_ids()
    assert len(ids) == len(set(ids))


def test_every_site_has_positive_ratings_and_at_least_one_bmu():
    for site in FLEET:
        assert site.bmu_ids, site.site
        assert site.power_mw > 0, site.site
        assert site.capacity_mwh > 0, site.site
        assert site.optimiser, site.site
        assert site.region, site.site


def test_bmu_to_site_covers_every_bmu():
    mapping = bmu_to_site()
    assert set(mapping) == set(all_bmu_ids())
    for site in FLEET:
        for bmu in site.bmu_ids:
            assert mapping[bmu] is site
