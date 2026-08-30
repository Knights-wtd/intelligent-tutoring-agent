from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import tutor_api.providers.models  # noqa: F401
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.main import create_app
from tutor_api.providers.models import FxVersion, PriceVersion, ProviderProfile
from tutor_api.providers.service import synchronize_provider_profiles


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    settings = Settings(
        app_env="test",
        provider_profiles_json=(
            '[{"id":"openai-gpt","provider":"openai","model":"gpt-test",'
            '"display_name":"测试模型","supports_usage":true,"enabled_by_default":true},'
            '{"id":"disabled","provider":"other","model":"other-test",'
            '"display_name":"已停用模型","supports_usage":true,"enabled_by_default":false},'
            '{"id":"unverifiable","provider":"other","model":"other-test",'
            '"display_name":"无法核验用量","supports_usage":false,"enabled_by_default":true}]'
        ),
    )
    return TestClient(create_app(settings, sessionmaker(bind=engine))), engine


def register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201


def test_user_sees_only_enabled_usage_capable_models(client_and_engine) -> None:
    client, _ = client_and_engine
    register(client, "learner")

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    # A profile with no active RMB snapshot stays usable, but deliberately has no price claim.
    assert response.json() == [
        {
            "id": "openai-gpt",
            "display_name": "测试模型",
            "provider": "openai",
            "price_summary": "价格待公布",
        }
    ]


def test_model_catalog_converts_the_current_price_snapshot_to_rmb(client_and_engine) -> None:
    client, engine = client_and_engine
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        profile = session.query(ProviderProfile).filter_by(profile_key="openai-gpt").one()
        session.add_all(
            [
                PriceVersion(
                    provider_profile_id=profile.id,
                    effective_at=datetime.now(UTC) - timedelta(days=1),
                    source_url="https://example.test/old-price",
                    currency="CNY",
                    input_unit_price=Decimal("0.50"),
                    cached_input_unit_price=Decimal("0.25"),
                    output_unit_price=Decimal("1.00"),
                    unit_size=1_000_000,
                ),
                PriceVersion(
                    provider_profile_id=profile.id,
                    effective_at=datetime.now(UTC) - timedelta(minutes=1),
                    source_url="https://example.test/current-price",
                    currency="USD",
                    input_unit_price=Decimal("1"),
                    cached_input_unit_price=Decimal("0.5"),
                    output_unit_price=Decimal("2"),
                    unit_size=1_000_000,
                ),
                FxVersion(
                    base_currency="USD",
                    quote_currency="CNY",
                    effective_at=datetime.now(UTC) - timedelta(minutes=1),
                    rate=Decimal("7.2"),
                    source_url="https://example.test/fx",
                ),
            ]
        )
    register(client, "learner")

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    assert response.json()[0]["price_summary"] == (
        "输入 ¥7.20000000；缓存输入 ¥3.60000000；输出 ¥14.40000000 / 1000000 tokens"
    )


def test_model_catalog_withholds_a_non_rmb_price_without_an_active_fx_rate(
    client_and_engine,
) -> None:
    client, engine = client_and_engine
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        profile = session.query(ProviderProfile).filter_by(profile_key="openai-gpt").one()
        session.add(
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                source_url="https://example.test/usd-price",
                currency="USD",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0.5"),
                output_unit_price=Decimal("2"),
                unit_size=1_000_000,
            )
        )
    register(client, "learner")

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    assert response.json()[0]["price_summary"] == "价格待公布"


def test_model_catalog_requires_an_authenticated_session(client_and_engine) -> None:
    client, _ = client_and_engine

    assert client.get("/api/v1/models").status_code == 401


def test_model_catalog_never_returns_provider_key_or_base_url(client_and_engine) -> None:
    client, _ = client_and_engine
    register(client, "learner")

    response = client.get("/api/v1/models")

    assert "api_key" not in response.text.casefold()
    assert "base_url" not in response.text.casefold()
    assert "timeout" not in response.text.casefold()
    assert "provider_profiles_json" not in response.text.casefold()


def test_startup_sync_updates_configured_profiles_without_deleting_historical_rows() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        session.add(
            ProviderProfile(
                profile_key="historic",
                provider="legacy",
                model="legacy-model",
                display_name="历史模型",
                supports_usage=True,
                enabled=False,
            )
        )
        session.add(
            ProviderProfile(
                profile_key="historic-unverifiable",
                provider="legacy",
                model="legacy-unverifiable-model",
                display_name="历史不可核验模型",
                supports_usage=False,
                enabled=True,
            )
        )

    settings = Settings(
        app_env="test",
        provider_profiles_json=(
            '[{"id":"openai-gpt","provider":"openai","model":"gpt-test",'
            '"display_name":"测试模型","supports_usage":true,"enabled_by_default":true}]'
        ),
    )
    with TestClient(create_app(settings, factory)):
        pass

    with factory() as session:
        profiles = {
            profile.profile_key: profile for profile in session.query(ProviderProfile).all()
        }
        assert profiles["openai-gpt"].enabled is True
        assert profiles["openai-gpt"].model == "gpt-test"
        assert profiles["historic"].display_name == "历史模型"
        assert profiles["historic-unverifiable"].enabled is False
    engine.dispose()


def test_startup_disables_a_profile_when_its_configured_model_changes() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    original_settings = Settings(
        app_env="test",
        provider_profiles_json=(
            '[{"id":"openai-gpt","provider":"openai","model":"gpt-test",'
            '"display_name":"测试模型","supports_usage":true,"enabled_by_default":true}]'
        ),
    )
    with TestClient(create_app(original_settings, factory)):
        pass
    with factory.begin() as session:
        profile = session.query(ProviderProfile).filter_by(profile_key="openai-gpt").one()
        session.add(
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                source_url="https://example.test/old-price",
                currency="CNY",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0.5"),
                output_unit_price=Decimal("2"),
                unit_size=1_000_000,
            )
        )
    changed_settings = Settings(
        app_env="test",
        provider_profiles_json=(
            '[{"id":"openai-gpt","provider":"openai","model":"gpt-new",'
            '"display_name":"新模型","supports_usage":true,"enabled_by_default":true}]'
        ),
    )
    with TestClient(create_app(changed_settings, factory)) as client:
        register(client, "learner")
        assert client.get("/api/v1/models").json() == []

    with factory() as session:
        profile = session.query(ProviderProfile).filter_by(profile_key="openai-gpt").one()
        assert profile.model == "gpt-test"
        assert profile.enabled is False
    engine.dispose()


def test_synchronization_is_idempotent_when_the_profile_key_already_exists() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    settings = Settings(
        app_env="test",
        provider_profiles_json=(
            '[{"id":"openai-gpt","provider":"openai","model":"gpt-test",'
            '"display_name":"测试模型","supports_usage":true,"enabled_by_default":true}]'
        ),
    )
    with factory.begin() as session:
        synchronize_provider_profiles(session, settings.provider_profiles)
    with factory.begin() as session:
        synchronize_provider_profiles(session, settings.provider_profiles)

    with factory() as session:
        assert session.query(ProviderProfile).filter_by(profile_key="openai-gpt").count() == 1
    engine.dispose()


@pytest.fixture
def client_and_engine():
    client, engine = make_client()
    try:
        with client:
            yield client, engine
    finally:
        engine.dispose()
