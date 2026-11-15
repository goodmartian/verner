import numpy as np
import pytest
from synth import clone, make_pair

from senda_pipeline import fit, ladder


def all_sel(d):
    return d.valid.copy()


def test_fit_recovers_known_k():
    d = make_pair(k=4.0)
    k = fit.fit_zone(d, all_sel(d), 0.0, False)
    assert k.shape == (len(d.zones), 12, 2)
    assert np.allclose(k, 4.0, atol=1e-9, rtol=0)


def test_shrinkage_pulls_to_zone():
    d = make_pair(rate=6.0, noise=True, k_fn=lambda z, c, cm, dn: 3.0 + 0.5 * (cm % 3))
    d.M[:, d.calmonth == 7, :] = 0.0  # July has no source hotspots at all
    d.V[:, d.calmonth == 7, :] = 0.0
    d2 = clone(d, d.M, d.V)
    sel = all_sel(d2)
    k0, basis = fit.fit_zone_full(d2, sel, 0.0, False)
    k3, _ = fit.fit_zone_full(d2, sel, 3.0, False)
    z = 0
    zr = d2.zV[z].sum() / d2.zM[z].sum()
    assert k0[z, 6, 0] == pytest.approx(zr)
    assert fit.BASIS[basis[z, 6]] == "zone"
    spread = lambda k: np.std(np.delete(k[z, :, 0], 6))
    assert spread(k3) < spread(k0)


def test_unsupported_zone_takes_global():
    d = make_pair(k=4.0)
    weak = d.g_zone == 2
    d.M[weak] = 0.0
    d.V[weak] = 0.0
    d.M[np.flatnonzero(weak)[0], 0, 0] = 5.0  # sum M of the zone is 5, below 25
    d.V[np.flatnonzero(weak)[0], 0, 0] = 20.0
    d = clone(d, d.M, d.V)
    k, basis = fit.fit_zone_full(d, all_sel(d), 0.1, False)
    assert (basis[2] == 2).all()
    assert fit.BASIS[2] == "global"
    assert np.allclose(k[2], k[d.zg])
    assert (basis[0] < 2).all()


def test_none_zone_is_never_supported():
    d = make_pair(k=4.0)
    _, basis = fit.fit_zone_full(d, all_sel(d), 0.0, False)
    assert (basis[d.zg] == 2).all()


def test_pick_lambda_rule():
    scores = {0.0: 0.100, 0.1: 0.0995, 1.0: 0.1004, 3.0: 0.12}
    assert fit.pick_lambda(scores) == 1.0
    assert fit.pick_lambda({0.0: None, 1.0: float("nan")}) == 0.0


def test_select_lambda_lists_every_candidate():
    d = make_pair(rate=8.0, noise=True)
    lam, scores = fit.select_lambda(d, all_sel(d), False)
    assert [s["lambda"] for s in scores] == list(fit.LAMBDAS)
    assert lam in fit.LAMBDAS


def test_split_dn_recovers_two_factors():
    d = make_pair(k_fn=lambda z, c, cm, dn: 3.0 if dn == "D" else 8.0)
    k = fit.fit_zone(d, all_sel(d), 0.0, True)
    assert np.allclose(k[..., 0], 3.0) and np.allclose(k[..., 1], 8.0)
    flat = fit.fit_zone(d, all_sel(d), 0.0, False)
    assert np.allclose(flat[..., 0], flat[..., 1])


def test_factor_floor():
    d = make_pair(k=0.0)
    k = fit.fit_zone(d, all_sel(d), 0.0, False)
    assert (k >= fit.K_MIN).all()


def wreck(d, outside):
    """Same layout, but the months outside `outside` carry unrelated counts, different per zone."""
    rng = np.random.default_rng(99)
    m, v = d.M.copy(), d.V.copy()
    scale = rng.uniform(0.2, 30.0, size=(m.shape[0], 1, 1))
    m[:, outside] = rng.poisson(40.0, size=m[:, outside].shape) * scale
    v[:, outside] = rng.poisson(5.0, size=v[:, outside].shape) * scale[::-1]
    return clone(d, m, v)


def test_no_leakage():
    """Counts of months outside the fit mask change nothing the fit produces: lambda, day and night, countries."""
    d = make_pair(rate=150.0, noise=True, k_fn=lambda z, c, cm, dn: (3.0 if c == "c0" else 5.0) + (cm % 3) * 0.2)
    sel = d.valid & (d.year <= 2017)
    other = wreck(d, ~sel)
    a, b = ladder.fit_l5(d, sel), ladder.fit_l5(other, sel)
    assert a.country.cand.any()  # the country rule really ran
    assert a.split == b.split and a.zone.lam == b.zone.lam
    for x, y in ((a.zone.k, b.zone.k), (a.zone.basis, b.zone.basis), (a.country.F, b.country.F), (a.country.use, b.country.use), (a.country.gain, b.country.gain)):
        assert np.array_equal(x, y)
    assert a.country.lam_c == b.country.lam_c
    assert [s["score"] for s in a.z3.scores] == [s["score"] for s in b.z3.scores]
    assert [s["score"] for s in a.z4.scores] == [s["score"] for s in b.z4.scores]
    # the check has teeth: letting the fit see the wrecked months does change it
    wide = ladder.fit_l5(other, d.valid)
    assert not np.array_equal(wide.zone.k, a.zone.k)


def test_country_rule_three_conditions():
    # gain 5 % fails, gain 20 % with a forward check that is not worse passes
    zl, zf = [0.2, 0.2], [0.2, 0.2]
    ok = fit.country_rule(zl, [0.19, 0.16], zf, [0.19, 0.16], [0.0, 0.0], [0.0, 0.0])
    assert ok.tolist() == [False, True]
    # forward error worse than the zone model
    assert not fit.country_rule([0.2], [0.16], [0.2], [0.21], [0.0], [0.0])[0]
    # bias beyond max(zone bias, 0.05)
    assert not fit.country_rule([0.2], [0.16], [0.2], [0.19], [0.0], [0.1])[0]
    assert fit.country_rule([0.2], [0.16], [0.2], [0.19], [0.0], [0.04])[0]
    # a missing metric keeps the country out
    assert not fit.country_rule([0.2], [0.16], [np.nan], [0.19], [0.0], [0.0])[0]


def test_country_fit_includes_only_a_country_that_gains():
    # c0 and c1 differ a lot inside every zone: zone factors are wrong for both
    d = make_pair(rate=300.0, noise=True, k_fn=lambda z, c, cm, dn: 6.0 if c == "c0" else 2.0)
    sel = d.valid & (d.year <= 2019)
    lam, _ = fit.select_lambda(d, sel, False)
    kz = fit.fit_zone(d, sel, lam, False)
    cf = fit.fit_country(d, sel, lam, kz)
    assert cf.cand.all() and cf.use.all()
    assert (cf.gain > 0.5).all()
    # same factor in both countries: the country coefficients add nothing
    same = make_pair(rate=300.0, noise=True, k_fn=lambda z, c, cm, dn: 4.0)
    kz = fit.fit_zone(same, sel, lam, False)
    assert not fit.fit_country(same, sel, lam, kz).use.any()


def test_country_candidates_need_size():
    d = make_pair(rate=2.0, noise=True, k_fn=lambda z, c, cm, dn: 6.0 if c == "c0" else 2.0)
    sel = d.valid & (d.year <= 2019)
    kz = fit.fit_zone(d, sel, 0.1, False)
    cf = fit.fit_country(d, sel, 0.1, kz)
    assert not cf.cand.any() and not cf.use.any()


def test_valid_mask_is_respected():
    d = make_pair(k=4.0)
    bad = d.year == 2015
    d.M[:, bad] *= 100  # poisoned months flagged as invalid
    d = fit.PairData(
        src=d.src, dst=d.dst, M=d.M, V=d.V, month=d.month, valid=~bad, g_zone=d.g_zone, g_country=d.g_country,
        g_block=d.g_block, zones=d.zones, countries=d.countries,
    )
    assert np.allclose(fit.fit_zone(d, np.ones(len(d.month), bool), 0.0, False), 4.0)
