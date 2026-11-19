Client: workflows
=================

``link``, ``chain``, ``group``, ``chord``, ``link_error``, ``map``, ``starmap`` and
``chunks`` work with the normal Celery API. How they run is explained in
:ref:`workflows <workflows>`.

.. literalinclude:: ../examples/client/canvas.py
   :language: python
   :caption: canvas.py

Which task a result belongs to
------------------------------

When the runner starts the next task of a workflow the client did not call
``apply_async`` for it, so it needs the id in advance: ``signature.freeze()`` returns the
``AsyncResult`` before the signature is sent (as in the ``link`` example), and a
``chain`` or ``chord`` result already knows its steps (``result.parent``).

Chords
------

* The body receives **one argument**: the list of results of the header, in the order of
  the header.
* A chord needs a result backend that can count: Celery's DynamoDB backend can (the
  client creates the ``chord_count`` item when it starts the chord), so use the same table
  as the runner.
* If a header task fails the body is not run: its result is ``FAILURE`` with
  ``celery.exceptions.ChordError`` (``Dependency <id> raised ...``), and its ``link_error``
  callbacks run.
* Every header task must store its result: do not send them with ``ignore_result``.

Errbacks
--------

A ``link_error`` task receives the **id of the failed task** (the classic errback form).
Declare it as ``def handler(task_id)``; to find out what went wrong look the task up with
``AsyncResult(task_id)``.

What happens if a step fails
----------------------------

* In a **chain** the next tasks never start; the chain result is the ``FAILURE`` of the
  failing step (``result.get()`` raises its original exception).
* In a **group** the other tasks are unaffected; ``get()`` raises the first failure.
* The messages that start the next tasks are sent after the task stores its result. If
  SQS rejects them (very rare, the SDK retries) the callback is lost and only logged.

Map, starmap and chunks
-----------------------

They run as ``celery.map`` / ``celery.starmap``: the runner calls the task once per item
in **one invocation**, so the whole list must finish within the time limit (about 15
minutes). ``chunks`` splits the work into several ``starmap`` messages, which run in
parallel. The mapped task must be listed in ``TASKS``.
