import logging
import signal
import time

from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import SessionLocal
from app.services.processing import claim_batch, process_certificate, recover_stale

logger = logging.getLogger("app.worker")


def run_once(session_factory: sessionmaker[Session], batch_size: int) -> int:
    claimed = claim_batch(session_factory, batch_size)
    for cert_id in claimed:
        process_certificate(session_factory, cert_id)
    return len(claimed)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("weasyprint").setLevel(logging.WARNING)
    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        logger.info("received signal %s, finishing current batch", signum)
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    logger.info("worker started")
    last_sweep = 0.0
    while not stopping:
        try:
            if time.monotonic() - last_sweep >= settings.worker_sweep_interval_seconds:
                recover_stale(SessionLocal)
                last_sweep = time.monotonic()
            processed = run_once(SessionLocal, settings.worker_batch_size)
        except Exception:
            logger.exception("worker loop error, retrying after a pause")
            processed = 0

        if processed:
            logger.info("processed %s certificates", processed)
        else:
            time.sleep(settings.worker_poll_interval_seconds)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
