import pytest

from spacedoc.tools.calculators import (
    CalcError,
    convert_units,
    glasgow_coma_scale,
    maintenance_fluids_421,
    qsofa,
    run_calculator,
    weight_based_dose,
)


def test_weight_dose_capped_and_rounded(formulary):
    r = weight_based_dose(formulary, "acetaminophen", 78)  # 15 mg/kg -> 1170, cap 1000
    assert r.value == 1000
    assert "Capped" in " ".join(r.warnings)
    assert "NOT clinician-validated" in " ".join(r.warnings)


def test_weight_dose_rounds_down_to_deliverable_units(formulary):
    r = weight_based_dose(formulary, "ibuprofen", 35)  # 10 mg/kg -> 350, round to 200 mg tablets
    assert r.value == 200


def test_weight_dose_by_alias(formulary):
    assert weight_based_dose(formulary, "paracetamol", 60).value == 500  # 900 -> 500 (tablet step)


def test_weight_dose_rejects_unknown_and_undosed(formulary):
    with pytest.raises(CalcError):
        weight_based_dose(formulary, "unobtainium", 70)
    with pytest.raises(CalcError):
        weight_based_dose(formulary, "tamsulosin", 70)  # no dosing table entry
    with pytest.raises(CalcError):
        weight_based_dose(formulary, "ibuprofen", 5)  # outside adult range


def test_calc_id_is_deterministic(formulary):
    a = weight_based_dose(formulary, "ibuprofen", 70)
    b = weight_based_dose(formulary, "ibuprofen", 70)
    assert a.calc_id == b.calc_id and a.calc_id.startswith("calc-")


def test_conversions():
    assert convert_units(1, "g", "mg").value == 1000
    assert convert_units(154, "lb", "kg").value == pytest.approx(69.85, abs=0.01)
    assert convert_units(100, "f", "c").value == pytest.approx(37.78, abs=0.01)
    assert convert_units(90, "mg/dl_glucose", "mmol/l_glucose").value == pytest.approx(
        5.0, abs=0.01
    )
    with pytest.raises(CalcError):
        convert_units(1, "mg", "c")


def test_gcs_and_qsofa():
    assert glasgow_coma_scale(4, 5, 6).value == 15
    with pytest.raises(CalcError):
        glasgow_coma_scale(5, 5, 6)
    assert qsofa(24, 95, False).value == 2
    assert qsofa(16, 120, False).value == 0


def test_maintenance_fluids():
    assert maintenance_fluids_421(10).value == 40
    assert maintenance_fluids_421(20).value == 60
    assert maintenance_fluids_421(70).value == 110


def test_weight_always_comes_from_record(formulary):
    r = run_calculator(
        "weight_based_dose", {"drug": "ibuprofen", "weight_kg": 120}, formulary, {"weight_kg": 60}
    )
    assert r.inputs["weight_kg"] == 60
    assert any("ignored" in w for w in r.warnings)
    with pytest.raises(CalcError):
        run_calculator("weight_based_dose", {"drug": "ibuprofen"}, formulary, None)
