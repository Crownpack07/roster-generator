"""The Phase 1 core must stay free of web and database dependencies.

P1 §8 calls the solver core "a pure Python library with no web dependencies".
Phase 1's only cross-task regression was roster/__init__.py rebinding an
attribute and silently disabling the equivalent guard for the verifier, so
this file checks the property two independent ways.
"""

import ast
import subprocess
import sys
import textwrap

FORBIDDEN_ROOTS = {"fastapi", "starlette", "pymongo", "bson", "mongomock"}


def test_the_solver_core_imports_neither_fastapi_nor_pymongo():
    """Checked in a fresh interpreter, so transitive imports are caught too.

    An AST scan of one file only sees that file's own import statements. A
    dependency three modules deep would pass it and still break the claim.
    """
    script = textwrap.dedent(
        """
        import sys
        import roster
        import roster.solve
        import roster.model
        import roster.verify
        import roster.io

        forbidden = {"fastapi", "starlette", "pymongo", "bson", "mongomock"}
        leaked = sorted(m for m in sys.modules if m.split(".")[0] in forbidden)
        print(",".join(leaked))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "", proc.stdout


def test_the_package_init_does_not_import_the_store_jobs_or_api_layers():
    """roster/__init__.py stays a pure-core surface.

    Importing roster.store here would drag pymongo into every `import roster`,
    including the CLI's and the child solve process's.
    """
    import roster

    tree = ast.parse(open(roster.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        m
        for m in imported
        if m.startswith(("roster.store", "roster.jobs", "roster.api"))
    }
    assert forbidden == set(), forbidden
