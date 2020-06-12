from typing import Dict, Any, List, Tuple

from splitgraph.core.types import TableSchema, TableColumn

try:
    from multicorn import ANY
except ImportError:
    # Don't fail the import if we're running this directly.
    ANY = object()


_socrata_types = {
    "checkbox": "boolean",
    "double": "double",
    "floating timestamp": "timestamp without time zone",
    "calendar date": "date",
    "money": "money",
    "number": "numeric",
    "text": "text",
    "url": "text",
}


def _socrata_to_pg_type(socrata_type):
    socrata_type = socrata_type.lower()
    if socrata_type in [
        "line",
        "location",
        "multiline",
        "multipoint",
        "multipolygon",
        "point",
    ]:
        return "json"
    if socrata_type in _socrata_types:
        return _socrata_types[socrata_type]
    else:
        return "text"


def dedupe_sg_schema(schema_spec: TableSchema, prefix_len: int = 59) -> TableSchema:
    """
    Some Socrata schemas have columns that are longer than 63 characters
    where the first 63 characters are the same between several columns
    (e.g. odn.data.socrata.com). This routine renames columns in a schema
    to make sure this can't happen (by giving duplicates a number suffix).
    """

    # We truncate the column name to 59 to leave space for the underscore
    # and 3 digits (max PG identifier is 63 chars)
    prefix_counts: Dict[str, int] = {}
    columns_nums: List[Tuple[str, int]] = []

    for column in schema_spec:
        column_short = column.name[:prefix_len]
        count = prefix_counts.get(column_short, 0)
        columns_nums.append((column_short, count))
        prefix_counts[column_short] = count + 1

    result = []
    for (_, position), column in zip(columns_nums, schema_spec):
        column_short = column.name[:prefix_len]
        count = prefix_counts[column_short]
        if count > 1:
            result.append(
                TableColumn(
                    column.ordinal,
                    f"{column_short}_{position:03d}",
                    column.pg_type,
                    column.is_pk,
                    column.comment,
                )
            )
        else:
            result.append(column)
    return result


def socrata_to_sg_schema(metadata: Dict[str, Any]) -> TableSchema:
    try:
        col_names = metadata["resource"]["columns_field_name"]
        col_types = metadata["resource"]["columns_datatype"]
    except KeyError:
        raise ValueError("Invalid Socrata metadata!")

    col_desc = metadata["resource"].get("columns_description") or [None] * len(col_names)

    # Prepend the Socrata :id column that we can order on and use as PK.
    col_names = [":id"] + col_names
    col_types = ["text"] + col_types
    col_desc = ["Socrata column ID"] + col_desc

    result = [
        TableColumn(i, n, _socrata_to_pg_type(t), False, d)
        for i, (n, t, d) in enumerate(zip(col_names, col_types, col_desc))
    ]

    return dedupe_sg_schema(result)


def estimate_socrata_rows_width(columns, metadata):
    """Estimate number of rows required for a query and each row's width
    from the table metadata."""

    # We currently don't use qualifiers for this, they get passed to Socrata
    # directly. Socrata's metadata does contain some statistics for each column
    # (min, max, sum, most popular values etc) that can be used to help the planner though.

    contents = metadata["columns"][0]["cachedContents"]
    cardinality = int(contents["non_null"]) + int(contents["null"])
    column_widths = {c["fieldName"]: c.get("width", 100) for c in metadata["columns"]}

    # Socrata doesn't return the Socrata Row ID width in its metadata but we know
    # how big it usually is (row-XXXX.XXXX_XXXX).
    row_width = sum(column_widths[c] if c != ":id" else 18 for c in columns)

    return cardinality, row_width


def _emit_col(col):
    return f"`{col}`"


def _emit_val(val):
    if val is None:
        return "NULL"
    if not isinstance(val, (int, float)):
        val = str(val).replace("'", "''")
        return f"'{val}'"
    return str(val)


def _convert_op(op):
    if op in ["=", ">", ">=", "<", "<=", "<>", "!="]:
        return op
    if op == "~~":
        return "LIKE"
    return None


def _base_qual_to_socrata(col, op, value):
    soql_op = _convert_op(op)
    if not soql_op:
        return "TRUE"
    else:
        return f"{_emit_col(col)} {soql_op} {_emit_val(value)}"


def _qual_to_socrata(qual):
    if qual.is_list_operator:
        if qual.list_any_or_all == ANY:
            # Convert col op ANY([a,b,c]) into (cop op a) OR (col op b)...
            return " OR ".join(
                f"({_base_qual_to_socrata(qual.field_name, qual.operator[0], v)})"
                for v in qual.value
            )
        # Convert col op ALL(ARRAY[a,b,c...]) into (cop op a) AND (col op b)...
        return " AND ".join(
            f"({_base_qual_to_socrata(qual.field_name, qual.operator[0], v)})" for v in qual.value
        )
    else:
        return f"{_base_qual_to_socrata(qual.field_name, qual.operator[0], qual.value)}"


def quals_to_socrata(quals):
    """Convert a list of Multicorn quals to a SoQL query"""
    return " AND ".join(f"({_qual_to_socrata(q)})" for q in quals)


def cols_to_socrata(cols):
    return ",".join(f"{_emit_col(c)}" for c in cols)


def sortkeys_to_socrata(sortkeys):
    if not sortkeys:
        # Always sort on ID for stable paging
        return ":id"

    clauses = []
    for key in sortkeys:
        if key.nulls_first != key.is_reversed:
            raise ValueError("Unsupported SortKey %s" % str(key))
        order = "DESC" if key.is_reversed else "ASC"
        clauses.append(f"{_emit_col(key.attname)} {order}")
    return ",".join(clauses)
