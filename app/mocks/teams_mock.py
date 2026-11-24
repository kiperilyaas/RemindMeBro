"""
Mock delle comunicazioni informali (Microsoft Teams, email dell'ateneo): ora vuoto.

L'app parte da zero: i messaggi arrivano dai docenti (area docente → Announce,
canale Teams o email) e dagli avvisi pubblicati in UniLearn.
"""
from typing import Any, Dict, List


def get_channel_messages() -> List[Dict[str, Any]]:
    return []


def get_emails() -> List[Dict[str, Any]]:
    return []
