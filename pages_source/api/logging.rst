Logging
=======

The runner logs with `loguru <https://loguru.readthedocs.io>`_. Every invocation
gets a ``trace_id`` that appears in all its log lines. Task code should use the
same ``logger`` so its messages carry that id:

.. code-block:: python

   from celery_cloud.logging import logger

   def add(args: list, kwargs: dict) -> int:
       logger.info("adding {} numbers", len(args))
       return sum(args)

.. automodule:: celery_cloud.logging
   :members:
   :show-inheritance:
