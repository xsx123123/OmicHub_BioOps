"""Compatibility import for the renamed AgentTeams Case watch service."""

from cygnusx.application.services.agentteams_case_watch_service import AgentTeamsCaseWatchService

CaseWatchService = AgentTeamsCaseWatchService

__all__ = ["AgentTeamsCaseWatchService", "CaseWatchService"]
