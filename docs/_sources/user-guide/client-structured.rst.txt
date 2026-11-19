Client: structured data
=======================

Celery serialises arguments and results as JSON. To exchange structured data, send
dicts: dump your pydantic (or dataclass) objects on the way out and validate them on
the way in.

.. literalinclude:: ../examples/client/structured.py
   :language: python
   :caption: structured.py

The task that answers is :doc:`server-local-tasks` (``reports.summarize``):

.. code-block:: text

   {'id': '8e5878aa-...', 'words': 10, 'first_words': 'Serverless workers scale to zero'}

Rules of thumb
--------------

* **Only JSON types** cross the wire: ``str``, numbers, ``bool``, ``None``, lists and
  dicts. ``datetime``, ``Decimal`` or ``UUID`` objects should be converted first
  (``model_dump(mode="json")`` does it for pydantic models). On the result side the
  runner stores anything else as its ``str()``.
* **Keep arguments small.** SQS messages are limited to 256 KB; send an S3 key or a
  database id rather than a payload.
* **Keep results small.** A result over about 380 KB becomes a ``FAILURE``
  (``ResultTooLargeException``). Store big outputs in S3 and return their location.
* **Use the same task name** on both sides and version your payloads (add new
  optional fields rather than renaming) so clients and the runner can be deployed
  independently.
