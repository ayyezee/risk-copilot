"""File storage service with local and S3 backends."""

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import aiofiles
import boto3
from botocore.exceptions import ClientError

from app.config import get_settings
from app.core.exceptions import StorageError

settings = get_settings()


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def upload(self, file_content: bytes, filename: str, content_type: str) -> str:
        """Upload a file and return the storage path."""
        pass

    @abstractmethod
    async def download(self, storage_path: str) -> bytes:
        """Download a file by its storage path."""
        pass

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete a file by its storage path."""
        pass

    @abstractmethod
    async def exists(self, storage_path: str) -> bool:
        """Check if a file exists."""
        pass

    @abstractmethod
    def get_url(self, storage_path: str) -> str:
        """Get a URL for accessing the file."""
        pass


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_full_path(self, storage_path: str) -> Path:
        return self.base_path / storage_path

    async def upload(self, file_content: bytes, filename: str, content_type: str) -> str:
        try:
            # Generate unique path with date-based folders
            from datetime import datetime
            date_prefix = datetime.now().strftime("%Y/%m/%d")
            unique_id = uuid.uuid4().hex[:8]
            ext = Path(filename).suffix
            storage_path = f"{date_prefix}/{unique_id}{ext}"

            full_path = self._get_full_path(storage_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(full_path, "wb") as f:
                await f.write(file_content)

            return storage_path
        except OSError as e:
            raise StorageError(f"Failed to upload file: {e}") from e

    async def download(self, storage_path: str) -> bytes:
        try:
            full_path = self._get_full_path(storage_path)
            async with aiofiles.open(full_path, "rb") as f:
                return await f.read()
        except FileNotFoundError as e:
            raise StorageError(f"File not found: {storage_path}") from e
        except OSError as e:
            raise StorageError(f"Failed to download file: {e}") from e

    async def delete(self, storage_path: str) -> None:
        try:
            full_path = self._get_full_path(storage_path)
            if full_path.exists():
                os.remove(full_path)
        except OSError as e:
            raise StorageError(f"Failed to delete file: {e}") from e

    async def exists(self, storage_path: str) -> bool:
        return self._get_full_path(storage_path).exists()

    def get_url(self, storage_path: str) -> str:
        return f"/files/{storage_path}"


class S3StorageBackend(StorageBackend):
    """AWS S3 storage backend."""

    def __init__(
        self,
        bucket_name: str,
        region: str,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.region = region
        self.client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    async def upload(self, file_content: bytes, filename: str, content_type: str) -> str:
        try:
            from datetime import datetime
            date_prefix = datetime.now().strftime("%Y/%m/%d")
            unique_id = uuid.uuid4().hex[:8]
            ext = Path(filename).suffix
            storage_path = f"{date_prefix}/{unique_id}{ext}"

            self.client.put_object(
                Bucket=self.bucket_name,
                Key=storage_path,
                Body=file_content,
                ContentType=content_type,
            )
            return storage_path
        except ClientError as e:
            raise StorageError(f"Failed to upload to S3: {e}") from e

    async def download(self, storage_path: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=storage_path)
            return response["Body"].read()
        except ClientError as e:
            raise StorageError(f"Failed to download from S3: {e}") from e

    async def delete(self, storage_path: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=storage_path)
        except ClientError as e:
            raise StorageError(f"Failed to delete from S3: {e}") from e

    async def exists(self, storage_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=storage_path)
            return True
        except ClientError:
            return False

    def get_url(self, storage_path: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": storage_path},
            ExpiresIn=3600,
        )


class FileStorageService:
    """File storage service that uses configured backend."""

    def __init__(self) -> None:
        if settings.storage_backend == "s3":
            if not settings.s3_bucket_name:
                raise StorageError("S3 bucket name is required for S3 storage")
            self.backend: StorageBackend = S3StorageBackend(
                bucket_name=settings.s3_bucket_name,
                region=settings.s3_region,
                access_key=settings.aws_access_key_id,
                secret_key=settings.aws_secret_access_key,
            )
        else:
            self.backend = LocalStorageBackend(settings.local_storage_path)

    async def upload_file(self, file_content: bytes, filename: str, content_type: str) -> str:
        """Upload a file and return the storage path."""
        return await self.backend.upload(file_content, filename, content_type)

    async def download_file(self, storage_path: str) -> bytes:
        """Download a file by its storage path."""
        return await self.backend.download(storage_path)

    async def delete_file(self, storage_path: str) -> None:
        """Delete a file by its storage path."""
        await self.backend.delete(storage_path)

    async def file_exists(self, storage_path: str) -> bool:
        """Check if a file exists."""
        return await self.backend.exists(storage_path)

    def get_file_url(self, storage_path: str) -> str:
        """Get a URL for accessing the file."""
        return self.backend.get_url(storage_path)


def get_file_storage_service() -> FileStorageService:
    """Get file storage service instance."""
    return FileStorageService()
