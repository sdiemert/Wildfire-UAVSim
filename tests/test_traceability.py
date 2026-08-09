"""Fails the suite when the requirement trace is broken.

specs/policies/ claims that every requirement is implemented somewhere named and verified by some test.
A claim like that is worth nothing unless something checks it: a traceability table maintained by hand
describes the repository as it was on the day somebody last remembered to update it, which is exactly when
it stops being evidence for anything.

So the trace is checked here, by the same suite that checks the code. A requirement that loses its
verification, a marker naming an id no specification defines, and a satisfied_by pointing at a symbol
somebody renamed away all break this file. The checks live in tools/trace.py; this is where they bite.

The second half tests the checker itself. It is load bearing now -- it is what makes the trace credible --
so it gets the same treatment as anything else here.

That half is mostly about the shape of a requirement record: heading, optional preamble, the statement as a
blockquote, optional discussion, and a yaml block last. Every rule there is a way the layout could drift
back into burying the statement among metadata, which is the thing the format exists to prevent.
"""

# python libraries

import pytest

# own python modules

from tools.trace import Finding, SpecError, parse_block, parse_section, validate_record

import tools.trace as trace


# the whole check is a few hundred file reads, so it is done once and shared. Each test below reports one
# kind of finding, which keeps a single broken link from burying the others in one enormous failure.
@pytest.fixture(scope="module")
def findings():
    found, _, _, _ = trace.check()
    return found


def of_kind(findings, *kinds):
    return [finding for finding in findings if finding.kind in kinds]


def report(findings):
    return "\n".join(f"  {finding}" for finding in findings)


# --- the specifications parse and mean something ----------------------------


def test_every_specification_file_parses(findings):
    problems = of_kind(findings, "spec")
    assert not problems, f"specifications that could not be read:\n{report(problems)}"


def test_requirement_ids_are_unique(findings):
    problems = of_kind(findings, "duplicate-id")
    assert not problems, f"an id names two requirements:\n{report(problems)}"


def test_each_specification_file_owns_one_tag(findings):
    # what lets the file a requirement lives in be worked out from its id alone
    problems = of_kind(findings, "tag")
    assert not problems, f"tags and files do not line up:\n{report(problems)}"


def test_every_registered_policy_has_a_specification(findings):
    problems = of_kind(findings, "missing-spec", "orphan-spec")
    assert not problems, f"policies and specifications do not line up:\n{report(problems)}"


# --- the implementation leg -------------------------------------------------


def test_every_requirement_traces_to_code_that_exists(findings):
    problems = of_kind(findings, "implementation")
    assert not problems, (f"satisfied_by points at something that is not there any more:\n"
                          f"{report(problems)}")


# --- the verification leg ---------------------------------------------------


def test_every_requirement_verified_by_test_has_one(findings):
    problems = of_kind(findings, "verification")
    assert not problems, (f"requirements offered as verified by test, with no test marked for them:\n"
                          f"{report(problems)}")


def test_every_marker_names_a_requirement_that_exists(findings):
    problems = of_kind(findings, "unknown-id")
    assert not problems, f"verifies() names an id no specification defines:\n{report(problems)}"


def test_every_marker_can_be_read_statically(findings):
    problems = of_kind(findings, "marker")
    assert not problems, f"markers the trace cannot follow:\n{report(problems)}"


def test_no_finding_goes_unreported(findings):
    # a new kind added to tools/trace.py must get a test above rather than passing quietly through here
    covered = {"spec", "duplicate-id", "tag", "missing-spec", "orphan-spec", "implementation",
               "verification", "unknown-id", "marker"}
    unexpected = [finding for finding in findings if finding.kind not in covered]
    assert not unexpected, f"findings of a kind no test above reports:\n{report(unexpected)}"


# --- the anatomy of a requirement section -----------------------------------


# the shape every requirement is written in. The tests below break one part of it at a time.
WELL_FORMED = """
A preamble, which is optional.

> The policy SHALL do the thing.

A rationale, which is optional too.

```yaml
id: POL-GEN-1
satisfied_by:
  - sim/policy/base.py::Policy
verified_by: test
status: agreed
```
"""


def section(text):
    return parse_section(text.split("\n"), "test")


def test_the_statement_is_the_blockquote_and_the_block_is_the_yaml():
    statement, block = section(WELL_FORMED)
    assert statement == "The policy SHALL do the thing."
    assert "id: POL-GEN-1" in block
    # the prose around the statement is for the reader and is not carried anywhere
    assert "preamble" not in block and "rationale" not in block


def test_a_statement_spanning_several_lines_is_joined_up():
    statement, _ = section(WELL_FORMED.replace(
        "> The policy SHALL do the thing.",
        "> The policy SHALL do the thing,\n> and it SHALL do it in order."))
    assert statement == "The policy SHALL do the thing, and it SHALL do it in order."


def test_markdown_in_a_statement_survives():
    # the whole reason the statement left the yaml block: `observation.pos` should read as code
    statement, _ = section(WELL_FORMED.replace(
        "do the thing", "return `Action.stay()` for `observation.pos`"))
    assert "`Action.stay()`" in statement


@pytest.mark.parametrize(
    "broken, because",
    [
        (WELL_FORMED.replace("> The policy SHALL do the thing.", "The policy SHALL do the thing."),
         "no blockquote, so nothing identifies the statement"),
        (WELL_FORMED.replace("A rationale, which is optional too.", "> A second SHALL blockquote."),
         "two blockquotes, so which one is the statement is ambiguous"),
        (WELL_FORMED.replace("> The policy SHALL do the thing.", "").replace(
            "```\n", "```\n\n> The policy SHALL do the thing.\n"),
         "the statement comes after the yaml block"),
        (WELL_FORMED + "\nA paragraph after the yaml block.\n",
         "the yaml block is not last"),
        (WELL_FORMED.replace("SHALL do", "does"),
         "the statement describes rather than requires"),
        (WELL_FORMED.replace("```yaml", "").replace("```", ""),
         "no yaml block at all"),
    ],
)
def test_a_section_outside_the_anatomy_is_rejected(broken, because):
    with pytest.raises(SpecError):
        section(broken)


# --- the yaml block ---------------------------------------------------------


def test_a_well_formed_block_is_read_into_its_fields():
    record = parse_block("id: POL-GEN-1\nsatisfied_by:\n  - sim/policy/base.py::Policy\n", "test")
    assert record == {"id": "POL-GEN-1", "satisfied_by": ["sim/policy/base.py::Policy"]}


def test_a_wrapped_list_item_is_one_item():
    record = parse_block("satisfied_by:\n  - sim/policy/base.py\n    ::Policy\n", "test")
    assert record == {"satisfied_by": ["sim/policy/base.py ::Policy"]}


def test_a_folded_scalar_is_rejected_and_says_where_prose_belongs():
    # the block holds metadata only; letting this through would invite the statement back into it
    with pytest.raises(SpecError, match="prose belongs above it"):
        parse_block("statement: >\n  the policy SHALL do the thing\n", "test")


@pytest.mark.parametrize(
    "block, because",
    [
        ("id POL-GEN-1\n", "no colon, so it is not a field at all"),
        ("  id: POL-GEN-1\n", "indented under nothing"),
        ("id: POL-GEN-1\nid: POL-GEN-2\n", "the same field twice"),
        ("satisfied_by:\n  not a list item\n", "a list block whose first line is not an item"),
    ],
)
def test_a_block_outside_the_accepted_subset_is_rejected(block, because):
    with pytest.raises(SpecError):
        parse_block(block, "test")


# a record that passes validation, for the tests below to break one field of at a time. Four fields is the
# whole of it: everything a human writes at length lives in the Markdown above the block.
GOOD = {
    "id": "POL-GEN-1",
    "satisfied_by": ["sim/policy/base.py::Policy.select_actions"],
    "verified_by": "test",
    "status": "agreed",
}


def test_a_complete_record_validates():
    validate_record(dict(GOOD), "POL-GEN-1", "test")


@pytest.mark.parametrize(
    "field, value, because",
    [
        ("id", "GEN-1", "not a well formed id"),
        ("satisfied_by", [], "no implementation named"),
        ("satisfied_by", ["Policy.select_actions"], "no file to resolve it against"),
        ("satisfied_by", "sim/policy/base.py::Policy", "a scalar where a list belongs"),
        ("verified_by", "hoping", "not one of the recognised methods"),
        ("status", "wip", "not one of the recognised statuses"),
    ],
)
def test_a_record_that_breaks_the_schema_is_rejected(field, value, because):
    record = dict(GOOD)
    record[field] = value
    with pytest.raises(SpecError):
        validate_record(record, record["id"], "test")


def test_a_missing_required_field_is_rejected():
    for field in GOOD:
        record = dict(GOOD)
        del record[field]
        with pytest.raises(SpecError):
            validate_record(record, GOOD["id"], "test")


def test_prose_left_behind_in_the_block_is_rejected():
    # the fields that used to live here and now belong in Markdown, caught rather than silently ignored
    for field in ("statement", "rationale", "assumptions"):
        with pytest.raises(SpecError, match="unknown field"):
            validate_record(dict(GOOD, **{field: "left over"}), GOOD["id"], "test")


def test_an_unknown_field_is_rejected():
    # a typo in a field name would otherwise be silently ignored, and the field it was meant to be would
    # be reported as missing somewhere else entirely
    record = dict(GOOD, satisfied_bt=["sim/policy/base.py::Policy"])
    with pytest.raises(SpecError):
        validate_record(record, GOOD["id"], "test")


def test_a_heading_and_its_block_have_to_agree():
    with pytest.raises(SpecError):
        validate_record(dict(GOOD), "POL-GEN-2", "test")


# --- the report -------------------------------------------------------------


def test_the_report_is_the_same_every_time_it_is_built():
    # it is committed, so a report that reordered itself between runs would churn every diff and make the
    # one change that mattered impossible to see
    _, requirements, verified_by, untagged = trace.check()
    first = trace.build_report(requirements, verified_by, untagged, [])
    assert trace.build_report(requirements, verified_by, untagged, []) == first


def test_the_report_names_every_requirement():
    _, requirements, verified_by, untagged = trace.check()
    rendered = trace.build_report(requirements, verified_by, untagged, [])
    missing = [requirement.id for requirement in requirements if requirement.id not in rendered]
    assert not missing, f"requirements the matrix leaves out: {', '.join(missing)}"


def test_the_committed_report_is_up_to_date():
    # the matrix is generated, so a stale one is a stale claim about what the evidence covers
    _, requirements, verified_by, untagged = trace.check()
    expected = trace.build_report(requirements, verified_by, untagged, [])
    assert trace.REPORT_PATH.exists(), "run `python3 tools/trace.py report`"
    assert trace.REPORT_PATH.read_text(encoding="utf-8") == expected, \
        "specs/TRACEABILITY.md is out of date, run `python3 tools/trace.py report`"


def test_a_finding_reads_as_one_line():
    assert str(Finding("verification", "specs/policies/random.md", "POL-RND-1 has no test")) == \
        "[verification] specs/policies/random.md: POL-RND-1 has no test"
