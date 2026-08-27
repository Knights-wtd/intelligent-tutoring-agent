from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tutor_api.core.config import ProviderProfileConfig
from tutor_api.providers.models import FxVersion, PriceVersion, ProviderProfile
from tutor_api.providers.schemas import ModelCatalogItem

_PRICE_PENDING = "价格待公布"


def synchronize_provider_profiles(
    session: Session, profiles: tuple[ProviderProfileConfig, ...]
) -> None:
    """Synchronize runtime descriptors while retaining profiles no longer configured."""

    profile_keys = [profile.id for profile in profiles]
    for configured in profiles:
        _insert_profile_if_missing(session, configured)
    existing_by_key = {
        profile.profile_key: profile
        for profile in session.scalars(
            select(ProviderProfile).where(ProviderProfile.profile_key.in_(profile_keys))
        )
    }
    for configured in profiles:
        profile = existing_by_key[configured.id]
        if profile.provider != configured.provider or profile.model != configured.model:
            # A price snapshot belongs to this exact provider/model identity.  Never
            # relabel it; keep the mismatched identity disabled but refresh its
            # presentation metadata so the catalog never shows stale descriptors.
            profile.display_name = configured.display_name
            profile.supports_usage = configured.supports_usage
            profile.enabled = False
            continue
        profile.display_name = configured.display_name
        profile.supports_usage = configured.supports_usage
        if not configured.supports_usage:
            profile.enabled = False

    for profile in session.scalars(
        select(ProviderProfile).where(
            ProviderProfile.enabled.is_(True), ProviderProfile.supports_usage.is_(False)
        )
    ):
        profile.enabled = False


def _insert_profile_if_missing(session: Session, configured: ProviderProfileConfig) -> None:
    values = {
        "profile_key": configured.id,
        "provider": configured.provider,
        "model": configured.model,
        "display_name": configured.display_name,
        "supports_usage": configured.supports_usage,
        "enabled": configured.enabled_by_default and configured.supports_usage,
    }
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(ProviderProfile).values(values).on_conflict_do_nothing(
            index_elements=["profile_key"]
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(ProviderProfile).values(values).on_conflict_do_nothing(
            index_elements=["profile_key"]
        )
    else:
        raise RuntimeError("Provider profile synchronization requires PostgreSQL or SQLite")
    session.execute(statement)


def list_user_models(session: Session) -> list[ModelCatalogItem]:
    now = datetime.now(UTC)
    profile_prices = session.execute(_catalog_price_query(now)).all()
    currencies = {
        price.currency
        for _, price in profile_prices
        if price is not None and price.currency != "CNY"
    }
    fx_by_currency = _latest_rmb_fx_by_currency(session, currencies, now)
    return [
        ModelCatalogItem(
            id=profile.profile_key,
            provider=profile.provider,
            display_name=profile.display_name,
            price_summary=_rmb_price_summary(
                price, fx_by_currency.get(price.currency) if price is not None else None
            ),
        )
        for profile, price in profile_prices
    ]


def _catalog_price_query(now: datetime) -> Select[tuple[ProviderProfile, PriceVersion | None]]:
    latest_price = (
        select(
            PriceVersion.id.label("price_id"),
            PriceVersion.provider_profile_id.label("profile_id"),
            func.row_number()
            .over(
                partition_by=PriceVersion.provider_profile_id,
                order_by=PriceVersion.effective_at.desc(),
            )
            .label("rank"),
        )
        .where(PriceVersion.effective_at <= now)
        .subquery()
    )
    return (
        select(ProviderProfile, PriceVersion)
        .outerjoin(
            latest_price,
            (latest_price.c.profile_id == ProviderProfile.id) & (latest_price.c.rank == 1),
        )
        .outerjoin(
            PriceVersion,
            (PriceVersion.provider_profile_id == ProviderProfile.id)
            & (PriceVersion.id == latest_price.c.price_id),
        )
        .where(ProviderProfile.enabled.is_(True), ProviderProfile.supports_usage.is_(True))
        .order_by(ProviderProfile.profile_key)
    )


def _latest_rmb_fx_by_currency(
    session: Session, currencies: set[str], now: datetime
) -> dict[str, FxVersion]:
    if not currencies:
        return {}
    latest_fx = (
        select(
            FxVersion.id.label("fx_id"),
            func.row_number()
            .over(
                partition_by=FxVersion.base_currency,
                order_by=FxVersion.effective_at.desc(),
            )
            .label("rank"),
        )
        .where(
            FxVersion.base_currency.in_(currencies),
            FxVersion.quote_currency == "CNY",
            FxVersion.effective_at <= now,
        )
        .subquery()
    )
    rates = session.scalars(
        select(FxVersion)
        .join(latest_fx, (FxVersion.id == latest_fx.c.fx_id) & (latest_fx.c.rank == 1))
    )
    return {rate.base_currency: rate for rate in rates}


def _rmb_price_summary(price: PriceVersion | None, fx: FxVersion | None) -> str:
    if price is None or (price.currency != "CNY" and fx is None):
        return _PRICE_PENDING
    exchange_rate = Decimal("1") if price.currency == "CNY" else fx.rate
    return (
        f"输入 ¥{price.input_unit_price * exchange_rate:.8f}；"
        f"缓存输入 ¥{price.cached_input_unit_price * exchange_rate:.8f}；"
        f"输出 ¥{price.output_unit_price * exchange_rate:.8f} / {price.unit_size} tokens"
    )
