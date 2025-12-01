import os
try:
	from celery import Celery
	REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
	celery = Celery('musicjacker', broker=REDIS_URL, backend=REDIS_URL)
	# basic celery config — tune in production
	celery.conf.update(task_serializer='json', result_serializer='json', accept_content=['json'], timezone='UTC', enable_utc=True)
except Exception:
	# Celery not available in this environment — provide a None placeholder and let tasks fall back
	celery = None
