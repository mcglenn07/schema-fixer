import pytest

from schema_fixer.io import InputError, load_schema, read_table


def test_csv_preserves_identifiers_literals_and_quoted_cells(tmp_path):
    path = tmp_path / "incoming.csv"
    path.write_text('\ufeffid,name,note\n0012,"Reyes, Ada",NA\n0013,Ben,\n')
    frame = read_table(path)
    assert frame.iloc[0].tolist() == ["0012", "Reyes, Ada", "NA"]
    assert frame.iloc[1]["note"] == ""


def test_json_preserves_native_scalars_and_missing_cells(tmp_path):
    path = tmp_path / "incoming.json"
    path.write_text('[{"id":"0012","n":2,"flag":true},{"id":"0013","n":"3"}]')
    frame = read_table(path)
    assert frame.iloc[0]["id"] == "0012"
    assert type(frame.iloc[0]["n"]) is int
    assert type(frame.iloc[0]["flag"]) is bool
    assert frame.iloc[1]["n"] == "3"


@pytest.mark.parametrize(
    ("suffix", "contents"),
    [
        ("csv", "email,email\na,b\n"),
        ("csv", "email,\na,b\n"),
        ("csv", "a,b\n1,2,3\n"),
        ("csv", "a,b\n1\n"),
        ("csv", 'a,b\n"unterminated,2\n'),
        ("csv", ""),
        ("csv", "a,b\n\n"),
        ("json", '{"email":"ada@example.com"}'),
        ("json", '[{"email":"a","email":"b"}]'),
        ("json", '[{"address":{"city":"Manila"}}]'),
        ("json", '[{"tags":["a"]}]'),
        ("json", "[null]"),
        ("json", "[1,2]"),
        ("json", "[{}]"),
        ("json", '[{"":1}]'),
        ("json", '[{"amount":NaN}]'),
        ("json", '[{"amount":Infinity}]'),
        ("json", '[{"amount":1}'),
        ("txt", "a,b\n1,2\n"),
    ],
)
def test_bad_tables_are_rejected(tmp_path, suffix, contents):
    path = tmp_path / f"input.{suffix}"
    path.write_text(contents)
    with pytest.raises(InputError):
        read_table(path)


def test_empty_data_with_known_headers_and_empty_json(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("email,full_name\n")
    assert list(read_table(csv_path).columns) == ["email", "full_name"]
    json_path = tmp_path / "empty.json"
    json_path.write_text("[]")
    assert read_table(json_path).empty


@pytest.mark.parametrize(
    "contents",
    [
        "name: x\nfields: {}\n",
        "name: x\nfields: {email: {type: string, requred: true}}\n",
        "name: x\nfields: {email: {type: executable}}\n",
        "name: x\nfields: {email: {type: string, required: 'yes'}}\n",
        "name: x\nfields: {plan: {type: string, enum: []}}\n",
        "name: x\nfields: {plan: {type: string, enum: [pro, pro]}}\n",
        "name: x\nfields: {amount: {type: number, format: email}}\n",
        "name: x\nfields: {email: {type: string}, email: {type: number}}\n",
        "name: x\nfields: {' spaced ': {type: string}}\n",
        "!!python/object/apply:os.system ['echo unsafe']",
        "[unclosed",
        "null",
    ],
)
def test_bad_schemas_are_rejected(tmp_path, contents):
    path = tmp_path / "schema.yaml"
    path.write_text(contents)
    with pytest.raises(InputError):
        load_schema(path)
