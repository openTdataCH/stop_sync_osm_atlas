"""Consumer properties use published fixture bytes without importing the producer."""
from copy import deepcopy
import math
from pathlib import Path

from hypothesis import example, given, settings, strategies as st
import pytest

from backend.importing.bundle import InvalidBundle, SECTIONS, read_bundle, validate_records


EXAMPLE = read_bundle(Path(__file__).parent / "fixtures/result-v1")
PROPERTY_SETTINGS = settings(max_examples=35, deadline=None, derandomize=True)
NON_OBJECT = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=30),
                       st.lists(st.integers(), max_size=5))
NON_LIST = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=30),
                     st.dictionaries(st.text(max_size=10), st.integers(), max_size=3))


@pytest.mark.parametrize("section", ["source_stops", "osm_nodes"])
@PROPERTY_SETTINGS
@example(latitude=-90.0, longitude=-180.0)
@example(latitude=90.0, longitude=180.0)
@given(latitude=st.one_of(st.integers(-90, 90), st.floats(-90, 90, allow_nan=False, allow_infinity=False)),
       longitude=st.one_of(st.integers(-180, 180), st.floats(-180, 180, allow_nan=False, allow_infinity=False)))
def test_consumer_accepts_all_finite_coordinates_in_the_wire_domain(section, latitude, longitude):
    bundle = deepcopy(EXAMPLE)
    for row in bundle[section]:
        row.update(lat=latitude, lon=longitude)
    validate_records(bundle)


@pytest.mark.parametrize("section", ["source_stops", "osm_nodes"])
@pytest.mark.parametrize("coordinate,limit", [("lat", 90.0), ("lon", 180.0)])
@PROPERTY_SETTINGS
@given(data=st.data())
def test_consumer_rejects_nonfinite_boolean_and_out_of_domain_coordinates(section, coordinate, limit, data):
    beyond_limit = math.nextafter(limit, math.inf)
    invalid = data.draw(st.one_of(
        st.none(), st.booleans(), st.text(max_size=15),
        st.sampled_from([float("nan"), float("inf"), float("-inf"), beyond_limit, -beyond_limit]),
        st.floats(min_value=beyond_limit, max_value=1e12),
        st.floats(min_value=-1e12, max_value=-beyond_limit),
    ), label="invalid coordinate")
    bundle = deepcopy(EXAMPLE)
    bundle[section][0][coordinate] = invalid
    with pytest.raises(InvalidBundle, match="[Cc]oordinates"):
        validate_records(bundle)


@pytest.mark.parametrize("section", SECTIONS)
@PROPERTY_SETTINGS
@given(malformed=NON_LIST)
def test_malformed_section_containers_raise_the_contract_error(section, malformed):
    bundle = deepcopy(EXAMPLE)
    bundle[section] = malformed
    with pytest.raises(InvalidBundle, match=f"Invalid {section} records"):
        validate_records(bundle)


@pytest.mark.parametrize("section", SECTIONS)
@PROPERTY_SETTINGS
@given(malformed=NON_OBJECT)
def test_malformed_section_records_raise_the_contract_error(section, malformed):
    bundle = deepcopy(EXAMPLE)
    bundle[section].append(malformed)
    with pytest.raises(InvalidBundle, match=f"Invalid {section} records"):
        validate_records(bundle)


@PROPERTY_SETTINGS
@given(data=st.data())
def test_reordering_top_level_records_preserves_valid_identity_relationships(data):
    bundle = deepcopy(EXAMPLE)
    for section in SECTIONS:
        bundle[section] = list(data.draw(st.permutations(bundle[section]), label=section))
    validate_records(bundle)


@PROPERTY_SETTINGS
@given(keep_match=st.booleans(), keep_unmatched=st.sets(st.integers(0, 1)))
def test_each_declared_entity_requires_exactly_one_matching_classification(keep_match, keep_unmatched):
    bundle = deepcopy(EXAMPLE)
    bundle["matches"] = bundle["matches"] if keep_match else []
    bundle["unmatched"] = [row for index, row in enumerate(bundle["unmatched"]) if index in keep_unmatched]
    if keep_match and keep_unmatched == {0, 1}:
        validate_records(bundle)
    else:
        with pytest.raises(InvalidBundle, match="match coverage is incomplete"):
            validate_records(bundle)


@pytest.mark.parametrize("side,key_field", [("source", "source_key"), ("osm", "osm_key")])
def test_matched_entity_cannot_also_be_unmatched(side, key_field):
    bundle = deepcopy(EXAMPLE)
    bundle["unmatched"].append({
        "side": side, "key": bundle["matches"][0][key_field],
        "isolated": False, "effectively_matched": False,
    })
    with pytest.raises(InvalidBundle, match="both matched and unmatched"):
        validate_records(bundle)
