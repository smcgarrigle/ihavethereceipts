"""The demo seed pins real USDA FoodData Central IDs.

Without fdc_id the USDA product-type chart is empty (it filters on
Item.fdc_id IS NOT NULL) and the "view on FDC" link on item insights has
nothing to point at. The IDs are baked in as a static table so seeding needs
no network access or API key.
"""

import importlib.util
import re
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py"


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_demo", SEED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_fdc_id_maps_to_a_known_nutrient_profile():
    seed = _load_seed()
    unknown = set(seed._FDC_IDS) - set(seed._P)
    assert not unknown, f"_FDC_IDS keys with no nutrient profile: {sorted(unknown)}"


def test_fdc_ids_are_plausible_identifiers():
    seed = _load_seed()
    assert seed._FDC_IDS, "expected a populated FDC id table"
    for key, fdc_id in seed._FDC_IDS.items():
        assert isinstance(fdc_id, int), f"{key}: {fdc_id!r} is not an int"
        assert 1000 < fdc_id < 10_000_000, f"{key}: {fdc_id} is outside the FDC id range"
    assert len(set(seed._FDC_IDS.values())) == len(seed._FDC_IDS), "duplicate FDC ids"


def test_most_profiles_are_matched_but_coverage_stays_partial():
    seed = _load_seed()
    matched, total = len(seed._FDC_IDS), len(seed._P)
    assert matched / total > 0.9, f"only {matched}/{total} profiles have an FDC id"
    # Partial coverage is deliberate — it exercises the nutrition-coverage UI.
    assert matched < total, "expected some profiles to stay unmatched on purpose"


def test_seed_assigns_fdc_ids_to_items():
    """The catalog wiring actually reaches the Item rows."""
    source = SEED.read_text()
    assert re.search(r"fdc_id=_FDC_IDS\.get\(profile\)", source), (
        "Item(...) no longer sets fdc_id from the profile table"
    )
