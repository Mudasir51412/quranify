"""
Gamification (report Module 7) — computed from real sessions on every
read. No stored counters: points, levels and badges can never drift
from the underlying recitation history.

Points: 1 per correct word + 10 per session + 15 bonus per perfect Ayah.
Levels: thresholds below; level = highest threshold reached (1-based).
"""
from datetime import timedelta

from ..ai.reference import load_reference
from ..models import RecitationSession

LEVEL_THRESHOLDS = [0, 100, 250, 500, 900, 1400, 2000, 3000, 4500, 6500]


def _longest_streak(sessions: list[RecitationSession]) -> int:
    days = sorted({s.created_at.date() for s in sessions if s.created_at})
    best = current = 1 if days else 0
    for prev, cur in zip(days, days[1:]):
        current = current + 1 if (cur - prev) == timedelta(days=1) else 1
        best = max(best, current)
    return best


def compute_gamification(sessions: list[RecitationSession]) -> dict:
    correct_words = sum(s.correct_words for s in sessions)
    perfect = [s for s in sessions if s.status == "ok" and s.mode != "phrase"
               and s.total_words > 0 and s.correct_words == s.total_words]
    points = correct_words + 10 * len(sessions) + 15 * len(perfect)

    level = 1
    for i, t in enumerate(LEVEL_THRESHOLDS):
        if points >= t:
            level = i + 1
    next_at = LEVEL_THRESHOLDS[level] if level < len(LEVEL_THRESHOLDS) else None

    # Surah completion: every Ayah of a Surah recited at least once
    ref = load_reference()
    recited: dict[int, set[int]] = {}
    for s in sessions:
        if s.mode == "phrase" or s.status != "ok":
            continue
        recited.setdefault(s.surah, set()).add(s.ayah)
    completed_surahs = [num for num, ayahs in recited.items()
                        if num in ref and len(ayahs) >= len(ref[num])]

    longest = _longest_streak(sessions)
    badges = [
        {"id": "first_recitation", "name": "First Recitation",
         "description": "Complete your first recitation analysis",
         "earned": len(sessions) >= 1, "progress": min(len(sessions), 1), "target": 1},
        {"id": "perfect_ayah", "name": "Perfect Ayah",
         "description": "Recite an Ayah with no detected mistakes",
         "earned": len(perfect) >= 1, "progress": min(len(perfect), 1), "target": 1},
        {"id": "hundred_words", "name": "100 Correct Words",
         "description": "Reach 100 correctly recited words",
         "earned": correct_words >= 100, "progress": min(correct_words, 100), "target": 100},
        {"id": "ten_sessions", "name": "Consistent Learner",
         "description": "Complete 10 recitation sessions",
         "earned": len(sessions) >= 10, "progress": min(len(sessions), 10), "target": 10},
        {"id": "streak_7", "name": "7-Day Streak",
         "description": "Recite on 7 consecutive days",
         "earned": longest >= 7, "progress": min(longest, 7), "target": 7},
        {"id": "huffaz_mode", "name": "Huffaz Mode Explorer",
         "description": "Complete a continuous (Huffaz) recitation session",
         "earned": any(s.mode == "continuous" for s in sessions),
         "progress": 1 if any(s.mode == "continuous" for s in sessions) else 0, "target": 1},
        {"id": "surah_complete", "name": "Surah Completed",
         "description": "Recite every Ayah of a Surah",
         "earned": len(completed_surahs) >= 1,
         "progress": len(completed_surahs), "target": 1},
    ]
    return {
        "points": points,
        "level": level,
        "next_level_at": next_at,
        "points_to_next_level": (next_at - points) if next_at is not None else 0,
        "badges": badges,
        "badges_earned": sum(1 for b in badges if b["earned"]),
        "completed_surahs": completed_surahs,
        "longest_streak_days": longest,
    }
