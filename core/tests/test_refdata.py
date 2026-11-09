from __future__ import annotations

import pytest

from workbench_core.refdata import (
    ColumnDef,
    EnumItem,
    EnumList,
    RefRow,
    RefTable,
    RefValidationError,
    check_enum,
    check_table_columns,
    convert_rows,
    validate_row,
)

VOLTS = EnumList(id="v", name="Voltage", items=[
    EnumItem(id="lv", code="LV", value="400 V"), EnumItem(id="hv", code="HV", value="11 kV")])


def test_enum_codes_and_values_unique() -> None:
    e = check_enum(EnumList(name="  Starter   types ", items=[EnumItem(code=" DOL ", value="Direct on line")]))
    assert e.name == "Starter types" and e.items[0].code == "DOL"
    with pytest.raises(RefValidationError) as err:
        check_enum(EnumList(name="X", items=[EnumItem(id="a", code="A", value="One"), EnumItem(id="b", code="a", value="one"),
                                             EnumItem(id="c", code="", value="")]))
    assert set(err.value.fields) == {"b.code", "b.value", "c.code", "c.value"}
    with pytest.raises(RefValidationError):
        check_enum(EnumList(name=" "))


def _table() -> RefTable:
    return RefTable(id="t", name="Motors", columns=[
        ColumnDef(id="tag", name="Tag", required=True, unique=True),
        ColumnDef(id="kw", name="kW", type="decimal"),
        ColumnDef(id="poles", name="Poles", type="integer"),
        ColumnDef(id="vsd", name="VSD", type="boolean"),
        ColumnDef(id="volt", name="Voltage", type="enum", enum_id="v"),
    ])


def test_row_types_are_validated_and_coerced() -> None:
    t = _table()
    v = validate_row(t, {"tag": "M-1", "kw": "2.50", "poles": "4", "vsd": "yes", "volt": "lv"}, {"v": VOLTS}, [])
    assert v == {"tag": "M-1", "kw": "2.5", "poles": 4, "vsd": True, "volt": "lv"}
    # Enum accepts a code or value too, decimals stay exact, blanks are None.
    v = validate_row(t, {"tag": "M-2", "kw": "0.1", "volt": "11 kv", "poles": ""}, {"v": VOLTS}, [])
    assert v["volt"] == "hv" and v["kw"] == "0.1" and v["poles"] is None and v["vsd"] is None
    with pytest.raises(RefValidationError) as err:
        validate_row(t, {"tag": "m-1", "kw": "abc", "poles": "1.5", "vsd": "maybe", "volt": "MV"}, {"v": VOLTS},
                     [RefRow(values={"tag": "M-1"})])
    assert set(err.value.fields) == {"tag", "kw", "poles", "vsd", "volt"}  # tag: unique ignoring case
    with pytest.raises(RefValidationError) as err:
        validate_row(t, {}, {"v": VOLTS}, [])
    assert err.value.fields == {"tag": "Required"}


def test_columns_checked() -> None:
    with pytest.raises(RefValidationError) as err:
        check_table_columns(RefTable(name="T", columns=[ColumnDef(id="a", name="A"), ColumnDef(id="b", name=" a "),
                                                        ColumnDef(id="c", name="C", type="enum")]), {})
    assert set(err.value.fields) == {"b.name", "c.enum_id"}


def test_convert_rows_on_type_change() -> None:
    old = RefTable(id="t", name="T", columns=[ColumnDef(id="a", name="A"), ColumnDef(id="b", name="B"),
                                              ColumnDef(id="gone", name="Gone")])
    rows = [RefRow(id="1", values={"a": "12", "b": "LV", "gone": "x"}), RefRow(id="2", values={"a": "7", "b": "hv"})]
    new = RefTable(id="t", name="T", columns=[ColumnDef(id="a", name="A", type="integer"),
                                              ColumnDef(id="b", name="B", type="enum", enum_id="v")])
    out = convert_rows(old, new, rows, {"v": VOLTS})
    assert [r.values for r in out] == [{"a": 12, "b": "lv"}, {"a": 7, "b": "hv"}]
    # And back to text: enum items become their code.
    back = convert_rows(new, old, out, {"v": VOLTS})
    assert back[0].values["b"] == "LV" and back[0].values["a"] == "12"

    bad = [RefRow(id="1", values={"a": "twelve"})]
    with pytest.raises(RefValidationError) as err:
        convert_rows(old, new, bad, {"v": VOLTS})
    assert "twelve" in err.value.fields["a"]
    strict = RefTable(id="t", name="T", columns=[ColumnDef(id="a", name="A", required=True, unique=True)])
    with pytest.raises(RefValidationError) as err:
        convert_rows(old, strict, [RefRow(values={"a": "x"}), RefRow(values={"a": "X"}), RefRow(values={})], {})
    assert "1 row(s) are empty" in err.value.fields["a"] and "duplicate" in err.value.fields["a"]
