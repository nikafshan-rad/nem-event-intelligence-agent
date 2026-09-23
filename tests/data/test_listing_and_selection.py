"""NEMWeb listing parser and G0 selection verifier (offline parts)."""

import copy

import pytest

from nem_agent.nemweb import creation_time_from_name, parse_listing
from nem_agent.verify import verify

LISTING_SNIPPET = (  # format sample of a NEMWeb IIS directory listing (two entries)
    '<pre><A HREF="/Reports/CURRENT">[To Parent Directory]</A><br><br>'
    ' Saturday, July 25, 2026  4:33 PM          462 <A HREF="/Reports/CURRENT/Operational_Demand/ACTUAL_HH/'
    'PUBLIC_ACTUAL_OPERATIONAL_DEMAND_HH_202607251630_20260725163006.zip">PUBLIC_ACTUAL_OPERATIONAL_DEMAND_HH_'
    '202607251630_20260725163006.zip</A><br>  Monday, July 27, 2026 10:05 AM        &lt;dir&gt; '
    '<A HREF="/Reports/CURRENT/X/">X</A><br></pre>'
)


def test_parse_listing_entries_and_times():
    entries = parse_listing(LISTING_SNIPPET, "https://nemweb.com.au/Reports/CURRENT/")
    assert len(entries) == 2
    f = entries[0]
    assert f.size == 462 and not f.is_dir
    assert f.url.startswith("https://nemweb.com.au/Reports/CURRENT/Operational_Demand/ACTUAL_HH/")
    assert f.listed_at_market == "2026/07/25 16:33"
    assert entries[1].is_dir


def test_creation_time_from_file_name():
    t = creation_time_from_name("PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607310300_20260731023138.zip")
    assert t is not None and t.isoformat() == "2026-07-30T16:31:38+00:00"


def test_committed_selection_passes_offline_verification(selection):
    raw = selection.model_dump()
    rep = verify(raw, live=False, deep=False)
    assert rep.ok, rep.failed


@pytest.mark.parametrize("mutate", [
    lambda s: s["sources"][0].__setitem__("url", ""),
    lambda s: s["sources"][0].__setitem__("url", "https://example.com/x.zip"),
    lambda s: s["sources"][0].__setitem__("sha256", "abc"),
    lambda s: s["comparisons"][0]["actual"].update(dataset="DISPATCHIS", table="DISPATCH/REGIONSUM",
                                                   field="TOTALDEMAND", definition="DISPATCH_TOTALDEMAND",
                                                   interval_minutes=5),
    lambda s: s["comparisons"][0]["forecast"].__setitem__("unit", "MWh"),
])
def test_verifier_rejects_mutations(selection, mutate):
    raw = copy.deepcopy(selection.model_dump())
    mutate(raw)
    assert not verify(raw, live=False, deep=False).ok
