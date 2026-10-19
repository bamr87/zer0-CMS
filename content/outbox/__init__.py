"""The transactional outbox: cross-plane events written in the same database
transaction as the change they describe, then relayed to Redis Streams."""
