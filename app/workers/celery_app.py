"""The one Celery application for the whole backend. Every module's tasks
register on it and are routed to their own queue (rule: three separate
queues — ingest / simulate / optimize — so a slow one never starves another,
design AD-18).
"""

from celery import Celery

from app.core.config import settings

# A Celery worker is a separate process from the FastAPI app, so it only has
# whatever SQLAlchemy model modules IT has imported — app.main.py importing
# app.gis.router (which imports app.gis.models) doesn't help a worker
# process that never runs app.main. Without these, resolving a string-based
# ForeignKey like ValidationReport.gis_layer_id -> "gis_layers.id" fails at
# first use with NoReferencedTableError, because GISLayer's table was never
# registered on this process's Base.metadata. Same reasoning as the
# explicit imports in migrations/env.py and tests/conftest.py.
from app.audit import models as _audit_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.budget import models as _budget_models  # noqa: F401
from app.gis import models as _gis_models  # noqa: F401
from app.habitation import models as _habitation_models  # noqa: F401
from app.ingestion import models as _ingestion_models  # noqa: F401
from app.optimization import models as _optimization_models  # noqa: F401
from app.parameters import models as _parameters_models  # noqa: F401
from app.scenario import models as _scenario_models  # noqa: F401
from app.simulation import models as _simulation_models  # noqa: F401
from app.validation import models as _validation_models  # noqa: F401

celery_app = Celery(
    "swms",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks_ingest",
        "app.workers.tasks_gis",
        "app.workers.tasks_simulate",
        "app.workers.tasks_optimize",
    ],
)

celery_app.conf.update(
    task_routes={
        "app.workers.tasks_ingest.*": {"queue": "ingest"},
        "app.workers.tasks_gis.*": {"queue": "ingest"},
        "app.workers.tasks_simulate.*": {"queue": "simulate"},
        "app.workers.tasks_optimize.*": {"queue": "optimize"},
    },
    # A worker that dies mid-task re-delivers the task instead of losing it
    # (rule: "worker killed mid-job -> job re-delivered, no partial data").
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
)
