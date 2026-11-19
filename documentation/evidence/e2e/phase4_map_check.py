"""map / starmap / chunks against a real Celery client."""
from celery import group
from e2e_client import add, natural_add

print("starmap:", add.starmap([(1, 2), (3, 4), (5, 6)]).apply_async().get(timeout=60))
print("map (one arg + sig arg):", natural_add.map([1, 2, 3]).apply_async().get(timeout=60))
print("chunks:", add.chunks([(1, 2), (3, 4), (5, 6), (7, 8)], 2).apply_async().get(timeout=60))
