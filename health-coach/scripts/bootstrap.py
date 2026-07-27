"""Bootstrap SQLite DB from the synthetic CSV sample."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics.daily_summary import rebuild_daily_summaries
from src.coaching.explanation import explain_weight_for_date
from src.db.config import ROOT_DIR, settings
from src.db.session import SessionLocal, init_db
from src.ingestion.csv_daily import import_daily_metrics_csv


def main() -> None:
    db_path = Path(settings.database_url.replace("sqlite:///", ""))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    init_db()
    csv_path = ROOT_DIR / "data" / "raw" / "synthetic" / "daily_metrics.csv"

    with SessionLocal() as db:
        result = import_daily_metrics_csv(
            db,
            csv_path,
            user_email=settings.default_user_email,
            user_name=settings.default_user_name,
            source="synthetic",
        )
        summaries = rebuild_daily_summaries(db, result["user_id"])
        explanation = explain_weight_for_date(db, date(2026, 7, 8))

    print(
        json.dumps(
            {
                "import": {**result, "summaries_built": summaries},
                "sample_explanation_date": "2026-07-08",
                "primary_hypothesis": explanation.primary_hypothesis,
                "confidence": explanation.confidence,
                "top_evidence": explanation.hypotheses[0].evidence,
                "recommendations": [r.action for r in explanation.recommendations],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
