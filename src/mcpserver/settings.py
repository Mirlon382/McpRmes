"""Every value this server can be configured with."""

from textwrap import dedent

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# (default, maximum) pairs of ToolLimits, checked together at startup.
DEFAULT_AND_MAXIMUM_FIELDS = (
    ("rmes_query_default_timeout_seconds", "rmes_query_max_timeout_seconds"),
    ("rmes_query_default_max_rows", "rmes_query_max_rows"),
)


class ToolLimits(BaseSettings):
    """The budgets written into the published tool schemas: defaults and maximums of the tool parameters.

    Kept apart from the rest because a tool's schema is built when its model module is imported, before
    server.py builds `Settings`. The models read this part on their own, through `load_tool_limits`.
    `Settings` inherits it, so every variable is still typed, overridable and documented in one place.
    Changing one changes the schema the tools advertise, after a restart like any other setting.
    """

    # run_rmes_sparql --------------------------------------------------------------------------------------------------
    rmes_query_default_timeout_seconds: float = Field(default=20.0, gt=0)
    rmes_query_max_timeout_seconds: float = Field(default=60.0, gt=0)
    # Appended as a LIMIT when the query has none.
    rmes_query_default_max_rows: int = Field(default=200, ge=1)
    rmes_query_max_rows: int = Field(default=2000, ge=1)

    @model_validator(mode="after")
    def keep_defaults_within_maximums(self) -> "ToolLimits":
        """FastMCP never validates a parameter's default, so a default above its maximum would be used as is."""
        for default_field, maximum_field in DEFAULT_AND_MAXIMUM_FIELDS:
            default, maximum = getattr(self, default_field), getattr(self, maximum_field)
            if default > maximum:
                raise ValueError(
                    f"{default_field.upper()} ({default}) is above {maximum_field.upper()} ({maximum}). "
                    "Lower the default or raise the maximum."
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


class Settings(BaseSettings):
    server_name: str = "INSEE-mcp-server"
    instructions: str = dedent("""
        - RMES -- statistical metadata: definitions and nomenclatures. It holds no figures.

    """).strip()

    # HTTP server ------------------------------------------------------------------------------------------------------
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    # JSON list of the hostnames clients use to reach this server, checked against the Host
    # header. "*" accepts any host, which disables the check.
    allowed_hosts: list[str] = ["*"]
    # JSON list of browser origins allowed to call the server. Empty rejects every cross-origin
    # browser request, which is right until a browser-based client needs in.
    allowed_origins: list[str] = []
    # Peers whose X-Forwarded-For header is believed; anything else keeps its real socket address.
    # Accepts addresses, CIDR networks and literals. Widening this lets callers forge their own address.
    trusted_proxy_hosts: list[str] = ["127.0.0.1"]

    # RMES services ----------------------------------------------------------------------------------------
    rmes_sparql_endpoint_url: str = "https://rdf.insee.fr/sparql"
    # Not an address to call: the namespace every named graph URI starts with, stripped off
    # before a graph is matched against a family.
    rmes_graph_base_uri: str = "http://rdf.insee.fr/graphes/"
    # Listing every graph counts triples across the whole store, so it gets its own budget.
    rmes_graph_listing_timeout_seconds: float = 45.0
    rmes_graph_listing_max_rows: int = 1000
    rmes_graph_cache_ttl_seconds: float = 3600.0
    # describe_rmes_resource sends a fixed query the model cannot size, so it has its own budget.
    rmes_resource_query_timeout_seconds: float = Field(default=20.0, gt=0)
    rmes_resource_query_max_rows: int = Field(default=2000, ge=1)

    # Rate limiting ----------------------------------------------------------------------------------------------------
    rate_limit_max_requests: int = 100
    rate_limit_window_minutes: int = 1

    # Logging ----------------------------------------------------------------------------------------------------------
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


def load_settings() -> Settings:
    return Settings()


def load_tool_limits() -> ToolLimits:
    return ToolLimits()
