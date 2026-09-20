#!/usr/bin/env sh
# Validate the AgentTeams Bridge prerequisites without exposing credentials.
set -eu

ENV_FILE="${1:-$(dirname "$0")/bridge.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: Bridge environment file not found: $ENV_FILE" >&2
  exit 2
fi

# shellcheck disable=SC1090
. "$ENV_FILE"

ok=0
warn=0
fail=0
report_ok() { printf 'OK   %s\n' "$1"; ok=$((ok + 1)); }
report_warn() { printf 'WARN %s\n' "$1"; warn=$((warn + 1)); }
report_fail() { printf 'FAIL %s\n' "$1"; fail=$((fail + 1)); }

case "${BRIDGE_ALLOWED_FLOW_IDS:-}" in
  *scrna_seq*) report_ok "Bridge flow allowlist includes scrna_seq" ;;
  *) report_warn "Bridge flow allowlist is '${BRIDGE_ALLOWED_FLOW_IDS:-<empty>}'; scrna_seq cannot be submitted yet" ;;
esac

identities="${BRIDGE_IDENTITIES:-}"
for identity in bioops-manager data-steward approval-authority workflow-operator agent-code agent-viz agent-scrna; do
  case ",$identities," in
    *",$identity:"*) report_ok "Bridge identity configured: $identity" ;;
    *) report_fail "Bridge identity missing: $identity" ;;
  esac
done

bridge_url="${AGENTTEAMS_BRIDGE_URL:-${BRIDGE_URL:-}}"
identity_token() {
  requested="$1"
  printf '%s' "$identities" | tr ',' '\n' | while IFS=: read -r identity token; do
    if [ "$identity" = "$requested" ]; then
      printf '%s' "$token"
      break
    fi
  done
}

if [ -n "$bridge_url" ]; then
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 5 "$bridge_url/healthz" >/dev/null; then
    report_ok "Bridge health endpoint reachable: $bridge_url"
    for identity in bioops-manager data-steward approval-authority workflow-operator; do
      token="$(identity_token "$identity")"
      if [ -n "$token" ] && curl -fsS --max-time 5 \
        -H "X-Bridge-Identity: $identity" \
        -H "X-Bridge-Token: $token" \
        "$bridge_url/v1/health/identity" >/dev/null; then
        report_ok "Bridge credential accepted: $identity"
      else
        report_fail "Bridge credential rejected or missing: $identity"
      fi
    done
    manager_token="$(identity_token bioops-manager)"
    worker_health="$(curl -fsS --max-time 5 \
      -H "X-Bridge-Identity: bioops-manager" \
      -H "X-Bridge-Token: $manager_token" \
      "$bridge_url/v1/health/workers" 2>/dev/null || true)"
    if [ -n "$worker_health" ]; then
      for worker in agent-code agent-viz agent-scrna; do
        if printf '%s' "$worker_health" | grep -Eq '"identity":"?'"$worker"'?"[^}]*"active":true'; then
          report_ok "External Worker heartbeat active: $worker"
        else
          report_fail "External Worker heartbeat missing: $worker (deploy Worker; config alone does not start it)"
        fi
      done
    else
      report_fail "Could not read authenticated Worker health from Bridge"
    fi
  else
    report_fail "Bridge health endpoint could not be reached: $bridge_url"
  fi
else
  report_warn "No AGENTTEAMS_BRIDGE_URL supplied; only static configuration was checked"
fi

cat <<'EOF'
INFO External Workers must actively poll GET /v1/work-items/assigned with their own identities.
INFO Editing CygnusX or Bridge configuration alone does not start agent-code, agent-viz, or agent-scrna Workers.
INFO Worker health is based on their most recent authenticated inbox poll recorded by this Bridge.
EOF
printf 'Summary: %s OK, %s warning, %s failure\n' "$ok" "$warn" "$fail"
[ "$fail" -eq 0 ]
