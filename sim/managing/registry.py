"""Name -> class lookup for the parts a managing system is built from.

There is one of these per MAPE-K role, declared in the __init__.py of the package that role lives in:
monitor/, analyze/, plan/, execute/ and knowledge/. A role's registry is the list of implementations that
exist for it, and naming one in a string is what lets a managing system be described as data rather than as
code -- see systems.py, where a whole managing system is one line naming five of them.

This is the same arrangement the simulation already uses for policies (sim/policy/__init__.py): a tuple of
registered classes, a name to class mapping built from it, and a build function that fails helpfully. It is
a small class here rather than five copies of that code because there are five roles, and because the error
a mistyped name produces is worth writing once.
"""


class Registry:
    """The implementations of one MAPE-K role, by name."""

    # constructor. 'role' is what the role is called in an error message ("planner"), and 'registered' is
    # the tuple of classes that implement it, each carrying a unique 'name'. The first of them is what the
    # role falls back to when a managing system does not name one, unless 'default' says otherwise.
    def __init__(self, role, registered=(), default=None):
        self.role = role
        self.registry = {}
        for implementation in registered:
            self.add(implementation)
        self.default = default if default is not None else next(iter(self.registry), None)

    # registers one implementation. Refuses to overwrite a name, because two components answering to the
    # same one would make which of them a managing system is built from depend on import order.
    def add(self, implementation):
        name = getattr(implementation, "name", None)
        if not name:
            raise ValueError(f"{implementation.__name__} has no 'name', so it cannot be registered "
                             f"as a {self.role}")
        if name in self.registry and self.registry[name] is not implementation:
            raise ValueError(f"two {self.role}s are both called {name!r}: "
                             f"{self.registry[name].__name__} and {implementation.__name__}")
        self.registry[name] = implementation
        return implementation

    # the class registered under a name, raising the way build_policy() does: naming what was not found and
    # what could have been
    def lookup(self, name):
        if name not in self.registry:
            raise KeyError(f"unknown {self.role} {name!r}, available: {', '.join(self.names())}")
        return self.registry[name]

    # builds the implementation registered under a name, or the default one when nothing is named.
    #
    # Anything already built is passed straight through, so that a caller holding an instance -- a test, or
    # a managing system being composed by hand -- can pass it as the same argument a caller naming one uses.
    # The keyword arguments are the constructor's, and are ignored for an instance, which already has them.
    def build(self, name=None, **kwargs):
        if name is None:
            name = self.default
        if not isinstance(name, str):
            return name
        return self.lookup(name)(**kwargs)

    # every registered name, sorted, which is what the error messages and the --list-managing output show
    def names(self):
        return sorted(self.registry)

    def __contains__(self, name):
        return name in self.registry

    def __iter__(self):
        return iter(self.names())

    def __len__(self):
        return len(self.registry)
