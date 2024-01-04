SovrynRollupBridge
==================

Getting Started
---------------

- cd ``<directory containing this file>``

- Create a Python 3.5+ virtual environment; hereinafter the directory is
  referred to as ``$VENV``.

- ``$VENV/bin/python -mpip install -e .``

- Migrate the database to the initial state with
  ``$VENV/bin/alembic -n dev upgrade head``

- Alternatively you might want to forgo the database creation now, remove the
  ``migrations/versions/INIT_initial.py``, edit the models and create a new
  initial migration with ``alembic -n dev revision --autogenerate``.

- ``$VENV/bin/pserve development.ini --reload``
