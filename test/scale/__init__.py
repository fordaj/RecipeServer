"""Opt-in scale/performance tests for RecipeServer.

These tests build and serve a mock recipe library at several sizes and
report timings. They are slow and are skipped unless ``RECIPE_SERVER_SCALE``
is set; see ``test/scale/conftest.py``.
"""
