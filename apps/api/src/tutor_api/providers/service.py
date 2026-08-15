from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.core.config import ProviderProfileConfig
from tutor_api.providers.models import PriceVersion, ProviderProfile
from tutor_api.providers.schemas import ModelCatalogItem

_PRICE_PENDING = "价格待公布"


def synchronize_provider_profiles(
    session: Session, profiles: tuple[ProviderProfileConfig, ...]
) -> None:
    """Synchronize runtime descriptors while retaining profiles no longer configured."""

    profile_keys = [profile.id for profile in profiles]
    existing_by_key = (
        {
            profile.profile_key: profile
            for profile in session.scalars(
                select(ProviderProfile).where(ProviderProfile.profile_key.in_(profile_keys))
            )
        }
        if profile_keys
        else {}
    )
    for configured in profiles:
        profile = existing_by_key.get(configured.id)
        if profile is None:
            session.add(
                ProviderProfile(
                    profile_key=configured.id,
                    provider=configured.provider,
                    model=configured.model,
                    display_name=configured.display_name,
                    supports_usage=configured.supports_usage,
                    enabled=configured.enabled_by_default and configured.supports_usage,
                )
            )
            continue
        profile.provider = configured.provider
        profile.model = configured.model
        profile.display_name = configured.display_name
        profile.supports_usage = configured.supports_usage
        if not configured.supports_usage:
            profile.enabled = False


def list_user_models(session: Session) -> list[ModelCatalogItem]:
    profiles = session.scalars(
        select(ProviderProfile)
        .where(ProviderProfile.enabled.is_(True), ProviderProfile.supports_usage.is_(True))
        .order_by(ProviderProfile.profile_key)
    ).all()
    now = datetime.now(UTC)
    return [
        ModelCatalogItem(
            id=profile.profile_key,
            provider=profile.provider,
            display_name=profile.display_name,
            price_summary=_current_rmb_price_summary(session, profile, now),
        )
        for profile in profiles
    ]


def _current_rmb_price_summary(
    session: Session, profile: ProviderProfile, now: datetime
) -> str:
    price = session.scalar(
        select(PriceVersion)
        .where(
            PriceVersion.provider_profile_id == profile.id,
            PriceVersion.currency == "CNY",
            PriceVersion.effective_at <= now,
        )
        .order_by(PriceVersion.effective_at.desc())
        .limit(1)
    )
    if price is None:
        return _PRICE_PENDING
    return (
        f"输入 ¥{price.input_unit_price:.8f}；"
        f"缓存输入 ¥{price.cached_input_unit_price:.8f}；"
        f"输出 ¥{price.output_unit_price:.8f} / {price.unit_size} tokens"
    )
