"""Test helper for the supported prepare-then-start execution contract."""


def start_worker(application, request):
    prepared = application.assign_worker(**request)
    if prepared["outcome"] not in {"committed", "prepared"}:
        return prepared
    return application.start(schedule_id=prepared["schedule_id"])
