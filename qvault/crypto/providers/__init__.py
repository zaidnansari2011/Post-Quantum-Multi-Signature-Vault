"""Concrete PQC backend providers.

This is the ONLY package permitted to import a post-quantum backend (``quantcrypt`` today,
``oqs``/liboqs in future). A test in ``tests/test_module_boundaries.py`` enforces this rule,
which is what keeps the rest of the codebase algorithm-agnostic.
"""
