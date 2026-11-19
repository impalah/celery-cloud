API Reference
=============

Reference of the ``celery_cloud`` package, generated from the docstrings of the
source code. Task authors need :doc:`api/tasks` and :doc:`api/signals`; client
applications may use :doc:`api/client`; the rest is for people extending or debugging the
runner.

.. toctree::
   :maxdepth: 2
   :caption: For task authors

   api/tasks
   api/signals
   api/logging
   api/exceptions

.. toctree::
   :maxdepth: 2
   :caption: For client applications

   api/client

.. toctree::
   :maxdepth: 2
   :caption: Runner internals

   api/runners
   api/strategies
   api/canvas
   api/messaging
   api/models
   api/serialization
   api/deadline
   api/entities
   api/settings
