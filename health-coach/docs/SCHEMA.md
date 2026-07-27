# Design notes for v0 schema (see also src/db/models.py)

## Entities

users
  id, email, display_name, created_at

source_files
  id, user_id, source, filename, checksum, imported_at, row_count, metadata_json

measurements
  id, user_id, metric_type, timestamp, value, unit, source,
  source_record_id, confidence, metadata_json, import_batch_id
  UNIQUE(user_id, metric_type, timestamp, source, source_record_id)

meals
  id, user_id, timestamp, meal_type, description, calories, protein_g,
  carbohydrate_g, fat_g, fiber_g, sodium_mg, source, confidence, ...

workouts / exercise_sets
  session + set-level strength data (Hevy later)

daily_contexts
  date-level soft signals: cycle, restaurant, alcohol, stress, hunger, notes

interventions
  deliberate experiments with hypothesis, adherence, results, confidence

daily_summaries
  one analytical row per user/day — primary input to hypothesis engine

hypotheses
  ranked explanations for a date (persisted optionally; computed on read in v0)

recommendations
  traceable actions linked to hypotheses

## Preferred sources (summary construction)

weight:     smart_scale > manual > macrofactor > apple_health > garmin > synthetic
nutrition:  macrofactor > manual > synthetic
steps:      apple_watch > garmin > apple_health > iphone > synthetic
sleep:      garmin > apple_watch > apple_health > synthetic
