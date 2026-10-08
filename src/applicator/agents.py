"""Three specialised agents, coordinated sequentially by the existing FIFO owner."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import Error as BrowserError

from .browser import LinkedInBrowser
from .discovery_memory import DiscoveryMemory
from .external_browser import ExternalBrowser
from .models import Job, Profile
from .operations import Operation

if TYPE_CHECKING:
    from .service import Service

AGENTS = {
    "Scout": "Research and preparation",
    "Link": "LinkedIn Easy Apply",
    "Bridge": "Company websites",
}


def agent_detail(name: str, detail: str) -> str:
    return (
        detail
        if any(detail.startswith(agent + " · ") for agent in AGENTS)
        else f"{name} · {detail}"
    )


class LinkAgent(LinkedInBrowser):
    agent_name = "Link"


class BridgeAgent(ExternalBrowser):
    agent_name = "Bridge"


class ScoutAgent:
    name = "Scout"

    def __init__(
        self,
        service: "Service",
        *,
        stopping: Callable[[], bool] | None = None,
        browser_factory: Callable[[Path, Profile], LinkedInBrowser] | None = None,
    ):
        self.service = service
        self.stopping = stopping or (lambda: False)
        self.browser_factory = browser_factory or LinkedInBrowser
        self.memory = DiscoveryMemory(service.store)

    def prepare(
        self,
        app_id: int,
        evidence_ids: list[str] | None = None,
        *,
        use_ai: bool | None = None,
        progress: Callable[[str, str], None],
    ) -> None:
        self.service.prepare(
            app_id,
            evidence_ids,
            use_ai=use_ai,
            progress=lambda stage, detail: progress(stage, agent_detail(self.name, detail)),
        )

    def screen(
        self, jobs: list[Job], progress: Callable[[str, str], None] | None = None
    ) -> dict[str, int]:
        return self.service.screen_discovery(
            jobs,
            None
            if progress is None
            else lambda stage, detail: progress(stage, agent_detail(self.name, detail)),
        )

    def search(self, operation: Operation, *, automatic: bool) -> list[Job]:
        store = self.service.store
        settings = store.settings()
        profile, _ = store.profile()
        adapter = self.browser_factory(self.service.data, profile)
        adapter.agent_name = self.name
        adapter.include_external_jobs = settings.external_applications_enabled
        adapter.progress = operation.progress
        adapter.discovery_failure = self.memory.defer
        adapter.discovery_stopping = lambda: (
            self.stopping() or (automatic and not store.settings().automation_enabled)
        )
        try:
            jobs = adapter.search(
                settings.search_keywords,
                settings.search_location,
                excluded_ids=self.memory.excluded_ids(known=automatic),
            )
        except (BrowserError, ValueError) as exc:
            retry_at = self.memory.defer("search", type(exc).__name__)
            operation.progress(
                adapter.form_stage,
                agent_detail(
                    self.name,
                    f"LinkedIn search could not complete ({type(exc).__name__}). Automatic discovery will wait until {retry_at}; check sign-in and page layout. No applications were sent by discovery.",
                ),
            )
            raise
        self.memory.resolved("search")
        for job in jobs:
            self.memory.resolved(job.source_id)
        return jobs
