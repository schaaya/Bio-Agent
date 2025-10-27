import os
import json
import asyncio
from datetime import datetime
from azure.storage.blob.aio import BlobServiceClient, ContainerClient
from azure.core.exceptions import ResourceNotFoundError
from dotenv import load_dotenv

load_dotenv()

class MetadataManager:
    def __init__(self, connection_string: str, container_name: str = "doc-metadata"):
        self.connection_string = connection_string
        self.container_name = container_name
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_client: ContainerClient = self.blob_service_client.get_container_client(container_name)
        self._lock = asyncio.Lock()

    async def initialize_container(self):
        if not await self.container_client.exists():
            await self.container_client.create_container()
            print(f"Container '{self.container_name}' created.")
        else:
            print(f"Container '{self.container_name}' already exists.")

    async def _get_user_blob_name(self, user_email: str) -> str:
        return f"{user_email}.json"

    async def _download_user_metadata(self, user_email: str) -> dict:
        blob_name = await self._get_user_blob_name(user_email)
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            stream = await blob_client.download_blob()
            data = await stream.readall()
            return json.loads(data.decode('utf-8'))
        except ResourceNotFoundError:
            return {}
        except Exception as e:
            print(f"Error downloading metadata for {user_email}: {e}")
            return {}

    async def _upload_user_metadata(self, user_email: str, metadata: dict) -> None:
        blob_name = await self._get_user_blob_name(user_email)
        blob_client = self.container_client.get_blob_client(blob_name)
        data = json.dumps(metadata)
        await blob_client.upload_blob(data, overwrite=True)

    async def get_all(self, user_email: str) -> dict:
        async with self._lock:
            return await self._download_user_metadata(user_email)

    async def get(self, user_email: str, filename: str) -> dict:
        async with self._lock:
            user_metadata = await self._download_user_metadata(user_email)
            return user_metadata.get(filename)

    async def set(self, user_email: str, filename: str, metadata: dict) -> None:
        async with self._lock:
            user_metadata = await self._download_user_metadata(user_email)
            user_metadata[filename] = metadata
            await self._upload_user_metadata(user_email, user_metadata)
            print(f"Metadata set for {filename}: {metadata}")

    async def get_all_sorted(self, user_email: str) -> list:
        async with self._lock:
            user_metadata = await self._download_user_metadata(user_email)
            files = list(user_metadata.items())
            sorted_files = sorted(files, key=lambda x: x[1].get("upload_time", ""), reverse=True)
            return sorted_files

_blob_metadata_manager_instance = None

def get_metadata_manager():
    global _blob_metadata_manager_instance
    if _blob_metadata_manager_instance is None:
        connection_string = os.environ.get("BLOB_CONNECTION_STRING")
        if not connection_string:
            raise ValueError("Azure Storage connection string not found in environment variables.")
        _blob_metadata_manager_instance = MetadataManager(connection_string)
        loop = asyncio.get_event_loop()
        loop.create_task(_blob_metadata_manager_instance.initialize_container())
    return _blob_metadata_manager_instance
