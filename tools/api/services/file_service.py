"""Blob Storage ファイル操作サービス。"""

from __future__ import annotations

import uuid

from azure.storage.blob import BlobServiceClient, ContentSettings


class FileService:
    def __init__(self, blob_service: BlobServiceClient) -> None:
        self._blob_service = blob_service

    def upload(
        self,
        container: str,
        data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """ファイルをBlobにアップロードし、blob名を返す。"""
        blob_name = f"{uuid.uuid4()}/{filename}"
        blob_client = self._blob_service.get_blob_client(container, blob_name)
        blob_client.upload_blob(
            data,
            content_settings=ContentSettings(content_type=content_type),
            overwrite=True,
        )
        return blob_name

    def download(self, container: str, blob_name: str) -> bytes:
        """Blobからファイルをダウンロードする。"""
        blob_client = self._blob_service.get_blob_client(container, blob_name)
        return blob_client.download_blob().readall()

    def get_download_url(self, container: str, blob_name: str) -> str:
        """Blobの直接URLを返す（SAS不要、Functions API経由でプロキシする設計）。"""
        return f"{container}/{blob_name}"
