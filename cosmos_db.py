"""
Cosmos DB data layer for ReactorPets.

Design decisions (aligned with cosmosdb-best-practices):
  - Singleton CosmosClient (sdk-singleton-client)
  - Gateway mode + disabled SSL verification for emulator (sdk-emulator-ssl)
  - Point reads where id + partition key are known (query-point-reads)
  - Embedded timeline in applications (model-embed-related)
  - Type discriminator on every document (model-type-discriminator)

Container layout & partition keys (partition-query-patterns):
  pets          /id        – point reads by pet ID; full-scan list is small
  users         /id        – point reads for session loading (login_manager)
  applications  /userId    – "my applications" = single-partition query
"""

import os
import urllib3

from dotenv import load_dotenv
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError

load_dotenv()

# ---------------------------------------------------------------------------
# Emulator defaults (sdk-emulator-ssl)
# ---------------------------------------------------------------------------
COSMOS_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
COSMOS_KEY = os.environ["COSMOS_KEY"]
DATABASE_NAME = os.environ.get("COSMOS_DATABASE", "reactorpets")

# Suppress self-signed cert warnings for emulator only
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Singleton client (sdk-singleton-client)
# Python SDK defaults to Gateway mode — correct for emulator.
# ---------------------------------------------------------------------------
_client = CosmosClient(
    url=COSMOS_ENDPOINT,
    credential=COSMOS_KEY,
    connection_verify=False,  # emulator self-signed cert
)


def init_db():
    """Create database and containers on startup (idempotent)."""
    db = _client.create_database_if_not_exists(DATABASE_NAME)

    db.create_container_if_not_exists(
        id="pets",
        partition_key=PartitionKey(path="/id"),
    )
    db.create_container_if_not_exists(
        id="users",
        partition_key=PartitionKey(path="/id"),
    )
    db.create_container_if_not_exists(
        id="applications",
        partition_key=PartitionKey(path="/userId"),
    )
    return db


_db = None


def _get_db():
    global _db
    if _db is None:
        _db = init_db()
    return _db


def _container(name):
    return _get_db().get_container_client(name)


# ---------------------------------------------------------------------------
# Pets
# ---------------------------------------------------------------------------
def upsert_pet(pet: dict):
    _container("pets").upsert_item(pet)


def get_pet(pet_id: str):
    """Point read by id (query-point-reads): 1 RU vs ~2.5 RU."""
    try:
        return _container("pets").read_item(item=pet_id, partition_key=pet_id)
    except CosmosResourceNotFoundError:
        return None


def list_pets():
    return list(_container("pets").read_all_items())


def delete_pet(pet_id: str):
    try:
        _container("pets").delete_item(item=pet_id, partition_key=pet_id)
    except CosmosResourceNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def upsert_user(user_doc: dict):
    _container("users").upsert_item(user_doc)


def get_user(user_id: str):
    """Point read (query-point-reads)."""
    try:
        return _container("users").read_item(item=user_id, partition_key=user_id)
    except CosmosResourceNotFoundError:
        return None


def find_user_by_username(username: str):
    """Single cross-partition query — infrequent (login only)."""
    items = list(
        _container("users").query_items(
            query="SELECT * FROM c WHERE c.username = @u",
            parameters=[{"name": "@u", "value": username}],
            enable_cross_partition_query=True,
        )
    )
    return items[0] if items else None


# ---------------------------------------------------------------------------
# Applications (timeline embedded per model-embed-related)
# ---------------------------------------------------------------------------
def upsert_application(app_doc: dict):
    _container("applications").upsert_item(app_doc)


def get_application(app_id: str, user_id: str):
    """Point read with userId partition key (query-point-reads)."""
    try:
        return _container("applications").read_item(
            item=app_id, partition_key=user_id
        )
    except CosmosResourceNotFoundError:
        return None


def list_applications_for_user(user_id: str):
    """Single-partition query — partition key = userId (partition-query-patterns)."""
    return list(
        _container("applications").query_items(
            query="SELECT * FROM c WHERE c.userId = @uid",
            parameters=[{"name": "@uid", "value": user_id}],
            partition_key=user_id,
        )
    )


def find_application_for_pet(pet_id: str, user_id: str):
    """Single-partition query scoped to one user."""
    items = list(
        _container("applications").query_items(
            query="SELECT * FROM c WHERE c.petId = @pid AND c.userId = @uid",
            parameters=[
                {"name": "@pid", "value": pet_id},
                {"name": "@uid", "value": user_id},
            ],
            partition_key=user_id,
        )
    )
    return items[0] if items else None
