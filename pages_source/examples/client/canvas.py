"""Workflows: link, chain, group and chord."""

from celery import chain, chord, group
from celery_app import add, divide, report_error, subtract, total

# link: run a second task with the result of the first
second = subtract.s(1)
second_result = second.freeze()  # freeze() gives us its AsyncResult before sending
add.apply_async(args=(10, 3), link=second)
print(second_result.get(timeout=60))  # (10 + 3) - 1 = 12

# chain: each task receives the result of the previous one
workflow = chain(add.s(1, 2), add.s(10), subtract.s(3)).apply_async()
print(workflow.get(timeout=60))  # ((1 + 2) + 10) - 3 = 10
print([step.result for step in (workflow.parent.parent, workflow.parent, workflow)])  # 3, 13, 10

# group: independent tasks, the result is the list of results
print(group(add.s(1, 1), add.s(2, 2), add.s(3, 3)).apply_async().get(timeout=60))  # [2, 4, 6]

# chord: a group, then ONE task that receives the list of results
print(chord([add.s(1, 2), add.s(3, 4), add.s(5, 6)])(total.s()).get(timeout=60))  # 21

# link_error: run a task when another one fails (it receives the failed task id)
handler = report_error.s()
handled = handler.freeze()
divide.apply_async(args=(1, 0), link_error=handler)
print(handled.get(timeout=60))  # handled failure of <task id>

# map / starmap / chunks: one task over many inputs
print(add.starmap([(1, 2), (3, 4), (5, 6)]).apply_async().get(timeout=60))  # [3, 7, 11]
print(add.chunks([(1, 1), (2, 2), (3, 3), (4, 4)], 2).apply_async().get(timeout=60))  # [[2, 4], [6, 8]]
