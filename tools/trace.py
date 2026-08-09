"""Checks and reports the requirement -> implementation -> verification trace for the UAV policies.

The three legs of the trace live in three different places, each of which is the only source of truth for
its leg: the requirement in a section of a file under specs/policies/, the implementation in that
requirement's `satisfied_by` field, and the verification in the `@pytest.mark.verifies` markers on the
tests. This module reads all three and reports where they fail to line up.

A requirement section has a fixed anatomy -- heading, optional preamble, the statement as a blockquote,
optional discussion, and a yaml block last carrying metadata and traceability. parse_section() enforces
it. The statement being a blockquote rather than a yaml field is what lets it be written in Markdown,
where `observation.low_fuel()` reads as code; the enforcement is what keeps it findable anyway.

Both sides are read statically, with `ast`, rather than by running the suite. That means `check()` gives
the same answer no matter which subset of the tests was collected, and that the checker and the report can
never disagree with one another about what the trace says, because they are the same code.

The YAML in the specification files is parsed here rather than with PyYAML. The project ships three
runtime dependencies and one test dependency, all of them earning their place, and a documentation tool is
a poor reason to add a fifth. The blocks use a deliberately small subset -- scalars, folded scalars and
lists of scalars, nothing nested -- and parse_block() rejects anything outside it rather than guessing, so
the constraint stays visible to whoever writes the next specification.

Usage:
    python3 tools/trace.py check     report the findings, exit non-zero if there are any
    python3 tools/trace.py report    regenerate specs/TRACEABILITY.md
"""

# python libraries

import ast
import re
import sys

from dataclasses import dataclass
from pathlib import Path

# the repository root, so that this runs as a script from anywhere and can still import the simulator
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# own python modules

from sim.policy import POLICIES

SPEC_DIR = REPO_ROOT / "specs"
POLICY_SPEC_DIR = SPEC_DIR / "policies"
TESTS_DIR = REPO_ROOT / "tests"
REPORT_PATH = SPEC_DIR / "TRACEABILITY.md"

# the specification that is not about any one policy: the obligations every policy inherits
CONTRACT_SPEC = "_contract.md"

# the yaml block carries metadata and traceability and nothing else. The statement is the blockquote
# above it, and the rationale and assumptions are the prose around it -- see specs/README.md.
REQUIRED_FIELDS = ("id", "satisfied_by", "verified_by", "status")
LIST_FIELDS = ("satisfied_by",)

VERIFICATION_METHODS = ("test", "inspection", "analysis", "none")
STATUSES = ("draft", "agreed", "retired")

REQUIREMENT_ID = re.compile(r"^POL-([A-Z]{2,4})-(\d+)$")
HEADING = re.compile(r"^##\s+(POL-[A-Z]{2,4}-\d+)\s*[-–—]?\s*(.*)$")
FIELD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$")
IMPLEMENTATION = re.compile(r"^(?P<path>[\w./-]+\.py)::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?)$")


class SpecError(Exception):
    """Raised when a specification file cannot be read as a set of requirement records."""


@dataclass
class Requirement:
    """One requirement record, as read from a specification file."""

    id: str
    title: str
    statement: str                  # the blockquote, not a field of the yaml block
    satisfied_by: list
    verified_by: str
    status: str
    spec: str                       # path relative to the repository root
    line: int                       # line the heading sits on, for error messages

    @property
    def tag(self):
        return REQUIREMENT_ID.match(self.id).group(1)

    @property
    def needs_test(self):
        return self.verified_by == "test" and self.status != "retired"


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the trace.

    'kind' groups findings so that the test suite can report them separately, and 'where' is the file the
    reader should open.
    """

    kind: str
    where: str
    message: str

    def __str__(self):
        return f"[{self.kind}] {self.where}: {self.message}"


# --- the specification block parser -----------------------------------------


# strips the quotes off a scalar, so that a statement which has to start with a character YAML would
# otherwise read as syntax can still be written
def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


# collects the run of lines belonging to the field just read: everything up to the next line that starts
# in column zero. Returns the lines and the index to carry on from.
def take_indented(lines, index):
    block = []
    while index < len(lines):
        line = lines[index]
        if line.strip() and not line[0].isspace():
            break
        block.append(line)
        index += 1
    return block, index


def parse_block(text, source):
    """Read one requirement block into a dictionary.

    The accepted subset is exactly two shapes, both at the top level:

        key: value              a scalar
        key:                    a list, its indented lines each starting with '- '

    Anything else raises SpecError. Guessing at a third shape would mean the specification format quietly
    growing past what everything downstream expects.

    Folded scalars ('key: >') are deliberately rejected rather than merely unused. The whole point of the
    format is that prose lives in Markdown above this block, where it renders; leaving the syntax working
    would be an open invitation to put it back.
    """
    record = {}
    lines = text.split("\n")
    index = 0

    while index < len(lines):
        raw = lines[index]
        index += 1

        if not raw.strip() or raw.startswith("#"):
            continue
        if raw[0].isspace():
            raise SpecError(f"{source}: indented line outside any field: {raw.strip()!r}")

        match = FIELD.match(raw)
        if not match:
            raise SpecError(f"{source}: expected 'field: value', got {raw.strip()!r}")

        key, rest = match.group(1), match.group(2).strip()
        if key in record:
            raise SpecError(f"{source}: field {key!r} given twice")

        if rest in (">", "|"):
            raise SpecError(f"{source}: field {key!r} is a folded scalar. This block holds metadata and "
                            f"traceability only; prose belongs above it, in the statement blockquote or "
                            f"the paragraphs around it")
        if rest == "":
            block, index = take_indented(lines, index)
            items = []
            for item in block:
                stripped = item.strip()
                if not stripped:
                    continue
                if stripped.startswith("- "):
                    items.append(unquote(stripped[2:].strip()))
                elif items:
                    # a wrapped item: an assumption worth writing down is usually longer than one line
                    items[-1] = f"{items[-1]} {stripped}"
                else:
                    raise SpecError(f"{source}: expected a '- ' list item under {key!r}, got {stripped!r}")
            record[key] = items
        else:
            record[key] = unquote(rest)

    return record


def validate_record(record, requirement_id, source):
    """Check one parsed block against the schema, raising SpecError on the first problem."""
    for key in record:
        if key not in REQUIRED_FIELDS:
            raise SpecError(f"{source}: unknown field {key!r}, expected one of "
                            f"{', '.join(sorted(REQUIRED_FIELDS))}")

    for key in REQUIRED_FIELDS:
        if key not in record:
            raise SpecError(f"{source}: missing required field {key!r}")

    for key, value in record.items():
        wanted_list = key in LIST_FIELDS
        if wanted_list and not isinstance(value, list):
            raise SpecError(f"{source}: field {key!r} must be a '- ' list")
        if not wanted_list and not isinstance(value, str):
            raise SpecError(f"{source}: field {key!r} must be a scalar, not a list")

    if not REQUIREMENT_ID.match(record["id"]):
        raise SpecError(f"{source}: {record['id']!r} is not a well formed id, expected POL-<TAG>-<number>")
    if record["id"] != requirement_id:
        raise SpecError(f"{source}: heading says {requirement_id}, the block says {record['id']}")

    if not record["satisfied_by"]:
        raise SpecError(f"{source}: {record['id']} names no implementation in satisfied_by")

    for target in record["satisfied_by"]:
        if not IMPLEMENTATION.match(target):
            raise SpecError(f"{source}: {record['id']} satisfied_by {target!r} is not 'path.py::Symbol' "
                            f"or 'path.py::Symbol.method'")

    if record["verified_by"] not in VERIFICATION_METHODS:
        raise SpecError(f"{source}: {record['id']} verified_by {record['verified_by']!r}, expected one of "
                        f"{', '.join(VERIFICATION_METHODS)}")
    if record["status"] not in STATUSES:
        raise SpecError(f"{source}: {record['id']} status {record['status']!r}, expected one of "
                        f"{', '.join(STATUSES)}")


# --- reading the specifications ---------------------------------------------


def spec_files():
    """Every policy specification file, in a stable order, the shared contract first."""
    if not POLICY_SPEC_DIR.is_dir():
        return []
    contract = POLICY_SPEC_DIR / CONTRACT_SPEC
    rest = sorted(path for path in POLICY_SPEC_DIR.glob("*.md") if path.name != CONTRACT_SPEC)
    return ([contract] if contract.exists() else []) + rest


def split_sections(lines):
    """Cut a specification file into requirement sections.

    A section runs from a '## POL-...' heading to the next one, or to the end of the file. Whatever sits
    above the first heading is the file's own prose and belongs to no requirement.

    Yields (requirement id, title, heading line number, body lines).
    """
    sections = []
    current = None

    for number, line in enumerate(lines, start=1):
        match = HEADING.match(line)
        if match:
            if current is not None:
                sections.append(current)
            current = (match.group(1), match.group(2).strip(), number, [])
        elif current is not None:
            current[3].append(line)

    if current is not None:
        sections.append(current)
    return sections


def parse_section(body, source):
    """Pull the statement and the yaml block out of one requirement section.

    The anatomy is fixed, and the point of fixing it is that a reader always finds the obligation in the
    same place:

        optional preamble
        > the statement, as a blockquote
        optional rationale and discussion
        ```yaml ... ```     metadata and traceability, last

    Everything this rejects is a way the layout could drift back into burying the statement. Returns
    (statement, block text); raises SpecError.
    """
    quotes = []            # runs of consecutive '>' lines, each (first index, last index, text)
    fence_start = None
    fence_end = None
    block = []
    inside = False

    for index, line in enumerate(body):
        stripped = line.strip()

        if stripped == "```yaml" and fence_start is None:
            fence_start, inside = index, True
            continue
        if inside:
            if stripped == "```":
                inside, fence_end = False, index
            else:
                block.append(line)
            continue
        if stripped.startswith("```"):
            continue       # some other fenced block, prose as far as we are concerned

        if stripped.startswith(">"):
            text = stripped[1:].lstrip()
            if quotes and quotes[-1][1] == index - 1:
                quotes[-1] = (quotes[-1][0], index, f"{quotes[-1][2]} {text}".strip())
            else:
                quotes.append((index, index, text))

    if inside:
        raise SpecError(f"{source}: the yaml block is never closed")
    if fence_start is None:
        raise SpecError(f"{source}: has no yaml block")
    if not quotes:
        raise SpecError(f"{source}: has no statement. The statement is a '>' blockquote between the "
                        f"heading and the yaml block")
    if len(quotes) > 1:
        raise SpecError(f"{source}: has {len(quotes)} blockquotes and exactly one is allowed, because the "
                        f"blockquote is what identifies the statement")
    if quotes[0][0] > fence_start:
        raise SpecError(f"{source}: the statement blockquote comes after the yaml block; the yaml block "
                        f"goes last")

    trailing = [line for line in body[fence_end + 1:] if line.strip()]
    if trailing:
        raise SpecError(f"{source}: {trailing[0].strip()!r} follows the yaml block; the yaml block goes "
                        f"last, so discussion belongs above it")

    statement = " ".join(quotes[0][2].split())
    # SHALL is what makes a statement an obligation rather than a description, and the specs/README.md
    # rule about it is worth enforcing rather than hoping for
    if "SHALL" not in statement:
        raise SpecError(f"{source}: the statement does not say SHALL, so it describes rather than requires")

    return statement, "\n".join(block)


def parse_spec_file(path):
    """Read one specification file into requirements and findings."""
    requirements = []
    findings = []
    relative = path.relative_to(REPO_ROOT).as_posix()

    lines = path.read_text(encoding="utf-8").split("\n")

    for requirement_id, title, number, body in split_sections(lines):
        source = f"{relative}:{number}"
        try:
            statement, block = parse_section(body, f"{source} ({requirement_id})")
            record = parse_block(block, source)
            validate_record(record, requirement_id, source)
        except SpecError as error:
            findings.append(Finding("spec", relative, str(error)))
            continue

        requirements.append(Requirement(
            id=record["id"],
            title=title,
            statement=statement,
            satisfied_by=record["satisfied_by"],
            verified_by=record["verified_by"],
            status=record["status"],
            spec=relative,
            line=number,
        ))

    return requirements, findings


def parse_specs():
    """Every requirement in the repository, with any findings from reading them."""
    requirements = []
    findings = []
    for path in spec_files():
        found, problems = parse_spec_file(path)
        requirements.extend(found)
        findings.extend(problems)
    return requirements, findings


# --- the implementation leg -------------------------------------------------


# every name a satisfied_by entry may point at: top level functions, classes, their methods, and module
# level constants, which is what lets a requirement trace to a setting in config.py
def module_symbols(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{child.name}")
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            names.add(f"{node.name}.{target.id}")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)

    return names


def resolve_implementations(requirements):
    """Report every satisfied_by entry that does not point at a symbol that exists."""
    findings = []
    cache = {}

    for requirement in requirements:
        for target in requirement.satisfied_by:
            path_part, symbol = target.split("::", 1)
            path = REPO_ROOT / path_part

            if path_part not in cache:
                if not path.is_file():
                    cache[path_part] = None
                else:
                    try:
                        cache[path_part] = module_symbols(path)
                    except SyntaxError as error:
                        cache[path_part] = None
                        findings.append(Finding("implementation", requirement.spec,
                                                f"{requirement.id} traces to {path_part}, which does not "
                                                f"parse: {error}"))

            symbols = cache[path_part]
            if symbols is None:
                if path.is_file():
                    continue  # already reported as a parse failure
                findings.append(Finding("implementation", requirement.spec,
                                        f"{requirement.id} traces to {path_part}, which does not exist"))
            elif symbol not in symbols:
                findings.append(Finding("implementation", requirement.spec,
                                        f"{requirement.id} traces to {symbol} in {path_part}, which has "
                                        f"no such class, method, function or constant"))

    return findings


# --- the verification leg ---------------------------------------------------


# whether a decorator is @pytest.mark.verifies(...)
def is_verifies(decorator):
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    return (isinstance(func, ast.Attribute) and func.attr == "verifies"
            and isinstance(func.value, ast.Attribute) and func.value.attr == "mark"
            and isinstance(func.value.value, ast.Name) and func.value.value.id == "pytest")


def collect_markers():
    """Read every @pytest.mark.verifies marker in the suite.

    Returns the requirement id -> test locations mapping, the test functions that carry no marker, and any
    findings. Only string literals are read: a marker built out of a variable is reported rather than
    skipped, because a link the tool cannot follow looks exactly like no link at all in the report.
    """
    verified_by = {}
    untagged = []
    findings = []

    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            ids = []
            for decorator in node.decorator_list:
                if not is_verifies(decorator):
                    continue
                if not decorator.args:
                    findings.append(Finding("marker", relative,
                                            f"{node.name} is marked verifies() with no requirement id"))
                for argument in decorator.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        ids.append(argument.value)
                    else:
                        findings.append(Finding("marker", relative,
                                                f"{node.name} passes a non literal to verifies(); only "
                                                f"string literals can be traced"))

            where = f"{relative}::{node.name}"
            for requirement_id in ids:
                verified_by.setdefault(requirement_id, []).append(where)

            if not ids and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test_"):
                untagged.append(where)

    return verified_by, untagged, findings


# --- the cross checks -------------------------------------------------------


def check():
    """Every way the trace is currently broken.

    Returns (findings, requirements, verified_by, untagged) so that a caller which has already paid for the
    parse can report on it without doing the work twice.
    """
    requirements, findings = parse_specs()
    verified_by, untagged, marker_findings = collect_markers()
    findings = list(findings) + marker_findings

    # ids are identities, so two requirements sharing one makes every reference to it ambiguous
    seen = {}
    for requirement in requirements:
        if requirement.id in seen:
            findings.append(Finding("duplicate-id", requirement.spec,
                                    f"{requirement.id} is also defined in {seen[requirement.id]}"))
        else:
            seen[requirement.id] = requirement.spec

    # one tag per file and one file per tag, which is what lets the file a requirement lives in be worked
    # out from its id alone
    tags = {}
    for requirement in requirements:
        tags.setdefault(requirement.spec, set()).add(requirement.tag)
    for spec, used in sorted(tags.items()):
        if len(used) > 1:
            findings.append(Finding("tag", spec,
                                    f"mixes the tags {', '.join(sorted(used))}; one file holds one tag"))
    owner = {}
    for spec, used in sorted(tags.items()):
        for tag in sorted(used):
            if tag in owner:
                findings.append(Finding("tag", spec, f"tag {tag} is also used by {owner[tag]}"))
            else:
                owner[tag] = spec

    # every registered policy has a specification, and every specification is about a registered policy
    present = {path.name for path in spec_files()}
    for name in sorted(POLICIES):
        if f"{name}.md" not in present:
            findings.append(Finding("missing-spec", f"specs/policies/{name}.md",
                                    f"policy {name!r} is registered but has no specification"))
    for name in sorted(present - {CONTRACT_SPEC}):
        if name[:-3] not in POLICIES:
            findings.append(Finding("orphan-spec", f"specs/policies/{name}",
                                    f"there is no registered policy named {name[:-3]!r}"))

    findings.extend(resolve_implementations(requirements))

    # a requirement that says it is verified by test, and is not
    for requirement in requirements:
        if requirement.needs_test and not verified_by.get(requirement.id):
            findings.append(Finding("verification", requirement.spec,
                                    f"{requirement.id} is verified_by test but no test is marked "
                                    f"verifies({requirement.id!r})"))

    # a marker naming a requirement that does not exist, or one that has been retired
    known = {requirement.id: requirement for requirement in requirements}
    for requirement_id, wheres in sorted(verified_by.items()):
        requirement = known.get(requirement_id)
        if requirement is None:
            findings.append(Finding("unknown-id", wheres[0],
                                    f"verifies({requirement_id!r}) names a requirement no specification "
                                    f"defines"))
        elif requirement.status == "retired":
            findings.append(Finding("unknown-id", wheres[0],
                                    f"verifies({requirement_id!r}) names a retired requirement"))

    return findings, requirements, verified_by, untagged


# --- the report -------------------------------------------------------------


# markdown table cells hold one line and cannot hold an unescaped pipe
def cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def joined(values):
    return "<br>".join(f"`{value}`" for value in values) if values else "—"


def build_report(requirements, verified_by, untagged, findings):
    """Render the traceability matrix. Deterministic: the same inputs give byte identical output."""
    out = []
    out.append("# Traceability matrix")
    out.append("")
    out.append("Generated by `python3 tools/trace.py report`. Do not edit by hand: every column below is")
    out.append("derived from the specifications under `specs/policies/` and the `@pytest.mark.verifies`")
    out.append("markers in `tests/`, so this file describes the repository as it is rather than as it was")
    out.append("when somebody last remembered to update a table.")
    out.append("")
    out.append(f"{len(requirements)} requirements, "
               f"{sum(len(verified_by.get(r.id, [])) for r in requirements)} verification links.")
    out.append("")

    for spec in sorted({requirement.spec for requirement in requirements}):
        out.append(f"## `{spec}`")
        out.append("")
        out.append("| Requirement | Statement | Implementation | Verified by | Status |")
        out.append("|---|---|---|---|---|")
        for requirement in [r for r in requirements if r.spec == spec]:
            tests = sorted(verified_by.get(requirement.id, []))
            method = requirement.verified_by if not tests else "test"
            out.append(f"| **{requirement.id}**<br>{cell(requirement.title)} "
                       f"| {cell(requirement.statement)} "
                       f"| {joined(requirement.satisfied_by)} "
                       f"| {joined(tests) if tests else cell(method)} "
                       f"| {requirement.status} |")
        out.append("")

    # the other direction: open a source symbol and see what it is required to do
    out.append("## By implementation")
    out.append("")
    out.append("| Symbol | Requirements |")
    out.append("|---|---|")
    reverse = {}
    for requirement in requirements:
        for target in requirement.satisfied_by:
            reverse.setdefault(target, []).append(requirement.id)
    for target in sorted(reverse):
        out.append(f"| `{target}` | {', '.join(sorted(reverse[target]))} |")
    out.append("")

    out.append("## Gaps")
    out.append("")
    without = [r for r in requirements if r.verified_by != "test" and r.status != "retired"]
    if without:
        out.append("Requirements offered without test evidence:")
        out.append("")
        for requirement in without:
            out.append(f"- **{requirement.id}** — `verified_by: {requirement.verified_by}`")
        out.append("")
    else:
        out.append("Every current requirement is verified by test.")
        out.append("")

    retired = [r for r in requirements if r.status == "retired"]
    if retired:
        out.append(f"Retired, ids held out of circulation: {', '.join(r.id for r in retired)}.")
        out.append("")

    policy_untagged = sorted(where for where in untagged if where.startswith("tests/policy/"))
    if policy_untagged:
        out.append(f"{len(policy_untagged)} tests under `tests/policy/` carry no `verifies` marker. That is")
        out.append("allowed — not every test is evidence for a stated requirement — but a long list here is")
        out.append("usually a sign that the specifications are behind the tests. The SuperPolicy tests are")
        out.append("expected to be here: see \"What is not specified here\" in `specs/README.md`.")
        out.append("")
        for where in policy_untagged:
            out.append(f"- `{where}`")
        out.append("")

    if findings:
        out.append("## Findings")
        out.append("")
        out.append("The trace is currently broken. `python3 tools/trace.py check` exits non-zero.")
        out.append("")
        for finding in findings:
            out.append(f"- {finding}")
        out.append("")

    return "\n".join(out)


def report():
    findings, requirements, verified_by, untagged = check()
    REPORT_PATH.write_text(build_report(requirements, verified_by, untagged, findings), encoding="utf-8")
    return findings


# --- command line -----------------------------------------------------------


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else "check"

    if command == "check":
        findings, requirements, _, _ = check()
    elif command == "report":
        findings = report()
        _, requirements, _, _ = check()
        print(f"wrote {REPORT_PATH.relative_to(REPO_ROOT)}")
    else:
        print(__doc__)
        return 2

    if not findings:
        print(f"{len(requirements)} requirements, trace complete")
        return 0

    for finding in findings:
        print(finding)
    print(f"\n{len(findings)} findings")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
