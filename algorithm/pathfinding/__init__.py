# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
The planner package.

Explicit ``__init__.py`` files: the reference relied on PEP-420 namespace packages, which
works at runtime but breaks pytest collection and packaging. Imports inside this package are
absolute (``from pathfinding...``, ``import config``), so ``algorithm`` must be on
``sys.path``.
"""
