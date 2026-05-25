"""
core.infra.sts
==============
Pure subprocess wrappers for Weaviate StatefulSet mutations and rollout
observation via ``kubectl``.  No Qt imports.

These helpers are invoked from background QThread workers in
``features/infra/statefulset/`` — never from the UI thread directly.
"""
