"""LeadHunter AI — a production-oriented autonomous lead-generation agent.

Pipeline: discover -> normalize -> dedup -> enrich -> verify -> qualify ->
score -> personalize -> demo -> approve -> send (approval-gated) -> track.
State is persisted in SQLite; every run is resumable from the last state.
"""

__version__ = "0.1.0"
