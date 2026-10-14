"""Deterministic score records derived from completed replay experiments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    display_name: str
    avatar: str
    faction: str


@dataclass(frozen=True, slots=True)
class ReplayScore:
    score_id: str
    experiment_id: str
    user_id: str
    stock_code: str
    stock_name: str
    decision_mode: str
    capital: float
    pnl: float
    pnl_pct: float
    faction: str


def normalize_profile(user_id: str, display_name: str, avatar: str, faction: str) -> UserProfile:
    """Validate display-only fields before they enter persistent storage."""

    name = " ".join(display_name.strip().split())
    if not user_id.strip():
        raise ValueError("user_id must not be empty")
    if not 1 <= len(name) <= 24:
        raise ValueError("display_name must contain 1 to 24 characters")
    if any(ord(character) < 32 or character in "<>{}" for character in name):
        raise ValueError("display_name contains unsupported characters")
    avatar = avatar.strip() or "🎮"
    if len(avatar) > 8:
        raise ValueError("avatar must contain at most 8 characters")
    if faction not in {"jin", "mu", "shui", "huo", "tu"}:
        raise ValueError("unsupported faction")
    return UserProfile(user_id=user_id, display_name=name, avatar=avatar, faction=faction)

