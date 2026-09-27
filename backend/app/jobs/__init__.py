"""
Orchestration entrypoints — each module here is runnable standalone
(`python -m app.jobs.run_X`) and is what a scheduler calls in production.

For a hackathon demo, running these manually (or via `make ingest` /
`make pipeline`) is enough. For anything longer-lived, wrap them with
APScheduler's BackgroundScheduler in app/main.py's startup hook:

    from apscheduler.schedulers.background import BackgroundScheduler
    from app.jobs.run_ingestion import run_ingestion
    from app.jobs.run_pipeline import run_pipeline

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_ingestion, "interval", hours=3)
    scheduler.add_job(run_pipeline, "interval", hours=3, minutes=15)  # offset so pipeline always sees fresh ingestion
    scheduler.start()

Left out of main.py by default so `uvicorn --reload` during development
doesn't double-schedule jobs across reloads.
"""
