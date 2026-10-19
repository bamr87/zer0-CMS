"""Deterministic agents: a definition whose `handler` names one of these runs
it instead of a model. Handlers act only through `registry.call`, so a rules
agent is held to exactly the policy, permissions and audit trail of a model
agent — the difference is that it is cheap and gives the same answer twice."""
