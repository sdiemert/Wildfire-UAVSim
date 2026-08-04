"""The architectural guarantee: the managing system cannot see the managed system.

Every other test in this directory checks that the managing system does the right thing. This one checks
that it *cannot* do the wrong thing, which is a different and more durable kind of check: it fails the
moment anybody, for any reason, imports the simulation into sim/managing/.

That matters because the independence claimed for this architecture is not a property of any one function.
It is a property of what the package is able to reach at all, and the only way to keep it true as the code
changes is to assert it directly rather than to rely on everyone remembering. Once this test passes, the
whole Plan step can be moved onto a server (see sim/managing/plan/remote.py) without anything being
discovered to have quietly depended on a model attribute along the way.
"""

# python libraries

import ast
import pathlib

import pytest

# the package under inspection, found relative to this file so the test does not care where the repository
# is checked out
MANAGING = pathlib.Path(__file__).resolve().parents[2] / "sim" / "managing"

# what the managing system may not reach. sim.policy is on the list as well as the model and the agents:
# the policies are part of the managed system, and the managing system names them only as the strings that
# travel in a directive, never as classes it could call.
FORBIDDEN = ("sim.model", "sim.agents", "sim.adaptive", "sim.adapters", "sim.policy",
             "sim.environment", "sim.fire_spread", "sim.formulas", "sim.gui", "sim.cli", "mesa")

# what it may reach: the standard library, and config, which is shared by the whole project and holds
# nothing but settings
ALLOWED_TOP_LEVEL = ("config",)


def managing_modules():
    return sorted(MANAGING.rglob("*.py"))


# every absolute module name imported by a file, with relative imports left out: those can only reach
# inside sim/managing/ itself, which is the point
def imported_modules(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    names = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 is a relative import: from .contract import ..., which stays in the package
            if node.level == 0 and node.module:
                names.append(node.module)

    return names


def test_the_package_was_actually_found():
    # guards against the test passing because rglob found nothing after a move
    assert managing_modules(), f"no modules found under {MANAGING}"


@pytest.mark.parametrize("path", managing_modules(), ids=lambda path: path.name)
def test_no_module_imports_the_managed_system(path):
    """No module in sim/managing/ may import the simulation, at any depth."""
    for name in imported_modules(path):
        for forbidden in FORBIDDEN:
            assert name != forbidden and not name.startswith(forbidden + "."), (
                f"{path.name} imports {name!r}. The managing system reaches the managed system only "
                f"through the Sensor and Effector interfaces in sim/managing/ports.py; put whatever this "
                f"was for into the snapshot (sim/managing/contract.py) or into the adapter that builds it "
                f"(sim/adapters.py)."
            )


@pytest.mark.parametrize("path", managing_modules(), ids=lambda path: path.name)
def test_the_only_project_module_it_imports_is_config(path):
    """Stated the other way round, so a newly added sim/ package is caught without updating FORBIDDEN."""
    for name in imported_modules(path):
        top_level = name.split(".")[0]
        assert top_level not in ("sim",), f"{path.name} imports {name!r} from the simulation"
        if top_level == "config":
            assert top_level in ALLOWED_TOP_LEVEL


def test_the_managing_package_imports_without_the_simulation(monkeypatch):
    """Importing sim.managing must not drag the model in behind it.

    A module can satisfy the source level checks above and still pull the simulation in through a package
    __init__, so this imports it for real in a fresh interpreter state and looks at what turned up.
    """
    import subprocess
    import sys

    code = (
        "import sim.managing, sys;"
        "leaked = [name for name in sys.modules"
        " if name.startswith(('sim.model', 'sim.agents', 'sim.policy', 'sim.adaptive', 'mesa'))];"
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            cwd=str(MANAGING.parents[1]))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"importing sim.managing pulled in: {result.stdout.strip()}"
